"""Procedural background: a glass office tower with the company name on it.

Every Reel gets the same cinematic look (deep sky, tall glass tower seen from
below) but with *that* company's name and logo on the facade, like real
"X is hiring" Reels that use a photo of the company building.

Drop real photos into job_hunt/assets/images/buildings/ to use them instead
(``<company>.jpg`` for a specific company, any other file as a random backdrop).
"""

from __future__ import annotations

import os
import random
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

W, H = 1080, 1920
PHOTO_DIR = Path(__file__).resolve().parent.parent / "assets" / "images" / "buildings"


def _coeffs(dst, src):
    """Perspective coefficients mapping output quad ``dst`` to input quad ``src``."""
    rows = []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(rows, dtype=float)
    b = np.array(src, dtype=float).reshape(8)
    return np.linalg.solve(a, b).tolist()


def _warp(tex, quad):
    """Place ``tex`` (RGBA) onto the canvas so its corners land on ``quad`` (TL, TR, BR, BL)."""
    w, h = tex.size
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    return tex.transform((W, H), Image.Transform.PERSPECTIVE, _coeffs(quad, src),
                         Image.Resampling.BICUBIC)


def _vgrad(size, top, bottom):
    w, h = size
    col = np.linspace(0, 1, h)[:, None]
    arr = np.array(top)[None, :] * (1 - col) + np.array(bottom)[None, :] * col
    arr = np.repeat(arr[:, None, :], w, axis=1)
    return Image.fromarray(arr.astype("uint8"), "RGB")


def _glass(size, base_top, base_bottom, col_w, floor_h, seed, sign=None):
    """Curtain-wall texture: tinted panels, mullions, sky reflection."""
    rnd = random.Random(seed)
    w, h = size
    tex = _vgrad(size, base_top, base_bottom).convert("RGBA")
    d = ImageDraw.Draw(tex)
    for x in range(0, w, col_w):
        for y in range(0, h, floor_h):
            shade = rnd.randint(-6, 7)
            lit = rnd.random() < 0.025
            fill = (255, 230, 180, 55) if lit else ((255, 255, 255, shade * 3) if shade > 0 else (0, 0, 0, -shade * 4))
            d.rectangle((x + 3, y + 3, x + col_w - 3, y + floor_h - 3), fill=fill)
    # Diagonal sky reflection.
    refl = Image.new("L", size, 0)
    rd = ImageDraw.Draw(refl)
    rd.polygon([(w * 0.15, 0), (w * 0.55, 0), (w * 0.05, h * 0.55), (-w * 0.35, h * 0.55)], fill=120)
    rd.polygon([(w * 0.75, 0), (w * 0.9, 0), (w * 0.4, h * 0.7), (w * 0.25, h * 0.7)], fill=70)
    refl = refl.filter(ImageFilter.GaussianBlur(w * 0.06))
    white = Image.new("RGBA", size, (210, 230, 255, 255))
    white.putalpha(refl)
    tex.alpha_composite(white)
    # Mullions and floor slabs drawn last so they stay crisp.
    for x in range(0, w + 1, col_w):
        d.line((x, 0, x, h), fill=(22, 38, 62, 200), width=3)
    for y in range(0, h + 1, floor_h):
        d.line((0, y, w, y), fill=(14, 26, 44, 235), width=4)
    if sign is not None:
        tex.alpha_composite(sign, (40, int(floor_h * 0.35)))
    return tex


