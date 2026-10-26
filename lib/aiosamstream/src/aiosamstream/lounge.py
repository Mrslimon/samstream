"""Play a specific YouTube video on the TV, over the YouTube Lounge protocol.

Launching YouTube (DIAL or Tizen app-control) only lands on its home page, so
a chosen video needs the Lounge (second-screen) protocol. Confirmed against a
QN800C:

  1. launch the YouTube DIAL app; while it runs, `/ws/apps/YouTube` reports a
     `<screenId>`;
  2. exchange the screen id for a lounge token (youtube.com);
  3. bind a REMOTE_CONTROL session (reads back SID + gsessionid);
  4. send `setPlaylist` with the video id.

Only playing one video is implemented. The TV handles DIAL; the lounge calls go
to youtube.com, so Home Assistant needs internet for this (the launch does not).
"""

from __future__ import annotations

import asyncio
import json
import re
from http import HTTPStatus
from typing import Any

import aiohttp

from .const import DIAL_PORT
from .exceptions import SamstreamConnectionError, SamstreamError

LOUNGE_BASE = "https://www.youtube.com/api/lounge"
# The TV only accepts a DIAL launch from a recognised YouTube sender.
_DIAL_ORIGIN = "package:com.google.android.youtube"
_SCREEN_ID = re.compile(r"<screenId>([0-9A-Za-z._-]+)</screenId>")
_SCREEN_POLLS = 12
_POLL_DELAY = 0.5

# SID + gsessionid + last event id, read back from a bind response.
Bound = tuple[str, str, int]
# A bind event is an [id, payload] pair.
_EVENT_PAIR = 2


async def play_youtube(
    host: str,
    session: aiohttp.ClientSession,
    video_id: str,
    *,
    timeout: float = 10.0,  # noqa: ASYNC109 - mirrors SamsungTV's timeout style
) -> None:
    """Open the YouTube app on `host` and play `video_id`."""
    ct = aiohttp.ClientTimeout(total=timeout)
    screen_id = await _launch_and_screen_id(host, session, ct)
    token = await _lounge_token(session, screen_id, ct)
    bound = await _bind(session, screen_id, token, ct)
    await _set_playlist(session, token, bound, video_id, ct)


