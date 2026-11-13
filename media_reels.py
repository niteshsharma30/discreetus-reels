"""Free cinematic Reels: renders a 9:16 animated MP4 (with an ambient soundtrack) from a short script.

No video AI and no editing tool: every frame is drawn in Python and encoded with ffmpeg (bundled
by the imageio-ffmpeg package). The look follows prompts/instagram_prompt.md: dark atmospheric
light, abstract silhouettes, slow camera, film grain, elegant type, and a quiet brand reveal.

A script looks like:
    {"lines": ["Everyone is looking.", "Not everyone should see you."],
     "end_line": "Something new is coming.", "motif": "two_figures", "palette": "midnight"}

Motifs:   two_figures  two silhouettes drift toward each other; a thread of light joins them
          window       one figure backlit by a glowing city window, slow push-in
          orbit        two lights circle closer and merge into one
          veil         a figure behind frosted glass slowly comes into focus
Palettes: midnight, dusk, rose, teal
"""
from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from config import ROOT, SETTINGS

MEDIA_DIR = ROOT / "media"
FONT_DIR = ROOT / "fonts"
W, H, FPS = 1080, 1920, 24
LW, LH = 270, 480            # low-res grid for soft light (upscaled, so it's smooth and fast)

MOTIFS = ["two_figures", "window", "orbit", "veil"]
PALETTES = {
    #            bg top         bg bottom      key light        accent           drone root (Hz)
    "midnight": ((6, 8, 22),    (20, 14, 44),  (110, 100, 255), (255, 170, 120), 110.0),
    "dusk":     ((16, 8, 14),   (48, 18, 32),  (255, 110, 80),  (255, 205, 150), 98.0),
    "rose":     ((14, 6, 14),   (42, 10, 32),  (255, 80, 150),  (190, 160, 255), 116.5),
    "teal":     ((3, 12, 16),   (8, 32, 38),   (50, 200, 190),  (255, 190, 120), 87.3),
}


# ---------------------------------------------------------------- helpers

def _font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    if not path.exists():
        return ImageFont.load_default(size=size)
    f = ImageFont.truetype(str(path), size)
    if weight is not None:
        try:
            axes = f.get_variation_axes()
            f.set_variation_by_axes([weight if a["minimum"] <= weight <= a["maximum"] and a["maximum"] > 100
                                     else a["default"] for a in axes])
        except Exception:
            pass
    return f


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _lerp(a, b, t):
    return a + (b - a) * t


def _glow(cx: float, cy: float, sigma: float, color, strength: float = 1.0,
          sx: float = 1.0, sy: float = 1.0) -> np.ndarray:
    """Soft radial light on the low-res grid. Positions and sigma are fractions of the width."""
    ys, xs = np.mgrid[0:LH, 0:LW].astype(np.float32)
    dx = (xs / LW - cx) / sx
    dy = (ys / LW - cy * LH / LW) / sy
    g = np.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma)) * strength
    return g[..., None] * np.array(color, np.float32)[None, None, :]


def _to_full(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").resize((W, H), Image.BILINEAR)


def _text_sprite(text: str, font, fill, tracking: int = 0, glow=None, max_w: int = int(W * 0.8)):
    """Render centred, optionally letter-spaced text once, with a soft glow, as an RGBA sprite."""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))

    def line_w(s):
        return sum(probe.textlength(c, font=font) for c in s) + tracking * max(0, len(s) - 1)

    lines: list[str] = []
    for word in text.split():
        if lines and line_w(lines[-1] + " " + word) <= max_w:
            lines[-1] += " " + word
        else:
            lines.append(word)
    lines = lines or [""]
    # avoid a lonely last word: pull one word down from the line above
    if len(lines) > 1 and " " not in lines[-1] and " " in lines[-2]:
        head, _, last = lines[-2].rpartition(" ")
        lines[-2], lines[-1] = head, last + " " + lines[-1]

    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.18)
    pad = 60
    sw = int(max(line_w(l) for l in lines)) + 2 * pad
    sh = lh * len(lines) + 2 * pad
    mask = Image.new("L", (sw, sh), 0)
    d = ImageDraw.Draw(mask)
    for i, l in enumerate(lines):
        x = (sw - line_w(l)) / 2
        for c in l:
            d.text((x, pad + i * lh), c, font=font, fill=255)
            x += probe.textlength(c, font=font) + tracking
    sprite = Image.new("RGBA", (sw, sh), fill + (0,))
    if glow:
        halo = mask.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.55))
        sprite = Image.composite(Image.new("RGBA", (sw, sh), glow + (255,)), sprite, halo)
        sprite.putalpha(halo)
    solid = Image.new("RGBA", (sw, sh), fill + (255,))
    solid.putalpha(mask)
    return Image.alpha_composite(sprite, solid)


