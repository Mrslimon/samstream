"""Frame TV Art Mode, over the `com.samsung.art-app` WebSocket channel.

Art Mode is a second WebSocket on the TLS port, separate from the remote-control
channel. The flow, confirmed against samsungtvws 3.0.6 and a 2024 "The Frame":

  1. open  wss://<host>:8002/api/v2/channels/com.samsung.art-app?name=..&token=..
  2. wait for `ms.channel.ready` (the art app is up), after `ms.channel.connect`;
  3. emit `art_app_request` with a per-request uuid in `id`/`request_id`, the
     request itself JSON-encoded in `data`;
  4. the reply is a `d2d_service_message` whose `data` is a JSON string, matched
     back by `request_id`.

Only the operations Samstream needs are wrapped (status, list, current, select,
brightness). An `ArtConnection` is an async context manager so a list-then-act
flow reuses one socket; the thin `SamsungTV.art_*` helpers open one per call.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import uuid
from types import TracebackType
from typing import Any, Self

import aiohttp

from .const import WS_PORT_SECURE
from .exceptions import (
    SamstreamConnectionError,
    SamstreamError,
    SamstreamTimeoutError,
)

ART_ENDPOINT = "com.samsung.art-app"

_MS_CHANNEL_READY = "ms.channel.ready"
_MS_CHANNEL_CONNECT = "ms.channel.connect"
_D2D_MESSAGE = "d2d_service_message"

_READY_TIMEOUT = 10.0
_REQUEST_TIMEOUT = 10.0


class ArtConnection:
    """One open art-app channel; reused across requests within a `with` block."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        token: str | None,
        name: str,
        timeout: float = _REQUEST_TIMEOUT,
    ) -> None:
        """Create a client for `host`; nothing connects until `open()`."""
        self._host = host
        self._session = session
        self._token = token
        self._name = name
        self._timeout = timeout
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    @property
    def _url(self) -> str:
        name = base64.b64encode(self._name.encode()).decode("ascii")
        url = (
            f"wss://{self._host}:{WS_PORT_SECURE}"
            f"/api/v2/channels/{ART_ENDPOINT}?name={name}"
        )
        if self._token:
            url += f"&token={self._token}"
        return url

    async def __aenter__(self) -> Self:
        """Open the channel on entering the `async with` block."""
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the channel on leaving the block."""
        await self.close()

    async def open(self) -> None:
        """Connect and wait until the art app reports ready."""
        try:
            self._ws = await self._session.ws_connect(
                self._url, ssl=False, heartbeat=None
            )
        except (aiohttp.ClientError, OSError) as err:
            msg = f"Cannot open the art channel on {self._host}:{WS_PORT_SECURE}"
            raise SamstreamConnectionError(msg) from err
        try:
            async with asyncio.timeout(_READY_TIMEOUT):
                while True:
                    frame = await self._recv_frame()
                    event = frame.get("event")
                    if event == _MS_CHANNEL_READY:
                        return
                    if event == _MS_CHANNEL_CONNECT:
                        continue  # keep waiting for ready
        except TimeoutError as err:
            await self.close()
            msg = f"The art app on {self._host} never became ready"
            raise SamstreamTimeoutError(msg) from err

    async def close(self) -> None:
        """Close the channel (safe to call more than once)."""
        ws, self._ws = self._ws, None
        if ws is not None and not ws.closed:
            with contextlib.suppress(aiohttp.ClientError, OSError):  # already gone
                await ws.close()

    async def _recv_frame(self) -> dict[str, Any]:
        ws = self._ws
        if ws is None:
            msg = "The art channel is not open"
            raise SamstreamError(msg)
        incoming = await ws.receive()
        if incoming.type in (
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        ):
            msg = f"The art channel to {self._host} closed"
            raise SamstreamConnectionError(msg)
        try:
            frame = json.loads(incoming.data)
        except (ValueError, TypeError):
            return {}
        return frame if isinstance(frame, dict) else {}

    async def request(
        self, request: str, *, wait: bool = True, **params: object
    ) -> dict[str, Any] | None:
        """Send one art request; return the decoded reply, or None if `wait=False`.

        Extra keyword arguments ride along in the request (e.g. `content_id`).
        """
        if self._ws is None:
            msg = "The art channel is not open"
            raise SamstreamError(msg)
        req_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "request": request,
            "id": req_id,
            "request_id": req_id,
        }
        payload.update({k: v for k, v in params.items() if v is not None})
        await self._ws.send_json(
            {
                "method": "ms.channel.emit",
                "params": {
                    "event": "art_app_request",
                    "to": "host",
                    "data": json.dumps(payload),
                },
            }
        )
        if not wait:
            return None
        return await self._read_reply(req_id, request)

    async def _read_reply(self, req_id: str, request: str) -> dict[str, Any]:
        """Wait for the `d2d_service_message` that answers `req_id`."""
        try:
            async with asyncio.timeout(self._timeout):
                while True:
                    reply = await self._next_d2d(req_id)
                    if reply is None:
                        continue
                    if reply.get("event") == "error":
                        code = reply.get("error_code", "unknown")
                        msg = f"Art request `{request}` failed ({code})"
                        raise SamstreamError(msg)
                    return reply
        except TimeoutError as err:
            msg = f"No art reply from {self._host} for `{request}`"
            raise SamstreamTimeoutError(msg) from err

    async def _next_d2d(self, req_id: str) -> dict[str, Any] | None:
        """Read one frame; return its payload if it answers `req_id`, else None."""
        frame = await self._recv_frame()
        if frame.get("event") != _D2D_MESSAGE:
            return None
        data = frame.get("data")
        if not isinstance(data, str):
            return None
        try:
            reply = json.loads(data)
        except ValueError:
            return None
        if not isinstance(reply, dict):
            return None
        if reply.get("request_id", reply.get("id")) != req_id:
            return None
        return reply

    # -- High-level operations -------------------------------------------------

    async def get_art_mode(self) -> bool:
        """Whether Art Mode is currently on."""
        reply = await self.request("get_artmode_status")
        if not reply:
            return False
        return str(reply.get("value")).lower() == "on"

    async def set_art_mode(self, *, on: bool) -> None:
        """Turn Art Mode on (the Frame shows artwork) or off (back to the TV)."""
        # Some firmwares don't reply to the setter; don't hang waiting.
        await self.request(
            "set_artmode_status", value="on" if on else "off", wait=False
        )

    async def available(self, category: str | None = None) -> list[dict[str, Any]]:
        """Return the stored artwork list (each item has a `content_id`)."""
        reply = await self.request("get_content_list", category=category)
        raw = (reply or {}).get("content_list")
        items = json.loads(raw) if isinstance(raw, str) else []
        if category:
            return [i for i in items if i.get("category_id") == category]
        return items

    async def current(self) -> str | None:
        """Return the `content_id` of the artwork showing now, if any."""
        reply = await self.request("get_current_artwork")
        return (reply or {}).get("content_id")

    async def select(self, content_id: str, *, show: bool = True) -> None:
        """Show artwork `content_id` (and switch to Art Mode when `show`)."""
        await self.request("select_image", content_id=content_id, show=show)

    async def get_brightness(self) -> object:
        """Return the Art Mode brightness level."""
        reply = await self.request("get_brightness")
        return (reply or {}).get("value")

    async def set_brightness(self, value: int) -> None:
        """Set the Art Mode brightness level."""
        await self.request("set_brightness", value=value, wait=False)
