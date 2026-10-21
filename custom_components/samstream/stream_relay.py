"""Camera streams for the TV app, relayed through Home Assistant.

Streams are registered in HA's built-in go2rtc (it listens on a private Unix
socket inside HA, so the TV cannot reach it). The TV plays go2rtc's WebSocket MSE
stream (fMP4 remux, no transcoding) through this view on HA's own port:

    ws://<ha>:8123/api/samstream/tv/{secret}/stream/{name}

Only names HA published for that TV are relayed, and only with that TV's secret.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import CONF_TV_SECRET, DOMAIN

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)

# HA's go2rtc integration keeps {url, session} here; the session talks to the
# Unix socket with go2rtc's credentials.
_GO2RTC_DATA = "go2rtc"
_PUBLISHED = f"{DOMAIN}_streams"


def _go2rtc(hass: HomeAssistant) -> tuple[str, aiohttp.ClientSession]:
    config: Any = hass.data.get(_GO2RTC_DATA)
    url = getattr(config, "url", None)
    session = getattr(config, "session", None)
    if not isinstance(url, str) or not isinstance(session, aiohttp.ClientSession):
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="go2rtc_unavailable"
        )
    return url, session


def stream_name(source: str) -> str:
    """Return a stable go2rtc stream name for a source (no credentials in it)."""
    return "samstream_" + hashlib.sha256(source.encode()).hexdigest()[:16]


async def async_publish_stream(
    hass: HomeAssistant, entry: SamstreamConfigEntry, source: str
) -> str:
    """Register `source` (RTSP URL) in go2rtc for this TV; return the stream name."""
    url, session = _go2rtc(hass)
    name = stream_name(source)
    try:
        async with session.put(
            f"{url}api/streams", params={"name": name, "src": source}
        ) as response:
            if response.status >= HTTPStatus.BAD_REQUEST:
                detail = (await response.text())[:200]
                msg = f"go2rtc refused the stream: {response.status} {detail}"
                raise HomeAssistantError(msg)
    except aiohttp.ClientError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="go2rtc_unavailable"
        ) from err
    published: dict[str, str] = hass.data.setdefault(_PUBLISHED, {})
    published[name] = entry.entry_id
    return name


def tv_stream_url(hass: HomeAssistant, entry: SamstreamConfigEntry, name: str) -> str:
    """WebSocket URL the TV app opens for a published stream."""
    try:
        base = get_url(hass, allow_external=False, allow_cloud=False)
    except NoURLAvailableError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="no_internal_url"
        ) from err
    parsed = urlparse(base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    secret = entry.data[CONF_TV_SECRET]
    return f"{scheme}://{parsed.netloc}/api/samstream/tv/{secret}/stream/{name}"


class SamstreamStreamView(HomeAssistantView):
    """Relay go2rtc's MSE WebSocket to the TV."""

    url = "/api/samstream/tv/{secret}/stream/{name}"
    name = "api:samstream:tv_stream"
    # The TV app has no HA token; its per-TV secret (from the package) is the key.
    requires_auth = False

    async def get(
        self, request: web.Request, secret: str, name: str
    ) -> web.StreamResponse:
        """Upgrade to WebSocket and pipe frames both ways until one side closes."""
        hass = request.app[KEY_HASS]
        owner = hass.data.get(_PUBLISHED, {}).get(name)
        entry = hass.config_entries.async_get_entry(owner) if owner else None
        known = entry.data.get(CONF_TV_SECRET) if entry else None
        if not known or not secrets.compare_digest(str(known), secret):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        go2rtc_url, session = _go2rtc(hass)

        downstream = web.WebSocketResponse(heartbeat=30)
        await downstream.prepare(request)
        try:
            async with session.ws_connect(
                f"{go2rtc_url}api/ws", params={"src": name}, heartbeat=30
            ) as upstream:
                await _pipe(downstream, upstream)
        except aiohttp.ClientError as err:
            _LOGGER.debug("go2rtc stream %s ended: %s", name, err)
        finally:
            await downstream.close()
        return downstream


async def _forward(
    source: web.WebSocketResponse | aiohttp.ClientWebSocketResponse,
    send_str: Callable[[str], Awaitable[None]],
    send_bytes: Callable[[bytes], Awaitable[None]],
) -> None:
    async for message in source:
        if message.type is aiohttp.WSMsgType.BINARY:
            await send_bytes(message.data)
        elif message.type is aiohttp.WSMsgType.TEXT:
            await send_str(message.data)
        else:
            break


async def _pipe(
    downstream: web.WebSocketResponse, upstream: aiohttp.ClientWebSocketResponse
) -> None:
    """Copy frames both ways; stop when either side goes away."""
    tasks = [
        asyncio.ensure_future(
            _forward(upstream, downstream.send_str, downstream.send_bytes)
        ),
        asyncio.ensure_future(
            _forward(downstream, upstream.send_str, upstream.send_bytes)
        ),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, aiohttp.ClientError):
                await task
