"""Camera streams for the TV app, relayed through Home Assistant.

ffmpeg opens the camera's own stream source directly (one process per
viewer - a TV does not share HA's single go2rtc connection the way its other
consumers do) and remuxes it to fragmented MP4 (`-c copy`, no transcoding
unless the codec needs it), which this view sends as WebSocket MSE on HA's
own port:

    ws://<ha>:8123/api/samstream/tv/{secret}/stream/{name}

Only names HA published for that TV are served, and only with that TV's
secret. `name` is a hash of the source, never the source itself: nothing
below ever sends or logs a raw URL, since `async_get_stream_source` can
return one with credentials embedded.

This deliberately does not go through HA's go2rtc integration: go2rtc's own
`hass.data` object is that integration's internal client, not a public API,
and reaching into it would mean using go2rtc's own credentials for requests
it did not make. A source with a strict limit on concurrent viewers (some
NVR channels only allow 2-4) is the trade-off; go2rtc would have shared one
upstream connection across every viewer.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
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
from homeassistant.helpers.storage import Store

from .const import CONF_TV_SECRET, DOMAIN

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)

# In-memory registry {name: set(entry_id)} of streams a TV may open, rebuilt at
# startup from the persistent store below (lost on restart otherwise, so a
# replayed stream URL would otherwise 404 - "ws closed" on the TV).
_PUBLISHED = f"{DOMAIN}_streams"
# {name: source} alongside _PUBLISHED: the camera's own stream source
# (resolved once via async_get_stream_source, possibly with credentials in
# it). Kept server-side only - never sent to the TV, never logged.
_SOURCES = f"{DOMAIN}_stream_sources"
_STORE = f"{DOMAIN}_stream_store"
_LOADED = f"{DOMAIN}_streams_loaded"
_STORE_VERSION = 1
_STORE_KEY = f"{DOMAIN}.streams"
_FFMPEG = "ffmpeg"
# The app asks for the stream right after the socket opens.
_REQUEST_TIMEOUT = 10.0
# Codec string for H.265 cameras (the TV's own offer); H.264 is read from avcC.
_HEVC_CODEC = "hvc1.1.6.L153.B0"
_CREDENTIALS_IN_URL = re.compile(r"//[^/@]*@")
# H.264 levels the TV's MSE client is confirmed to accept (tv-app/src/mse.ts
# VIDEO_CODECS). A camera encoding at another level (e.g. Level 5.0,
# "avc1.640032" - some DVRs/NVRs default to it) plays fine through ffmpeg but
# the TV's own decoder refuses it; the stream copy gets transcoded once to a
# safe level instead, rather than asking every camera to be reconfigured.
_TV_SAFE_AVC_CODECS = frozenset({"avc1.640029", "avc1.64002A", "avc1.640033"})
_TRANSCODE_LEVEL = "4.1"  # matches avc1.640029 above


def _redact(source: str) -> str:
    """Hide credentials before a source can reach a log line or error message."""
    return _CREDENTIALS_IN_URL.sub("//***@", source)


def stream_name(source: str) -> str:
    """Return a stable, opaque name for a source (no credentials in it)."""
    return "samstream_" + hashlib.sha256(source.encode()).hexdigest()[:16]


async def _ensure_loaded(hass: HomeAssistant) -> None:
    """Rebuild the in-memory stream registry from the store, once per run.

    Lost on restart otherwise, so a TV replaying a saved stream URL would
    otherwise 404 ("ws closed"). The store keeps {name: {source, entries}}.
    """
    if hass.data.get(_LOADED):
        return
    hass.data[_LOADED] = True
    store: Store[dict[str, Any]] = hass.data.setdefault(
        _STORE, Store(hass, _STORE_VERSION, _STORE_KEY)
    )
    data = await store.async_load()
    published: dict[str, set[str]] = hass.data.setdefault(_PUBLISHED, {})
    sources: dict[str, str] = hass.data.setdefault(_SOURCES, {})
    for name, record in (data or {}).get("streams", {}).items():
        source = record.get("source")
        entries = record.get("entries", [])
        if not isinstance(source, str) or not entries:
            continue
        published.setdefault(name, set()).update(entries)
        sources[name] = source


async def _save(hass: HomeAssistant) -> None:
    """Persist the current registry so replays survive a restart."""
    published: dict[str, set[str]] = hass.data.get(_PUBLISHED, {})
    sources: dict[str, str] = hass.data.get(_SOURCES, {})
    streams = {
        name: {"source": sources[name], "entries": sorted(entries)}
        for name, entries in published.items()
        if name in sources and entries
    }
    store: Store[dict[str, Any]] = hass.data.setdefault(
        _STORE, Store(hass, _STORE_VERSION, _STORE_KEY)
    )
    await store.async_save({"streams": streams})


async def async_publish_stream(
    hass: HomeAssistant, entry: SamstreamConfigEntry, source: str
) -> str:
    """Record `source` as servable for this TV; return its (opaque) name.

    Purely local bookkeeping now - no registration call to make, so there is
    nothing here that can be refused or unreachable.
    """
    await _ensure_loaded(hass)
    name = stream_name(source)
    # A camera can be on several TVs at once: each one may open the stream.
    published: dict[str, set[str]] = hass.data.setdefault(_PUBLISHED, {})
    published.setdefault(name, set()).add(entry.entry_id)
    hass.data.setdefault(_SOURCES, {})[name] = source
    await _save(hass)
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
        await _ensure_loaded(hass)
        if not _allowed(hass, name, secret):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        source = hass.data.get(_SOURCES, {}).get(name)
        if not source:
            return web.Response(status=HTTPStatus.NOT_FOUND)

        socket = web.WebSocketResponse(heartbeat=30)
        await socket.prepare(request)
        try:
            if await _wait_for_request(socket):
                await _serve(socket, source)
        finally:
            await socket.close()
            _drop_heartbeat(socket)
        return socket


def _drop_heartbeat(socket: web.WebSocketResponse) -> None:
    """Stop aiohttp re-arming the heartbeat once the socket is closed.

    aiohttp 3.14 resets the heartbeat for data that arrives after close() (the
    TV's own close frame), so a 30 s ping timer would outlive the connection.
    Its reset path does nothing when no heartbeat interval is set.
    """
    if hasattr(socket, "_heartbeat"):
        socket._heartbeat = None  # noqa: SLF001
    cancel = getattr(socket, "_cancel_heartbeat", None)
    if callable(cancel):
        cancel()


def _allowed(hass: HomeAssistant, name: str, secret: str) -> bool:
    """Tell whether `secret` is a TV the stream `name` was published for."""
    for entry_id in hass.data.get(_PUBLISHED, {}).get(name, ()):
        entry = hass.config_entries.async_get_entry(entry_id)
        known = entry.data.get(CONF_TV_SECRET) if entry else None
        if known and secrets.compare_digest(str(known), secret):
            return True
    return False


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
        await _ensure_loaded(hass)
        if not _allowed(hass, name, secret):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        source = hass.data.get(_SOURCES, {}).get(name)
        if not source:
            return web.Response(status=HTTPStatus.NOT_FOUND)
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
            _LOGGER.debug("TV picture stream from %s ended", _redact(source))
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


def transcode_args(source: str) -> list[str]:
    """Re-encode the video track to a level the TV's MSE client accepts.

    Used only once a copy's codec turns out not to be in `_TV_SAFE_AVC_CODECS`
    (most cameras never hit this; it's the fallback, not the default).
    """
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
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-level:v",
        _TRANSCODE_LEVEL,
        "-preset",
        "veryfast",
        "-f",
        "mp4",
        "-movflags",
        "empty_moov+default_base_moof+frag_keyframe",
        "-frag_duration",
        "100000",
        "pipe:1",
    ]


async def _start_ffmpeg(args: list[str]) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def _kill(process: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    await process.wait()


async def _serve(socket: web.WebSocketResponse, source: str) -> None:
    process = await _start_ffmpeg(ffmpeg_args(source))
    stdout = process.stdout
    if stdout is None:  # pragma: no cover - PIPE always gives a reader
        return
    try:
        init, codec = await _read_init(stdout)
    except (ValueError, EOFError, ConnectionError) as err:
        await socket.send_str(json.dumps({"type": "error", "value": str(err)}))
        await _kill(process)
        return
    if codec not in _TV_SAFE_AVC_CODECS and codec != _HEVC_CODEC:
        _LOGGER.debug(
            "TV stream from %s: %s not TV-safe, transcoding instead of copying",
            _redact(source),
            codec,
        )
        await _kill(process)
        process = await _start_ffmpeg(transcode_args(source))
        stdout = process.stdout
        if stdout is None:  # pragma: no cover - PIPE always gives a reader
            return
        try:
            init, codec = await _read_init(stdout)
        except (ValueError, EOFError, ConnectionError) as err:
            await socket.send_str(json.dumps({"type": "error", "value": str(err)}))
            await _kill(process)
            return
    await socket.send_str(
        json.dumps({"type": "mse", "value": f'video/mp4; codecs="{codec}"'})
    )
    await socket.send_bytes(init)
    tasks = [
        asyncio.ensure_future(_send_fmp4(stdout, socket)),
        asyncio.ensure_future(_until_closed(socket)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        _LOGGER.debug("TV stream from %s ended", _redact(source))
        for task in tasks:
            task.cancel()
        await _kill(process)
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


async def _read_init(reader: asyncio.StreamReader) -> tuple[bytes, str]:
    """Read ffmpeg's init segment (up to and including `moov`).

    Returns it with its codec string. Raises `ValueError` if it has no
    H.264/H.265 track.
    """
    init = b""
    while True:
        kind, box = await _read_box(reader)
        init += box
        if kind == b"moov":
            break
    return init, mse_codec(init)


async def _send_fmp4(
    reader: asyncio.StreamReader, socket: web.WebSocketResponse
) -> None:
    """Send whole fragments as they arrive (the init segment already went)."""
    fragment = b""
    while True:
        kind, box = await _read_box(reader)
        fragment += box
        # A moof is useless without its mdat; send them together.
        if kind != b"moof":
            await socket.send_bytes(fragment)
            fragment = b""
