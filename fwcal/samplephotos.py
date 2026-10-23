"""Sample background photos for mock mode: flat layered landscapes drawn with the
standard library, so mock mode needs no personal photos and no downloads."""

from __future__ import annotations

import math
import random
import struct
import zlib
from pathlib import Path

from .store import atomic_write

W, H = 540, 960

# sky bands (top to bottom), sun, ridge layers (far to near)
_PALETTES = {
    "dusk": ([(86, 112, 160), (128, 146, 184), (214, 168, 150)], (250, 236, 200),
             [(96, 106, 140), (72, 82, 116), (52, 62, 92), (34, 42, 66)]),
    "forest": ([(120, 170, 196), (156, 196, 210), (206, 222, 214)], (250, 246, 220),
               [(110, 150, 132), (78, 118, 96), (54, 92, 70), (34, 64, 46)]),
    "desert": ([(214, 140, 104), (236, 176, 128), (250, 214, 168)], (255, 244, 214),
               [(196, 118, 90), (164, 92, 74), (124, 66, 58), (82, 42, 42)]),
    "lake": ([(70, 120, 180), (110, 156, 204), (170, 200, 224)], (240, 244, 250),
             [(88, 120, 156), (64, 96, 132), (44, 72, 104), (26, 46, 70)]),
}


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _image(name: str, seed: int) -> bytes:
    sky, sun, layers = _PALETTES[name]
    rnd = random.Random(seed)
    ridges: list[list[int]] = []
    for i in range(len(layers)):
        base = H * (0.42 + 0.12 * i)
        amp, freq, phase = 60 - 8 * i, 0.006 + 0.004 * i, rnd.random() * 6.28
        jag = [rnd.uniform(-1, 1) for _ in range(W // 30 + 2)]
        row = []
        for x in range(W):
            j = jag[x // 30] + (jag[x // 30 + 1] - jag[x // 30]) * (x % 30) / 30
            y = int(base + amp * math.sin(x * freq + phase) + 18 * j)
            row.append(max(y, ridges[-1][x] + 4) if ridges else y)
        ridges.append(row)
    sx, sy, sr = rnd.randint(90, W - 90), rnd.randint(140, 260), 46
    px = [bytes(c) for c in sky] + [bytes(c) for c in layers] + [bytes(sun)]
    rows = []
    for y in range(H):
        band = min(len(sky) - 1, y * len(sky) * 2 // H)
        out = []
        for x in range(W):
            n = 0
            for r in ridges:
                if y >= r[x]:
                    n += 1
            if n:
                out.append(px[len(sky) + n - 1])
            elif (x - sx) ** 2 + (y - sy) ** 2 <= sr * sr:
                out.append(px[-1])
            else:
                out.append(px[band])
        rows.append(b"".join(out))
    return _png(W, H, rows)


def ensure(dest: Path) -> Path:
    """Writes the sample set into `dest` once."""
    dest.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(_PALETTES):
        path = dest / f"sample-{name}.png"
        if not path.exists():
            atomic_write(path, _image(name, i), 0o644)
    return dest
