"""Write placeholder icons (replace them with real artwork; see docs/icons.md).

    uv run python scripts/make_placeholder_icons.py

A dark rounded tile with an accent "play" mark, in the TV app palette. Pure
Python (zlib PNG) so it runs without Pillow.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKGROUND = (0x0B, 0x14, 0x20)
SURFACE = (0x1A, 0x26, 0x36)
ACCENT = (0x3A, 0x9B, 0xD9)

# (path, width, height, transparent corners outside the tile)
TARGETS = [
    ("custom_components/samstream/brand/icon.png", 256, 256, True),
    ("custom_components/samstream/brand/icon@2x.png", 512, 512, True),
    ("custom_components/samstream/brand/logo.png", 256, 256, True),
    ("custom_components/samstream/brand/logo@2x.png", 512, 512, True),
    ("tv-app/public/icon.png", 512, 423, False),
]


def _inside_rounded(x: float, y: float, w: int, h: int, radius: float) -> bool:
    cx = min(max(x, radius), w - radius)
    cy = min(max(y, radius), h - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _inside_play(x: float, y: float, w: int, h: int) -> bool:
    """Right-pointing triangle centred in the tile."""
    size = min(w, h) * 0.42
    left, top = w / 2 - size * 0.38, h / 2 - size / 2
    if not (left <= x <= left + size * 0.86 and top <= y <= top + size):
        return False
    progress = (x - left) / (size * 0.86)
    half = (1 - progress) * size / 2
    return abs(y - h / 2) <= half


def render(w: int, h: int, *, transparent: bool) -> bytes:
    radius = min(w, h) * 0.18
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # PNG filter: none
        for x in range(w):
            if transparent and not _inside_rounded(x + 0.5, y + 0.5, w, h, radius):
                rows += bytes((0, 0, 0, 0))
                continue
            if _inside_play(x + 0.5, y + 0.5, w, h):
                color = ACCENT
            else:
                color = SURFACE if transparent else BACKGROUND
            rows += bytes((*color, 255))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    for relative, w, h, transparent in TARGETS:
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render(w, h, transparent=transparent))
        print(f"wrote {relative} ({w}x{h})")


if __name__ == "__main__":
    main()
