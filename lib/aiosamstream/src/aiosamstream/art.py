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
import random
import socket
import ssl
import time
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
# An image transfer runs its own socket and the TV can take a while to accept it.
_UPLOAD_TIMEOUT = 90.0
# Thumbnails come back over the same kind of socket; refuse absurd sizes.
_MAX_HEADER = 64 * 1024
MAX_THUMBNAIL = 4 * 1024 * 1024
MAX_THUMBNAILS = 64  # per request, so one call cannot pull the whole gallery


def _d2d_socket(info: dict[str, Any], timeout: float) -> socket.socket:
    """Connect to a socket the art app opened for one transfer (blocking).

    Not asyncio: the TV's D2D endpoint rejects the TLS SNI that asyncio sends
    for an IP host, so the socket is wrapped without a server name, exactly as
    Samsung's own clients do.
    """
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.settimeout(timeout)
    sock: socket.socket = raw
    if info.get("secured"):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        sock = context.wrap_socket(raw)  # handshake on connect, no SNI
    try:
        sock.connect((str(info["ip"]), int(info["port"])))
    except OSError:
        sock.close()
        raise
    return sock


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(size - len(data), 65536))
        if not chunk:
            msg = "the art socket closed early"
            raise OSError(msg)
        data += chunk
    return bytes(data)


