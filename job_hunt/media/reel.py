import os
import io
import re
import random
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoClip
from moviepy.audio.fx import AudioLoop

from .background import BrandTheme, animated_background_frame, create_brand_theme
from .qr_code import generate_qr_code
from ..config import OUTPUT_DIR

WIDTH = 1080
HEIGHT = 1920
# Static job-card Reels are always exactly five seconds.
REEL_DURATION_SECONDS = 5
APPROVED_REEL_HOLD_SECONDS = REEL_DURATION_SECONDS
DEFAULT_BACKGROUND_VOLUME = 0.20
MUSIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "music"))
SUPPORTED_MUSIC_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".aac"}
WHITE = (255, 255, 255)
BLACK = (15, 23, 42)
NAVY = (15, 23, 42)
BLUE = (37, 99, 235)
PURPLE = (124, 58, 237)
LIGHT_BLUE = (239, 246, 255)
LIGHT_PURPLE = (245, 243, 255)
GREY = (100, 116, 139)
BORDER = (226, 232, 240)

TEMPLATE_WIDTH = 1080
TEMPLATE_HEIGHTS = {1350, 1620, 1920}
TEMPLATE_COLORS = {
    "canvas": "#FDFDFE",
    "surface": "#FFFFFF",
    "main_text": "#111827",
    "secondary_text": "#374151",
    "muted_text": "#64748B",
    "primary_blue": "#0865FF",
    "blue_start": "#1684FF",
    "blue_end": "#0057E7",
    "pale_blue": "#E6F6FE",
    "pale_mint": "#E2FBE8",
    "pale_cream": "#FFF8DF",
    "pale_lavender": "#EFEDFB",
    "green": "#04BB56",
    "green_soft": "#00D084",
    "white": "#FFFFFF",
    "subtle_border": "#E5E7EB",
}

