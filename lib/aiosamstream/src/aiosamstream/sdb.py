"""Pure-Python async client for Samsung's Smart Development Bridge (sdb, TCP 26101).

No Tizen Studio binary is needed, so it runs wherever Home Assistant runs (Docker,
HA OS, aarch64). Protocol reference: PatrickSt1991/tizen-sdb (MIT), the independent
implementation behind Apps2Samsung.

Wire format: ADB-style 24-byte little-endian headers (command, arg0, arg1, payload
length, byte-sum checksum, command ^ 0xFFFFFFFF). Every WRTE must be acknowledged with
OKAY before the next one on that stream. TVs with `secure_protocol:enabled` start with
an RSA AUTH challenge.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import re
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Self

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .apps import ListedApp, parse_app_list
from .const import SDB_PORT
from .exceptions import SdbConnectionError, SdbError

_LOGGER = logging.getLogger(__name__)


def _command(name: bytes) -> int:
    return int.from_bytes(name, "little")


CNXN = _command(b"CNXN")
AUTH = _command(b"AUTH")
OPEN = _command(b"OPEN")
OKAY = _command(b"OKAY")
WRTE = _command(b"WRTE")
CLSE = _command(b"CLSE")

AUTH_TOKEN = 1
AUTH_SIGNATURE = 2
AUTH_RSAPUBLICKEY = 3

CLIENT_VERSION = 0x01000000
# Offered payload size; the TV answers with its own and the smaller one is used.
CLIENT_MAX_DATA = 256 * 1024
SYNC_DATA_MAX = 64 * 1024
BANNER = b"host::samstream"
KEY_COMMENT = " samstream@homeassistant"

_HEADER = struct.Struct("<6I")
_SYNC_HEADER = struct.Struct("<4sI")
_RSA_BITS = 2048
_RSA_WORDS = _RSA_BITS // 32

# sdbd sometimes drops a fresh connection mid-handshake, typically right after the
# previous one was torn down; a new socket a moment later works.
_CONNECT_ATTEMPTS = 3
_CONNECT_RETRY_DELAY = 0.4
_DUID_ATTEMPTS = 3
_INSTALL_FAILED = re.compile(
    r"install failed\[(?P<code>[^\]]*)\][^\n]*?(?:reason:\s*(?P<reason>.*))?$"
)


def generate_key() -> bytes:
    """Create an RSA key for the AUTH handshake, as PKCS#8 PEM (store and reuse it)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=_RSA_BITS)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def android_public_key(key: rsa.RSAPrivateKey) -> bytes:
    """Public key in Android's `RSAPublicKey` struct layout (what sdbd expects).

    uint32 words, uint32 n0inv, uint32 n[64] (LE), uint32 rr[64] (LE), uint32 e.
    """
    numbers = key.public_key().public_numbers()
    modulus = numbers.n
    word = 1 << 32
    n0inv = (word - pow(modulus % word, -1, word)) % word
    rr = pow(1 << _RSA_BITS, 2, modulus)
    return (
        struct.pack("<II", _RSA_WORDS, n0inv)
        + modulus.to_bytes(_RSA_BITS // 8, "little")
        + rr.to_bytes(_RSA_BITS // 8, "little")
        + struct.pack("<I", numbers.e)
    )


@dataclass
class _Stream:
    """One OPEN'd service on the connection."""

    local_id: int
    service: str
    remote_id: int = 0
    closed: bool = False
    opened: asyncio.Event = field(default_factory=asyncio.Event)
    acked: asyncio.Event = field(default_factory=asyncio.Event)
    incoming: asyncio.Queue[bytes | None] = field(default_factory=asyncio.Queue)
    buffer: bytearray = field(default_factory=bytearray)

    async def read_exactly(self, size: int) -> bytes:
        while len(self.buffer) < size:
            chunk = await self.incoming.get()
            if chunk is None:
                msg = f"sdb stream {self.service!r} closed early"
                raise SdbError(msg)
            self.buffer += chunk
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    async def read_all(self) -> bytes:
        while (chunk := await self.incoming.get()) is not None:
            self.buffer += chunk
        data = bytes(self.buffer)
        self.buffer.clear()
        return data


@dataclass(frozen=True)
class InstallResult:
    """Outcome of `vd_appinstall`; `lines` is the TV's own progress log."""

    app_id: str
    lines: list[str]


class SdbClient:
    """Connection to one TV's sdbd. Use as `async with SdbClient(...) as sdb:`."""

    def __init__(
        self,
        host: str,
        key_pem: bytes,
        *,
        port: int = SDB_PORT,
        timeout: float = 10.0,
    ) -> None:
        """Prepare a connection authenticated with `key_pem` (see generate_key)."""
        self.host = host
        self.port = port
        self.timeout = timeout
        loaded = serialization.load_pem_private_key(key_pem, password=None)
        if not isinstance(loaded, rsa.RSAPrivateKey):
            msg = "sdb key must be an RSA private key"
            raise TypeError(msg)
        self._key = loaded
        self.max_data = 4096
        self.banner = ""
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pump: asyncio.Task[None] | None = None
        self._streams: dict[int, _Stream] = {}
        self._next_id = 1
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        """Connect and authenticate."""
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the connection."""
        await self.close()

    async def connect(self) -> None:
        """Connect, retrying the handshake a few times."""
        for attempt in range(_CONNECT_ATTEMPTS):
            try:
                await self._connect_once()
            except (OSError, asyncio.IncompleteReadError, TimeoutError) as err:
                await self._drop()
                if attempt == _CONNECT_ATTEMPTS - 1:
                    msg = (
                        f"Cannot open sdb on {self.host}:{self.port}. Is Developer "
                        "Mode on with this machine's IP as the host?"
                    )
                    raise SdbConnectionError(msg) from err
                await asyncio.sleep(_CONNECT_RETRY_DELAY)
            else:
                return

    async def close(self) -> None:
        """Close all streams and the socket."""
        await self._drop()

    async def shell(self, command: str) -> str:
        """Run one sdbd shell verb (e.g. `0 getduid`) and return its output."""
        stream = await self._open(f"shell:{command}")
        try:
            async with asyncio.timeout(self.timeout * 6):
                output = await stream.read_all()
        finally:
            await self._close_stream(stream)
        return output.decode(errors="replace")

    async def capability(self) -> dict[str, str]:
        """Device facts, e.g. `platform_version`, `sdk_toolpath`, `cpu_arch`."""
        stream = await self._open("capability:")
        try:
            async with asyncio.timeout(self.timeout):
                raw = (await stream.read_all()).decode(errors="replace")
        finally:
            await self._close_stream(stream)
        facts: dict[str, str] = {}
        for line in re.split(r"[\n\x00]", raw):
            key, sep, value = line.partition(":")
            if sep and key.strip():
                facts[key.strip()] = value.strip()
        return facts

    async def duid(self) -> str:
        """Read the DUID a Samsung distributor certificate must list for this TV."""
        reply = ""
        for _ in range(_DUID_ATTEMPTS):
            # The first reply after connecting is sometimes empty or truncated.
            reply = (await self.shell("0 getduid")).strip()
            if re.fullmatch(r"[A-Za-z0-9._-]{8,}", reply):
                return reply
        msg = f"No DUID from {self.host} (got {reply!r})"
        raise SdbError(msg)

    async def push(self, data: bytes, remote_path: str) -> None:
        """Write `data` to `remote_path` with the sync protocol."""
        stream = await self._open("sync:")
        try:
            # Unlike ADB, Samsung's SEND carries only the path, no ",mode" suffix.
            await self._sync_send(stream, b"SEND", remote_path.encode())
            for offset in range(0, len(data), SYNC_DATA_MAX):
                await self._sync_send(
                    stream, b"DATA", data[offset : offset + SYNC_DATA_MAX]
                )
            await self._sync_send(stream, b"DONE", struct.pack("<I", int(time.time())))
            async with asyncio.timeout(self.timeout * 3):
                status, length = _SYNC_HEADER.unpack(await stream.read_exactly(8))
                if status != b"OKAY":
                    reason = (await stream.read_exactly(length)).decode(
                        errors="replace"
                    )
                    msg = f"sdb push to {remote_path} failed: {reason}"
                    raise SdbError(msg)
        finally:
            await self._close_stream(stream)

    async def install(
        self,
        wgt: bytes,
        app_id: str,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> InstallResult:
        """Push a signed .wgt to the TV's temp dir and run `vd_appinstall`."""
        tool_path = (await self.capability()).get(
            "sdk_toolpath", "/home/owner/share/tmp/sdk_tools"
        )
        # sdbd splits the command on whitespace, so keep the file name plain.
        remote_path = f"{tool_path}/samstream-install.wgt"
        await self.push(wgt, remote_path)
        output = await self.shell(f"0 vd_appinstall {app_id} {remote_path}")
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        for line in lines:
            _LOGGER.debug("vd_appinstall: %s", line)
            if on_line is not None:
                on_line(line)
        for index, line in enumerate(lines):
            if failure := _INSTALL_FAILED.search(line):
                # The TV continues the reason on the next line(s).
                reason = (failure.group("reason") or failure.group("code")).strip()
                rest = " ".join(lines[index + 1 : index + 2])
                msg = f"Install of {app_id} failed: {reason} {rest}".strip()
                raise SdbError(msg)
        if not any("install completed" in line for line in lines):
            tail = " | ".join(lines[-3:])
            msg = f"Install of {app_id} did not report completion: {tail}"
            raise SdbError(msg)
        return InstallResult(app_id=app_id, lines=lines)

    async def uninstall(self, app_id: str) -> str:
        """Remove an app; sdbd needs the full app ID (`SmStrm0001.Samstream`).

        With only the package ID the TV answers "was get app info failed".
        """
        return await self.shell(f"0 vd_appuninstall {app_id}")

    async def app_list(self) -> str:
        """Return the raw `vd_applist` listing."""
        return await self.shell("0 vd_applist")

    async def installed_apps(self) -> list[ListedApp]:
        """Every visible installed app, including ones no catalog knows."""
        listing = await self.app_list()
        apps = parse_app_list(listing)
        if not apps and "apps count: 0" not in listing:
            msg = f"No app listing from {self.host}"
            raise SdbError(msg)
        return apps

    # --- connection internals -------------------------------------------------

    async def _connect_once(self) -> None:
        async with asyncio.timeout(self.timeout):
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port
            )
            await self._send(CNXN, CLIENT_VERSION, CLIENT_MAX_DATA, BANNER)
            signed = False
            while True:
                command, arg0, arg1, payload = await self._read_frame()
                if command == CNXN:
                    self.max_data = min(CLIENT_MAX_DATA, arg1 or self.max_data)
                    self.banner = payload.decode(errors="replace").strip("\x00")
                    break
                if command != AUTH:
                    msg = f"Unexpected sdb frame {command:#x} during handshake"
                    raise SdbError(msg)
                if arg0 == AUTH_TOKEN and not signed:
                    # Samsung sdbd verifies a SHA-1/PKCS#1 v1.5 signature of the token.
                    sha1 = hashes.SHA1()  # noqa: S303  # fixed by the protocol
                    signature = self._key.sign(payload, padding.PKCS1v15(), sha1)
                    await self._send(AUTH, AUTH_SIGNATURE, 0, signature)
                    signed = True
                else:
                    # Signature not accepted (or the TV asks for it): offer the key.
                    blob = base64.b64encode(android_public_key(self._key))
                    await self._send(
                        AUTH,
                        AUTH_RSAPUBLICKEY,
                        0,
                        blob + KEY_COMMENT.encode() + b"\x00",
                    )
        self._pump = asyncio.create_task(self._pump_frames(), name=f"sdb {self.host}")

    async def _drop(self) -> None:
        pump, self._pump = self._pump, None
        if pump is not None:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pump
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        for stream in self._streams.values():
            self._mark_closed(stream)
        self._streams.clear()

    async def _send(
        self, command: int, arg0: int, arg1: int, payload: bytes = b""
    ) -> None:
        if self._writer is None:
            msg = "sdb is not connected"
            raise SdbError(msg)
        header = _HEADER.pack(
            command,
            arg0,
            arg1,
            len(payload),
            sum(payload) & 0xFFFFFFFF,
            command ^ 0xFFFFFFFF,
        )
        async with self._write_lock:
            self._writer.write(header + payload)
            await self._writer.drain()

    async def _read_frame(self) -> tuple[int, int, int, bytes]:
        if self._reader is None:
            msg = "sdb is not connected"
            raise SdbError(msg)
        command, arg0, arg1, length, _checksum, magic = _HEADER.unpack(
            await self._reader.readexactly(_HEADER.size)
        )
        if magic != command ^ 0xFFFFFFFF:
            msg = "Corrupt sdb frame header"
            raise SdbError(msg)
        payload = await self._reader.readexactly(length) if length else b""
        return command, arg0, arg1, payload

    async def _pump_frames(self) -> None:
        """Route frames to streams until the connection ends."""
        try:
            while True:
                command, arg0, arg1, payload = await self._read_frame()
                stream = self._streams.get(arg1)
                if stream is None:
                    continue
                if command == OKAY:
                    if not stream.remote_id:
                        stream.remote_id = arg0
                        stream.opened.set()
                    else:
                        stream.acked.set()
                elif command == WRTE:
                    stream.incoming.put_nowait(payload)
                    await self._send(OKAY, stream.local_id, stream.remote_id)
                elif command == CLSE:
                    self._mark_closed(stream)
        except (asyncio.IncompleteReadError, OSError, SdbError) as err:
            _LOGGER.debug("sdb connection to %s ended: %s", self.host, err)
        finally:
            for stream in self._streams.values():
                self._mark_closed(stream)

    @staticmethod
    def _mark_closed(stream: _Stream) -> None:
        if not stream.closed:
            stream.closed = True
            stream.incoming.put_nowait(None)
        stream.opened.set()
        stream.acked.set()

    async def _open(self, service: str) -> _Stream:
        if self._pump is None or self._pump.done():
            await self.connect()
        stream = _Stream(local_id=self._next_id, service=service)
        self._next_id += 1
        self._streams[stream.local_id] = stream
        await self._send(OPEN, stream.local_id, 0, service.encode() + b"\x00")
        try:
            async with asyncio.timeout(self.timeout):
                await stream.opened.wait()
        except TimeoutError as err:
            self._streams.pop(stream.local_id, None)
            msg = f"TV did not open sdb service {service!r}"
            raise SdbError(msg) from err
        if not stream.remote_id:
            self._streams.pop(stream.local_id, None)
            msg = f"TV refused sdb service {service!r}"
            raise SdbError(msg)
        return stream

    async def _write_stream(self, stream: _Stream, data: bytes) -> None:
        for offset in range(0, len(data), self.max_data):
            if stream.closed:
                msg = f"sdb stream {stream.service!r} closed while writing"
                raise SdbError(msg)
            stream.acked.clear()
            await self._send(
                WRTE,
                stream.local_id,
                stream.remote_id,
                data[offset : offset + self.max_data],
            )
            async with asyncio.timeout(self.timeout):
                await stream.acked.wait()

    async def _sync_send(self, stream: _Stream, tag: bytes, payload: bytes) -> None:
        await self._write_stream(stream, _SYNC_HEADER.pack(tag, len(payload)) + payload)

    async def _close_stream(self, stream: _Stream) -> None:
        self._streams.pop(stream.local_id, None)
        if not stream.closed and stream.remote_id and self._writer is not None:
            with contextlib.suppress(OSError, SdbError):
                await self._send(CLSE, stream.local_id, stream.remote_id)
        self._mark_closed(stream)
