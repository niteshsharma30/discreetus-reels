"""Still-image alternative to the Reel (DAILY_FORMAT=card): a 1080x1350 JPEG with one line of text,
using the same palettes and fonts as media_reels.py."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from config import SETTINGS
from media_reels import MEDIA_DIR, PALETTES, _font, _text_sprite

W, H = 1080, 1350


def render_card(text: str, palette: str, name: str) -> Path:
    top, bottom, key, accent, _ = PALETTES.get(palette, PALETTES["midnight"])
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):                                   # vertical gradient
        t = y / H
        d.line((0, y, W, y), fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    img = img.convert("RGBA")

    line = _text_sprite(text, _font("CormorantGaramond-Italic.ttf", 76, 400), (245, 240, 235),
                        glow=key, max_w=int(W * 0.8))
    img.alpha_composite(line, ((W - line.width) // 2, int(H * 0.42 - line.height / 2)))
    logo = _text_sprite(SETTINGS.brand_name, _font("Inter.ttf", 54, 250), (255, 255, 255), tracking=18)
    img.alpha_composite(logo, ((W - logo.width) // 2, int(H * 0.80 - logo.height / 2)))
    soon = _text_sprite("COMING SOON", _font("Inter.ttf", 24, 400), accent, tracking=10)
    img.alpha_composite(soon, ((W - soon.width) // 2, int(H * 0.86 - soon.height / 2)))

    MEDIA_DIR.mkdir(exist_ok=True)
    path = MEDIA_DIR / f"{name}.jpg"
    img.convert("RGB").save(path, "JPEG", quality=92)
    return path
