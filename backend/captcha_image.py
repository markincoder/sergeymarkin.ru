# -*- coding: utf-8 -*-
"""PNG-капча в классическом виде: цветные буквы, линии, круги, шум."""
from __future__ import annotations

import math
import secrets
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent
CAPTCHA_WIDTH = 220
CAPTCHA_HEIGHT = 72
CAPTCHA_LENGTH = 5
# Латиница и цифры без похожих 0/O/1/I.
CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_BG = (244, 245, 241)
_LETTER_COLORS = (
    (48, 92, 62),
    (110, 72, 42),
    (62, 108, 112),
    (86, 86, 70),
    (70, 82, 58),
)
_NOISE_COLORS = (
    (196, 92, 86),
    (72, 148, 96),
    (90, 92, 98),
    (186, 168, 92),
    (140, 150, 130),
    (120, 88, 140),
)

_FONT_CANDIDATES = (
    BASE_DIR / "static" / "fonts" / "DejaVuSans-Bold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
)


def random_code(length: int = CAPTCHA_LENGTH) -> str:
    return "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(length))


def normalize_code(value: str) -> str:
    return "".join((value or "").split()).upper()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _wave(im: Image.Image) -> Image.Image:
    w, h = im.size
    amp = 1.6
    period = secrets.choice((22, 24, 26, 28))
    out = Image.new("RGB", im.size, _BG)
    src = im.load()
    dst = out.load()
    for y in range(h):
        shift = int(amp * math.sin(2 * math.pi * y / period))
        for x in range(w):
            nx = x + shift
            if 0 <= nx < w:
                dst[x, y] = src[nx, y]
    return out


def render_png(code: str) -> bytes:
    im = Image.new("RGB", (CAPTCHA_WIDTH, CAPTCHA_HEIGHT), _BG)
    draw = ImageDraw.Draw(im)

    for _ in range(3):
        color = secrets.choice(_NOISE_COLORS)
        x1, y1 = secrets.randbelow(CAPTCHA_WIDTH), secrets.randbelow(CAPTCHA_HEIGHT)
        x2, y2 = secrets.randbelow(CAPTCHA_WIDTH), secrets.randbelow(CAPTCHA_HEIGHT)
        draw.line((x1, y1, x2, y2), fill=color, width=1)

    for _ in range(2):
        color = secrets.choice(_NOISE_COLORS)
        x = secrets.randbelow(CAPTCHA_WIDTH) - 8
        y = secrets.randbelow(CAPTCHA_HEIGHT) - 8
        rw = secrets.randbelow(36) + 20
        rh = secrets.randbelow(18) + 10
        draw.ellipse((x, y, x + rw, y + rh), outline=color, width=1)

    for _ in range(28):
        x, y = secrets.randbelow(CAPTCHA_WIDTH), secrets.randbelow(CAPTCHA_HEIGHT)
        draw.point((x, y), fill=secrets.choice(_NOISE_COLORS))

    n = max(len(code), 1)
    slot = CAPTCHA_WIDTH / (n + 0.35)
    for i, ch in enumerate(code):
        size = secrets.choice((34, 36, 38))
        font = _font(size)
        glyph = Image.new("RGBA", (58, 66), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glyph)
        gdraw.text((4, 2), ch, font=font, fill=(*secrets.choice(_LETTER_COLORS), 255))
        angle = secrets.randbelow(17) - 8
        glyph = glyph.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        x = int(slot * i + 10) + secrets.randbelow(3) - 1
        y = secrets.randbelow(8) + 8
        im.paste(glyph, (x, y), glyph)

    im = _wave(im)
    im = im.filter(ImageFilter.SMOOTH)
    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
