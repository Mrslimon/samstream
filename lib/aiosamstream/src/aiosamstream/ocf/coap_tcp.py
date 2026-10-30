"""CoAP over TCP/TLS framing (RFC 8323), as the TV's OCF cloud client speaks it.

Each message is `len|tkl`, an extended length, the code, the token, then the
options and an optional `0xFF` + payload. There are no message ids or ACKs
(TCP is reliable); signalling codes 7.xx carry CSM, ping and pong.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

GET, POST, PUT, DELETE = 0x01, 0x02, 0x03, 0x04
CREATED, VALID, CHANGED, CONTENT = 0x41, 0x43, 0x44, 0x45
BAD_REQUEST, UNAUTHORIZED, NOT_FOUND = 0x80, 0x81, 0x84
CSM, PING, PONG, RELEASE, ABORT = 0xE1, 0xE2, 0xE3, 0xE4, 0xE5

OBSERVE, URI_PATH, CONTENT_FORMAT, URI_QUERY, ACCEPT = 6, 11, 12, 15, 17
CSM_MAX_MESSAGE_SIZE = 2
CBOR_FORMAT = 60

MAX_FRAME = 1 << 20  # refuse anything bigger: the TV's largest reply is ~100 kB
_MAX_TOKEN = 8
_EXT1, _EXT2, _EXT4 = 13, 14, 15
_BASE1, _BASE2, _BASE4 = 13, 269, 65805
_PAYLOAD_MARKER = 0xFF


class CoapError(ValueError):
    """A malformed or oversized frame; the connection should be dropped."""


def code_text(code: int) -> str:
    """`0x45` as `2.05`."""
    return f"{code >> 5}.{code & 0x1F:02d}"


def code_value(text: str) -> int:
    """`2.05` as `0x45`."""
    major, _, minor = text.partition(".")
    return (int(major) << 5) | int(minor or 0)


def is_request(code: int) -> bool:
    """Tell whether a code is a method, 0.01-0.31 (GET, POST, ...)."""
    return 0 < code < 0x20  # noqa: PLR2004


def is_success(code: int) -> bool:
    """Tell whether a code is a 2.xx response."""
    return code >> 5 == 2  # noqa: PLR2004


@dataclass(frozen=True, slots=True)
class Message:
    """One CoAP message; options are (number, value) pairs in any order."""

    code: int
    token: bytes = b""
    options: tuple[tuple[int, bytes], ...] = field(default=())
    payload: bytes = b""

    def values(self, number: int) -> list[bytes]:
        """All values of one option, in order."""
        return [value for num, value in self.options if num == number]

    def has(self, number: int) -> bool:
        """Whether the option is present (Observe may be empty)."""
        return any(num == number for num, _ in self.options)

    @property
    def path(self) -> str:
        """The Uri-Path as `/a/b`."""
        return "/" + "/".join(
            seg.decode(errors="replace") for seg in self.values(URI_PATH)
        )


def uint(value: int) -> bytes:
    """Encode an option uint: big-endian, no leading zero bytes (0 is empty)."""
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def path_options(href: str) -> list[tuple[int, bytes]]:
    """Uri-Path and Uri-Query options for `/a/b?x=1`."""
    path, _, query = href.partition("?")
    out = [(URI_PATH, seg.encode()) for seg in path.split("/") if seg]
    out += [(URI_QUERY, item.encode()) for item in query.split("&") if item]
    return out


def _nibble(value: int) -> tuple[int, bytes]:
    if value < _BASE1:
        return value, b""
    if value < _BASE2:
        return _EXT1, bytes([value - _BASE1])
    return _EXT2, struct.pack(">H", value - _BASE2)


def encode_body(options: tuple[tuple[int, bytes], ...], payload: bytes) -> bytes:
    """Options (delta-encoded, in order) and `0xFF` + payload: shared with UDP."""
    body = bytearray()
    last = 0
    for number, value in sorted(options, key=lambda item: item[0]):
        delta, delta_ext = _nibble(number - last)
        length, length_ext = _nibble(len(value))
        body += bytes([delta << 4 | length]) + delta_ext + length_ext + value
        last = number
    if payload:
        body += bytes([_PAYLOAD_MARKER]) + payload
    return bytes(body)


def encode(message: Message) -> bytes:
    """Serialise one message."""
    if len(message.token) > _MAX_TOKEN:
        msg = "token longer than 8 bytes"
        raise CoapError(msg)
    body = encode_body(message.options, message.payload)
    size = len(body)
    tkl = len(message.token)
    if size < _BASE1:
        head = bytes([size << 4 | tkl])
    elif size < _BASE2:
        head = bytes([_EXT1 << 4 | tkl, size - _BASE1])
    elif size < _BASE4:
        head = bytes([_EXT2 << 4 | tkl]) + struct.pack(">H", size - _BASE2)
    else:
        head = bytes([_EXT4 << 4 | tkl]) + struct.pack(">I", size - _BASE4)
    return head + bytes([message.code]) + message.token + bytes(body)


def _option_field(body: bytes, pos: int, nibble: int) -> tuple[int, int]:
    if nibble < _EXT1:
        return nibble, pos
    if nibble == _EXT1:
        return body[pos] + _BASE1, pos + 1
    if nibble == _EXT2:
        return struct.unpack_from(">H", body, pos)[0] + _BASE2, pos + 2
    msg = "reserved option nibble 15"
    raise CoapError(msg)


def parse_body(body: bytes) -> tuple[tuple[tuple[int, bytes], ...], bytes]:
    """Split options and payload (the inverse of `encode_body`)."""
    options: list[tuple[int, bytes]] = []
    pos = number = 0
    try:
        while pos < len(body):
            if body[pos] == _PAYLOAD_MARKER:
                return tuple(options), body[pos + 1 :]
            delta, length = body[pos] >> 4, body[pos] & 0x0F
            delta, pos = _option_field(body, pos + 1, delta)
            length, pos = _option_field(body, pos, length)
            if pos + length > len(body):
                msg = "option runs past the frame"
                raise CoapError(msg)
            number += delta
            options.append((number, body[pos : pos + length]))
            pos += length
    except (IndexError, struct.error) as err:
        msg = "truncated option"
        raise CoapError(msg) from err
    return tuple(options), b""


class FrameReader:
    """Accumulate TCP bytes and yield whole messages."""

    def __init__(self, max_frame: int = MAX_FRAME) -> None:
        """Start with an empty buffer."""
        self._buffer = bytearray()
        self._max = max_frame

    def feed(self, data: bytes) -> list[Message]:
        """Add received bytes; return every message now complete."""
        self._buffer += data
        out = []
        while (message := self._take()) is not None:
            out.append(message)
        return out

    def _header(self) -> tuple[int, int] | None:
        """(header length, body length) once the length bytes are in."""
        buf = self._buffer
        nibble = buf[0] >> 4
        sizes = {_EXT1: (1, _BASE1), _EXT2: (2, _BASE2), _EXT4: (4, _BASE4)}
        if nibble not in sizes:
            return 1, nibble
        extra, base = sizes[nibble]
        if len(buf) < 1 + extra:
            return None
        return 1 + extra, int.from_bytes(buf[1 : 1 + extra], "big") + base

    def _take(self) -> Message | None:
        buf = self._buffer
        if not buf:
            return None
        header = self._header()
        if header is None:
            return None
        head, size = header
        tkl = buf[0] & 0x0F
        if tkl > _MAX_TOKEN:
            msg = "token length over 8"
            raise CoapError(msg)
        total = head + 1 + tkl + size
        if total > self._max:
            msg = f"frame of {total} bytes is over the limit"
            raise CoapError(msg)
        if len(buf) < total:
            return None
        code = buf[head]
        token = bytes(buf[head + 1 : head + 1 + tkl])
        options, payload = parse_body(bytes(buf[head + 1 + tkl : total]))
        del buf[:total]
        return Message(code, token, options, payload)
