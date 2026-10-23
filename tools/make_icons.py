"""Draws the app icons (static/icons/*.png): a calendar on the page's dark
background, its header in the Home calendar's blue and today's square in the
Work orange. Standard library only and deterministic, like the package build.
Opaque (iOS fills transparent touch icons with black); iOS rounds the corners.

    python tools/make_icons.py
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "icons"
SIZES = {"icon-32.png": 32, "apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}

BG = (0x1D, 0x27, 0x38)      # the page background (app.css)
PAPER = (0xF4, 0xF6, 0xFA)
HEADER = (0x7F, 0xB3, 0xFF)  # Home calendar blue
RING = (0xC9, 0xD3, 0xE3)
CELL = (0xC9, 0xD3, 0xE3)
TODAY = (0xEF, 0x9F, 0x27)   # Work calendar orange

# Shapes in unit coordinates, painted in order: (x0, y0, x1, y1, corner radius, colour).
SHAPES = [(0.17, 0.25, 0.83, 0.83, 0.07, PAPER), (0.17, 0.25, 0.83, 0.41, 0.07, HEADER),
          (0.17, 0.34, 0.83, 0.41, 0.0, HEADER)]
SHAPES += [(cx - 0.03, 0.16, cx + 0.03, 0.31, 0.03, RING) for cx in (0.34, 0.66)]
_COLS, _ROWS = 4, 3
for r in range(_ROWS):
    for c in range(_COLS):
        x0, y0 = 0.25 + c * 0.13, 0.48 + r * 0.11
        SHAPES.append((x0, y0, x0 + 0.08, y0 + 0.07, 0.015, TODAY if (r, c) == (1, 2) else CELL))


def _inside(x: float, y: float, x0: float, y0: float, x1: float, y1: float, rad: float) -> bool:
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + rad), x1 - rad)
    cy = min(max(y, y0 + rad), y1 - rad)
    return (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad


def _render(size: int) -> list[bytes]:
    ss = 4 if size <= 192 else 2  # samples per pixel per axis, for smooth edges
    n = size * ss
    rows = []
    for py in range(size):
        acc = [[0, 0, 0] for _ in range(size)]
        for sy in range(ss):
            y = (py * ss + sy + 0.5) / n
            row_shapes = [s for s in SHAPES if s[1] <= y <= s[3]]
            for px in range(size):
                for sx in range(ss):
                    x = (px * ss + sx + 0.5) / n
                    colour = BG
                    for x0, y0, x1, y1, rad, col in row_shapes:
                        if _inside(x, y, x0, y0, x1, y1, rad):
                            colour = col
                    a = acc[px]
                    a[0] += colour[0]
                    a[1] += colour[1]
                    a[2] += colour[2]
        k = ss * ss
        rows.append(bytes(round(v / k) for a in acc for v in a))
    return rows


def _png(size: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        (OUT / name).write_bytes(_png(size, _render(size)))
        print(f"wrote static/icons/{name} ({size}x{size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