async def _launch_and_screen_id(
    host: str, session: aiohttp.ClientSession, ct: aiohttp.ClientTimeout
) -> str:
    """Start the YouTube DIAL app and return the screen id it reports."""
    url = f"http://{host}:{DIAL_PORT}/ws/apps/YouTube"
    headers = {
        "Origin": _DIAL_ORIGIN,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        async with session.post(url, data="", headers=headers, timeout=ct) as resp:
            if resp.status not in (HTTPStatus.OK, HTTPStatus.CREATED):
                msg = f"The TV refused to start YouTube ({resp.status})"
                raise SamstreamError(msg)
        for _ in range(_SCREEN_POLLS):
            async with session.get(url, timeout=ct) as resp:
                text = await resp.text()
            match = _SCREEN_ID.search(text)
            if match:
                return match.group(1)
            await asyncio.sleep(_POLL_DELAY)
    except (aiohttp.ClientError, OSError, TimeoutError) as err:
        msg = f"Cannot reach the TV's DIAL service on {host}:{DIAL_PORT}"
        raise SamstreamConnectionError(msg) from err
    msg = "The TV's YouTube app did not report a screen id"
    raise SamstreamError(msg)


async def _lounge_token(
    session: aiohttp.ClientSession, screen_id: str, ct: aiohttp.ClientTimeout
) -> str:
    try:
        async with session.post(
            f"{LOUNGE_BASE}/pairing/get_lounge_token_batch",
            data={"screen_ids": screen_id},
            timeout=ct,
        ) as resp:
            if resp.status != HTTPStatus.OK:
                msg = f"YouTube refused a lounge token ({resp.status})"
                raise SamstreamError(msg)
            data = await resp.json()
    except (aiohttp.ClientError, OSError, TimeoutError) as err:
        msg = "Cannot reach YouTube to get a lounge token"
        raise SamstreamConnectionError(msg) from err
    try:
        return str(data["screens"][0]["loungeToken"])
    except (KeyError, IndexError, TypeError) as err:
        msg = "YouTube returned no lounge token (TV not signed in?)"
        raise SamstreamError(msg) from err


async def _bind(
    session: aiohttp.ClientSession,
    screen_id: str,
    token: str,
    ct: aiohttp.ClientTimeout,
) -> Bound:
    params = {"RID": "1", "VER": "8", "CVER": "1", "auth_failure_option": "send_error"}
    body = {
        "app": "web",
        "mdx-version": "3",
        "id": screen_id,
        "device": "REMOTE_CONTROL",
        "ui": "false",
        "theme": "cl",
        "loungeIdToken": token,
        "capabilities": "que,dsdtr,atp,vsp",
        "magnaKey": "cloudPairedDevice",
        "name": "Samstream",
    }
    try:
        async with session.post(
            f"{LOUNGE_BASE}/bc/bind", params=params, data=body, timeout=ct
        ) as resp:
            if resp.status != HTTPStatus.OK:
                msg = f"YouTube lounge bind failed ({resp.status})"
                raise SamstreamError(msg)
            text = await resp.text()
    except (aiohttp.ClientError, OSError, TimeoutError) as err:
        msg = "Cannot reach YouTube to bind the lounge session"
        raise SamstreamConnectionError(msg) from err
    sid, gsession, aid = parse_bind(text)
    if not sid or not gsession:
        msg = "YouTube bind returned no session id"
        raise SamstreamError(msg)
    return sid, gsession, aid


async def _set_playlist(
    session: aiohttp.ClientSession,
    token: str,
    bound: Bound,
    video_id: str,
    ct: aiohttp.ClientTimeout,
) -> None:
    sid, gsession, aid = bound
    params = {
        "name": "Samstream",
        "loungeIdToken": token,
        "SID": sid,
        "gsessionid": gsession,
        "AID": str(aid),
        "device": "REMOTE_CONTROL",
        "app": "web",
        "VER": "8",
        "v": "2",
        "RID": "2",
    }
    body = {
        "count": "1",
        "ofs": "0",
        "req0__sc": "setPlaylist",
        "req0_videoId": video_id,
        "req0_currentTime": "0",
        "req0_listId": "",
    }
    try:
        async with session.post(
            f"{LOUNGE_BASE}/bc/bind", params=params, data=body, timeout=ct
        ) as resp:
            if resp.status != HTTPStatus.OK:
                detail = (await resp.text())[:100]
                msg = f"YouTube setPlaylist failed ({resp.status}): {detail}"
                raise SamstreamError(msg)
    except (aiohttp.ClientError, OSError, TimeoutError) as err:
        msg = "Cannot reach YouTube to start the video"
        raise SamstreamConnectionError(msg) from err


def parse_bind(text: str) -> tuple[str | None, str | None, int]:
    """Read SID, gsessionid and the last event id from a bind response.

    The body is length-prefixed chunks: a line with the character count, then a
    JSON array of `[eventId, [eventType, ...]]`. Event `c` carries the SID, `S`
    the gsessionid.
    """
    sid: str | None = None
    gsession: str | None = None
    last_id = 0
    for events in _iter_chunks(text):
        for event in events:
            # Each event is a [id, payload] pair.
            if not (isinstance(event, list) and len(event) == _EVENT_PAIR):
                continue
            event_id, payload = event
            if isinstance(event_id, int):
                last_id = max(last_id, event_id)
            if isinstance(payload, list) and payload:
                if payload[0] == "c" and len(payload) > 1:
                    sid = str(payload[1])
                elif payload[0] == "S" and len(payload) > 1:
                    gsession = str(payload[1])
    return sid, gsession, last_id


def _iter_chunks(text: str) -> list[list[Any]]:
    chunks: list[list[Any]] = []
    pos = 0
    length = len(text)
    while pos < length:
        newline = text.find("\n", pos)
        if newline == -1:
            break
        head = text[pos:newline].strip()
        pos = newline + 1
        if not head.isdigit():
            continue
        size = int(head)
        body = text[pos : pos + size]
        pos += size
        try:
            parsed = json.loads(body)
        except ValueError:
            continue
        if isinstance(parsed, list):
            chunks.append(parsed)
    return chunks