REGULAR_FONT_PATHS = [
    "C:/Windows/Fonts/Inter-Regular.ttf",
    "C:/Windows/Fonts/InterVariable.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]
BOLD_FONT_PATHS = [
    "C:/Windows/Fonts/Inter-Bold.ttf",
    "C:/Windows/Fonts/InterVariable.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]

DISPLAY_DEFAULTS = {}  # Missing parsed fields are intentionally omitted.

REEL_TEMPLATES = [
    ("template_1", "Minimal Line"),
    ("template_2", "Dual Accent"),
    ("template_3", "Finance Focus"),
    ("template_4", "Side Rail"),
    ("template_5", "Gradient Glow"),
    ("template_6", "Bold Strip"),
    ("template_7", "Dark Contrast"),
    ("template_8", "Angular Frame"),
    ("template_9", "Graduate Spot"),
    ("template_10", "Modern Dark"),
    ("template_11", "Reference"),
]

os.makedirs(OUTPUT_DIR, exist_ok=True)


def clean_keyword(text):
    text = str(text).lower()
    text = re.sub(r"[^a-zA-Z0-9 ]", " ", text)
    return " ".join(text.split())


def text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def center_text(draw, text, y, font, fill):
    width = text_width(draw, text, font)
    draw.text(((WIDTH - width) / 2, y), text, font=font, fill=fill)


def wrap_text(draw, text, font, max_width):
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def get_font(size, bold=False):
    paths = BOLD_FONT_PATHS if bold else REGULAR_FONT_PATHS
    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _audio_subclip(source_audio, start, end):
    """Trim audio using the MoviePy v2 API, with a v1 compatibility fallback."""
    if hasattr(source_audio, "subclipped"):
        return source_audio.subclipped(start, end)
    if hasattr(source_audio, "subclip"):
        return source_audio.subclip(start, end)
    raise RuntimeError("This MoviePy audio clip does not support subclipping; refusing to attach untrimmed audio.")


def resolve_background_music_path(music_dir=MUSIC_DIR):
    if not os.path.isdir(music_dir):
        return None
    files = []
    for entry in os.listdir(music_dir):
        path = os.path.join(music_dir, entry)
        if os.path.isfile(path) and os.path.splitext(entry)[1].lower() in SUPPORTED_MUSIC_EXTENSIONS:
            files.append(path)
    if not files:
        return None
    return random.choice(files)


def pick_background_music(music_dir=MUSIC_DIR):
    return resolve_background_music_path(music_dir=music_dir)


def get_company_domain(company):
    key = str(company).lower().strip()
    known = {
        "microsoft": "microsoft.com",
        "google": "google.com",
        "amazon": "amazon.com",
        "apple": "apple.com",
        "meta": "meta.com",
        "netflix": "netflix.com",
        "adobe": "adobe.com",
        "salesforce": "salesforce.com",
        "oracle": "oracle.com",
        "servicenow": "servicenow.com",
        "deloitte": "deloitte.com",
        "accenture": "accenture.com",
        "infosys": "infosys.com",
        "tcs": "tcs.com",
        "wipro": "wipro.com",
        "flipkart": "flipkart.com",
        "swiggy": "swiggy.com",
        "zomato": "zomato.com",
        "uber": "uber.com",
        "atlassian": "atlassian.com",
        "nvidia": "nvidia.com",
        "visa": "visa.com",
        "mastercard": "mastercard.com",
        "deshaw": "deshaw.com",
        "goldman sachs": "goldmansachs.com",
        "morgan stanley": "morganstanley.com",
        "jpmorgan": "jpmorgan.com",
        "jp morgan": "jpmorgan.com",
        "qualcomm": "qualcomm.com",
        "intel": "intel.com",
        "cisco": "cisco.com",
        "ibm": "ibm.com",
        "sap": "sap.com",
        "paypal": "paypal.com",
        "stripe": "stripe.com",
    }
    if key in known:
        return known[key]
    cleaned = re.sub(r"[^a-z0-9]", "", key)
    return (cleaned or "example") + ".com"


def download_logo(company, output_path):
    """Try Logo.dev first, log the result, then fall back to Google's favicon."""
    domain = get_company_domain(company)
    logo_dev_token = os.getenv("LOGO_DEV_TOKEN", "").strip()
    print(f"[LOGO] company={company} domain={domain} token_loaded={bool(logo_dev_token)}")
    urls = []
    if logo_dev_token:
        urls.append(("Logo.dev", f"https://img.logo.dev/{domain}", {
            "token": logo_dev_token, "size": 512, "format": "png"
        }))
    else:
        print("[LOGO] LOGO_DEV_TOKEN is missing/empty; skipping Logo.dev and trying Google favicon.")
    urls.append(("Google favicon", f"https://www.google.com/s2/favicons", {
        "domain": domain, "sz": 256
    }))

    for provider, url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=12,
                                    headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                print(f"[LOGO] {provider} failed for {domain}: HTTP {response.status_code}")
                continue
            try:
                image = Image.open(io.BytesIO(response.content)).convert("RGBA")
                image.load()
            except Exception as exc:
                print(f"[LOGO] {provider} returned non-image data for {domain}: {exc}")
                continue
            if image.width < 20 or image.height < 20:
                print(f"[LOGO] {provider} returned a tiny image for {domain}; trying fallback.")
                continue
            bbox = image.getbbox()
            if bbox:
                image = image.crop(bbox)
            image.thumbnail((280, 280), Image.Resampling.LANCZOS)
            parent = os.path.dirname(os.path.abspath(output_path))
            os.makedirs(parent, exist_ok=True)
            image.save(output_path)
            print(f"[LOGO] Success: loaded {domain} logo from {provider} ({image.width}x{image.height}).")
            return output_path
        except Exception as exc:
            print(f"[LOGO] {provider} request failed for {domain}: {type(exc).__name__}: {exc}")
    print(f"[LOGO] All logo providers failed for {company} ({domain}). Check network, LOGO_DEV_TOKEN, and remote provider availability.")
    raise RuntimeError(f"Could not download a logo for {company}; check network and LOGO_DEV_TOKEN.")


def _normalize_optional_text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    if text.lower() in {"", "n/a", "na", "none", "not mentioned", "not specified", "null", "nil"}:
        return default
    return text


def _coalesce_field(value, default):
    return _normalize_optional_text(value, default)


def _card_icon(draw, x, y, fill, kind):
    if kind == "location":
        draw.ellipse((x + 4, y + 2, x + 34, y + 32), outline=fill, width=2)
        draw.line((x + 19, y + 31, x + 19, y + 42), fill=fill, width=2)
        draw.line((x + 19, y + 42, x + 26, y + 48), fill=fill, width=2)
    elif kind == "salary":
        draw.ellipse((x + 8, y + 10, x + 26, y + 28), outline=fill, width=2)
        draw.ellipse((x + 18, y + 2, x + 36, y + 20), outline=fill, width=2)
        draw.line((x + 7, y + 26, x + 32, y + 26), fill=fill, width=2)
    elif kind == "experience":
        draw.rounded_rectangle((x + 6, y + 10, x + 35, y + 31), radius=6, outline=fill, width=2)
        draw.line((x + 10, y + 10, x + 10, y + 6), fill=fill, width=2)
        draw.line((x + 30, y + 10, x + 30, y + 6), fill=fill, width=2)
        draw.line((x + 12, y + 31, x + 28, y + 31), fill=fill, width=2)
    elif kind == "eligibility":
        draw.line((x + 12, y + 8, x + 12, y + 28), fill=fill, width=2)
        draw.line((x + 12, y + 8, x + 29, y + 8), fill=fill, width=2)
        draw.line((x + 29, y + 8, x + 29, y + 28), fill=fill, width=2)
        draw.line((x + 12, y + 28, x + 21, y + 36), fill=fill, width=2)
        draw.line((x + 29, y + 28, x + 20, y + 36), fill=fill, width=2)


def _draw_wave(canvas, canvas_height):
    wave_layer = Image.new("RGBA", (TEMPLATE_WIDTH, canvas_height), (0, 0, 0, 0))
    wave_draw = ImageDraw.Draw(wave_layer)
    base_y = canvas_height
    wave_y = canvas_height - 110 if canvas_height == 1350 else canvas_height - 120
    wave_points = [
        (0, base_y),
        (0, wave_y),
        (120, wave_y - 40),
        (260, wave_y - 88),
        (420, wave_y - 52),
        (600, wave_y - 98),
        (760, wave_y - 70),
        (910, wave_y - 110),
        (1080, wave_y - 56),
        (1080, base_y),
    ]
    wave_draw.polygon(wave_points, fill=(4, 187, 86, 255))
    wave_draw.polygon(
        [
            (0, base_y),
            (0, wave_y + 10),
            (110, wave_y - 20),
            (260, wave_y + 10),
            (430, wave_y - 25),
            (620, wave_y + 6),
            (785, wave_y - 8),
            (980, wave_y - 12),
            (1080, wave_y + 30),
            (1080, base_y),
        ],
        fill=(0, 208, 132, 255),
    )
    canvas.alpha_composite(wave_layer, (0, 0))


def _fit_font(draw, text, max_width, min_size, max_size, bold=False):
    font = get_font(max_size, bold=bold)
    while max_size >= min_size:
        candidate = get_font(max_size, bold=bold)
        if text_width(draw, text, candidate) <= max_width:
            return candidate
        max_size -= 2
    return get_font(min_size, bold=bold)


def _find_job_card_background():
    """Find the reusable background saved at job_hunt/assets/images/job_card_bg.png."""
    env_path = os.getenv("JOB_CARD_BACKGROUND")
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser())

    module_path = Path(__file__).resolve()
    # Works whether this module is directly inside job_hunt or one package below it.
    for parent in module_path.parents:
        candidates.append(parent / "assets" / "images" / "job_card_bg.png")

    # The exact path supplied for the user's Windows project (fallback only).
    candidates.append(Path(r"C:\Users\Shrija\OneDrive\Desktop\srisha\tech_job_finder_main\job_hunt\assets\images\job_card_bg.png"))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _create_static_card(
    company, job_title, location, ctc, eligibility, experience, skills,
    application_link, brand_image_path=None, job_id=None, posted_on=None,
    job_type=None, tagline="CAREER OPPORTUNITY", role_note=None, location_note=None,
    ctc_note=None, experience_note=None, canvas_height=1920,
    promotional_text=None,
):
    """Create a bold editorial job poster inspired by the supplied IBM reference.

    Uses only provided values, with a large company wordmark, bold role title,
    left-aligned detail rows, and a large framed QR code with blue corner marks.
    """
    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), (246, 246, 247))
    draw = ImageDraw.Draw(image)
    navy = (12, 18, 32)
    blue = (0, 96, 255)
    cyan = (0, 166, 225)
    grey = (125, 128, 135)
    line_grey = (205, 207, 211)

    def clean(value):
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            return ", ".join(clean(v) for v in value if clean(v))
        text = str(value).strip()
        if not text or text.lower() in {
            "none", "null", "n/a", "na", "unknown", "not specified",
            "not available", "ctc not disclosed", "salary not disclosed",
            "eligibility not specified", "skills not specified", "india",
            "job opportunity", "company", "-", "not mentioned",
        }:
            return ""
        return re.sub(r"\s+", " ", text)

    def fit(text, max_width, start_size, min_size=28, bold=True):
        for size in range(start_size, min_size - 1, -2):
            font = get_font(size, bold)
            if text_width(draw, text, font) <= max_width:
                return font
        return get_font(min_size, bold)

    def draw_wrapped(text, box, font, fill, max_lines=3, spacing=8, align="left", stroke=0):
        x1, y1, x2, y2 = box
        lines = wrap_text(draw, text, font, x2 - x1)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            if lines:
                last = lines[-1]
                while last and text_width(draw, last + "…", font) > x2 - x1:
                    last = last[:-1]
                lines[-1] = last.rstrip() + "…"
        if not lines:
            return 0
        line_h = font.size + spacing
        total_h = len(lines) * line_h - spacing
        y = y1 + max(0, (y2 - y1 - total_h) // 2)
        for line in lines:
            if align == "center":
                draw.text(((x1 + x2) // 2, y), line, font=font, fill=fill, anchor="mt", stroke_width=stroke, stroke_fill=fill)
            else:
                draw.text((x1, y), line, font=font, fill=fill, anchor="lt", stroke_width=stroke, stroke_fill=fill)
            y += line_h
        return total_h

    def draw_gradient_text(text, box, font):
        x1, y1, x2, y2 = box
        lines = wrap_text(draw, text, font, x2 - x1)
        line_h = font.size + 4
        total_h = len(lines) * line_h - 4 if lines else 0
        y = y1 + max(0, (y2 - y1 - total_h) // 2)
        mask = Image.new("L", (width, height), 0)
        md = ImageDraw.Draw(mask)
        for line in lines:
            md.text(((x1 + x2) // 2, y), line, font=font, fill=255, anchor="mt", stroke_width=2, stroke_fill=255)
            y += line_h
        # Use a darker, more legible brand blue for the company wordmark so it stays
        # visible and premium without looking pastel or washed out.
        company_brand = (13, 87, 195)
        brand_deeper = (10, 60, 145)
        gradient = Image.new("RGB", (width, height), company_brand)
        gd = ImageDraw.Draw(gradient)
        for gx in range(max(0, x1), min(width, x2)):
            t = (gx - x1) / max(1, x2 - x1 - 1)
            color = tuple(round(company_brand[i] * (1 - t) + brand_deeper[i] * t) for i in range(3))
            gd.line((gx, y1, gx, y2), fill=color)
        image.paste(gradient, (0, 0), mask)

    company_text = clean(company)
    role_title = clean(job_title)
    if role_title and len(role_title.split()) <= 2:
        role_text = f"Role: {role_title}"
    else:
        role_text = role_title
    location = _coalesce_field(location, "India")
    eligibility = _coalesce_field(eligibility, "Bachelor's degree / B.Tech or equivalent")
    experience = _coalesce_field(experience, "")
    skills = _coalesce_field(skills, "")
    ctc = _coalesce_field(ctc, "")

    # Keep the brand block higher so the lower information stack and QR/CTA
    # have breathing room without crowding the top of the card.
    logo_y = 220
    logo_path = str(brand_image_path) if brand_image_path and os.path.isfile(str(brand_image_path)) else None
    logo_drawn = False
    if logo_path:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            alpha = logo.getchannel("A")
            bbox = alpha.getbbox()
            if bbox:
                logo = logo.crop(bbox)
            else:
                bbox = ImageOps.invert(logo.convert("RGB").convert("L")).getbbox()
                if bbox:
                    logo = logo.crop(bbox)
            logo.thumbnail((300, 150), Image.Resampling.LANCZOS)
            lx = (width - logo.width) // 2
            ly = logo_y + (150 - logo.height) // 2
            image.paste(logo, (lx, ly), logo if logo.mode == "RGBA" else None)
            draw = ImageDraw.Draw(image)
            logo_drawn = True
        except Exception:
            logo_path = None

    # Centered initials tile fallback when no real company logo can be fetched.
    if not logo_drawn and company_text:
        initials = "".join(part[0] for part in company_text.split()[:3]).upper()[:3]
        tile_w = tile_h = 112
        tile_x = (width - tile_w) // 2
        draw.rounded_rectangle((tile_x, logo_y + 12, tile_x + tile_w, logo_y + 12 + tile_h), radius=20, fill=(232, 241, 255), outline=(210, 226, 250), width=3)
        draw.text((width // 2, logo_y + 68), initials, font=get_font(48, True), fill=blue, anchor="mm", stroke_width=1, stroke_fill=blue)

    # Company name centered directly beneath the logo, using heavy gradient text.
    company_box = (60, 398, 1020, 530)
    if company_text:
        company_font = fit(company_text, 940, 112, 54, True)
        draw_gradient_text(company_text, company_box, company_font)

    # Role title follows the company name; keep it higher to leave room for
    # detail rows and the QR headline above the QR code itself.
    role_box = (78, 560, 1002, 760)
    if role_text:
        role_font = fit(role_text, 924, 78, 42, True)
        draw_wrapped(role_text, role_box, role_font, navy, max_lines=2, spacing=2, align="left", stroke=2)

    draw.rounded_rectangle((80, 790, 270, 799), radius=4, fill=line_grey)

    rows = [
        ("Location", clean(location)),
        ("Qualifications", clean(eligibility)),
        ("Salary", clean(ctc)),
        ("Experience", clean(experience)),
        ("Skills", clean(skills)),
    ]
    rows = [
        (label, value) for label, value in rows
        if value and value not in {"[]", "[ ]", "[", "]"}
        and not (label == "Skills" and re.fullmatch(r"\[.*\]", value) is not None and value.strip("[] ") == "")
    ]

    # Keep mandatory content in front. If the card starts to overflow, trim the
    # least important optional rows first: Skills, then Experience, then Salary.
    # We do not drop Location or Qualifications.
    if rows and not any(label == "Location" for label, _ in rows):
        rows.insert(0, ("Location", "India"))
    if rows and not any(label == "Qualifications" for label, _ in rows):
        rows.insert(1, ("Qualifications", "Bachelor's degree / B.Tech or equivalent"))

    # Fixed columns: every label starts at x=80 and every value at x=390.
    # Values are top-aligned to the label baseline; wrapped values stay in their row.
    left_x, right_x, right_edge = 80, 390, 1000
    rows_top = 820
    qr_present = bool(clean(application_link))
    details_bottom = 1360 if qr_present else 1780

    def build_prepared_rows(row_items):
        prepared = []
        for label, value in row_items:
            value_font = get_font(38, False)
            value_lines = wrap_text(draw, value, value_font, right_edge - right_x)
            while len(value_lines) > 3 and value_font.size > 30:
                value_font = get_font(value_font.size - 2, False)
                value_lines = wrap_text(draw, value, value_font, right_edge - right_x)
            line_height = value_font.size + 8
            row_height = max(64, len(value_lines) * line_height + 18)
            prepared.append((label, value, value_font, value_lines, row_height))
        return prepared

    candidate_rows = list(rows)
    while candidate_rows:
        prepared = build_prepared_rows(candidate_rows)
        required = sum(item[4] for item in prepared)
        if required <= (details_bottom - rows_top):
            break
        labels = [label for label, _ in candidate_rows]
        if "Skills" in labels:
            candidate_rows = [(label, value) for label, value in candidate_rows if label != "Skills"]
        elif "Experience" in labels:
            candidate_rows = [(label, value) for label, value in candidate_rows if label != "Experience"]
        elif "Salary" in labels:
            candidate_rows = [(label, value) for label, value in candidate_rows if label != "Salary"]
        else:
            break

    rows = candidate_rows
    if rows:
        label_font = get_font(38, True)
        prepared = build_prepared_rows(rows)

        available = details_bottom - rows_top
        required = sum(item[4] for item in prepared)
        if required > available and prepared:
            scale = available / required
            revised = []
            for label, value, value_font, value_lines, row_height in prepared:
                new_size = max(28, int(value_font.size * scale))
                value_font = get_font(new_size, False)
                value_lines = wrap_text(draw, value, value_font, right_edge - right_x)
                row_height = max(54, len(value_lines) * (new_size + 5) + 12)
                revised.append((label, value, value_font, value_lines, row_height))
            prepared = revised

        y = rows_top
        for label, value, value_font, value_lines, row_height in prepared:
            draw.text((left_x, y), label + ":", font=label_font, fill=(12, 14, 20), anchor="lt", stroke_width=1, stroke_fill=(12, 14, 20))
            line_y = y
            for line in value_lines[:3]:
                draw.text((right_x, line_y), line, font=value_font, fill=(20, 23, 30), anchor="lt")
                line_y += value_font.size + 8
            y += row_height

    # Large, scannable QR with the same blue corner-frame treatment as the reference.
    link = clean(application_link)
    if link:
        try:
            link = validate_application_link(link)
            qr_bytes = generate_qr_code(link)
            qr = Image.open(io.BytesIO(qr_bytes)).convert("RGB")
            qr_size = 340
            qr = qr.resize((qr_size, qr_size), Image.Resampling.NEAREST)
            qr_x, qr_y = (width - qr_size) // 2, 1405
            pad = 28
            frame = (qr_x - pad, qr_y - pad, qr_x + qr_size + pad, qr_y + qr_size + pad)
            draw.rounded_rectangle(frame, radius=28, fill=(255, 255, 255), outline=(225, 234, 250), width=4)
            image.paste(qr, (qr_x, qr_y))
            draw = ImageDraw.Draw(image)
            # Four blue corner brackets. Draw each segment with normalized endpoints
            # so all four corners render correctly, including the bottom-right corner.
            bx1, by1, bx2, by2 = frame
            inset = 18
            bracket = 48
            thick = 8
            corners = [
                (bx1 + inset, by1 + inset,  1,  1),  # top-left
                (bx2 - inset, by1 + inset, -1,  1),  # top-right
                (bx1 + inset, by2 - inset,  1, -1),  # bottom-left
                (bx2 - inset, by2 - inset, -1, -1),  # bottom-right
            ]
            for x, y, sx, sy in corners:
                # Horizontal segment
                hx1, hx2 = sorted((x, x + sx * bracket))
                hy1, hy2 = sorted((y, y + sy * thick))
                draw.rounded_rectangle((hx1, hy1, hx2, hy2), radius=4, fill=blue)
                # Vertical segment
                vx1, vx2 = sorted((x, x + sx * thick))
                vy1, vy2 = sorted((y, y + sy * bracket))
                draw.rounded_rectangle((vx1, vy1, vx2, vy2), radius=4, fill=blue)

            cta_box = (170, 1240, 910, 1332)
            draw.rounded_rectangle(cta_box, radius=32, fill=blue)
            cta_font = fit("SCAN TO APPLY HERE  →", cta_box[2] - cta_box[0] - 48, 42, 28, True)
            draw.text((width // 2, (cta_box[1] + cta_box[3]) // 2), "SCAN TO APPLY HERE  →", font=cta_font, fill=(255, 255, 255), anchor="mm", stroke_width=1, stroke_fill=(255, 255, 255))
        except Exception:
            pass

    return image

def validate_application_link(link):
    if not link:
        raise ValueError("Application link is required.")
    parsed = urlparse(str(link))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid application URL: {link}")
    return str(link)


def create_static_job_reel(
    company,
    job_title,
    location,
    ctc,
    eligibility,
    experience,
    skills,
    application_link,
    output_path=None,
    brand_image_path=None,
    job_id=None,
    posted_on=None,
    job_type=None,
    tagline="CAREER OPPORTUNITY",
    role_note=None,
    location_note=None,
    ctc_note=None,
    experience_note=None,
    canvas_height=HEIGHT,
    promotional_text=None,
):
    if application_link:
        try:
            application_link = validate_application_link(application_link)
        except ValueError:
            application_link = None
    company = str(company or "")
    job_title = str(job_title or "")
    if output_path is None:
        safe_company = re.sub(r"[^a-zA-Z0-9]+", "_", company).strip("_") or "company"
        safe_role = re.sub(r"[^a-zA-Z0-9]+", "_", job_title).strip("_") or "job"
        output_path = os.path.join(OUTPUT_DIR, f"{safe_company}_{safe_role}_static_reel.png")
    image = _create_static_card(
        company=company,
        job_title=job_title,
        location=location,
        ctc=ctc,
        eligibility=eligibility,
        experience=experience,
        skills=skills,
        application_link=application_link,
        brand_image_path=brand_image_path,
        job_id=job_id,
        posted_on=posted_on,
        job_type=job_type,
        tagline=tagline,
        role_note=role_note,
        location_note=location_note,
        ctc_note=ctc_note,
        experience_note=experience_note,
        canvas_height=canvas_height,
        promotional_text=promotional_text,
    )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    image.convert("RGB").save(output_path, format="PNG", optimize=True)
    return output_path


def create_video(
    image_path,
    output_path,
    background_audio_path=None,
    application_link=None,
    theme=None,
    details_image_path=None,
    demo_mode=False,
    scene_images=None,
    background_volume=DEFAULT_BACKGROUND_VOLUME,
    music_dir=MUSIC_DIR,
    include_qr_end_card=False,
):
    theme = theme or BrandTheme(BLUE, PURPLE, 0)
    bg = Image.new("RGB", (WIDTH, HEIGHT), (8, 15, 28))
    background_clip = VideoClip(
        frame_function=lambda t: np.asarray(bg),
        duration=REEL_DURATION_SECONDS,
    ).resized((WIDTH, HEIGHT))
    image_clip = ImageClip(image_path, transparent=False).with_duration(REEL_DURATION_SECONDS)
    clips = [background_clip, image_clip]
    final_clip = CompositeVideoClip(clips, size=(WIDTH, HEIGHT)).with_duration(REEL_DURATION_SECONDS)
    audio_clip = None
    source_audio = None
    try:
        if background_audio_path:
            source_audio = AudioFileClip(background_audio_path)
            audio_clip = source_audio
            if source_audio.duration < final_clip.duration:
                audio_clip = AudioLoop(duration=final_clip.duration).apply(source_audio)
            elif source_audio.duration > final_clip.duration:
                audio_clip = _audio_subclip(source_audio, 0, final_clip.duration)
            audio_clip = audio_clip.with_volume_scaled(background_volume)
            final_clip = final_clip.with_audio(audio_clip)
        elif music_dir:
            music_path = resolve_background_music_path(music_dir=music_dir)
            if music_path:
                source_audio = AudioFileClip(music_path)
                if source_audio.duration < final_clip.duration:
                    audio_clip = AudioLoop(duration=final_clip.duration).apply(source_audio)
                elif source_audio.duration > final_clip.duration:
                    audio_clip = _audio_subclip(source_audio, 0, final_clip.duration)
                audio_clip = audio_clip.with_volume_scaled(background_volume)
                final_clip = final_clip.with_audio(audio_clip)
        final_clip.write_videofile(
            output_path,
            fps=30,
            codec="libx264",
            audio=bool(audio_clip),
            audio_codec="aac" if audio_clip else None,
            preset="medium",
        )
        actual_duration = float(getattr(final_clip, "duration", 0) or 0)
        print(f"[REEL] Wrote {output_path}; expected duration={REEL_DURATION_SECONDS}s, timeline duration={actual_duration:.3f}s")
        if abs(actual_duration - REEL_DURATION_SECONDS) > 0.05:
            raise RuntimeError(f"Reel duration mismatch: expected {REEL_DURATION_SECONDS}s, got {actual_duration:.3f}s")
    finally:
        final_clip.close()
        image_clip.close()
        background_clip.close()
        if audio_clip:
            audio_clip.close()
        if source_audio:
            source_audio.close()


def _create_concept_frame(style, phase, company, job_title, location, ctc, eligibility, experience, skills, job_description, logo_path, theme):
    if phase.startswith("template_"):
        template_number = int(phase.removeprefix("template_"))
        if template_number == 11:
            return _create_static_card(company, job_title, location, ctc, eligibility, experience, skills, "https://example.com", brand_image_path=logo_path, job_id="template")
        return _create_static_card(company, job_title, location, ctc, eligibility, experience, skills, "https://example.com", brand_image_path=logo_path, job_id=f"{template_number}")
    return _create_static_card(company, job_title, location, ctc, eligibility, experience, skills, "https://example.com", brand_image_path=logo_path, job_id=f"{style}-{phase}")


def _concept_timeline(style, content_duration):
    if style == "reference":
        return [("reference", content_duration)]
    if style.startswith("template_"):
        return [(style, content_duration)]
    timelines = {
        "logo_reveal": [("brand", 2), ("company", 2), ("role", 2), ("eligible", 2), ("reference", max(0, content_duration - 8))],
        "salary_first": [("salary", 2), ("salary_reveal", 2), ("salary_role", 2), ("eligible", 2), ("reference", max(0, content_duration - 8))],
        "job_unlock": [("unlock_role", 1), ("unlock_location", 1), ("unlock_salary", 1), ("unlock_experience", 1), ("unlock_skills", 1), ("unlock_eligibility", 1), ("application_open", 2), ("reference", max(0, content_duration - 8))],
        "guess_company": [("guess_hook", 2), ("guess_salary", 2), ("guess_role", 2), ("guess_reveal", 2), ("reference", max(0, content_duration - 8))],
    }
    if style not in timelines:
        raise ValueError(f"Unsupported Reel style: {style}")
    return [(phase, duration) for phase, duration in timelines[style] if duration > 0]


def create_template_previews(
    company,
    job_title,
    location,
    ctc,
    eligibility,
    experience,
    skills,
    brand_image_path=None,
    job_id=None,
):
    safe_company = re.sub(r"[^a-zA-Z0-9]+", "_", str(company)).strip("_") or "company"
    safe_role = re.sub(r"[^a-zA-Z0-9]+", "_", str(job_title)).strip("_") or "job"
    prefix = f"{safe_company}_{safe_role}_{job_id or 'preview'}"
    theme = create_brand_theme(company, job_title, job_id, brand_image_path)
    previews = []
    for style, name in REEL_TEMPLATES:
        path = os.path.join(OUTPUT_DIR, f"{prefix}_{style}.png")
        frame = _create_concept_frame(style, style, company, job_title, location, ctc, eligibility, experience, skills, None, brand_image_path, theme)
        frame.save(path)
        previews.append({"style": style, "name": name, "path": path})
    return previews


def detect_category(job_title):
    title = str(job_title).lower()
    if any(x in title for x in ["software", "developer", "engineer", "backend", "frontend", "full stack", "devops", "sde"]):
        return ["#techjobs", "#softwarejobs", "#engineeringjobs", "#developerjobs"]
    if any(x in title for x in ["data", "analyst", "machine learning", "ml", "ai"]):
        return ["#datajobs", "#dataanalytics", "#aijobs", "#machinelearningjobs"]
    if "product" in title:
        return ["#productjobs", "#productmanagement", "#productcareers"]
    if any(x in title for x in ["intern", "internship"]):
        return ["#internship", "#internships", "#studentjobs"]
    return ["#careers", "#careeropportunities", "#professionaljobs"]


def get_experience_tags(eligibility):
    text = str(eligibility).lower()
    if any(x in text for x in ["fresher", "freshers", "graduate", "2026", "2025"]):
        return ["#freshers", "#fresherjobs", "#graduatejobs", "#2026graduates"]
    return ["#experiencedjobs", "#jobseekers"]


def get_location_tags(location):
    text = str(location).lower()
    mapping = {
        "hyderabad": ["#hyderabadjobs", "#hyderabadcareers", "#jobsinhyderabad"],
        "bangalore": ["#bangalorejobs", "#bangalorecareers", "#jobsinbangalore"],
        "bengaluru": ["#bangalorejobs", "#bangalorecareers", "#jobsinbangalore"],
        "pune": ["#punejobs", "#punecareers", "#jobsinpune"],
        "chennai": ["#chennaijobs", "#chennaicareers", "#jobsinchennai"],
        "mumbai": ["#mumbaijobs", "#mumbaicareers", "#jobsinmumbai"],
        "delhi": ["#delhijobs", "#delhicareers", "#jobsindelhi"],
    }
    for key, values in mapping.items():
        if key in text:
            return values
    return []


def get_skill_tags(skills):
    parts = re.split(r"[·,|/]+", str(skills))
    tags = []
    for skill in parts:
        item = clean_keyword(skill).replace(" ", "")
        if len(item) > 1:
            tags.append("#" + item)
    return tags


def get_company_tags(company):
    clean = re.sub(r"[^a-zA-Z0-9]", "", str(company)).lower()
    if not clean:
        return []
    return [f"#{clean}", f"#{clean}jobs", f"#{clean}careers"]


def create_caption(
    job_title,
    company,
    location,
    ctc,
    eligibility,
    skills,
    job_description,
    company_description,
    output_path,
    application_link=None,
    ctc_source="not_available",
    demo_mode=False,
):
    if demo_mode:
        caption = (
            "INDEPENDENT DESIGN CONCEPT ONLY\n"
            "This is not an official vacancy or employer announcement. "
            "The role details and compensation are fictional and are shown "
            "only to test Reel layouts.\n\n"
            f"Test link: {application_link or 'not provided'}"
        )
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(caption)
        return caption

    tag_candidates = [*detect_category(job_title)[:2], *get_location_tags(location)[:1], *get_company_tags(company)[:1]]
    hashtags = " ".join(dict.fromkeys(tag_candidates))
    eligibility_text = eligibility or "Bachelor's degree / B.Tech or equivalent"
    caption_lines = [
        f"🚀 {job_title} at {company}",
        f"📍 {location or 'India'}",
        f"🎓 {eligibility_text}",
        f"💼 {ctc or 'Salary not disclosed'}",
        "Scan the QR code or use the link to apply.",
        f"{application_link or 'Application link not available'}",
    ]
    caption = "\n".join(line for line in caption_lines if line)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(caption)
    return caption


def create_job_post(
    job_title=None,
    company=None,
    location=None,
    ctc=None,
    eligibility=None,
    experience=None,
    skills=None,
    job_description=None,
    company_description=None,
    application_link=None,
    ctc_source="not_available",
    brand_image_path=None,
    job_id=None,
    background_audio_path=None,
    background_volume=DEFAULT_BACKGROUND_VOLUME,
    demo_mode=False,
    reel_style="reference",
    static_image_path=None,
):
    job_title = str(job_title or "")
    company = str(company or "")
    location = _coalesce_field(location, "India")
    eligibility = _coalesce_field(eligibility, "Bachelor's degree / B.Tech or equivalent")
    experience = _coalesce_field(experience, "")
    skills = _coalesce_field(skills, "")
    ctc = _coalesce_field(ctc, "")
    if isinstance(skills, (list, tuple)):
        skills = " · ".join(str(skill) for skill in skills)
    skills = _coalesce_field(skills, "")
    if application_link:
        try:
            application_link = validate_application_link(application_link)
        except ValueError:
            application_link = None
    safe_company = re.sub(r"[^a-zA-Z0-9]+", "_", company).strip("_") or "company"
    safe_role = re.sub(r"[^a-zA-Z0-9]+", "_", job_title).strip("_") or "job"
    suffix = f"_{job_id}" if job_id else ""
    prefix = f"{safe_company}_{safe_role}{suffix}"
    card_path = os.path.join(OUTPUT_DIR, f"{prefix}_card.png")
    video_path = os.path.join(OUTPUT_DIR, f"{prefix}_reel.mp4")
    caption_path = os.path.join(OUTPUT_DIR, f"{prefix}_caption.txt")

    logo_path = brand_image_path
    if not logo_path:
        try:
            logo_path = download_logo(company, os.path.join(OUTPUT_DIR, f"{prefix}_company_logo.png"))
        except RuntimeError:
            logo_path = None

    # Rule: if a fresh company logo was downloaded or supplied, it wins over any
    # stale static preview. The stale preview can keep an older favicon/logo and
    # override the brand image even when the fetch succeeded.
    fresh_logo_available = bool((logo_path and os.path.isfile(str(logo_path))) or (brand_image_path and os.path.isfile(str(brand_image_path))))
    if fresh_logo_available:
        print(f"[LOGO] Fresh logo available: {logo_path or brand_image_path}; ignoring stale static_image_path={static_image_path}")
        static_image_path = None

    if static_image_path and os.path.isfile(static_image_path):
        # Only reuse a static preview when there is no newer brand image to prefer.
        print(f"[LOGO] Using saved static image for MP4 generation: {static_image_path}")
        card_path = static_image_path
    else:
        print(f"[LOGO] Creating card for company={company} with brand_image_path={logo_path}")
        card = _create_static_card(
            company=company,
            job_title=job_title,
            location=location,
            ctc=ctc,
            eligibility=eligibility,
            experience=experience,
            skills=skills,
            application_link=application_link,
            brand_image_path=logo_path,
            job_id=job_id,
        )
        card.save(card_path)

    create_video(
        image_path=card_path,
        output_path=video_path,
        background_audio_path=background_audio_path,
        background_volume=background_volume,
        theme=create_brand_theme(company, job_title, job_id, logo_path),
        application_link=application_link,
    )

    caption = create_caption(
        job_title=job_title,
        company=company,
        location=location,
        ctc=ctc,
        eligibility=eligibility,
        skills=skills,
        job_description=job_description,
        company_description=company_description,
        output_path=caption_path,
        application_link=application_link,
        ctc_source=ctc_source,
        demo_mode=demo_mode,
    )

    return {
        "card": card_path,
        "video": video_path,
        "caption": caption_path,
        "caption_text": caption,
    }


if __name__ == "__main__":
    result = create_job_post(
        job_title="Software Engineer",
        company="Microsoft",
        location="Hyderabad, India",
        ctc="₹15–25 LPA",
        eligibility="B.Tech CSE · 2026 Graduates",
        skills="Python · React · AWS",
        job_description="Build scalable software and solve real-world engineering problems.",
        company_description="Microsoft is a global technology company.",
        ctc_source="explicit",
    )
    print(result["caption_text"])