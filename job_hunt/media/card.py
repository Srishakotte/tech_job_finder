"""Layered 1080x1920 job-card renderer.

The card is drawn as two layers:

* ``background`` - an opaque RGB plate (soft gradient, glow blobs, dot grid).
* ``content``    - a transparent RGBA layer holding every element.

Each element's bounding box is recorded in ``regions`` together with an entry
animation, so ``motion.py`` can animate the exact same artwork into a Reel.
Flattening the two layers gives the static PNG used as the Reel cover.

Layout keeps all important information between y≈230 and y≈1640, which is the
area Instagram does not cover with its top bar, caption and username overlay.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .qr_code import generate_qr_code
from .scene import building_background

WIDTH, HEIGHT = 1080, 1920

NAVY = (11, 18, 36)
INK = (30, 38, 56)
MUTED = (100, 110, 128)
BLUE = (0, 98, 255)
BLUE_DEEP = (0, 60, 190)
BLUE_TINT = (232, 240, 255)
GREEN = (16, 185, 129)
WHITE = (255, 255, 255)
LINE = (226, 231, 240)

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_BOLD_NAMES = [
    "Inter-Bold.ttf", "Poppins-Bold.ttf", "Montserrat-Bold.ttf",
]
_REGULAR_NAMES = [
    "Inter-Regular.ttf", "Inter-Medium.ttf", "Poppins-Regular.ttf", "Montserrat-Regular.ttf",
]
_BOLD_SYSTEM = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_REGULAR_SYSTEM = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
_font_cache: dict = {}


def font(size: int, bold: bool = False):
    """Bundled fonts in job_hunt/assets/fonts win; then system fonts."""
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    names = _BOLD_NAMES if bold else _REGULAR_NAMES
    candidates = [FONT_DIR / n for n in names] + [Path(p) for p in (_BOLD_SYSTEM if bold else _REGULAR_SYSTEM)]
    result = None
    for path in candidates:
        if path.is_file():
            try:
                result = ImageFont.truetype(str(path), size=size)
                break
            except OSError:
                continue
    if result is None:
        result = ImageFont.load_default(size=size)
    _font_cache[key] = result
    return result


def _tw(draw, text, f):
    box = draw.textbbox((0, 0), text, font=f)
    return box[2] - box[0]


def _wrap(draw, text, f, max_w):
    words, lines, cur = str(text).split(), [], ""
    for word in words:
        cand = f"{cur} {word}".strip()
        if _tw(draw, cand, f) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit_lines(draw, text, max_w, max_lines, start, minimum, bold=True):
    """Largest font where ``text`` wraps into ``max_lines``; ellipsis at minimum."""
    for size in range(start, minimum - 1, -2):
        f = font(size, bold)
        lines = _wrap(draw, text, f, max_w)
        if len(lines) <= max_lines and all(_tw(draw, l, f) <= max_w for l in lines):
            return f, lines
    f = font(minimum, bold)
    lines = _wrap(draw, text, f, max_w)[:max_lines]
    last = lines[-1] if lines else ""
    while last and _tw(draw, last + "…", f) > max_w:
        last = last[:-1]
    if lines:
        lines[-1] = last.rstrip() + "…"
    return f, lines


def _rrect(layer, box, radius, fill, outline=None, width=0, ss=4):
    """Anti-aliased rounded rectangle composited onto an RGBA layer."""
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    mask = Image.new("L", (w * ss, h * ss), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=radius * ss, fill=255)
    mask = mask.resize((w, h), Image.Resampling.LANCZOS)
    tile = Image.new("RGBA", (w, h), fill if len(fill) == 4 else (*fill, 255))
    if len(fill) == 4:
        mask = Image.eval(mask, lambda v, a=fill[3]: v * a // 255)
    tile.putalpha(mask)
    layer.alpha_composite(tile, (x1, y1))
    if outline and width:
        omask = Image.new("L", (w * ss, h * ss), 0)
        od = ImageDraw.Draw(omask)
        od.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=radius * ss,
                             outline=255, width=width * ss)
        omask = omask.resize((w, h), Image.Resampling.LANCZOS)
        otile = Image.new("RGBA", (w, h), (*outline[:3], 255))
        otile.putalpha(omask)
        layer.alpha_composite(otile, (x1, y1))


def _ellipse(layer, box, fill, ss=4):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    w, h = x2 - x1, y2 - y1
    mask = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, w * ss - 1, h * ss - 1), fill=255)
    mask = mask.resize((w, h), Image.Resampling.LANCZOS)
    tile = Image.new("RGBA", (w, h), (*fill[:3], 255))
    tile.putalpha(mask)
    layer.alpha_composite(tile, (x1, y1))


def _shadow(layer, box, radius, blur=28, opacity=34, dy=14):
    x1, y1, x2, y2 = box
    pad = blur * 2
    w, h = int(x2 - x1 + pad * 2), int(y2 - y1 + pad * 2)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, w - pad, h - pad), radius=radius, fill=opacity)
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    tile = Image.new("RGBA", (w, h), (20, 40, 90, 255))
    tile.putalpha(mask)
    layer.alpha_composite(tile, (int(x1 - pad), int(y1 - pad + dy)))


def _gradient_tile(size, start, end, horizontal=False):
    w, h = size
    tile = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(tile)
    steps = w if horizontal else h
    for i in range(steps):
        t = i / max(1, steps - 1)
        c = tuple(round(start[k] * (1 - t) + end[k] * t) for k in range(3))
        if horizontal:
            d.line((i, 0, i, h), fill=c)
        else:
            d.line((0, i, w, i), fill=c)
    return tile


def _gradient_text(layer, draw, text, center_x, top, f, start, end):
    box = draw.textbbox((0, 0), text, font=f, anchor="lt")
    w, h = box[2] - box[0] + 8, box[3] - box[1] + 8
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((4 - box[0], 4 - box[1]), text, font=f, fill=255, anchor="lt")
    tile = _gradient_tile((w, h), start, end, horizontal=True).convert("RGBA")
    tile.putalpha(mask)
    x = int(center_x - w / 2)
    layer.alpha_composite(tile, (x, int(top)))
    return (x, int(top), x + w, int(top) + h)


# --- tiny vector icons (drawn, so they work with any font) -----------------

def _icon(layer, kind, cx, cy, color=BLUE):
    d = ImageDraw.Draw(layer)
    if kind == "location":
        _ellipse(layer, (cx - 11, cy - 15, cx + 11, cy + 7), color)
        d.polygon([(cx - 9, cy + 1), (cx + 9, cy + 1), (cx, cy + 16)], fill=color)
        _ellipse(layer, (cx - 4, cy - 8, cx + 4, cy), BLUE_TINT)
    elif kind == "education":
        d.polygon([(cx - 18, cy - 4), (cx, cy - 13), (cx + 18, cy - 4), (cx, cy + 5)], fill=color)
        d.rectangle((cx - 10, cy + 1, cx + 10, cy + 10), fill=color)
        d.line((cx + 15, cy - 3, cx + 15, cy + 10), fill=color, width=3)
    elif kind == "salary":
        _rrect(layer, (cx - 17, cy - 11, cx + 17, cy + 12), 5, color)
        _ellipse(layer, (cx - 6, cy - 6, cx + 6, cy + 6), BLUE_TINT)
    elif kind == "experience":
        _rrect(layer, (cx - 17, cy - 8, cx + 17, cy + 14), 5, color)
        d.rounded_rectangle((cx - 7, cy - 15, cx + 7, cy - 6), radius=3, outline=color, width=3)
        d.line((cx - 17, cy + 2, cx + 17, cy + 2), fill=BLUE_TINT, width=2)
    elif kind == "skills":
        f = font(22, True)
        d.text((cx, cy), "</>", font=f, fill=color, anchor="mm")


def _comment_icon(layer, cx, cy, color=WHITE, dot=BLUE):
    _rrect(layer, (cx - 34, cy - 26, cx + 34, cy + 20), 16, color)
    ImageDraw.Draw(layer).polygon([(cx - 18, cy + 16), (cx - 4, cy + 16), (cx - 22, cy + 32)], fill=color)
    for dx in (-16, 0, 16):
        _ellipse(layer, (cx + dx - 5, cy - 8, cx + dx + 5, cy + 2), dot)


# --- data -------------------------------------------------------------------

_BLANK = {
    "", "none", "null", "n/a", "na", "unknown", "not specified", "not available",
    "ctc not disclosed", "salary not disclosed", "not disclosed", "undisclosed", "eligibility not specified",
    "skills not specified", "job opportunity", "company", "-", "not mentioned", "nil", "[]",
}


def clean(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(c for c in (clean(v) for v in value) if c)
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "" if text.lower() in _BLANK else text


@dataclass
class Region:
    name: str
    box: tuple  # (x1, y1, x2, y2) in 1080x1920 space
    tile: Image.Image  # this element only, cropped to ``box``
    effect: str = "rise"  # rise | pop | fade | slide_left | slide_right
    delay: float = 0.0
    loop: str | None = None  # pulse | scan
    focus: tuple | None = None  # e.g. the QR code square, for the scan effect


@dataclass
class CardLayers:
    background: Image.Image
    content: Image.Image
    regions: list = field(default_factory=list)

    def flatten(self) -> Image.Image:
        base = self.background.convert("RGBA")
        base.alpha_composite(self.content)
        out = base.convert("RGB")
        base.close()
        return out

    def close(self):
        self.background.close()
        self.content.close()
        for region in self.regions:
            region.tile.close()


class _Canvas:
    """Draw each element on its own layer so it can be animated independently."""

    def __init__(self):
        self.content = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        self.regions = []
        self.begin()

    def begin(self):
        self.layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)
        return self.layer, self.draw

    def commit(self, name, effect="rise", delay=0.0, loop=None, focus=None):
        box = self.layer.getchannel("A").getbbox()
        if box:
            self.content.alpha_composite(self.layer)
            self.regions.append(Region(name, box, self.layer.crop(box), effect, delay, loop, focus))
        self.layer.close()
        return self.begin()


def _background():
    bg = _gradient_tile((WIDTH, HEIGHT), (250, 251, 255), (236, 241, 251)).convert("RGBA")
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((560, -260, 1400, 560), fill=(0, 98, 255, 60))
    gd.ellipse((-420, 1250, 420, 2100), fill=(16, 185, 129, 42))
    gd.ellipse((-300, 380, 260, 940), fill=(124, 92, 255, 26))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    bg.alpha_composite(glow)
    dots = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for y in range(36, HEIGHT, 44):
        for x in range(36, WIDTH, 44):
            dd.ellipse((x - 1.6, y - 1.6, x + 1.6, y + 1.6), fill=(40, 70, 140, 26))
    bg.alpha_composite(dots)
    glow.close()
    dots.close()
    return bg.convert("RGB")


def _load_logo(path):
    if not path or not os.path.isfile(str(path)):
        return None
    try:
        with Image.open(str(path)) as src:
            logo = src.convert("RGBA")
        bbox = logo.getchannel("A").getbbox()
        if bbox and bbox != (0, 0, logo.width, logo.height):
            logo = logo.crop(bbox)
        else:
            # Opaque image: crop away a near-white border.
            gray = logo.convert("L").point(lambda v: 255 if v < 245 else 0)
            bbox = gray.getbbox()
            if bbox:
                logo = logo.crop(bbox)
        return logo
    except Exception:
        return None


# --- defaults & hooks --------------------------------------------------------

DEFAULTS = {
    "job_title": "Multiple Roles",
    "location": "India",
    "eligibility": "Any Graduate / B.E / B.Tech",
    "experience": "Freshers & Experienced",
    "ctc": "As per company norms",
    "job_type": "Full Time",
}

_SERIF_BOLD = [
    FONT_DIR / "PlayfairDisplay-Bold.ttf", FONT_DIR / "DMSerifDisplay-Regular.ttf",
    Path("C:/Windows/Fonts/georgiab.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
]


def serif(size):
    key = ("serif", size)
    if key not in _font_cache:
        for path in _SERIF_BOLD:
            if path.is_file():
                _font_cache[key] = ImageFont.truetype(str(path), size=size)
                break
        else:
            _font_cache[key] = font(size, True)
    return _font_cache[key]


def with_defaults(fields):
    """Return display values plus the set of keys that fell back to a default."""
    out, defaulted = {}, set()
    for key, default in DEFAULTS.items():
        value = clean(fields.get(key))
        if not value:
            value, _ = default, defaulted.add(key)
        out[key] = value
    out["skills"] = clean(fields.get("skills"))
    out["company"] = clean(fields.get("company"))
    return out, defaulted


def _batches(text):
    years = sorted(set(re.findall(r"\b(20(?:2[3-9]))\b", text)))
    return years


def hook_lines(d, defaulted):
    """Headline + highlighted subline, chosen from what the post actually says."""
    company = d["company"]
    blob = " ".join(str(d.get(k, "")) for k in ("job_title", "job_type", "eligibility", "experience")).lower()
    line1 = f"{company} Hiring Alert" if company else "Hiring Alert"
    years = _batches(blob)
    if "intern" in blob:
        line2 = "Internship Opportunity"
    elif years:
        line2 = f"For {' & '.join(years[-2:])} Batch"
    elif re.search(r"fresher|0\s*[-–to]+\s*\d|entry level|graduate trainee", blob) or "experience" in defaulted:
        line2 = "For Freshers"
    elif re.search(r"\d+\s*\+?\s*(?:-|–|to)?\s*\d*\s*years?", blob):
        line2 = "For Experienced"
    else:
        line2 = "Apply Now"
    return line1, line2


def sticker_texts(d, defaulted, line2):
    stickers = []
    if "ctc" not in defaulted:
        ctc = d["ctc"]
        stickers.append(("dark", ctc if re.search(r"ctc|stipend|pm|month", ctc, re.I) else f"{ctc} CTC"))
    loc = d["location"].lower()
    if re.search(r"remote|work from home|wfh", loc):
        stickers.append(("yellow", "Work From Home"))
    blob = (d["experience"] + " " + d["eligibility"]).lower()
    if "fresher" in blob and "Freshers" not in line2:
        stickers.append(("yellow", "Freshers Eligible"))
    if not stickers or (len(stickers) == 1 and stickers[0][0] == "dark"):
        stickers.append(("yellow", "Apply Fast"))
    return stickers[:2]


def _accent_from_logo(logo):
    """Brand colour from the logo (most common saturated colour), darkened for contrast."""
    if logo is None:
        return BLUE
    small = logo.convert("RGBA").resize((48, 48))
    best, count = None, {}
    for r, g, b, a in small.getdata():
        if a < 200:
            continue
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn < 60 or mx < 60:
            continue
        key = (r // 32, g // 32, b // 32)
        count[key] = count.get(key, 0) + 1
    if not count:
        return BLUE
    key = max(count, key=count.get)
    color = tuple(min(255, c * 32 + 16) for c in key)
    lum = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
    if lum > 120:  # too light for text on white: darken
        f = 120 / lum
        color = tuple(int(c * f) for c in color)
    return color


def _sticker(text, style, angle):
    f = font(52, True)
    tmp = ImageDraw.Draw(Image.new("L", (1, 1)))
    tw = int(tmp.textlength(text, font=f))
    w, h = tw + 64, 96
    img = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    _shadow(img, (20, 20, 20 + w, 20 + h), 18, blur=10, opacity=90, dy=6)
    fill, ink = ((255, 214, 10), (12, 12, 12)) if style == "yellow" else ((12, 14, 20), (255, 255, 255))
    _rrect(img, (20, 20, 20 + w, 20 + h), 18, fill)
    ImageDraw.Draw(img).text((20 + w // 2, 20 + h // 2), text, font=f, fill=ink, anchor="mm")
    return img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


def _whiten_to_alpha(logo):
    """Logo.dev returns logos on white; make that white transparent for the card."""
    logo = logo.convert("RGBA")
    px = logo.load()
    w, h = logo.size
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    if all(c[3] > 250 and min(c[:3]) > 240 for c in corners):
        arr = np.array(logo)
        whiteness = arr[..., :3].min(axis=2).astype(int)
        arr[..., 3] = np.where(whiteness > 245, 0, arr[..., 3])
        logo = Image.fromarray(arr, "RGBA")
        bbox = logo.getchannel("A").getbbox()
        if bbox:
            logo = logo.crop(bbox)
    return logo


def render_card_layers(
    company, job_title, location, ctc, eligibility, experience, skills,
    application_link=None, brand_image_path=None, job_type=None,
    comment_keyword=None, brand_handle=None,
) -> CardLayers:
    d, defaulted = with_defaults({
        "company": company, "job_title": job_title, "location": location, "ctc": ctc,
        "eligibility": eligibility, "experience": experience, "skills": skills, "job_type": job_type,
    })
    link = clean(application_link)
    keyword = clean(comment_keyword).upper() if link else ""
    handle = clean(brand_handle if brand_handle is not None else os.getenv("BRAND_HANDLE"))

    logo = _load_logo(brand_image_path)
    if logo is not None:
        logo = _whiten_to_alpha(logo)
    accent = _accent_from_logo(logo)

    canvas = _Canvas()
    layer, draw = canvas.layer, canvas.draw

    # 1. Hook headline ------------------------------------------------------------
    line1, line2 = hook_lines(d, defaulted)
    # One line if it fits at a readable size, otherwise two balanced lines.
    l1 = [line1]
    for size in range(96, 61, -2):
        f1 = serif(size)
        if draw.textlength(line1, font=f1) <= 980:
            break
    else:
        words = line1.split()
        cut = max(1, len(words) - 2)  # "<Company>" / "Hiring Alert"
        l1 = [" ".join(words[:cut]), " ".join(words[cut:])]
        for size in range(88, 51, -2):
            f1 = serif(size)
            if max(draw.textlength(l, font=f1) for l in l1) <= 980:
                break
    y = 205
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    sdw = ImageDraw.Draw(shadow)
    for line in l1:
        sdw.text((540, y + 5), line, font=f1, fill=(0, 0, 0, 170), anchor="mt")
        y += int(f1.size * 1.12)
    y1_end = y
    f2 = serif(min(80, f1.size))
    while draw.textlength(line2, font=f2) > 980 and f2.size > 44:
        f2 = serif(f2.size - 4)
    sdw.text((540, y1_end + 9), line2, font=f2, fill=(0, 0, 0, 170), anchor="mt")
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    y = 205
    for line in l1:
        draw.text((540, y), line, font=f1, fill=WHITE, anchor="mt")
        y += int(f1.size * 1.12)
    layer, draw = canvas.commit("hook1", "rise", 0.1)
    draw.text((540, y1_end + 4), line2, font=f2, fill=(255, 205, 0), anchor="mt")
    layer, draw = canvas.commit("hook2", "pop", 0.35)
    hook_bottom = y1_end + 4 + int(f2.size * 1.15)

    # 2. Measure the job card -------------------------------------------------------
    cx1, cx2 = 56, 1024
    inner1, inner2 = cx1 + 44, cx2 - 44
    label_f, value_f = font(34, True), font(34, False)
    role_text = d["job_title"]
    rf, rlines = _fit_lines(draw, role_text, inner2 - inner1 - 130, 2, 52, 36)
    rows = [("Job Type", d["job_type"]), ("Experience", d["experience"]),
            ("Location", d["location"]), ("Salary", d["ctc"]), ("Qualification", d["eligibility"])]
    val_x = inner1 + 270

    def row_lines(value):
        lines = _wrap(draw, value, value_f, inner2 - val_x - 20)
        if len(lines) > 2:
            lines = lines[:2]
            lines[1] = lines[1][: max(0, len(lines[1]) - 2)].rstrip(" ,/") + "…"
        return lines

    prepared = [(label, value, row_lines(value)) for label, value in rows]
    skill_items = [s.strip() for s in re.split(r"[,·|/;\n]+", d["skills"]) if s.strip()][:8]
    chip_f = font(28, True)

    def chip_rows(items):
        rows_, cur, x = [], [], inner1
        for item in items:
            w = int(draw.textlength(item, font=chip_f)) + 40
            if x + w > inner2 and cur:
                rows_.append(cur)
                cur, x = [], inner1
            cur.append((item, w))
            x += w + 12
        if cur:
            rows_.append(cur)
        return rows_[:2]

    chips = chip_rows(skill_items)
    header_h, cta_h = 120, (236 if link else 0)

    def total(with_skills):
        h = 36 + header_h + 26 + len(rlines) * int(rf.size * 1.2) + 22 + 18
        h += sum(len(l) * 44 + 18 for _, _, l in prepared)
        if with_skills and chips:
            h += 16 + 44 + len(chips) * 58
        return h + (18 + cta_h) + 30

    card_bottom = 1612
    # Leave room between hook and card for the building sign + stickers.
    max_h = card_bottom - max(hook_bottom + 290, 700)
    # Too tall? Squeeze: one-line rows, then a smaller single-line role.
    if total(False) > max_h:
        prepared = [(label, value, row_lines(value)[:1]) for label, value, _ in prepared]
        prepared = [(lb, v, [l[0] if l[0].endswith("…") or len(row_lines(v)) == 1 else l[0].rstrip(" ,/") + "…"])
                    for lb, v, l in prepared]
    if total(False) > max_h:
        rf, rlines = _fit_lines(draw, role_text, inner2 - inner1 - 130, 1, 44, 30)
    show_skills = bool(chips) and total(True) <= max_h
    card_h = min(total(show_skills), max_h)
    card_top = card_bottom - card_h

    background = building_background(d["company"] or "Now Hiring", logo, font, top=hook_bottom + 40)

    # 3. Card surface -----------------------------------------------------------------
    _shadow(layer, (cx1, card_top, cx2, card_bottom), 40, blur=34, opacity=120, dy=18)
    _rrect(layer, (cx1, card_top, cx2, card_bottom), 40, WHITE)
    _rrect(layer, (cx1, card_top, cx2, card_top + 12), 6, accent)  # brand strip
    layer, draw = canvas.commit("card", "rise", 0.55)

    # 4. Header: logo | Company: name ---------------------------------------------------
    y = card_top + 36
    box = (inner1, y, inner1 + header_h, y + header_h)
    _rrect(layer, box, 24, (246, 248, 252), outline=LINE, width=2)
    if logo is not None:
        mark = logo.copy()
        mark.thumbnail((header_h - 30, header_h - 30), Image.Resampling.LANCZOS)
        layer.alpha_composite(mark, (box[0] + (header_h - mark.width) // 2, box[1] + (header_h - mark.height) // 2))
    else:
        initials = "".join(p[0] for p in (d["company"] or "Hiring").split()[:2]).upper()
        draw.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), initials, font=font(54, True), fill=accent, anchor="mm")
    tx = box[2] + 34
    draw.line((tx - 17, y + 12, tx - 17, y + header_h - 12), fill=LINE, width=3)
    draw.text((tx + 4, y + 14), "Company:", font=font(28, False), fill=MUTED, anchor="lt")
    nf, nl = _fit_lines(draw, d["company"] or "Top MNC", inner2 - tx, 1, 58, 34)
    draw.text((tx, y + 54), nl[0], font=nf, fill=NAVY, anchor="lt")
    layer, draw = canvas.commit("header", "fade", 0.8)
    y += header_h + 26

    # 5. Role ------------------------------------------------------------------------------
    draw.text((inner1, y), "Role:", font=font(rf.size, True), fill=NAVY, anchor="lt")
    rx = inner1 + int(draw.textlength("Role: ", font=font(rf.size, True)))
    for line in rlines:
        draw.text((rx, y), line, font=rf, fill=accent, anchor="lt")
        y += int(rf.size * 1.2)
    _rrect(layer, (inner1, y + 8, inner2, y + 14), 3, accent)
    layer, draw = canvas.commit("role", "slide_left", 0.9)
    y += 22 + 18

    # 6. Detail rows ---------------------------------------------------------------------------
    for i, (label, value, lines) in enumerate(prepared):
        draw.text((inner1, y), label, font=label_f, fill=NAVY, anchor="lt")
        draw.text((val_x - 26, y), ":", font=label_f, fill=NAVY, anchor="lt")
        ly = y
        for line in lines:
            draw.text((val_x, ly), line, font=value_f, fill=INK, anchor="lt")
            ly += 44
        layer, draw = canvas.commit(f"row{i}", "slide_left", 1.0 + 0.08 * i)
        y += len(lines) * 44 + 18

    # 7. Key skills ------------------------------------------------------------------------------
    if show_skills:
        y += 16
        draw.text((inner1, y), "Key Skills:", font=label_f, fill=NAVY, anchor="lt")
        y += 50
        for row in chips:
            x = inner1
            for item, w in row:
                _rrect(layer, (x, y, x + w, y + 46), 23, tuple(int(min(255, c + (255 - c) * 0.86)) for c in accent))
                draw.text((x + w // 2, y + 23), item, font=chip_f, fill=accent, anchor="mm")
                x += w + 12
            y += 58
        layer, draw = canvas.commit("skills", "fade", 1.45)

    # 8. Apply strip: QR + "Comment LINK" ------------------------------------------------------------
    if link:
        sy1, sy2 = card_bottom - 30 - cta_h, card_bottom - 30
        _rrect(layer, (inner1 - 14, sy1, inner2 + 14, sy2), 28, (240, 245, 255), outline=(214, 226, 250), width=2)
        qr_size = cta_h - 36
        qx, qy = inner1 + 4, sy1 + 18
        try:
            with Image.open(io.BytesIO(generate_qr_code(link))) as raw:
                q = raw.convert("RGB")
            inner = q.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
            if inner:
                q = q.crop(inner)
            q = q.resize((qr_size - 20, qr_size - 20), Image.Resampling.NEAREST)
            _rrect(layer, (qx, qy, qx + qr_size, qy + qr_size), 16, WHITE)
            layer.paste(q, (qx + 10, qy + 10))
        except Exception:
            pass
        tx = qx + qr_size + 36
        if keyword:
            draw.text((tx, sy1 + 30), "Comment", font=font(34, False), fill=INK, anchor="lt")
            kf, _ = _fit_lines(draw, f"\u2018{keyword}\u2019", inner2 - tx, 1, 74, 40)
            draw.text((tx, sy1 + 68), f"\u2018{keyword}\u2019", font=kf, fill=accent, anchor="lt")
            draw.text((tx, sy1 + 76 + int(kf.size * 1.1)), "to get the link in DM", font=font(30, True), fill=NAVY, anchor="lt")
            draw.text((tx, sy2 - 46), "or scan the QR to apply", font=font(28, False), fill=MUTED, anchor="lt")
        else:
            draw.text((tx, (sy1 + sy2) // 2), "Scan to apply", font=font(52, True), fill=NAVY, anchor="lm")
        layer, draw = canvas.commit("cta", "pop", 1.6, loop="scan",
                                    focus=(qx + 10, qy + 10, qx + qr_size - 10, qy + qr_size - 10))

    # 9. Stickers (attention grabbers) ----------------------------------------------------------------
    stickers = sticker_texts(d, defaulted, line2)
    # Stickers sit on the card's top edge, below the building sign.
    spots = [(40, -5), (1040, 4)]
    for i, ((style, text), (sx, angle)) in enumerate(zip(stickers, spots)):
        st = _sticker(text, style, angle)
        x = sx if i == 0 else sx - st.width
        layer.alpha_composite(st, (max(0, x), card_top - st.height + 34))
        layer, draw = canvas.commit(f"sticker{i}", "pop", 0.75 + 0.25 * i, loop="pulse" if i == 0 else None)
        st.close()

    # 10. Trust footer -------------------------------------------------------------------------------------
    footer = "Free to apply  •  Never pay for a job  •  Verify on careers page"
    draw.text((540, 1640), footer, font=font(27, True), fill=(235, 240, 250), anchor="mt")
    if handle:
        draw.text((540, 1684), f"Follow {handle} for daily jobs", font=font(26, False), fill=(200, 210, 230), anchor="mt")
    layer, draw = canvas.commit("footer", "fade", 1.9)

    layer.close()
    if logo is not None:
        logo.close()
    return CardLayers(background, canvas.content, canvas.regions)