def _place(frame: Image.Image, sprite: Image.Image, cx: int, cy: int, alpha: float) -> None:
    if alpha <= 0.01:
        return
    if alpha < 0.99:
        sprite = sprite.copy()
        sprite.putalpha(sprite.getchannel("A").point(lambda v: int(v * alpha)))
    frame.alpha_composite(sprite, (int(cx - sprite.width / 2), int(cy - sprite.height / 2)))


def _bust(height: int, hair: str = "short") -> Image.Image:
    """An abstract head-and-shoulders silhouette mask, drawn at 2x for smooth edges."""
    s = 2
    w, h = int(height * 0.9) * s, height * s
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    cx = w // 2
    hr = int(h * 0.125)                     # head radius
    hy = int(h * 0.24)                      # head centre
    if hair == "long":                      # hair falling to the shoulders
        d.ellipse((cx - hr * 1.12, hy - hr * 1.15, cx + hr * 1.12, hy + hr * 2.3), fill=255)
    d.ellipse((cx - hr * 0.92, hy - hr * 1.12, cx + hr * 0.92, hy + hr * 1.08), fill=255)
    nw = int(hr * 0.42)
    d.polygon([(cx - nw, hy + hr * 0.7), (cx + nw, hy + hr * 0.7),
               (cx + nw * 1.5, hy + hr * 2.05), (cx - nw * 1.5, hy + hr * 2.05)], fill=255)
    sy = int(hy + hr * 1.85)                # shoulders: a wide ellipse gives a natural slope
    d.ellipse((int(w * 0.04), sy, int(w * 0.96), sy + int(h * 0.95)), fill=255)
    return m.resize((w // s, h // s), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.2))


class _Figure:
    """A silhouette sprite with a coloured rim light, ready to paste each frame."""

    def __init__(self, height: int, hair: str, rim_color, mirror: bool = False):
        mask = _bust(height, hair)
        if mirror:
            mask = mask.transpose(Image.FLIP_LEFT_RIGHT)
        pad = 50
        big = Image.new("L", (mask.width + 2 * pad, mask.height + 2 * pad), 0)
        big.paste(mask, (pad, pad))
        # rim light: a soft band hugging the outline (blurred mask minus a slightly shrunk mask)
        edge = ImageChops.subtract(big.filter(ImageFilter.GaussianBlur(5)), ImageChops.invert(
            ImageChops.invert(big).filter(ImageFilter.MaxFilter(9))))
        self.mask = big
        self.rim = Image.merge("RGB", [edge.point(lambda v, c=c: int(v * c / 255 * 1.6)) for c in rim_color])
        self.body = Image.new("RGB", big.size, (3, 3, 6))

    def paste(self, frame: Image.Image, cx: float, bottom: float) -> None:
        x = int(cx - self.mask.width / 2)
        y = int(bottom - self.mask.height + 50)
        frame.paste(self.body, (x, y), self.mask)
        rim_full = Image.new("RGB", frame.size, (0, 0, 0))
        rim_full.paste(self.rim, (x, y))
        frame.paste(ImageChops.screen(frame, rim_full))


# ---------------------------------------------------------------- the renderer

def render_reel(script: dict, name: str) -> Path:
    """Render media/<name>.mp4 from a script dict and return its path."""
    lines = [l.strip() for l in script.get("lines", []) if l and l.strip()][:4] or ["Something is changing."]
    end_line = (script.get("end_line") or "Something new is coming.").strip()
    motif = script.get("motif") if script.get("motif") in MOTIFS else MOTIFS[0]
    palette = script.get("palette") if script.get("palette") in PALETTES else "midnight"
    top, bottom, key, accent, root = PALETTES[palette]
    rng = random.Random(name)

    line_slot, intro, outro = 3.1, 1.0, 4.6
    T = intro + line_slot * len(lines) + outro
    n_frames = int(T * FPS)
    logo_t = intro + line_slot * len(lines)

    # --- static layers
    grad = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    base = Image.fromarray(((1 - grad) * np.array(top, np.float32) + grad * np.array(bottom, np.float32))
                           .repeat(W, axis=1).astype(np.uint8), "RGB")
    ys, xs = np.mgrid[0:LH, 0:LW].astype(np.float32)
    vig = 1 - 0.75 * np.clip(((xs / LW - 0.5) ** 2 * 1.6 + (ys / LH - 0.5) ** 2 * 1.9) * 1.7, 0, 1)
    vignette = Image.fromarray((vig * 255).astype(np.uint8), "L").resize((W, H), Image.BILINEAR).convert("RGB")
    grains = []
    for _ in range(6):
        g = np.random.default_rng(rng.randint(0, 10 ** 6)).normal(128, 38, (H // 2, W // 2)).clip(0, 255)
        grains.append(Image.fromarray(g.astype(np.uint8), "L").resize((W, H), Image.NEAREST).convert("RGB"))

    particles = [dict(x=rng.random(), y=rng.random(), r=rng.uniform(1.2, 5.5), vx=rng.uniform(-0.004, 0.004),
                      vy=rng.uniform(-0.012, -0.002), ph=rng.uniform(0, 6.28), warm=rng.random() < 0.35)
                 for _ in range(55)]

    # Fonts and text sprites
    serif = _font("CormorantGaramond-Italic.ttf", 84, 400)
    line_sprites = [_text_sprite(l, serif, (245, 240, 235), tracking=1, glow=key) for l in lines]
    logo = _text_sprite(SETTINGS.brand_name, _font("Inter.ttf", 78, 250), (255, 255, 255), tracking=26, glow=key)
    end_sprite = _text_sprite(end_line, _font("CormorantGaramond-Italic.ttf", 54, 400), (230, 225, 220), glow=None)
    soon = _text_sprite("COMING SOON", _font("Inter.ttf", 26, 400), accent, tracking=12)

    fig_h = int(H * 0.40)
    figs = {
        "two_figures": [_Figure(fig_h, "short", key), _Figure(int(fig_h * 0.94), "long", accent, mirror=True)],
        "window": [_Figure(int(fig_h * 1.05), "long", accent)],
        "veil": [_Figure(int(H * 0.5), "long", key)],
    }.get(motif, [])
    text_y = {"two_figures": 0.27, "window": 0.13, "orbit": 0.22, "veil": 0.17}[motif]
    window_lights = [(rng.uniform(0.27, 0.73), rng.uniform(0.30, 0.56), rng.uniform(1.0, 3.2), rng.random())
                     for _ in range(70)]
    trail: list[tuple[float, float, int]] = []

    ffmpeg = _ffmpeg_exe()
    MEDIA_DIR.mkdir(exist_ok=True)
    out = MEDIA_DIR / f"{name}.mp4"
    proc = subprocess.Popen(
        [ffmpeg, "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-f", "lavfi", "-i", _soundtrack(T, root, logo_t),
         "-map", "0:v", "-map", "1:a", "-shortest",
         "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "7M", "-bufsize", "14M",
         "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out)],
        stdin=subprocess.PIPE,
    )

    for i in range(n_frames):
        t = i / FPS
        p = t / T
        end_dim = 1 - 0.55 * _ease((t - logo_t) / 1.2)          # scene dims for the logo
        light = np.zeros((LH, LW, 3), np.float32)
        breathe = 0.85 + 0.15 * math.sin(t * 0.9)

        # --- scene lighting per motif
        if motif == "two_figures":
            light += _glow(0.5, 0.66, 0.30, key, 0.75 * breathe, sx=1.3)
            light += _glow(0.5, 0.95, 0.20, accent, 0.25)
        elif motif == "window":
            light += _glow(0.5, 0.43, 0.22, accent, 0.55 * breathe, sx=1.1, sy=1.5)
            light += _glow(0.5, 0.43, 0.10, (255, 240, 220), 0.35)
        elif motif == "orbit":
            light += _glow(0.5, 0.64, 0.38, key, 0.30 * breathe)
            ang = t * (0.9 + p * 2.6)
            rad = 0.30 * (1 - _ease(min(1, t / (logo_t + 0.4))))
            for k, col in ((0, key), (math.pi, accent)):
                ox, oy = 0.5 + rad * math.cos(ang + k), 0.64 + rad * 0.55 * W / H * math.sin(ang + k)
                light += _glow(ox, oy, 0.035, col, 1.6)
                light += _glow(ox, oy, 0.11, col, 0.35)
                if i % 2 == 0:
                    trail.append((ox, oy, i))
            merge = _ease((t - logo_t + 0.6) / 1.0)
            if merge > 0:
                light += _glow(0.5, 0.64, 0.05 + 0.25 * merge, (255, 245, 235), 1.4 * merge * (1.2 - merge))
        elif motif == "veil":
            light += _glow(0.5, 0.55, 0.28, key, 0.8 * breathe, sy=1.3)
            sweep = (t * 0.16) % 1.6 - 0.3
            light += _glow(sweep, 0.40, 0.08, (255, 255, 255), 0.22, sx=0.6, sy=4.0)

        frame = ImageChops.screen(base, _to_full(light * end_dim))

        # --- dust / bokeh
        dust = Image.new("RGB", (W // 2, H // 2))
        dd = ImageDraw.Draw(dust)
        for q in particles:
            x = ((q["x"] + q["vx"] * t) % 1.0) * W / 2
            y = ((q["y"] + q["vy"] * t) % 1.0) * H / 2
            a = (0.45 + 0.55 * math.sin(t * 1.3 + q["ph"])) * 0.55 * end_dim
            c = accent if q["warm"] else key
            col = tuple(int(v * a) for v in c)
            r = q["r"]
            dd.ellipse((x - r, y - r, x + r, y + r), fill=col)
        frame = ImageChops.screen(frame, dust.filter(ImageFilter.GaussianBlur(1.6)).resize((W, H), Image.BILINEAR))

        # --- foreground motif
        if motif == "two_figures":
            m = _ease(p * 1.15)
            xa, xb = _lerp(0.17, 0.31, m) * W, _lerp(0.83, 0.69, m) * W
            thread = _ease((t - (intro + line_slot * 0.8)) / (line_slot * 1.6))
            if thread > 0:
                th = Image.new("RGB", (W // 2, H // 2))
                td = ImageDraw.Draw(th)
                yh = int((H - fig_h * 0.74) / 2)
                half = (xb - xa) / 2 * thread / 2 * 0.62
                mid = W / 4
                bright = tuple(int(c * (0.6 + 0.4 * math.sin(t * 2.2))) for c in (255, 235, 210))
                td.line((mid - half, yh, mid + half, yh), fill=bright, width=2)
                frame = ImageChops.screen(frame, th.filter(ImageFilter.GaussianBlur(3)).resize((W, H)))
                frame = ImageChops.screen(frame, th.resize((W, H)))
            figs[0].paste(frame, xa, H * 1.0)
            figs[1].paste(frame, xb, H * 1.0)
        elif motif == "window":
            wl = Image.new("RGB", (W // 2, H // 2))
            wd = ImageDraw.Draw(wl)
            for (lx, ly, lr, ph) in window_lights:
                a = (0.5 + 0.5 * math.sin(t * 0.8 + ph * 6.28)) * 0.8 * end_dim
                col = tuple(int(v * a) for v in (accent if ph < 0.6 else key))
                x, y, r = lx * W / 2, ly * H / 2, lr * 2.2
                wd.ellipse((x - r, y - r, x + r, y + r), fill=col)
            wl = wl.filter(ImageFilter.GaussianBlur(2.2)).resize((W, H), Image.BILINEAR)
            frame = ImageChops.screen(frame, wl)
            figs[0].paste(frame, W * 0.5, H * 1.0)
        elif motif == "orbit":
            if trail:
                tr = Image.new("RGB", (W // 2, H // 2))
                tdr = ImageDraw.Draw(tr)
                trail[:] = [q for q in trail if i - q[2] < 30]
                for (ox, oy, fi) in trail:
                    a = (1 - (i - fi) / 30) * 0.5 * end_dim
                    x, y = ox * W / 2, oy * H / 2
                    tdr.ellipse((x - 2, y - 2, x + 2, y + 2), fill=tuple(int(255 * a) for _ in range(3)))
                frame = ImageChops.screen(frame, tr.filter(ImageFilter.GaussianBlur(2)).resize((W, H)))
        elif motif == "veil":
            layer = frame.copy()
            figs[0].paste(layer, W * 0.5, H * 1.0)
            blur = _lerp(26, 1.5, _ease((t - 0.5) / (logo_t - 0.5)))
            small = layer.resize((W // 2, H // 2), Image.BILINEAR).filter(ImageFilter.GaussianBlur(blur / 2))
            frame = small.resize((W, H), Image.BILINEAR)

        # --- slow camera push-in
        zoom = 1.0 + 0.07 * _ease(p)
        if motif == "window":
            zoom = 1.0 + 0.12 * _ease(p)
        if zoom > 1.001:
            cw, ch = W / zoom, H / zoom
            x0, y0 = (W - cw) / 2, (H - ch) * 0.55
            frame = frame.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))

        frame = ImageChops.multiply(frame, vignette)

        # --- typography (after the camera move, so text stays still and crisp)
        rgba = frame.convert("RGBA")
        for k, spr in enumerate(line_sprites):
            s0 = intro + k * line_slot
            a = _ease((t - s0) / 0.9) * (1 - _ease((t - (s0 + line_slot - 0.7)) / 0.7))
            drift = (1 - _ease((t - s0) / 1.4)) * 26
            _place(rgba, spr, W // 2, int(H * text_y + drift), a)
        la = _ease((t - logo_t - 0.4) / 1.3)
        _place(rgba, logo, W // 2, int(H * 0.47 + (1 - la) * 14), la)
        _place(rgba, end_sprite, W // 2, int(H * 0.535), _ease((t - logo_t - 1.3) / 1.1))
        _place(rgba, soon, W // 2, int(H * 0.585), _ease((t - logo_t - 2.0) / 1.0))
        frame = rgba.convert("RGB")

        # --- film grain and fades
        frame = Image.blend(frame, grains[(i // 2) % len(grains)], 0.045)
        fade = min(_ease(t / 0.9), _ease((T - t) / 0.8))
        if fade < 0.999:
            frame = Image.blend(Image.new("RGB", (W, H)), frame, fade)
        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed to encode the Reel")
    return out


def _soundtrack(T: float, root: float, chime_t: float) -> str:
    """An ambient drone pad with slow swells and a soft chime at the logo, made by ffmpeg's synth."""
    r = root
    left = (f"0.05*sin(2*PI*{r}*t)*(0.6+0.4*sin(2*PI*0.07*t))"
            f"+0.035*sin(2*PI*{r * 1.5:.2f}*t)*(0.5+0.5*sin(2*PI*0.05*t+1))"
            f"+0.025*sin(2*PI*{r * 2:.2f}*t+0.6*sin(2*PI*0.25*t))*(0.5+0.5*sin(2*PI*0.09*t+2))"
            f"+0.012*sin(2*PI*{r * 3:.2f}*t)*(0.5+0.5*sin(2*PI*0.11*t))"
            f"+0.06*sin(2*PI*{r * 8:.2f}*t)*exp(-2.2*(t-{chime_t + 0.4:.2f}))*gte(t,{chime_t + 0.4:.2f})"
            f"+0.035*sin(2*PI*{r * 12:.2f}*t)*exp(-2.6*(t-{chime_t + 0.4:.2f}))*gte(t,{chime_t + 0.4:.2f})")
    right = left.replace("+1))", "+1.7))").replace("+2))", "+2.5))")
    return (f"aevalsrc='{left}|{right}':s=48000:d={T:.2f},"
            f"aecho=0.8:0.7:180|310:0.35|0.22,lowpass=f=3200,"
            f"afade=t=in:d=1.5,afade=t=out:st={T - 1.8:.2f}:d=1.8,volume=5.5")


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"
