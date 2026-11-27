"""Draw the corner camera's frame images for the notifier (no dependencies).

    uv run python scripts/make_pip_frames.py

One PNG per size in tv-app/notifier-dotnet/res/frames/: a thin rounded white line
with dark edges and a drop shadow, transparent in the middle. The TV lays it over
the square camera picture, which gives the picture rounded corners
(NUI's own corner radius is not available on older TVs).
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tv-app/notifier-dotnet/res/frames"
# Must match CornerCamera.cs.
SIZES = {"small": (480, 270), "medium": (640, 360), "large": (880, 495)}
MARGIN = 32  # canvas around the picture: line, then shadow
RING = 6
OUTER_RADIUS = 22
INNER_RADIUS = 16  # the picture's visible corners
DARK = (11, 20, 32)
WHITE = (236, 240, 244)


def distance(
    x: float, y: float, box: tuple[float, float, float, float], r: float
) -> float:
    """Signed distance to a rounded rectangle (negative inside)."""
    left, top, right, bottom = box
    dx = abs(x - (left + right) / 2) - (right - left) / 2 + r
    dy = abs(y - (top + bottom) / 2) - (bottom - top) / 2 + r
    outside = math.hypot(max(dx, 0), max(dy, 0))
    return outside + min(max(dx, dy), 0) - r


def clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def over(base: tuple, colour: tuple, alpha: float) -> tuple:
    """Lay `colour` at `alpha` over a straight-alpha pixel."""
    r, g, b, a = base
    out = alpha + a * (1 - alpha)
    if out <= 0:
        return (0, 0, 0, 0.0)
    mix = [
        (c * alpha + p * a * (1 - alpha)) / out
        for c, p in zip(colour, (r, g, b), strict=True)
    ]
    return (*mix, out)


def pixel(x: float, y: float, width: int, height: int) -> tuple:
    video = (MARGIN, MARGIN, MARGIN + width, MARGIN + height)
    outer = (video[0] - RING, video[1] - RING, video[2] + RING, video[3] + RING)
    d_out = distance(x, y, outer, OUTER_RADIUS)
    inside_picture = clamp(0.5 - distance(x, y, video, INNER_RADIUS))
    inside_frame = clamp(0.5 - d_out)
    result = (0, 0, 0, 0.0)
    if inside_frame < 1:
        reach = MARGIN - RING
        shadow = distance(x, y - 7, outer, OUTER_RADIUS)
        fade = clamp(1 - max(shadow, 0) / reach)
        result = over(result, (0, 0, 0), 0.55 * fade**2 * (1 - inside_frame))
    ring = inside_frame * (1 - inside_picture)
    if ring > 0:
        depth = -d_out
        line = clamp(depth - 0.5) * clamp(RING - 0.5 - depth)
        colour = tuple(d + (w - d) * line for d, w in zip(DARK, WHITE, strict=True))
        result = over(result, colour, ring)
    return result


def png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (width, height) in SIZES.items():
        full_w, full_h = width + 2 * MARGIN, height + 2 * MARGIN
        clear = bytes(4)
        rows = []
        for j in range(full_h):
            row = bytearray()
            for i in range(full_w):
                # The middle of the picture is always transparent: skip the maths.
                edge = MARGIN + INNER_RADIUS
                if edge <= i < full_w - edge and edge <= j < full_h - edge:
                    row += clear
                    continue
                r, g, b, a = pixel(i + 0.5, j + 0.5, width, height)
                row += bytes((round(r), round(g), round(b), round(a * 255)))
            rows.append(bytes(row))
        target = OUT / f"{name}.png"
        png(target, full_w, full_h, rows)
        print(f"{target.name}: {full_w}x{full_h}, {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
