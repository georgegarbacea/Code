"""Generate the LumiBeat Studio icon (PNG + multi-size ICO) with Pillow.

Design: dark glass tile, 6 + 6 glowing neon bars (the wall's profiles, shaped like a
symmetric equalizer) around a small central flame (the fireplace).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def gradient_color(t: float):
    stops = [(124, 92, 255), (34, 211, 238), (255, 79, 163)]
    if t < 0.5:
        return lerp(stops[0], stops[1], t * 2)
    return lerp(stops[1], stops[2], (t - 0.5) * 2)


def make(size: int = S) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # tile background with vertical gradient
    bg = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(bg)
    for y in range(size):
        t = y / size
        d.line([(0, y), (size, y)], fill=lerp((22, 16, 48, 255), (6, 7, 14, 255), t))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([size * 0.04, size * 0.04, size * 0.96, size * 0.96], radius=size * 0.22, fill=255)
    img.paste(bg, (0, 0), mask)

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bars = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    bd = ImageDraw.Draw(bars)
    cx = size / 2
    base = size * 0.74
    heights = [0.30, 0.42, 0.36, 0.52, 0.44, 0.34]      # outer -> inner
    bw = size * 0.034
    spacing = size * 0.058
    gap = size * 0.25
    for side in (-1, 1):
        for k in range(6):
            x = cx + side * (gap / 2 + (5 - k) * spacing)
            h = heights[k] * size
            col = gradient_color(k / 5 if side < 0 else 1 - k / 5)
            top = base - h
            gd.rounded_rectangle([x - bw * 1.6, top - bw, x + bw * 1.6, base + bw], radius=bw * 1.6, fill=col + (160,))
            # bar body with vertical fade
            for i in range(int(h)):
                t = i / max(1, h)
                c = lerp(col, (255, 255, 255), max(0.0, 0.35 - t) * 1.2)
                bd.line([(x - bw / 2, base - i), (x + bw / 2, base - i)], fill=c + (255,))
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.035))
    img = Image.alpha_composite(img, Image.composite(glow, Image.new("RGBA", (size, size), (0, 0, 0, 0)), mask))
    bars_m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(bars_m).rectangle([0, 0, size, size], fill=255)
    rounded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rounded.paste(bars, (0, 0), bars)
    img = Image.alpha_composite(img, rounded)

    # central flame (fireplace)
    fl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fl)
    fw, fh = size * 0.13, size * 0.24
    fy = base
    pts = []
    for i in range(41):
        a = i / 40 * math.pi
        r = math.sin(a)
        x = cx - math.cos(a) * fw * (0.55 + 0.45 * r)
        y = fy - r ** 0.7 * fh * (1 - 0.15 * math.cos(a * 3))
        pts.append((x, y))
    pts = [(cx - fw, fy)] + pts + [(cx + fw, fy)]
    fd.polygon(pts, fill=(255, 120, 30, 255))
    inner = [(cx + (x - cx) * 0.55, fy - (fy - y) * 0.62) for x, y in pts]
    fd.polygon(inner, fill=(255, 214, 120, 255))
    flg = fl.filter(ImageFilter.GaussianBlur(size * 0.03))
    img = Image.alpha_composite(img, flg)
    img = Image.alpha_composite(img, fl.filter(ImageFilter.GaussianBlur(size * 0.004)))
    # mantel line
    ld = ImageDraw.Draw(img)
    ld.rounded_rectangle([cx - size * 0.12, base + size * 0.03, cx + size * 0.12, base + size * 0.045],
                         radius=size * 0.008, fill=(230, 232, 245, 220))
    # glass highlight
    hl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse([-size * 0.3, -size * 0.75, size * 1.3, size * 0.32], fill=(255, 255, 255, 18))
    img = Image.alpha_composite(img, Image.composite(hl, Image.new("RGBA", (size, size), (0, 0, 0, 0)), mask))
    edge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle([size * 0.04, size * 0.04, size * 0.96, size * 0.96], radius=size * 0.22,
                                           outline=(255, 255, 255, 40), width=max(1, size // 200))
    img = Image.alpha_composite(img, edge)
    return img


def main() -> None:
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    big = make(S)
    big.save(out / "icon.png")
    big.resize((256, 256), Image.LANCZOS).save(out / "icon_256.png")
    big.resize((192, 192), Image.LANCZOS).save(ROOT / "lumibeat" / "web" / "static" / "icon.png")
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    big.save(out / "icon.ico", sizes=sizes)
    # installer sidebar / header images (Inno Setup)
    side = Image.new("RGB", (164, 314), (8, 9, 16))
    ic = big.resize((120, 120), Image.LANCZOS)
    side.paste(ic, (22, 40), ic)
    side.save(out / "installer_side.bmp")
    small = Image.new("RGB", (55, 58), (8, 9, 16))
    ic2 = big.resize((48, 48), Image.LANCZOS)
    small.paste(ic2, (4, 5), ic2)
    small.save(out / "installer_small.bmp")
    print("icons written to", out)


if __name__ == "__main__":
    sys.exit(main())
