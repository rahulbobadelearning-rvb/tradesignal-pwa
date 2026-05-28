#!/usr/bin/env python3
"""
Generate TradeSignal PWA icons (192x192 and 512x512) using only stdlib.
Draws a candlestick chart pattern on a dark background.
"""
import struct
import zlib
import math
import os

# ── Brand colours ──────────────────────────────────────────
BG    = (10,  14,  26)      # #0a0e1a
TEAL  = (0,  212, 170)      # #00d4aa
RED   = (255,  75,  75)     # #ff4b4b
WHITE = (255, 255, 255)

def lerp(a, b, t):
    return a + (b - a) * t

def distance_sq(x1, y1, x2, y2):
    return (x1 - x2) ** 2 + (y1 - y2) ** 2

# ── Per-pixel renderer ──────────────────────────────────────
def get_pixel(px, py, size):
    """Return (R, G, B) for pixel (px, py) in an icon of `size` x `size`."""
    nx = px / size   # 0.0 – 1.0
    ny = py / size

    # ── Rounded-rect background (radius = 22% of size) ──
    r_frac = 0.22
    ox = max(r_frac, min(1 - r_frac, nx))
    oy = max(r_frac, min(1 - r_frac, ny))
    d = math.sqrt((nx - ox) ** 2 + (ny - oy) ** 2)
    if d > r_frac:
        return (0, 0, 0)    # transparent / outside icon

    # ── Subtle inner background gradient ──
    mix = (nx * 0.3 + (1 - ny) * 0.1)
    bg = tuple(min(255, int(BG[i] + mix * 20)) for i in range(3))

    # ── Chart bounds ──
    left   = 0.10
    right  = 0.90
    bottom = 0.82
    top    = 0.14

    # Candle data  [x_center, body_low, body_high, wick_low, wick_high, bullish]
    # Prices increase left → right (overall bullish trend)
    bar_hw = 0.065     # half-width of body
    wick_w = 0.012     # half-width of wick

    candles = [
        # cx,  body_lo, body_hi, wick_lo, wick_hi, bull
        (0.20, 0.65, 0.52, 0.72, 0.46, False),
        (0.38, 0.50, 0.35, 0.55, 0.30, True),
        (0.56, 0.38, 0.22, 0.42, 0.17, True),
        (0.75, 0.26, 0.12, 0.30, 0.08, True),
    ]

    for (cx, bl, bh, wl, wh, bull) in candles:
        color = TEAL if bull else RED
        # Map chart-relative coords to screen
        scx = left + cx * (right - left)
        sy_bl = top + bl * (bottom - top)
        sy_bh = top + bh * (bottom - top)
        sy_wl = top + wl * (bottom - top)
        sy_wh = top + wh * (bottom - top)

        body_x0, body_x1 = scx - bar_hw, scx + bar_hw
        wick_x0, wick_x1 = scx - wick_w, scx + wick_w

        # Body (solid rectangle)
        if body_x0 <= nx <= body_x1 and sy_bh <= ny <= sy_bl:
            # Anti-alias outer edge
            edge = min(
                nx - body_x0, body_x1 - nx,
                ny - sy_bh,   sy_bl - ny
            ) * size
            alpha = min(1.0, edge * 1.5)
            if alpha > 0:
                return tuple(int(lerp(bg[i], color[i], alpha)) for i in range(3))

        # Wick (thin line above and below body)
        if wick_x0 <= nx <= wick_x1:
            if sy_wh <= ny < sy_bh or sy_bl < ny <= sy_wl:
                edge = min(nx - wick_x0, wick_x1 - nx) * size
                alpha = min(1.0, edge * 3)
                if alpha > 0:
                    return tuple(int(lerp(bg[i], color[i], alpha)) for i in range(3))

    # ── Trend line through candle tops ──
    pts = [
        (left + 0.20 * (right - left), top + 0.52 * (bottom - top)),
        (left + 0.38 * (right - left), top + 0.35 * (bottom - top)),
        (left + 0.56 * (right - left), top + 0.22 * (bottom - top)),
        (left + 0.75 * (right - left), top + 0.12 * (bottom - top)),
    ]
    line_w = 0.010
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        # Point-to-segment distance
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((nx - x1) * dx + (ny - y1) * dy) / (dx * dx + dy * dy)))
        cx2 = x1 + t * dx
        cy2 = y1 + t * dy
        dist = math.sqrt((nx - cx2) ** 2 + (ny - cy2) ** 2)
        if dist < line_w:
            alpha = max(0.0, 1.0 - dist / line_w) * 0.35
            r = int(lerp(bg[0], WHITE[0], alpha))
            g = int(lerp(bg[1], WHITE[1], alpha))
            b = int(lerp(bg[2], WHITE[2], alpha))
            return (r, g, b)

    return bg

# ── PNG encoder ─────────────────────────────────────────────
def make_chunk(ctype: bytes, data: bytes) -> bytes:
    c = ctype + data
    return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

def create_png(size: int) -> bytes:
    # IHDR: width, height, bit-depth=8, colour-type=2 (RGB), compression=0, filter=0, interlace=0
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)

    # Build raw scanlines
    rows = bytearray()
    for y in range(size):
        rows.append(0)          # filter type: None
        for x in range(size):
            r, g, b = get_pixel(x, y, size)
            rows += bytes([r, g, b])

    idat = zlib.compress(bytes(rows), 9)

    return (
        b'\x89PNG\r\n\x1a\n'
        + make_chunk(b'IHDR', ihdr)
        + make_chunk(b'IDAT', idat)
        + make_chunk(b'IEND', b'')
    )

# ── Main ────────────────────────────────────────────────────
if __name__ == '__main__':
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'tradesignal')
    os.makedirs(out_dir, exist_ok=True)

    for size, name in [(192, 'icon-192.png'), (512, 'icon-512.png')]:
        print(f'Generating {name} ({size}×{size})…', end=' ', flush=True)
        png = create_png(size)
        path = os.path.join(out_dir, name)
        with open(path, 'wb') as f:
            f.write(png)
        print(f'done  ({len(png):,} bytes)')

    print('Icons written to tradesignal/')
