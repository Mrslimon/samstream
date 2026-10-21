"""Camera streams for the TV app, relayed through Home Assistant.

Streams are registered in HA's built-in go2rtc, which keeps the one connection
to the camera. HA starts go2rtc without its mp4 module, so it cannot serve MSE
itself; instead ffmpeg remuxes go2rtc's local RTSP restream to fragmented MP4
(`-c copy`, no transcoding) while a TV is watching, and this view sends it in
go2rtc's WebSocket MSE format on HA's own port:

    ws://<ha>:8123/api/samstream/tv/{secret}/stream/{name}

Only names HA published for that TV are served, and only with that TV's secret.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
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
_FFMPEG = "ffmpeg"
# The app asks for the stream right after the socket opens.
_REQUEST_TIMEOUT = 10.0
# Fallback when go2rtc's API does not say where its RTSP server listens.
_DEFAULT_RTSP = "127.0.0.1:18554"
# Codec string for H.265 cameras (the TV's own offer); H.264 is read from avcC.
_HEVC_CODEC = "hvc1.1.6.L153.B0"


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
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="go2rtc_refused",
                    translation_placeholders={
                        "status": str(response.status),
                        "detail": detail,
                    },
                )
    except aiohttp.ClientError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="go2rtc_unavailable"
        ) from err
    # A camera can be on several TVs at once: each one may open the stream.
    published: dict[str, set[str]] = hass.data.setdefault(_PUBLISHED, {})
    published.setdefault(name, set()).add(entry.entry_id)
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


def tv_mjpeg_url(hass: HomeAssistant, entry: SamstreamConfigEntry, name: str) -> str:
    """HTTP URL of the picture stream (MJPEG) the TV app shows in corner mode."""
    ws = tv_stream_url(hass, entry, name)
    return ws.replace("ws", "http", 1).replace("/stream/", "/mjpeg/", 1)


class SamstreamStreamView(HomeAssistantView):
    """Serve a published stream to the TV as go2rtc-style WebSocket MSE."""

    url = "/api/samstream/tv/{secret}/stream/{name}"
    name = "api:samstream:tv_stream"
    # The TV app has no HA token; its per-TV secret (from the package) is the key.
    requires_auth = False

    async def get(
        self, request: web.Request, secret: str, name: str
    ) -> web.StreamResponse:
        """Upgrade to WebSocket and stream fMP4 until either side stops."""
        hass = request.app[KEY_HASS]
        if not _allowed(hass, name, secret):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        source = await _restream_url(hass, name)

        socket = web.WebSocketResponse(heartbeat=30)
        await socket.prepare(request)
        try:
            if await _wait_for_request(socket):
                await _serve(socket, source)
        finally:
            await socket.close()
        return socket


def _allowed(hass: HomeAssistant, name: str, secret: str) -> bool:
    """Tell whether `secret` is a TV the stream `name` was published for."""
    for entry_id in hass.data.get(_PUBLISHED, {}).get(name, ()):
        entry = hass.config_entries.async_get_entry(entry_id)
        known = entry.data.get(CONF_TV_SECRET) if entry else None
        if known and secrets.compare_digest(str(known), secret):
            return True
    return False


async def _restream_url(hass: HomeAssistant, name: str) -> str:
    """go2rtc's RTSP restream of `name`, reachable from inside HA only."""
    url, session = _go2rtc(hass)
    listen = _DEFAULT_RTSP
    with contextlib.suppress(aiohttp.ClientError, ValueError, TypeError):
        async with session.get(f"{url}api") as response:
            info = await response.json(content_type=None)
        listen = str(info["rtsp"]["listen"]) or _DEFAULT_RTSP
    host, _, port = listen.rpartition(":")
    return f"rtsp://{host or '127.0.0.1'}:{port}/{name}"


async def _wait_for_request(socket: web.WebSocketResponse) -> bool:
    """Wait for the app's `{"type": "mse", ...}` request."""
    try:
        message = await socket.receive(timeout=_REQUEST_TIMEOUT)
    except TimeoutError:
        return False
    if message.type is not aiohttp.WSMsgType.TEXT:
        return False
    with contextlib.suppress(ValueError):
        return bool(json.loads(message.data).get("type") == "mse")
    return False


