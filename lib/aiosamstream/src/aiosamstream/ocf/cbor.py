"""The small CBOR subset OCF uses: ints, strings, bytes, lists, maps, bools, null.

The TV's stack (IoTivity, OIC 1.1) sends nothing else except an occasional
float, so this avoids a dependency for a few dozen lines.
"""

from __future__ import annotations

import struct
from typing import Any

_UINT, _NINT, _BYTES, _TEXT, _ARRAY, _MAP, _TAG, _SIMPLE = range(8)
_INDEFINITE = 31
_BREAK = 0xFF
_FALSE, _TRUE, _NULL, _UNDEFINED = 20, 21, 22, 23
_HALF, _SINGLE, _DOUBLE = 25, 26, 27
_ONE_BYTE, _TWO_BYTES, _FOUR_BYTES, _EIGHT_BYTES = 24, 25, 26, 27
_TINY = 24
_U8, _U16, _U32 = 0x100, 0x10000, 0x100000000
MAX_DEPTH = 32  # nesting limit: a hostile peer must not exhaust the stack


class CborError(ValueError):
    """Malformed or unsupported CBOR."""


def _head(major: int, value: int) -> bytes:
    if value < _TINY:
        return bytes([major << 5 | value])
    if value < _U8:
        return bytes([major << 5 | _ONE_BYTE, value])
    if value < _U16:
        return bytes([major << 5 | _TWO_BYTES]) + struct.pack(">H", value)
    if value < _U32:
        return bytes([major << 5 | _FOUR_BYTES]) + struct.pack(">I", value)
    return bytes([major << 5 | _EIGHT_BYTES]) + struct.pack(">Q", value)


def dumps(value: Any) -> bytes:  # noqa: PLR0911
    """Encode a value."""
    if value is True:
        return b"\xf5"
    if value is False:
        return b"\xf4"
    if value is None:
        return b"\xf6"
    if isinstance(value, int):
        return _head(_UINT, value) if value >= 0 else _head(_NINT, -1 - value)
    if isinstance(value, float):
        return b"\xfb" + struct.pack(">d", value)
    if isinstance(value, bytes | bytearray):
        return _head(_BYTES, len(value)) + bytes(value)
    if isinstance(value, str):
        raw = value.encode()
        return _head(_TEXT, len(raw)) + raw
    if isinstance(value, list | tuple):
        return _head(_ARRAY, len(value)) + b"".join(dumps(item) for item in value)
    if isinstance(value, dict):
        return _head(_MAP, len(value)) + b"".join(
            dumps(key) + dumps(item) for key, item in value.items()
        )
    msg = f"cannot encode {type(value).__name__} as CBOR"
    raise CborError(msg)


def loads(data: bytes) -> Any:
    """Decode one value (trailing bytes are ignored, as the TV pads some replies)."""
    try:
        value, _ = _decode(data, 0, 0)
    except (IndexError, struct.error, RecursionError) as err:
        msg = "truncated or malformed CBOR"
        raise CborError(msg) from err
    return value


def _argument(data: bytes, pos: int, info: int) -> tuple[int, int]:
    if info < _TINY:
        return info, pos
    sizes = {_ONE_BYTE: 1, _TWO_BYTES: 2, _FOUR_BYTES: 4, _EIGHT_BYTES: 8}
    size = sizes.get(info)
    if size is None:
        msg = f"unsupported CBOR additional info {info}"
        raise CborError(msg)
    if pos + size > len(data):
        raise IndexError(pos)
    return int.from_bytes(data[pos : pos + size], "big"), pos + size


def _decode(data: bytes, pos: int, depth: int) -> tuple[Any, int]:  # noqa: C901, PLR0911
    if depth > MAX_DEPTH:
        msg = "CBOR nested too deeply"
        raise CborError(msg)
    initial = data[pos]
    major, info = initial >> 5, initial & 0x1F
    pos += 1
    if major == _SIMPLE:
        return _simple(data, pos, info)
    if info == _INDEFINITE:
        return _indefinite(data, pos, major, depth)
    value, pos = _argument(data, pos, info)
    if major == _UINT:
        return value, pos
    if major == _NINT:
        return -1 - value, pos
    if major in (_BYTES, _TEXT):
        if pos + value > len(data):
            raise IndexError(pos)
        raw = data[pos : pos + value]
        text = raw.decode(errors="replace") if major == _TEXT else bytes(raw)
        return text, pos + value
    if major == _ARRAY:
        items = []
        for _ in range(value):
            item, pos = _decode(data, pos, depth + 1)
            items.append(item)
        return items, pos
    if major == _MAP:
        mapping: dict[Any, Any] = {}
        for _ in range(value):
            key, pos = _decode(data, pos, depth + 1)
            mapping[key], pos = _decode(data, pos, depth + 1)
        return mapping, pos
    # Tags (major 6): the value is what matters here.
    return _decode(data, pos, depth + 1)


def _simple(data: bytes, pos: int, info: int) -> tuple[Any, int]:
    if info == _FALSE:
        return False, pos
    if info == _TRUE:
        return True, pos
    if info in (_NULL, _UNDEFINED):
        return None, pos
    if info == _HALF:
        return struct.unpack(">e", data[pos : pos + 2])[0], pos + 2
    if info == _SINGLE:
        return struct.unpack(">f", data[pos : pos + 4])[0], pos + 4
    if info == _DOUBLE:
        return struct.unpack(">d", data[pos : pos + 8])[0], pos + 8
    msg = f"unsupported CBOR simple value {info}"
    raise CborError(msg)


def _indefinite(data: bytes, pos: int, major: int, depth: int) -> tuple[Any, int]:
    if major == _ARRAY:
        items = []
        while data[pos] != _BREAK:
            item, pos = _decode(data, pos, depth + 1)
            items.append(item)
        return items, pos + 1
    if major == _MAP:
        mapping: dict[Any, Any] = {}
        while data[pos] != _BREAK:
            key, pos = _decode(data, pos, depth + 1)
            mapping[key], pos = _decode(data, pos, depth + 1)
        return mapping, pos + 1
    if major in (_BYTES, _TEXT):
        chunks = []
        while data[pos] != _BREAK:
            chunk, pos = _decode(data, pos, depth + 1)
            chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
        joined = b"".join(chunks)
        return (joined.decode(errors="replace") if major == _TEXT else joined), pos + 1
    msg = f"indefinite length not allowed for major type {major}"
    raise CborError(msg)
