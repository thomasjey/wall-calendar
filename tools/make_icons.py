"""Draws the app icons (static/icons/*.png): a cute animal peeking over a
calendar, on the page's dark background. Standard library only and
deterministic, like the package build. Opaque (iOS fills transparent touch
icons with black); iOS rounds the corners.

    python tools/make_icons.py                  # the chosen animal, into static/icons
    python tools/make_icons.py --preview DIR    # every animal at 512 px, for choosing
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "icons"
SIZES = {"icon-32.png": 32, "apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}
ANIMAL = "bunny"

BG = (0x1D, 0x27, 0x38)      # the page background (app.css)
PAPER = (0xF4, 0xF6, 0xFA)
HEADER = (0x7F, 0xB3, 0xFF)  # Home calendar blue
CELL = (0xC9, 0xD3, 0xE3)
TODAY = (0xEF, 0x9F, 0x27)   # Work calendar orange
INK = (0x2A, 0x23, 0x2E)     # eyes
SHINE = (0xFF, 0xFF, 0xFF)
BLUSH = (0xF7, 0xB2, 0xC4)
NOSE = (0xE8, 0x7A, 0x96)

# Shapes in unit coordinates, painted in order:
#   ("rect", x0, y0, x1, y1, corner radius, colour)
#   ("ellipse", cx, cy, rx, ry, colour)


def _calendar() -> list[tuple]:
    shapes = [("rect", 0.15, 0.52, 0.85, 0.90, 0.07, PAPER), ("rect", 0.15, 0.52, 0.85, 0.64, 0.07, HEADER),
              ("rect", 0.15, 0.59, 0.85, 0.64, 0.0, HEADER)]
    for r in range(2):
        for c in range(4):
            x0, y0 = 0.24 + c * 0.14, 0.69 + r * 0.10
            shapes.append(("rect", x0, y0, x0 + 0.09, y0 + 0.065, 0.016, TODAY if (r, c) == (1, 2) else CELL))
    return shapes


def _face(fur: tuple, cy: float = 0.43) -> list[tuple]:
    """Eyes with a shine, a small nose and rosy cheeks: the part that makes it cute."""
    return [("ellipse", 0.40, cy + 0.06, 0.045, 0.03, BLUSH), ("ellipse", 0.60, cy + 0.06, 0.045, 0.03, BLUSH),
            ("ellipse", 0.43, cy, 0.03, 0.036, INK), ("ellipse", 0.57, cy, 0.03, 0.036, INK),
            ("ellipse", 0.44, cy - 0.013, 0.011, 0.011, SHINE), ("ellipse", 0.58, cy - 0.013, 0.011, 0.011, SHINE),
            ("ellipse", 0.50, cy + 0.045, 0.022, 0.015, NOSE)]


def _paws(fur: tuple, shade: tuple) -> list[tuple]:
    return [("ellipse", 0.37, 0.535, 0.065, 0.045, fur), ("ellipse", 0.63, 0.535, 0.065, 0.045, fur),
            ("ellipse", 0.37, 0.55, 0.03, 0.018, shade), ("ellipse", 0.63, 0.55, 0.03, 0.018, shade)]


def _fluff(cx: float, cy: float, rx: float, ry: float, fur: tuple, tufts: int = 14) -> list[tuple]:
    """A soft, fluffy outline: small round tufts all around the head."""
    import math

    out = []
    for i in range(tufts):
        a = 2 * math.pi * i / tufts
        out.append(("ellipse", cx + rx * 0.93 * math.cos(a), cy + ry * 0.93 * math.sin(a), rx * 0.24, ry * 0.24, fur))
    return out + [("ellipse", cx, cy, rx, ry, fur)]


def _bunny() -> list[tuple]:
    fur, inner = (0xFB, 0xF7, 0xF5), (0xF6, 0xC2, 0xD0)
    return ([("ellipse", 0.39, 0.19, 0.075, 0.17, fur), ("ellipse", 0.61, 0.19, 0.075, 0.17, fur),
             ("ellipse", 0.39, 0.21, 0.035, 0.12, inner), ("ellipse", 0.61, 0.21, 0.035, 0.12, inner)]
            + _fluff(0.50, 0.44, 0.21, 0.17, fur) + _calendar() + _paws(fur, inner) + _face(fur))


def _kitten() -> list[tuple]:
    fur, inner, stripe = (0xF6, 0xC8, 0x8C), (0xF7, 0xB2, 0xC4), (0xE4, 0xA5, 0x62)
    ears = [("ellipse", 0.33, 0.27, 0.09, 0.10, fur), ("ellipse", 0.67, 0.27, 0.09, 0.10, fur),
            ("ellipse", 0.34, 0.285, 0.045, 0.055, inner), ("ellipse", 0.66, 0.285, 0.045, 0.055, inner)]
    stripes = [("ellipse", 0.50, 0.30, 0.02, 0.05, stripe), ("ellipse", 0.44, 0.31, 0.015, 0.04, stripe),
               ("ellipse", 0.56, 0.31, 0.015, 0.04, stripe)]
    return ears + _fluff(0.50, 0.43, 0.23, 0.17, fur) + stripes + _calendar() + _paws(fur, inner) + _face(fur)


def _bear() -> list[tuple]:
    fur, inner, muzzle = (0xC8, 0x95, 0x6A), (0xA8, 0x74, 0x4E), (0xEE, 0xD6, 0xBE)
    ears = [("ellipse", 0.32, 0.29, 0.08, 0.08, fur), ("ellipse", 0.68, 0.29, 0.08, 0.08, fur),
            ("ellipse", 0.32, 0.29, 0.04, 0.04, inner), ("ellipse", 0.68, 0.29, 0.04, 0.04, inner)]
    return (ears + _fluff(0.50, 0.43, 0.22, 0.17, fur) + [("ellipse", 0.50, 0.48, 0.07, 0.05, muzzle)]
            + _calendar() + _paws(fur, inner) + _face(fur))


def _hamster() -> list[tuple]:
    fur, belly, inner = (0xF2, 0xB8, 0x6E), (0xFF, 0xF1, 0xDE), (0xF6, 0xC2, 0xD0)
    ears = [("ellipse", 0.34, 0.30, 0.06, 0.06, fur), ("ellipse", 0.66, 0.30, 0.06, 0.06, fur),
            ("ellipse", 0.34, 0.30, 0.03, 0.03, inner), ("ellipse", 0.66, 0.30, 0.03, 0.03, inner)]
    return (ears + _fluff(0.50, 0.44, 0.25, 0.17, fur, tufts=18)
            + [("ellipse", 0.50, 0.50, 0.15, 0.08, belly)] + _calendar() + _paws(belly, inner) + _face(fur))


def _puppy() -> list[tuple]:
    fur, ear, patch, muzzle = (0xF3, 0xD2, 0x9E), (0xB0, 0x74, 0x48), (0xD9, 0xA8, 0x70), (0xFF, 0xF4, 0xE4)
    ears = [("ellipse", 0.29, 0.43, 0.075, 0.15, ear), ("ellipse", 0.71, 0.43, 0.075, 0.15, ear)]
    head = _fluff(0.50, 0.42, 0.20, 0.17, fur) + [("ellipse", 0.57, 0.405, 0.055, 0.05, patch),
                                                  ("ellipse", 0.50, 0.48, 0.08, 0.05, muzzle)]
    flaps = [("ellipse", 0.30, 0.46, 0.065, 0.13, ear), ("ellipse", 0.70, 0.46, 0.065, 0.13, ear)]
    return ears + head + flaps + _calendar() + _paws(fur, ear) + _face(fur)


def _fluffy_puppy() -> list[tuple]:
    fur, ear, shade = (0xFB, 0xF8, 0xF4), (0xE6, 0xD2, 0xB8), (0xEC, 0xE4, 0xDA)
    ears = (_fluff(0.29, 0.47, 0.085, 0.15, ear, tufts=10) + _fluff(0.71, 0.47, 0.085, 0.15, ear, tufts=10))
    bow = [("ellipse", 0.56, 0.255, 0.045, 0.03, BLUSH), ("ellipse", 0.64, 0.255, 0.045, 0.03, BLUSH),
           ("ellipse", 0.60, 0.255, 0.018, 0.018, NOSE)]
    return (ears + _fluff(0.50, 0.42, 0.20, 0.18, fur, tufts=18) + bow
            + _calendar() + _paws(fur, shade) + _face(fur))


ANIMALS = {"bunny": _bunny, "kitten": _kitten, "bear": _bear, "hamster": _hamster,
           "puppy": _puppy, "fluffy puppy": _fluffy_puppy}


def _covers(shape: tuple, x: float, y: float) -> bool:
    if shape[0] == "rect":
        _, x0, y0, x1, y1, rad, _ = shape
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        cx = min(max(x, x0 + rad), x1 - rad)
        cy = min(max(y, y0 + rad), y1 - rad)
        return (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad
    _, cx, cy, rx, ry, _ = shape
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def _span(shape: tuple) -> tuple[float, float]:
    return (shape[2], shape[4]) if shape[0] == "rect" else (shape[2] - shape[4], shape[2] + shape[4])


def _render(size: int, animal: str = ANIMAL) -> list[bytes]:
    shapes = [(s, _span(s), s[-1]) for s in ANIMALS[animal]()]
    ss = 4 if size <= 192 else 2  # samples per pixel per axis, for smooth edges
    n = size * ss
    rows = []
    for py in range(size):
        acc = [[0, 0, 0] for _ in range(size)]
        for sy in range(ss):
            y = (py * ss + sy + 0.5) / n
            row_shapes = [(s, col) for s, (lo, hi), col in shapes if lo <= y <= hi]
            for px in range(size):
                for sx in range(ss):
                    x = (px * ss + sx + 0.5) / n
                    colour = BG
                    for s, col in row_shapes:
                        if _covers(s, x, y):
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


def main(argv: list[str]) -> int:
    if argv[:1] == ["--preview"] and len(argv) == 2:
        out = Path(argv[1])
        out.mkdir(parents=True, exist_ok=True)
        for animal in ANIMALS:
            for size in (512, 32):
                (out / f"{animal}-{size}.png").write_bytes(_png(size, _render(size, animal)))
        print(f"previews in {out}")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        (OUT / name).write_bytes(_png(size, _render(size)))
        print(f"wrote static/icons/{name} ({size}x{size})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