def _sign(company, logo, font_fn, width):
    """White company signage (logo + name) to mount on the facade."""
    name = company or ""
    words = name.split()
    # Long legal names read badly on a sign: "Goldman Sachs International" -> "Goldman Sachs".
    while len(words) > 2 and len(" ".join(words)) > 16:
        words = words[:-1]
    name = " ".join(words)
    f = font_fn(150, True)
    tmp = ImageDraw.Draw(Image.new("L", (1, 1)))
    size = 150
    while size > 44:
        f = font_fn(size, True)
        if tmp.textlength(name, font=f) <= width * (0.5 if logo is not None else 0.46):
            break
        size -= 6
    text_w = int(tmp.textlength(name, font=f))
    logo_w = 0
    mark = None
    if logo is not None:
        mark = logo.copy()
        mark.thumbnail((int(size * 1.25), int(size * 1.25)), Image.Resampling.LANCZOS)
        logo_w = mark.width + 36
    sw, sh = text_w + logo_w + 40, int(size * 1.6)
    sign = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    glow = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    sd = ImageDraw.Draw(sign)
    x = 20
    if mark is not None:
        # Logo on a white plaque so any logo colour reads on glass.
        pad = 14
        plaque = (x, (sh - mark.height) // 2 - pad, x + mark.width + pad * 2, (sh + mark.height) // 2 + pad)
        sd.rounded_rectangle(plaque, radius=18, fill=(255, 255, 255, 245))
        sign.alpha_composite(mark, (x + pad, (sh - mark.height) // 2))
        x = plaque[2] + 26
    gd.text((x, sh // 2), name, font=f, fill=(190, 225, 255, 200), anchor="lm")
    sd.text((x, sh // 2), name, font=f, fill=(255, 255, 255, 255), anchor="lm")
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    glow.alpha_composite(sign)
    return glow


def _photo_background(company):
    if not PHOTO_DIR.is_dir():
        return None
    files = [p for p in PHOTO_DIR.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    if not files:
        return None
    key = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    exact = [p for p in files if re.sub(r"[^a-z0-9]", "", p.stem.lower()) == key]
    generic = [p for p in files if p.stem.lower().startswith(("generic", "office", "bg"))]
    pick = exact[0] if exact else (random.choice(generic) if generic else None)
    if not pick:
        return None
    with Image.open(pick) as im:
        return ImageOps.fit(im.convert("RGB"), (W, H), Image.Resampling.LANCZOS)


def building_background(company, logo, font_fn, accent=(0, 98, 255), top=450):
    photo = _photo_background(company)
    if photo is not None:
        return _finish(photo)

    seed = sum(map(ord, company or "x"))
    canvas = _vgrad((W, H), (8, 22, 58), (92, 140, 205)).convert("RGBA")
    # Soft clouds.
    clouds = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(clouds)
    rnd = random.Random(seed)
    for _ in range(7):
        cx, cy = rnd.randint(-100, 700), rnd.randint(300, 900)
        cd.ellipse((cx, cy, cx + rnd.randint(260, 520), cy + rnd.randint(70, 140)), fill=(255, 255, 255, 46))
    canvas.alpha_composite(clouds.filter(ImageFilter.GaussianBlur(40)))

    # Distant hazy towers on the left.
    far = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(far)
    fd.polygon([(-40, 760), (150, 720), (170, 1920), (-40, 1920)], fill=(70, 105, 160, 255))
    fd.polygon([(120, 900), (300, 880), (300, 1920), (130, 1920)], fill=(85, 122, 178, 255))
    canvas.alpha_composite(far.filter(ImageFilter.GaussianBlur(3)))

    # Main tower: side face + front face with the sign.
    front_tex = _glass((900, 2200), (78, 128, 186), (16, 36, 72), 56, 92, seed,
                       sign=_sign(company, logo, font_fn, 900))
    side_tex = _glass((320, 2200), (34, 62, 104), (8, 20, 44), 40, 92, seed + 1)
    t = int(top)
    side_q = [(300, t + 70), (470, t), (420, 1920), (170, 1920)]
    front_q = [(470, t), (1100, t - 60), (1180, 1920), (420, 1920)]
    canvas.alpha_composite(_warp(side_tex, side_q))
    canvas.alpha_composite(_warp(front_tex, front_q))
    # Roof edge highlight.
    ImageDraw.Draw(canvas).line([side_q[0], side_q[1], front_q[1]], fill=(200, 225, 255, 255), width=5)
    return _finish(canvas.convert("RGB"))


def _finish(img):
    """Darken top (hook text) and add a gentle vignette for depth."""
    img = img.convert("RGBA")
    shade = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shade)
    for y in range(0, 520):
        sd.line((0, y, W, y), fill=int(150 * (1 - y / 520) ** 1.4))
    for y in range(1350, H):
        sd.line((0, y, W, y), fill=int(140 * ((y - 1350) / (H - 1350)) ** 1.2))
    black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    black.putalpha(shade)
    img.alpha_composite(black)
    return img.convert("RGB")