class SamstreamMjpegView(HomeAssistantView):
    """Serve a published stream as MJPEG, for the TV's corner mode.

    A <video> on the TV takes the hardware video layer the TV window needs; an
    image stream does not. This transcodes (unlike the MSE view), so it only
    runs while a TV shows a camera with its own picture in a corner.
    """

    url = "/api/samstream/tv/{secret}/mjpeg/{name}"
    name = "api:samstream:tv_mjpeg"
    requires_auth = False

    async def get(
        self, request: web.Request, secret: str, name: str
    ) -> web.StreamResponse:
        """Stream JPEG frames until the TV stops reading."""
        hass = request.app[KEY_HASS]
        if not _allowed(hass, name, secret):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        source = await _restream_url(hass, name)
        process = await asyncio.create_subprocess_exec(
            *mjpeg_args(source),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        response = web.StreamResponse(
            headers={
                "Content-Type": f"multipart/x-mixed-replace;boundary={MJPEG_BOUNDARY}",
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*",
            }
        )
        try:
            await response.prepare(request)
            stdout = process.stdout
            while stdout is not None and (chunk := await stdout.read(65536)):
                await response.write(chunk)
        except ConnectionError, aiohttp.ClientError:
            pass  # The TV went away.
        finally:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            _LOGGER.debug("TV picture stream from %s ended", source)
        return response


MJPEG_BOUNDARY = "ffmpeg"  # ffmpeg's mpjpeg muxer default


def mjpeg_args(source: str) -> list[str]:
    """Decode the restream to 10 JPEG frames a second at 720p (multipart)."""
    return [
        _FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-probesize",
        "500000",
        "-analyzeduration",
        "1000000",
        "-rtsp_transport",
        "tcp",
        "-i",
        source,
        "-an",
        "-vf",
        "fps=10,scale=-2:720",
        "-q:v",
        "6",
        "-f",
        "mpjpeg",
        "pipe:1",
    ]


def ffmpeg_args(source: str) -> list[str]:
    """Remux the video track to fragmented MP4 on stdout, in small fragments."""
    return [
        _FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-probesize",
        "500000",
        "-analyzeduration",
        "1000000",
        "-rtsp_transport",
        "tcp",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-c",
        "copy",
        "-f",
        "mp4",
        "-movflags",
        "empty_moov+default_base_moof+frag_keyframe",
        "-frag_duration",
        "100000",
        "pipe:1",
    ]


async def _serve(socket: web.WebSocketResponse, source: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *ffmpeg_args(source),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout = process.stdout
    if stdout is None:  # pragma: no cover - PIPE always gives a reader
        return
    tasks = [
        asyncio.ensure_future(_send_fmp4(stdout, socket)),
        asyncio.ensure_future(_until_closed(socket)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        _LOGGER.debug("TV stream from %s ended", source)
        for task in tasks:
            task.cancel()
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        for task in tasks:
            with contextlib.suppress(
                asyncio.CancelledError, asyncio.IncompleteReadError, ConnectionError
            ):
                await task


async def _until_closed(socket: web.WebSocketResponse) -> None:
    async for _message in socket:
        pass


async def _read_box(reader: asyncio.StreamReader) -> tuple[bytes, bytes]:
    """Read one top-level MP4 box; return (type, whole box)."""
    header = await reader.readexactly(8)
    size = int.from_bytes(header[:4], "big")
    if size == 1:
        header += await reader.readexactly(8)
        size = int.from_bytes(header[8:16], "big")
    if size < len(header):
        msg = f"bad MP4 box size {size}"
        raise ValueError(msg)
    return header[4:8], header + await reader.readexactly(size - len(header))


def mse_codec(init: bytes) -> str:
    """RFC 6381 codec string for the video track in an fMP4 init segment."""
    avcc = init.find(b"avcC")
    if avcc >= 0:
        return "avc1." + init[avcc + 5 : avcc + 8].hex().upper()
    if b"hvcC" in init:
        return _HEVC_CODEC
    msg = "no H.264/H.265 video track"
    raise ValueError(msg)


async def _send_fmp4(
    reader: asyncio.StreamReader, socket: web.WebSocketResponse
) -> None:
    """Send go2rtc's MSE handshake, the init segment, then whole fragments."""
    init = b""
    while True:
        kind, box = await _read_box(reader)
        init += box
        if kind == b"moov":
            break
    try:
        codec = mse_codec(init)
    except ValueError as err:
        await socket.send_str(json.dumps({"type": "error", "value": str(err)}))
        return
    await socket.send_str(
        json.dumps({"type": "mse", "value": f'video/mp4; codecs="{codec}"'})
    )
    await socket.send_bytes(init)
    fragment = b""
    while True:
        kind, box = await _read_box(reader)
        fragment += box
        # A moof is useless without its mdat; send them together.
        if kind != b"moof":
            await socket.send_bytes(fragment)
            fragment = b""