def _read_files(sock: socket.socket) -> dict[str, tuple[bytes, str]]:
    """Read `length|JSON header|bytes` records until the last one (`num`, `total`).

    The TV skips files it has no thumbnail for (some store artwork), so the
    stream can end early: a close between records ends it, mid-record is an error.
    """
    files: dict[str, tuple[bytes, str]] = {}
    for _ in range(MAX_THUMBNAILS):
        first = sock.recv(4)
        if not first and files:
            break
        size = int.from_bytes(first + _recv_exact(sock, 4 - len(first)), "big")
        if not 0 < size <= _MAX_HEADER:
            msg = "bad art file header"
            raise OSError(msg)
        header = json.loads(_recv_exact(sock, size))
        length = int(header["fileLength"])
        if not 0 <= length <= MAX_THUMBNAIL:
            msg = "art file too large"
            raise OSError(msg)
        body = _recv_exact(sock, length)
        files[str(header.get("fileID", len(files)))] = (
            body,
            str(header.get("fileType", "jpg")).lower(),
        )
        if int(header.get("num", 0)) + 1 >= int(header.get("total", 1)):
            break
    return files


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

    async def _emit(self, request: str, req_id: str, **params: object) -> None:
        """Send one `art_app_request` with the given id (no waiting)."""
        if self._ws is None:
            msg = "The art channel is not open"
            raise SamstreamError(msg)
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

    async def request(
        self, request: str, *, wait: bool = True, **params: object
    ) -> dict[str, Any] | None:
        """Send one art request; return the decoded reply, or None if `wait=False`.

        Extra keyword arguments ride along in the request (e.g. `content_id`).
        """
        req_id = str(uuid.uuid4())
        await self._emit(request, req_id, **params)
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

    async def _wait_event(
        self, event: str, *, req_id: str | None, wait: float
    ) -> dict[str, Any]:
        """Wait for a named art event (e.g. `ready_to_use`, `image_added`).

        Unlike `_read_reply`, these events are not always keyed to our request,
        so a payload with no matching `request_id` is still accepted.
        """
        try:
            async with asyncio.timeout(wait):
                while True:
                    frame = await self._recv_frame()
                    payload = frame
                    if frame.get("event") == _D2D_MESSAGE:
                        data = frame.get("data")
                        if not isinstance(data, str):
                            continue
                        try:
                            decoded = json.loads(data)
                        except ValueError:
                            continue
                        if not isinstance(decoded, dict):
                            continue
                        payload = decoded
                    if payload.get("event") == "error":
                        code = payload.get("error_code", "unknown")
                        msg = f"Art event `{event}` failed ({code})"
                        raise SamstreamError(msg)
                    if payload.get("event") != event:
                        continue
                    pr = payload.get("request_id", payload.get("id"))
                    if req_id is None or pr is None or pr == req_id:
                        return payload
        except TimeoutError as err:
            msg = f"No `{event}` from {self._host}"
            raise SamstreamTimeoutError(msg) from err

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

    async def upload(
        self,
        image: bytes,
        *,
        file_type: str = "png",
        matte: str = "none",
        portrait_matte: str = "none",
        date: str | None = None,
    ) -> str | None:
        """Upload an image to "My Photos" and return its new `content_id`.

        The TV answers `send_image` with a one-shot socket (its own ip/port); we
        push the bytes there, then it reports `image_added` with the id to use in
        `select`. `matte`/`portrait_matte` are "none" by default so no mat is
        forced; the id can then be shown with `select(content_id)`.
        """
        file_type = file_type.lower()
        if file_type == "jpeg":
            file_type = "jpg"
        if date is None:
            date = time.strftime("%Y:%m:%d %H:%M:%S")
        req_id = str(uuid.uuid4())
        await self._emit(
            "send_image",
            req_id,
            file_type=file_type,
            conn_info={
                "d2d_mode": "socket",
                "connection_id": random.randrange(4 * 1024 * 1024 * 1024),  # noqa: S311 - an id, not a secret
                # The TV ties the upload socket to the request by this id.
                "id": req_id,
            },
            image_date=date,
            matte_id=matte,
            portrait_matte_id=portrait_matte,
            file_size=len(image),
        )
        ready = await self._wait_event(
            "ready_to_use", req_id=req_id, wait=self._timeout
        )
        raw = ready.get("conn_info")
        info = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(info, dict) or "ip" not in info or "port" not in info:
            msg = f"The art app on {self._host} gave no upload socket"
            raise SamstreamError(msg)
        header = json.dumps(
            {
                "num": 0,
                "total": 1,
                "fileLength": len(image),
                "fileName": "samstream",
                "fileType": file_type,
                "secKey": info.get("key", ""),
                "version": "0.0.1",
            }
        ).encode()
        added = await self._send_bytes(info, header, image)
        return added.get("content_id")

    async def _send_bytes(
        self, info: dict[str, Any], header: bytes, image: bytes
    ) -> dict[str, Any]:
        """Open the TV's upload socket, push header + image, await `image_added`."""
        timeout = self._timeout

        def _push() -> None:
            sock = _d2d_socket(info, timeout)
            try:
                sock.sendall(len(header).to_bytes(4, "big"))
                sock.sendall(header)
                sock.sendall(image)
            finally:
                with contextlib.suppress(OSError):
                    sock.close()

        try:
            await asyncio.to_thread(_push)
        except OSError as err:
            msg = f"Cannot reach the art upload socket on {self._host}"
            raise SamstreamConnectionError(msg) from err
        return await self._wait_event("image_added", req_id=None, wait=_UPLOAD_TIMEOUT)

    async def mattes(self) -> tuple[list[str], dict[str, tuple[int, int, int]]]:
        """Return the frame borders: (styles, {colour: (R, G, B)}).

        A border id is `none` or `<style>_<colour>`, e.g. `shadowbox_sand`.
        """
        reply = await self.request("get_matte_list") or {}

        def _decoded(key: str) -> list[Any]:
            raw = reply.get(key)
            try:
                value = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                return []
            return value if isinstance(value, list) else []

        styles = [
            str(item["matte_type"])
            for item in _decoded("matte_type_list")
            if isinstance(item, dict) and item.get("matte_type")
        ]
        colours = {
            str(item["color"]): (int(item["R"]), int(item["G"]), int(item["B"]))
            for item in _decoded("matte_color_list")
            if isinstance(item, dict) and {"color", "R", "G", "B"} <= item.keys()
        }
        return styles, colours

    async def change_matte(self, content_id: str, matte_id: str) -> None:
        """Put stored artwork `content_id` in border `matte_id` (or `none`)."""
        await self.request("change_matte", content_id=content_id, matte_id=matte_id)

    async def thumbnails(self, content_ids: list[str]) -> dict[str, tuple[bytes, str]]:
        """Fetch thumbnails: `{content_id: (image bytes, "jpg"|"png")}`.

        `get_thumbnail_list` answers with a one-shot socket that streams one
        `length|header|bytes` record per artwork (at most MAX_THUMBNAILS).
        """
        ids = list(dict.fromkeys(content_ids))[:MAX_THUMBNAILS]
        if not ids:
            return {}
        reply = await self.request(
            "get_thumbnail_list",
            content_id_list=[{"content_id": content_id} for content_id in ids],
            conn_info={
                "d2d_mode": "socket",
                "connection_id": random.randrange(4 * 1024 * 1024 * 1024),  # noqa: S311 - an id, not a secret
                "id": str(uuid.uuid4()),
            },
        )
        raw = (reply or {}).get("conn_info")
        info = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(info, dict) or "ip" not in info or "port" not in info:
            msg = f"The art app on {self._host} gave no thumbnail socket"
            raise SamstreamError(msg)
        timeout = self._timeout

        def _pull() -> dict[str, tuple[bytes, str]]:
            sock = _d2d_socket(info, timeout)
            try:
                return _read_files(sock)
            finally:
                with contextlib.suppress(OSError):
                    sock.close()

        try:
            files = await asyncio.to_thread(_pull)
        except (OSError, ValueError, KeyError) as err:
            msg = f"Cannot read thumbnails from {self._host}"
            raise SamstreamConnectionError(msg) from err
        # The TV names each file by its content id; keep only what was asked.
        return {key: value for key, value in files.items() if key in ids}

    async def get_brightness(self) -> object:
        """Return the Art Mode brightness level."""
        reply = await self.request("get_brightness")
        return (reply or {}).get("value")

    async def set_brightness(self, value: int) -> None:
        """Set the Art Mode brightness level."""
        await self.request("set_brightness", value=value, wait=False)
