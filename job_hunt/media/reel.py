import os
import io
import re
import requests
import numpy as np

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
)
from moviepy.audio.fx import AudioLoop

from .background import (
    BrandTheme,
    animated_background_frame,
    create_brand_theme,
)
from .qr_code import generate_qr_code
from ..config import OUTPUT_DIR

# ============================================================
# SETTINGS
# ============================================================

WIDTH = 1080
HEIGHT = 1920
DURATION = 18
QR_END_CARD_DURATION = 5
REEL_TEMPLATES = (
    ("template_01", "Clean Editorial (Light)"),
    ("template_02", "Dark Neon (Premium)"),
    ("template_03", "Salary / Role Spotlight"),
    ("template_04", "Corporate Grid (Structured)"),
    ("template_05", "Gradient Brand (Vibrant)"),
    ("template_06", "Bold Opportunity (Dark)"),
    ("template_07", "Minimal Monochrome"),
    ("template_08", "Geometric Tech (Modern)"),
    ("template_09", "Fresher Spotlight (Batch Focus)"),
    ("template_10", "Premium Card (Balanced)"),
    ("template_11", "Desk Reference"),
)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# COLORS
# ============================================================

WHITE = (255, 255, 255)
BLACK = (15, 23, 42)
NAVY = (15, 23, 42)
BLUE = (37, 99, 235)
PURPLE = (124, 58, 237)
LIGHT_BLUE = (239, 246, 255)
LIGHT_PURPLE = (245, 243, 255)
GREY = (100, 116, 139)
BORDER = (226, 232, 240)

# ============================================================
# FONTS
# ============================================================

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

def find_font(paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return None

REGULAR_FONT = find_font(REGULAR_FONT_PATHS)
BOLD_FONT = find_font(BOLD_FONT_PATHS)

def get_font(size, bold=False):
    path = BOLD_FONT if bold else REGULAR_FONT
    if path is None:
        raise FileNotFoundError(
            "No suitable font found. Install Inter, Arial, or DejaVu Sans."
        )
    return ImageFont.truetype(path, size)

# ============================================================
# DISPLAY FALLBACKS
# These are visual fallbacks only; parser.py still returns null
# for information that was not found.
# ============================================================

DISPLAY_DEFAULTS = {
    "job_title": "Job Opportunity",
    "company": "Company",
    "location": "India",
    "ctc": "CTC NOT DISCLOSED",
    "eligibility": "Eligibility not specified",
    "skills": "Skills not specified",
}

KNOWN_DOMAINS = {
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
        test = (current + " " + word).strip()
        if text_width(draw, test, font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def get_company_domain(company):
    key = str(company).lower().strip()
    if key in KNOWN_DOMAINS:
        return KNOWN_DOMAINS[key]
    cleaned = re.sub(r"[^a-z0-9]", "", key)
    return (cleaned or "example") + ".com"

def download_logo(company, output_path):
    domain = get_company_domain(company)
    urls = [
        f"https://img.logo.dev/{domain}?size=256&format=png",
        f"https://www.google.com/s2/favicons?domain={domain}&sz=256",
    ]

    for url in urls:
        try:
            response = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if response.status_code != 200:
                continue

            image = Image.open(io.BytesIO(response.content)).convert("RGBA")
            if image.width < 20:
                continue

            bbox = image.getbbox()
            if bbox:
                image = image.crop(bbox)

            image.thumbnail((280, 280), Image.Resampling.LANCZOS)
            image.save(output_path)
            print(f"✓ Logo found for {company}")
            return output_path
        except Exception as e:
            print(f"Logo attempt failed: {e}")

    print(f"⚠ Could not find logo for {company}")
    return None

# ============================================================
# JOB CARD
# ============================================================

def create_job_card(
    job_title,
    company,
    location,
    ctc,
    eligibility,
    skills,
    output_path,
    ctc_source="not_available",
    brand_image_path=None,
):
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(252, 253, 255))
    draw.rectangle((0, 0, WIDTH, 18), fill=BLUE)

    blob = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
    blob_draw = ImageDraw.Draw(blob)
    blob_draw.ellipse((0, 0, 500, 500), fill=(37, 99, 235, 30))
    blob = blob.filter(ImageFilter.GaussianBlur(60))
    image.paste(blob, (650, -150), blob)
    draw = ImageDraw.Draw(image)

    logo = brand_image_path
    if not logo:
        logo_path = os.path.join(OUTPUT_DIR, "company_logo.png")
        logo = download_logo(company, logo_path)

    if logo:
        try:
            with Image.open(logo) as source:
                logo_img = ImageOps.fit(
                    source.convert("RGB"),
                    (250, 250),
                    method=Image.Resampling.LANCZOS,
                ).convert("RGBA")

            logo_x = (WIDTH - logo_img.width) // 2
            logo_y = 130
            padding = 24
            mask = Image.new("L", logo_img.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, logo_img.width - 1, logo_img.height - 1),
                radius=42,
                fill=255,
            )

            draw.rounded_rectangle(
                (
                    logo_x - padding,
                    logo_y - padding,
                    logo_x + logo_img.width + padding,
                    logo_y + logo_img.height + padding,
                ),
                radius=52,
                fill=WHITE,
                outline=BORDER,
                width=2,
            )
            image.paste(logo_img, (logo_x, logo_y), mask)
        except (OSError, ValueError) as error:
            print(f"⚠ Could not use supplied company image: {error}")
            logo = None

    if not logo:
        initial = str(company)[0].upper()
        circle = 220
        cx = (WIDTH - circle) // 2
        cy = 145
        draw.ellipse((cx, cy, cx + circle, cy + circle), fill=NAVY)
        center_text(draw, initial, cy + 45, get_font(95, True), WHITE)

    center_text(draw, str(company).upper(), 455, get_font(55, True), NAVY)

    badge_text = "HIRING NOW"
    badge_font = get_font(24, True)
    badge_width = text_width(draw, badge_text, badge_font) + 60
    badge_x = (WIDTH - badge_width) / 2

    draw.rounded_rectangle(
        (badge_x, 535, badge_x + badge_width, 590),
        radius=28,
        fill=LIGHT_BLUE,
    )
    center_text(draw, badge_text, 548, badge_font, BLUE)

    draw.line((80, 680, WIDTH - 80, 680), fill=BORDER, width=3)

    title_font = get_font(58, True)
    title_lines = wrap_text(draw, job_title, title_font, 900)
    title_y = 755

    for line in title_lines[:2]:
        center_text(draw, line, title_y, title_font, NAVY)
        title_y += 82

    center_text(
        draw,
        f"●  {location}",
        title_y + 10,
        get_font(32),
        GREY,
    )

    # Dynamic information cards.
    card_top = title_y + 105
    card_bottom = card_top

    if ctc:
        ctc_height = 185
        draw.rounded_rectangle(
            (64, card_top, WIDTH - 64, card_top + ctc_height),
            radius=40,
            fill=NAVY,
        )

        label = "EST. CTC" if ctc_source == "estimated" else "CTC"
        center_text(
            draw,
            label,
            card_top + 25,
            get_font(27, True),
            (148, 163, 184),
        )
        center_text(
            draw,
            str(ctc).replace("₹", "INR "),
            card_top + 70,
            get_font(58, True),
            WHITE,
        )
        card_bottom = card_top + ctc_height

    if eligibility:
        eligibility_top = card_bottom + 30
        eligibility_font = get_font(36, True)
        lines = wrap_text(draw, eligibility, eligibility_font, 820)
        height = max(150, 90 + 48 * min(len(lines), 2))

        draw.rounded_rectangle(
            (64, eligibility_top, WIDTH - 64, eligibility_top + height),
            radius=40,
            fill=LIGHT_PURPLE,
        )
        draw.rounded_rectangle(
            (64, eligibility_top, 80, eligibility_top + height),
            radius=8,
            fill=PURPLE,
        )
        center_text(
            draw,
            "ELIGIBILITY",
            eligibility_top + 25,
            get_font(27, True),
            PURPLE,
        )

        ey = eligibility_top + 72
        for line in lines[:2]:
            center_text(draw, line, ey, eligibility_font, NAVY)
            ey += 48

        card_bottom = eligibility_top + height

    if skills and skills != DISPLAY_DEFAULTS["skills"]:
        skills_top = card_bottom + 35
        skill_font = get_font(29, True)
        lines = wrap_text(draw, skills, skill_font, 850)

        center_text(draw, "KEY SKILLS", skills_top, get_font(25, True), BLUE)

        sy = skills_top + 42
        for line in lines[:2]:
            center_text(draw, line, sy, skill_font, GREY)
            sy += 40

    center_text(
        draw,
        "APPLICATION LINK IN CAPTION",
        HEIGHT - 105,
        get_font(27, True),
        BLUE,
    )

    image.save(output_path, quality=95)
    print(f"✓ Job card created: {output_path}")


def create_reel_scene(
    scene_number,
    job_title,
    company,
    location,
    ctc,
    eligibility,
    skills,
    job_description,
    brand_image_path=None,
    experience=None,
    brand_color=BLUE,
    lookup_logo=True,
    demo_mode=False,
    brand_accents=None,
):
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    accents = brand_accents or (brand_color,)
    accent_width = WIDTH // len(accents)
    for index, accent in enumerate(accents):
        draw.rectangle(
            (index * accent_width, 0, (index + 1) * accent_width, 12),
            fill=(*accent, 255),
        )
    logo = brand_image_path
    if not logo and lookup_logo:
        logo = download_logo(
            company,
            os.path.join(OUTPUT_DIR, "company_logo.png"),
        )
    logo_size = 104 if scene_number == 0 else 72
    logo_x, logo_y = 82, 115
    draw.rounded_rectangle(
        (logo_x, logo_y, logo_x + logo_size, logo_y + logo_size),
        radius=20,
        fill=(255, 255, 255, 255),
    )
    if logo and os.path.isfile(logo):
        try:
            with Image.open(logo) as source:
                logo_image = ImageOps.contain(
                    source.convert("RGBA"),
                    (logo_size - 18, logo_size - 18),
                    method=Image.Resampling.LANCZOS,
                )
            image.alpha_composite(
                logo_image,
                (
                    logo_x + (logo_size - logo_image.width) // 2,
                    logo_y + (logo_size - logo_image.height) // 2,
                ),
            )
            draw = ImageDraw.Draw(image)
        except (OSError, ValueError) as error:
            print(f"⚠ Could not use company image in Reel: {error}")
            logo = None
    if not logo:
        initial = str(company or "C")[:1].upper()
        center_text(draw, initial, logo_y + 18, get_font(58, True), brand_color)

    company_font = get_font(29 if scene_number == 0 else 25, True)
    company_x = logo_x + logo_size + 22
    company_y = logo_y + (logo_size - 36) // 2
    draw.text((company_x, company_y), company, font=company_font, fill=WHITE)
    if demo_mode:
        label = "DESIGN CONCEPT  /  NOT A LIVE JOB"
        draw.text(
            (company_x, company_y + 42),
            label,
            font=get_font(16, True),
            fill=(180, 190, 210, 255),
        )

    # A slim color rail and page marker give the two slides a clear sequence.
    draw.rounded_rectangle(
        (82, 270, 88, 1690),
        radius=3,
        fill=(255, 255, 255, 38),
    )
    draw.rounded_rectangle(
        (82, 270, 88, 990 if scene_number == 0 else 1690),
        radius=3,
        fill=(*brand_color, 255),
    )
    draw.text(
        (WIDTH - 160, 145),
        "01 / 02" if scene_number == 0 else "02 / 02",
        font=get_font(18, True),
        fill=(190, 198, 211, 255),
    )
    draw.text(
        (620, 1000),
        "01" if scene_number == 0 else "02",
        font=get_font(410, True),
        fill=(*brand_color, 18),
    )

    if scene_number == 0:
        draw.text(
            (122, 410),
            "CAREER OPPORTUNITY",
            font=get_font(22, True),
            fill=(*brand_color, 255),
        )
        title_font = get_font(88, True)
        title_lines = wrap_text(draw, job_title, title_font, 850)
        title_y = 500
        for line in title_lines[:3]:
            draw.text((122, title_y), line, font=title_font, fill=WHITE)
            title_y += 112

        draw.rounded_rectangle(
            (122, title_y + 12, 122 + 210, title_y + 66),
            radius=27,
            fill=(*brand_color, 255),
        )
        draw.text(
            (148, title_y + 24),
            "NOW HIRING",
            font=get_font(20, True),
            fill=WHITE,
        )
        location_text = location or "Location not specified"
        draw.text(
            (122, title_y + 110),
            location_text,
            font=get_font(30, True),
            fill=(222, 226, 235, 255),
        )

        tagline = "Build what comes next."
        draw.text(
            (122, 1380),
            tagline,
            font=get_font(27),
            fill=(185, 193, 207, 255),
        )
        draw.text(
            (122, 1560),
            "ROLE DETAILS  →",
            font=get_font(20, True),
            fill=(*brand_color, 255),
        )
    else:
        draw.text(
            (122, 330),
            "THE ROLE",
            font=get_font(21, True),
            fill=(*brand_color, 255),
        )
        title_font = get_font(56, True)
        title_lines = wrap_text(draw, job_title, title_font, 850)
        title_y = 380
        for line in title_lines[:2]:
            draw.text((122, title_y), line, font=title_font, fill=WHITE)
            title_y += 70

        details = [
            ("LOCATION", location or "Not specified"),
            ("EXPERIENCE", experience or "See job description"),
        ]
        if ctc:
            details.append(("COMPENSATION", str(ctc).replace("₹", "INR ")))
        if eligibility:
            details.append(("ELIGIBILITY", eligibility))

        details_y = max(600, title_y + 58)
        row_height = 142
        for index, (label, value) in enumerate(details[:4]):
            top = details_y + index * 160
            draw.line(
                (122, top, WIDTH - 100, top),
                fill=(255, 255, 255, 64),
                width=2,
            )
            draw.text(
                (122, top + 24),
                label,
                font=get_font(18, True),
                fill=(*brand_color, 255),
            )
            value_font = get_font(30, True)
            value_lines = wrap_text(draw, value, value_font, 790)
            for line_index, line in enumerate(value_lines[:2]):
                draw.text(
                    (122, top + 58 + line_index * 38),
                    line,
                    font=value_font,
                    fill=WHITE,
                )

        summary_y = details_y + min(len(details), 4) * 160 + 28
        description = re.sub(
            r"\s+",
            " ",
            job_description or "Explore this opportunity and its requirements.",
        ).strip()
        description_lines = wrap_text(draw, description, get_font(24), 820)
        draw.text(
            (122, summary_y),
            "ABOUT",
            font=get_font(18, True),
            fill=(*brand_color, 255),
        )
        for index, line in enumerate(description_lines[:3]):
            draw.text(
                (122, summary_y + 38 + index * 34),
                line,
                font=get_font(24),
                fill=(222, 226, 235, 255),
            )

        if skills:
            skills_y = min(summary_y + 170, 1510)
            draw.text(
                (122, skills_y),
                "SKILLS",
                font=get_font(18, True),
                fill=(*brand_color, 255),
            )
            skill_text = re.sub(r"\s+", " ", str(skills)).strip()
            for index, line in enumerate(wrap_text(draw, skill_text, get_font(23), 820)[:2]):
                draw.text(
                    (122, skills_y + 36 + index * 32),
                    line,
                    font=get_font(23),
                    fill=(222, 226, 235, 255),
                )

        draw.text(
            (122, 1610),
            "SCAN THE FINAL SCREEN TO APPLY",
            font=get_font(19, True),
            fill=(*brand_color, 255),
        )

    return image

# ============================================================
# CAPTION HELPERS
# ============================================================

def detect_category(job_title):
    title = str(job_title).lower()

    if any(x in title for x in [
        "software", "developer", "engineer", "backend",
        "frontend", "full stack", "devops", "sde"
    ]):
        return ["#techjobs", "#softwarejobs", "#engineeringjobs", "#developerjobs"]

    if any(x in title for x in [
        "data", "analyst", "machine learning", "ml", "ai"
    ]):
        return ["#datajobs", "#dataanalytics", "#aijobs", "#machinelearningjobs"]

    if "product" in title:
        return ["#productjobs", "#productmanagement", "#productcareers"]

    if any(x in title for x in ["intern", "internship"]):
        return ["#internship", "#internships", "#studentjobs"]

    return ["#careers", "#careeropportunities", "#professionaljobs"]

def get_experience_tags(eligibility):
    text = str(eligibility).lower()

    if any(x in text for x in [
        "fresher", "freshers", "graduate", "2026", "2025"
    ]):
        return ["#freshers", "#fresherjobs", "#graduatejobs", "#2026graduates"]

    return ["#experiencedjobs", "#jobseekers"]

def get_location_tags(location):
    text = str(location).lower()
    tags = []

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
            tags.extend(values)
            break

    return tags

def get_skill_tags(skills):
    parts = re.split(r"[·,|/]+", str(skills))
    tags = []

    for skill in parts:
        skill = clean_keyword(skill).replace(" ", "")
        if len(skill) > 1:
            tags.append("#" + skill)

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
        print(f"✓ Caption saved: {output_path}")
        return caption

    tag_candidates = [
        *detect_category(job_title)[:2],
        *get_experience_tags(eligibility)[:1],
        *get_location_tags(location)[:1],
        *get_company_tags(company)[:1],
    ]
    hashtags = " ".join(dict.fromkeys(tag_candidates))

    ctc_label = "EST. CTC" if ctc_source == "estimated" else "CTC"
    link_cta = (
        "Use the application link below or scan the QR code at the end of the Reel."
        if application_link
        else "Application link will be added after confirmation."
    )

    sections = [
        f"🚨 {job_title} at {company} — {location}",
        "New job opportunity for job seekers looking for this role and location.",
        "",
    ]

    if ctc:
        sections.append(f"💰 {ctc_label}: {ctc}")

    if eligibility:
        sections.append(f"🎓 Eligibility: {eligibility}")

    if job_description:
        sections.extend(["", "💼 ABOUT THE ROLE", job_description[:350].rstrip()])

    if company_description:
        sections.extend([
            "",
            f"🏢 ABOUT {str(company).upper()}",
            company_description[:250].rstrip(),
        ])

    sections.extend([
        "",
        "🔥 Interested in this opportunity?",
        "",
        link_cta,
        "Please verify the vacancy and details on the employer’s official careers page.",
        "",
        "📌 Save this post so you don't miss the deadline.",
        "📤 Share it with a friend who's job hunting!",
        "",
        f"🔎 Search: {job_title} jobs at {company} in {location}.",
        "",
        hashtags,
    ])
    if application_link:
        sections.extend(["", f"🔗 Apply here: {application_link}"])

    caption = "\n".join(sections)

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(caption)

    print(f"✓ Caption saved: {output_path}")
    return caption

# ============================================================
# VIDEO
# ============================================================

def create_video(
    image_path,
    output_path,
    background_audio_path=None,
    application_link=None,
    theme=None,
    details_image_path=None,
    demo_mode=False,
    scene_images=None,
):
    theme = theme or BrandTheme(BLUE, PURPLE, 0)
    background_clip = VideoClip(
        frame_function=lambda time_seconds: animated_background_frame(
            time_seconds,
            theme,
        ),
        duration=DURATION,
    ).resized((WIDTH, HEIGHT))
    content_duration = (
        DURATION - QR_END_CARD_DURATION if application_link else DURATION
    )
    scene_duration = content_duration / 2
    overlay_clip = None
    qr_clip = None
    clips = [background_clip]
    if not scene_images:
        overlay_clip = ImageClip(image_path, transparent=True).with_duration(
            scene_duration if details_image_path else DURATION
        )
        clips.append(overlay_clip)
    details_clip = None
    if details_image_path:
        details_clip = ImageClip(details_image_path, transparent=True).with_start(
            scene_duration
        ).with_duration(scene_duration)
        clips.append(details_clip)
    scene_clips = []
    if scene_images:
        start_time = 0
        for scene_path, duration in scene_images:
            scene_clip = ImageClip(scene_path, transparent=True).with_start(
                start_time
            ).with_duration(duration)
            scene_clips.append(scene_clip)
            clips.append(scene_clip)
            start_time += duration
    if application_link:
        end_card = _create_application_qr_end_card(
            application_link,
            theme,
            demo_mode=demo_mode,
        )
        qr_clip = ImageClip(np.asarray(end_card)).with_start(
            max(0, content_duration)
        ).with_duration(min(QR_END_CARD_DURATION, DURATION))
        clips.append(qr_clip)

    final_clip = CompositeVideoClip(
        clips,
        size=(WIDTH, HEIGHT),
    )
    audio_clip = None
    source_audio = None
    try:
        if background_audio_path:
            source_audio = AudioFileClip(background_audio_path)
            audio_clip = AudioLoop(duration=final_clip.duration).apply(source_audio)
            audio_clip = audio_clip.with_volume_scaled(0.10)
            final_clip = final_clip.with_audio(audio_clip)

        final_clip.write_videofile(
            output_path,
            fps=30,
            codec="libx264",
            audio=bool(background_audio_path),
            audio_codec="aac" if background_audio_path else None,
            preset="medium",
        )
    finally:
        final_clip.close()
        if audio_clip:
            audio_clip.close()
        if source_audio:
            source_audio.close()
        if qr_clip:
            qr_clip.close()
        if details_clip:
            details_clip.close()
        for scene_clip in scene_clips:
            scene_clip.close()
        background_clip.close()
        if overlay_clip:
            overlay_clip.close()
    print(f"✓ Video created: {output_path}")


def _create_application_qr_end_card(application_link, theme, demo_mode=False):
    qr = Image.open(io.BytesIO(generate_qr_code(application_link))).convert("RGB")
    qr.thumbnail((480, 480), Image.Resampling.NEAREST)

    end_card = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(end_card)
    accents = theme.accents or (theme.primary, theme.secondary)
    accent_width = WIDTH // len(accents)
    for index, accent in enumerate(accents):
        draw.rectangle(
            (index * accent_width, 0, (index + 1) * accent_width, 18),
            fill=accent,
        )
    if demo_mode:
        center_text(
            draw,
            "DESIGN CONCEPT  /  NOT A LIVE JOB",
            260,
            get_font(19, True),
            (180, 190, 210),
        )
    center_text(draw, "SCAN TO APPLY", 395, get_font(52, True), theme.primary)
    center_text(
        draw,
        "Open your camera and point it at the code",
        475,
        get_font(28),
        (203, 213, 225),
    )
    qr_x = (WIDTH - qr.width) // 2
    qr_y = 600
    end_card.paste(qr, (qr_x, qr_y))
    center_text(
        draw,
        "Application link",
        qr_y + qr.height + 48,
        get_font(30, True),
        theme.primary,
    )
    center_text(draw, "JOB HUNT HUB", 1470, get_font(26, True), (148, 163, 184))
    return end_card


def _draw_concept_logo(image, logo_path, company, color, size=184, y=410, left=None):
    draw = ImageDraw.Draw(image)
    left = (WIDTH - size) // 2 if left is None else left
    draw.rounded_rectangle(
        (left, y, left + size, y + size),
        radius=42,
        fill=(255, 255, 255, 255),
    )
    if logo_path and os.path.isfile(logo_path):
        try:
            with Image.open(logo_path) as source:
                mark = ImageOps.contain(
                    source.convert("RGBA"),
                    (size - 28, size - 28),
                    method=Image.Resampling.LANCZOS,
                )
            image.alpha_composite(
                mark,
                (left + (size - mark.width) // 2, y + (size - mark.height) // 2),
            )
        except (OSError, ValueError) as error:
            print(f"Could not render logo for {company}: {error}")
            draw.text(
                (left + size // 2, y + size // 2),
                str(company)[:1].upper(),
                font=get_font(90, True),
                fill=color,
                anchor="mm",
            )
    else:
        draw.text(
            (left + size // 2, y + size // 2),
            str(company)[:1].upper(),
            font=get_font(90, True),
            fill=color,
            anchor="mm",
        )


def _create_reference_frame(
    company,
    job_title,
    location,
    ctc,
    eligibility,
    experience,
    skills,
    job_description,
    logo_path,
    theme,
):
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))

    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.rounded_rectangle(
        (104, 275, WIDTH - 104, 1695),
        radius=64,
        outline=(*theme.primary, 185),
        width=12,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(26))
    image = Image.alpha_composite(image, glow)

    desk = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(desk)
    draw.polygon(
        [(0, 530), (105, 565), (105, 1405), (0, 1450)],
        fill=(11, 20, 38, 220),
        outline=(54, 81, 125, 180),
    )
    draw.polygon(
        [(0, 1405), (265, 1360), (390, 1515), (0, 1640)],
        fill=(39, 49, 68, 205),
        outline=(93, 111, 137, 150),
    )
    for row in range(5):
        for column in range(3):
            x = 20 + column * 27
            y = 1470 + row * 24
            draw.rounded_rectangle(
                (x, y, x + 18, y + 12),
                radius=2,
                fill=(130, 149, 176, 100),
            )
    draw.ellipse((920, 1230, 1100, 1410), fill=(3, 8, 18, 235), outline=(60, 70, 89, 255), width=7)
    draw.rounded_rectangle((948, 1270, 1070, 1555), radius=24, fill=(10, 18, 32, 225), outline=(60, 70, 89, 220), width=5)
    for leaf in range(5):
        x = 925 + leaf * 35
        draw.ellipse((x, 340 + (leaf % 2) * 45, x + 90, 520 + (leaf % 2) * 45), fill=(34, 88, 69, 135))
    image = Image.alpha_composite(image, desk)

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (116, 286, WIDTH - 116, 1684),
        radius=58,
        fill=(6, 12, 25, 242),
        outline=(86, 129, 195, 210),
        width=3,
    )
    draw.rounded_rectangle(
        (122, 292, WIDTH - 122, 301),
        radius=4,
        fill=(*theme.primary, 255),
    )

    _draw_concept_logo(image, logo_path, company, theme.primary, size=210, y=335)
    draw = ImageDraw.Draw(image)
    center_text(draw, company, 570, get_font(43, True), WHITE)
    center_text(draw, "CAREER OPPORTUNITY  /  DEMO CONCEPT", 628, get_font(17, True), (*theme.primary, 255))

    grid = [
        ("ROLE", job_title, "01"),
        ("LOCATION", location, "02"),
        ("COMPENSATION", ctc.replace("₹", "INR "), "03"),
        ("EXPERIENCE", experience, "04"),
    ]
    grid_left, grid_top, cell_width, cell_height, gap = 150, 690, 375, 162, 18
    for index, (label, value, number) in enumerate(grid):
        column, row = index % 2, index // 2
        x = grid_left + column * (cell_width + gap)
        y = grid_top + row * (cell_height + gap)
        draw.rounded_rectangle(
            (x, y, x + cell_width, y + cell_height),
            radius=24,
            fill=(20, 29, 46, 255),
            outline=(63, 78, 103, 210),
            width=2,
        )
        draw.rounded_rectangle(
            (x + 18, y + 22, x + 63, y + 67),
            radius=13,
            fill=(*theme.primary, 255),
        )
        draw.text((x + 29, y + 32), number, font=get_font(16, True), fill=WHITE)
        draw.text((x + 78, y + 30), label, font=get_font(15, True), fill=(167, 184, 207, 255))
        for line_index, line in enumerate(wrap_text(draw, value, get_font(19, True), cell_width - 35)[:2]):
            draw.text(
                (x + 20, y + 91 + line_index * 27),
                line,
                font=get_font(19, True),
                fill=WHITE,
            )

    skills_y = 1060
    draw.text((150, skills_y), "KEY SKILLS", font=get_font(16, True), fill=(*theme.primary, 255))
    skill_values = [part.strip() for part in re.split(r"[·,|/]+", str(skills)) if part.strip()]
    chip_x, chip_y = 150, skills_y + 34
    for skill in skill_values[:4]:
        chip_font = get_font(15, True)
        chip_width = min(text_width(draw, skill, chip_font) + 32, 350)
        if chip_x + chip_width > WIDTH - 145:
            chip_x = 150
            chip_y += 48
        draw.rounded_rectangle(
            (chip_x, chip_y, chip_x + chip_width, chip_y + 38),
            radius=19,
            fill=(34, 44, 63, 255),
            outline=(82, 99, 128, 180),
            width=1,
        )
        draw.text((chip_x + 16, chip_y + 10), skill, font=chip_font, fill=(226, 232, 240, 255))
        chip_x += chip_width + 10

    eligibility_y = chip_y + 78
    draw.rounded_rectangle(
        (150, eligibility_y, WIDTH - 150, eligibility_y + 92),
        radius=20,
        fill=(20, 29, 46, 255),
        outline=(63, 78, 103, 210),
        width=2,
    )
    draw.text((174, eligibility_y + 15), "ELIGIBILITY", font=get_font(15, True), fill=(*theme.primary, 255))
    for line_index, line in enumerate(wrap_text(draw, eligibility, get_font(18, True), 700)[:2]):
        draw.text(
            (174, eligibility_y + 42 + line_index * 24),
            line,
            font=get_font(18, True),
            fill=WHITE,
        )

    description = re.sub(r"\s+", " ", job_description or "").strip()
    if description:
        draw.text(
            (150, eligibility_y + 108),
            description[:110],
            font=get_font(16),
            fill=(182, 193, 210, 255),
        )
    draw.text(
        (150, eligibility_y + 150),
        "JOB TYPE   Full time     ·     POSTED   DEMO",
        font=get_font(15, True),
        fill=(182, 193, 210, 255),
    )

    button_y = 1534
    draw.rounded_rectangle(
        (270, button_y, WIDTH - 270, button_y + 84),
        radius=38,
        fill=(*theme.primary, 255),
    )
    center_text(draw, "APPLY NOW  →  QR AT END", button_y + 24, get_font(22, True), WHITE)
    draw.text((27, 470), "NEW JOB", font=get_font(18, True), fill=(255, 198, 64, 255))
    draw.line((70, 500, 108, 535), fill=(255, 198, 64, 255), width=4)
    draw.text((934, 745), "SAVE", font=get_font(17, True), fill=(255, 198, 64, 255))
    draw.line((950, 780, 918, 812), fill=(255, 198, 64, 255), width=4)
    return image


def _create_template_frame(
    template_number,
    company,
    job_title,
    location,
    ctc,
    eligibility,
    experience,
    skills,
    logo_path,
    theme,
):
    company = str(company or DISPLAY_DEFAULTS["company"])
    job_title = str(job_title or DISPLAY_DEFAULTS["job_title"])
    location = str(location or DISPLAY_DEFAULTS["location"])
    ctc = str(ctc or DISPLAY_DEFAULTS["ctc"])
    display_ctc = ctc.replace("₹", "INR ")
    eligibility = str(eligibility or DISPLAY_DEFAULTS["eligibility"])
    experience = str(experience or "Not specified")
    skills = str(skills or DISPLAY_DEFAULTS["skills"])

    if template_number == 11:
        return _create_reference_frame(
            company,
            job_title,
            location,
            ctc,
            eligibility,
            experience,
            skills,
            "Independent template preview. Verify the role on the employer careers page.",
            logo_path,
            theme,
        )

    light_templates = {1, 3, 4, 7, 9}
    light = template_number in light_templates
    background = (248, 249, 252, 255) if light else (7, 12, 27, 255)
    foreground = (18, 27, 44, 255) if light else WHITE
    muted = (90, 104, 125, 255) if light else (177, 190, 209, 255)
    accent = (112, 112, 112) if template_number == 7 else theme.primary
    image = Image.new("RGBA", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)

    if template_number == 1:
        draw.ellipse((780, -180, 1190, 250), fill=(*accent, 42))
        draw.ellipse((-190, 650, 130, 970), fill=(255, 100, 80, 70))
        draw.rectangle((0, 0, 22, HEIGHT), fill=(*accent, 255))
    elif template_number == 2:
        draw.polygon([(0, 0), (WIDTH, 0), (WIDTH, 330), (0, 800)], fill=(*theme.primary, 45))
        for offset in (0, 32, 64):
            draw.line((0, 600 + offset, WIDTH, 100 + offset), fill=(*theme.secondary, 150), width=3)
        draw.rounded_rectangle((52, 220, WIDTH - 52, 1700), radius=48, outline=(*theme.primary, 225), width=4)
    elif template_number == 5:
        left = theme.primary
        right = theme.secondary
        for y in range(HEIGHT):
            blend = y / HEIGHT
            color = tuple(round(left[channel] * (1 - blend) + right[channel] * blend) for channel in range(3))
            draw.line((0, y, WIDTH, y), fill=(*color, 255))
        draw.ellipse((750, 1150, 1200, 1600), fill=(255, 255, 255, 38))
        draw.ellipse((-150, 250, 230, 630), fill=(255, 255, 255, 25))
    elif template_number == 6:
        draw.rectangle((0, 0, 30, HEIGHT), fill=(*theme.primary, 255))
        draw.ellipse((710, 1120, 1250, 1660), fill=(*theme.primary, 45))
        draw.polygon([(0, 1460), (WIDTH, 1250), (WIDTH, HEIGHT), (0, HEIGHT)], fill=(255, 255, 255, 8))
    elif template_number == 7:
        draw.rectangle((0, 0, WIDTH, 16), fill=(40, 40, 40, 255))
        draw.line((90, 315, WIDTH - 90, 315), fill=(176, 181, 190, 255), width=2)
    elif template_number == 8:
        draw.polygon([(0, 0), (WIDTH, 0), (WIDTH, 540), (540, 800)], fill=(*theme.primary, 255))
        draw.polygon([(WIDTH, 300), (WIDTH, 900), (780, 1100)], fill=(*theme.secondary, 210))
        for offset in range(5):
            draw.line((700 + offset * 42, 900, 1000, 640 + offset * 42), fill=(255, 255, 255, 95), width=2)
    elif template_number == 9:
        draw.rectangle((0, 0, WIDTH, 390), fill=(255, 226, 136, 255))
        draw.ellipse((840, 280, 1160, 600), fill=(*theme.primary, 75))
    elif template_number == 10:
        draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(6, 13, 27, 255))
        draw.polygon([(720, 300), (WIDTH, 210), (WIDTH, 1650), (780, 1550)], fill=(*theme.primary, 65))
        draw.line((800, 320, 800, 1550), fill=(*theme.primary, 210), width=3)
    elif template_number == 4:
        draw.rectangle((0, 0, 26, HEIGHT), fill=(*theme.primary, 255))

    card_box = (55, 225, WIDTH - 55, 1700)
    card_fill = (255, 255, 255, 255) if light else (9, 16, 32, 235)
    card_outline = (219, 225, 234, 255) if light else (*accent, 180)
    draw.rounded_rectangle(card_box, radius=42, fill=card_fill, outline=card_outline, width=3)
    draw.rectangle((100, 250, WIDTH - 100, 258), fill=(*accent, 255))

    if template_number == 4:
        draw.rectangle((90, 270, 300, 1650), fill=(*theme.primary, 255))
        _draw_concept_logo(
            image,
            logo_path,
            company,
            theme.primary,
            size=150,
            y=330,
            left=120,
        )
        content_left = 335
    else:
        _draw_concept_logo(image, logo_path, company, theme.primary, size=110, y=300)
        content_left = 120
    draw = ImageDraw.Draw(image)

    logo_company_y = 465 if template_number == 4 else 430
    company_font_size = 24 if template_number == 4 else 27
    draw.text((content_left, logo_company_y), company, font=get_font(company_font_size, True), fill=foreground)
    draw.text((content_left, logo_company_y + 40), "INDEPENDENT DESIGN CONCEPT", font=get_font(14, True), fill=muted)

    if template_number == 3:
        ctc_font = get_font(55, True)
        ctc_lines = wrap_text(draw, display_ctc, ctc_font, 820)[:2]
        for index, line in enumerate(ctc_lines):
            draw.text((120, 555 + index * 68), line, font=ctc_font, fill=accent)
        title_y = 710
    elif template_number == 9:
        draw.rounded_rectangle((120, 560, WIDTH - 120, 680), radius=28, fill=(255, 229, 143, 255))
        draw.text((150, 582), "GRADUATES / EARLY CAREER", font=get_font(19, True), fill=(73, 57, 18, 255))
        for index, line in enumerate(wrap_text(draw, eligibility, get_font(23, True), 700)[:2]):
            draw.text((150, 616 + index * 28), line, font=get_font(23, True), fill=(43, 40, 31, 255))
        title_y = 730
    else:
        title_y = 555

    if template_number == 6:
        title_font_size = 68
        title_color = WHITE
    elif template_number == 3:
        title_font_size = 44
        title_color = foreground
    else:
        title_font_size = 48 if template_number == 4 else 53
        title_color = foreground
    title_font = get_font(title_font_size, True)
    title_width = WIDTH - content_left - 150
    title_lines = wrap_text(draw, job_title, title_font, title_width)[:3]
    for index, line in enumerate(title_lines):
        draw.text((content_left, title_y + index * (title_font_size + 9)), line, font=title_font, fill=title_color)
    title_bottom = title_y + len(title_lines) * (title_font_size + 9)

    if template_number == 3:
        draw.text((content_left, title_bottom + 8), location, font=get_font(21, True), fill=muted)
    elif template_number == 6:
        draw.text((content_left, title_bottom + 18), "BUILD  ·  SOLVE  ·  GROW", font=get_font(19, True), fill=(*theme.primary, 255))
    else:
        draw.text((content_left, title_bottom + 18), location, font=get_font(21, True), fill=muted)

    details_top = max(title_bottom + 90, 810)
    details = [
        ("COMPENSATION", display_ctc),
        ("EXPERIENCE", experience),
    ]
    if template_number != 9:
        details.append(("ELIGIBILITY", eligibility))
    details.append(("KEY SKILLS", skills))
    if template_number == 3:
        details = [
            ("EXPERIENCE", experience),
            ("ELIGIBILITY", eligibility),
            ("KEY SKILLS", skills),
        ]
    for index, (label, value) in enumerate(details):
        y = details_top + index * 154
        if template_number in {2, 4, 5, 8, 10}:
            draw.rounded_rectangle(
                (content_left, y, WIDTH - 112, y + 128),
                radius=20,
                fill=(21, 31, 51, 255) if not light else (243, 246, 250, 255),
                outline=(61, 75, 99, 255) if not light else (218, 225, 234, 255),
                width=1,
            )
        else:
            draw.line((content_left, y, WIDTH - 112, y), fill=(195, 203, 215, 180), width=2)
        draw.text((content_left + 18, y + 18), label, font=get_font(15, True), fill=accent)
        value_font = get_font(20, True)
        for line_index, line in enumerate(wrap_text(draw, value, value_font, WIDTH - content_left - 165)[:2]):
            draw.text((content_left + 18, y + 49 + line_index * 27), line, font=value_font, fill=foreground)

    apply_y = 1550
    apply_fill = (0, 0, 0, 255) if template_number == 7 else (*accent, 255)
    if template_number == 6:
        apply_fill = (*theme.primary, 255)
    draw.rounded_rectangle((content_left, apply_y, WIDTH - 115, apply_y + 82), radius=24, fill=apply_fill)
    draw.text((content_left + 28, apply_y + 24), "APPLY NOW  -  QR ON FINAL REEL", font=get_font(19, True), fill=WHITE)
    return image


def _create_concept_frame(
    style,
    phase,
    company,
    job_title,
    location,
    ctc,
    eligibility,
    experience,
    skills,
    job_description,
    logo_path,
    theme,
):
    if phase.startswith("template_"):
        template_number = int(phase.removeprefix("template_"))
        return _create_template_frame(
            template_number,
            company,
            job_title,
            location,
            ctc,
            eligibility,
            experience,
            skills,
            logo_path,
            theme,
        )

    if phase == "reference":
        return _create_reference_frame(
            company,
            job_title,
            location,
            ctc,
            eligibility,
            experience,
            skills,
            job_description,
            logo_path,
            theme,
        )

    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    accents = theme.accents or (theme.primary,)
    strip_width = WIDTH // len(accents)
    for index, accent in enumerate(accents):
        draw.rectangle(
            (index * strip_width, 0, (index + 1) * strip_width, 14),
            fill=(*accent, 255),
        )

    draw.rounded_rectangle(
        (54, 210, WIDTH - 54, 1720),
        radius=48,
        fill=(5, 11, 24, 214),
        outline=(*theme.primary, 145),
        width=2,
    )
    draw.text(
        (92, 244),
        "INDEPENDENT DESIGN CONCEPT - NOT AN OFFICIAL VACANCY",
        font=get_font(16, True),
        fill=(203, 213, 225, 255),
    )
    draw.rounded_rectangle(
        (90, 290, WIDTH - 90, 294),
        radius=2,
        fill=(255, 255, 255, 44),
    )

    def paragraph(text, y, size=32, color=WHITE, bold=True, max_width=850, max_lines=3):
        font = get_font(size, bold)
        lines = wrap_text(draw, text, font, max_width)[:max_lines]
        for line_index, line in enumerate(lines):
            center_text(draw, line, y + line_index * (size + 14), font, color)
        return y + len(lines) * (size + 14)

    def logo_and_company(size=128, y=350):
        _draw_concept_logo(image, logo_path, company, theme.primary, size=size, y=y)
        return y + size

    if phase in {"brand", "company", "guess_reveal", "salary_reveal"}:
        logo_y = 430 if phase == "brand" else 390
        logo_size = 250 if phase == "brand" else 190
        logo_and_company(size=logo_size, y=logo_y)
        title_y = logo_y + logo_size + 86
        if phase == "brand":
            headline = "NEW JOB ALERT"
            paragraph(headline, title_y, size=47, color=theme.primary)
            paragraph(company, title_y + 100, size=38, max_lines=1)
        elif phase == "company":
            paragraph(f"A NEW OPPORTUNITY AT", title_y, size=24, color=theme.primary)
            paragraph(company, title_y + 64, size=49, max_lines=1)
            paragraph("Save this. Check the official listing.", title_y + 150, size=22, bold=False, color=(211, 219, 231, 255))
        elif phase in {"guess_reveal", "salary_reveal"}:
            paragraph("THE COMPANY IS", title_y, size=22, color=theme.primary)
            paragraph(company, title_y + 72, size=48, max_lines=1)
            paragraph(job_title, title_y + 160, size=31, max_lines=2)
        return image

    if phase == "role":
        paragraph("THE ROLE", 430, size=22, color=theme.primary)
        paragraph(job_title, 530, size=70, max_lines=3)
        paragraph(location, 920, size=30, color=(211, 219, 231, 255))
        paragraph(experience, 1000, size=25, color=(171, 184, 202, 255), bold=False)
        return image

    if phase == "eligible":
        paragraph("ELIGIBLE?", 470, size=68, color=theme.primary)
        paragraph(eligibility, 600, size=34, max_lines=3)
        paragraph("SAVE THIS  ·  APPLY NOW", 1030, size=31, color=WHITE)
        paragraph("Verify the opening on the official careers page.", 1150, size=20, color=(184, 196, 213, 255), bold=False)
        return image

    if phase == "salary":
        paragraph("THE NUMBER FIRST", 425, size=21, color=theme.primary)
        paragraph(ctc.replace("₹", "INR "), 650, size=84, max_lines=2)
        paragraph("DEMO FIGURE · VERIFY WITH EMPLOYER", 885, size=19, color=(188, 198, 213, 255), bold=False)
        return image

    if phase == "salary_role":
        paragraph(ctc.replace("₹", "INR "), 420, size=69, max_lines=2)
        paragraph(company, 655, size=38, color=theme.primary, max_lines=1)
        paragraph(job_title, 760, size=52, max_lines=2)
        paragraph(eligibility, 1050, size=26, color=(211, 219, 231, 255), bold=False)
        return image

    if phase.startswith("unlock_"):
        key = phase.removeprefix("unlock_")
        details = {
            "role": ("01  /  ROLE", job_title),
            "location": ("02  /  LOCATION", location),
            "salary": ("03  /  COMPENSATION", ctc.replace("₹", "INR ")),
            "experience": ("04  /  EXPERIENCE", experience),
            "skills": ("05  /  SKILLS", skills),
            "eligibility": ("06  /  ELIGIBILITY", eligibility),
        }
        label, value = details[key]
        paragraph("JOB UNLOCK", 400, size=23, color=theme.primary)
        draw.rounded_rectangle(
            (115, 535, WIDTH - 115, 1120),
            radius=38,
            fill=(255, 255, 255, 13),
            outline=(*theme.primary, 180),
            width=2,
        )
        paragraph(label, 675, size=20, color=(193, 203, 219, 255))
        paragraph(value, 775, size=54, max_lines=3)
        scan_y = 535 + list(details).index(key) * 116
        draw.rectangle((105, scan_y, WIDTH - 105, scan_y + 5), fill=(*theme.primary, 255))
        draw.ellipse((WIDTH - 120, scan_y - 8, WIDTH - 96, scan_y + 16), fill=WHITE)
        paragraph("SCANNING OPPORTUNITY", 1320, size=20, color=(193, 203, 219, 255), bold=False)
        return image

    if phase == "application_open":
        paragraph("APPLICATION", 550, size=30, color=(202, 212, 226, 255))
        paragraph("OPEN", 650, size=112, color=theme.primary)
        paragraph("Check the official careers page to apply.", 900, size=24, color=WHITE, bold=False)
        return image

    if phase == "guess_hook":
        paragraph("A ROLE AT A TOP TECH COMPANY", 480, size=23, color=theme.primary)
        paragraph("GUESS THE", 680, size=55)
        paragraph("COMPANY", 770, size=80, color=WHITE)
        paragraph("We’ll reveal it in a moment.", 1000, size=23, color=(192, 202, 218, 255), bold=False)
        return image

    if phase == "guess_salary":
        paragraph("HERE'S THE CLUE", 440, size=22, color=theme.primary)
        paragraph(ctc, 610, size=82, max_lines=2)
        paragraph("DEMO FIGURE · NOT AN EMPLOYER CLAIM", 875, size=18, color=(188, 198, 213, 255), bold=False)
        return image

    if phase == "guess_role":
        paragraph("THE ROLE", 450, size=22, color=theme.primary)
        paragraph(job_title, 570, size=68, max_lines=3)
        paragraph(location, 970, size=28, color=(211, 219, 231, 255))
        paragraph("Can you guess the company?", 1110, size=23, color=(188, 198, 213, 255), bold=False)
        return image

    raise ValueError(f"Unsupported concept phase: {phase}")


def _concept_timeline(style, content_duration):
    if style == "reference":
        style = "template_11"
    if style.startswith("template_"):
        try:
            template_number = int(style.removeprefix("template_"))
        except ValueError as error:
            raise ValueError(f"Unsupported Reel style: {style}") from error
        if not 1 <= template_number <= len(REEL_TEMPLATES):
            raise ValueError(f"Unsupported Reel style: {style}")
        return [(style, content_duration)]

    timelines = {
        "logo_reveal": [
            ("brand", 2),
            ("company", 2),
            ("role", 2),
            ("eligible", 2),
            ("reference", content_duration - 8),
        ],
        "salary_first": [
            ("salary", 2),
            ("salary_reveal", 2),
            ("salary_role", 2),
            ("eligible", 2),
            ("reference", content_duration - 8),
        ],
        "job_unlock": [
            ("unlock_role", 1),
            ("unlock_location", 1),
            ("unlock_salary", 1),
            ("unlock_experience", 1),
            ("unlock_skills", 1),
            ("unlock_eligibility", 1),
            ("application_open", 2),
            ("reference", content_duration - 8),
        ],
        "guess_company": [
            ("guess_hook", 2),
            ("guess_salary", 2),
            ("guess_role", 2),
            ("guess_reveal", 2),
            ("reference", content_duration - 8),
        ],
    }
    if style not in timelines:
        raise ValueError(f"Unsupported Reel style: {style}")
    timeline = timelines[style]
    return [(phase, duration) for phase, duration in timeline if duration > 0]


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
    logo_path = brand_image_path
    if not logo_path:
        logo_path = download_logo(
            company,
            os.path.join(OUTPUT_DIR, f"{prefix}_company_logo.png"),
        )
    theme = create_brand_theme(company, job_title, job_id, logo_path)
    previews = []
    background = Image.fromarray(
        animated_background_frame(0, theme, size=(WIDTH, HEIGHT))
    ).convert("RGBA")
    for template_number, (style, name) in enumerate(REEL_TEMPLATES, start=1):
        path = os.path.join(OUTPUT_DIR, f"{prefix}_{style}.png")
        image = _create_template_frame(
            template_number,
            company,
            job_title,
            location or "Location not specified",
            ctc or DISPLAY_DEFAULTS["ctc"],
            eligibility or DISPLAY_DEFAULTS["eligibility"],
            experience or "Not specified",
            skills or DISPLAY_DEFAULTS["skills"],
            logo_path,
            theme,
        )
        Image.alpha_composite(background, image.convert("RGBA")).convert("RGB").save(path)
        previews.append({"style": style, "name": name, "path": path})
    return previews


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
):
    company = str(company or DISPLAY_DEFAULTS["company"])
    job_title = str(job_title or DISPLAY_DEFAULTS["job_title"])
    location = str(location or DISPLAY_DEFAULTS["location"])
    ctc = str(ctc or DISPLAY_DEFAULTS["ctc"])
    eligibility = str(eligibility or DISPLAY_DEFAULTS["eligibility"])
    experience = str(experience or "Not specified")
    qr_png = generate_qr_code(application_link)
    if isinstance(skills, (list, tuple)):
        skills = " · ".join(str(skill) for skill in skills)
    skills = str(skills or DISPLAY_DEFAULTS["skills"])

    safe_company = re.sub(r"[^a-zA-Z0-9]+", "_", company).strip("_") or "company"
    safe_role = re.sub(r"[^a-zA-Z0-9]+", "_", job_title).strip("_") or "job"
    if output_path is None:
        suffix = f"_{job_id}" if job_id else ""
        output_path = os.path.join(
            OUTPUT_DIR,
            f"{safe_company}_{safe_role}{suffix}_static_reel.png",
        )

    theme = create_brand_theme(company, job_title, job_id, brand_image_path)
    width, height = WIDTH, HEIGHT
    x_grid, y_grid = np.meshgrid(
        np.linspace(0, 1, width, dtype=np.float32),
        np.linspace(0, 1, height, dtype=np.float32),
    )
    glow = np.exp(-(((x_grid - 0.5) / 0.48) ** 2 + ((y_grid - 0.5) / 0.62) ** 2) * 2)
    background_pixels = np.empty((height, width, 3), dtype=np.float32)
    grain = np.random.default_rng(theme.seed).normal(0, 1.8, (height, width))
    for channel, base in enumerate((5, 10, 20)):
        background_pixels[:, :, channel] = (
            base + glow * theme.primary[channel] * 0.19 + grain
        )
    image = Image.fromarray(np.clip(background_pixels, 0, 255).astype(np.uint8)).convert("RGBA")

    ambient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ambient_draw = ImageDraw.Draw(ambient)
    for x, y, radius, color in (
        (45, 560, 52, (26, 125, 255, 95)),
        (74, 930, 20, (20, 204, 244, 145)),
        (1010, 735, 22, (255, 159, 51, 180)),
        (990, 815, 10, (255, 218, 138, 185)),
        (1000, 1200, 28, (255, 151, 42, 100)),
    ):
        ambient_draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    ambient = ambient.filter(ImageFilter.GaussianBlur(32))
    image = Image.alpha_composite(image, ambient)

    # Desk props frame the card without competing with its job details or QR.
    desk = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(desk)
    draw.polygon(
        [(0, 0), (120, 0), (155, 1000), (0, 1080)],
        fill=(16, 27, 47, 230),
        outline=(34, 58, 91, 210),
    )
    draw.polygon(
        [(0, 1370), (300, 1305), (490, 1920), (0, 1920)],
        fill=(38, 40, 55, 240),
        outline=(87, 91, 107, 180),
    )
    for row in range(7):
        for column in range(3):
            key_x = 18 + column * 34
            key_y = 1450 + row * 42
            draw.rounded_rectangle(
                (key_x, key_y, key_x + 24, key_y + 24),
                radius=5,
                fill=(117, 134, 157, 100),
            )
    draw.polygon(
        [(0, 1740), (260, 1680), (455, 1920), (0, 1920)],
        fill=(120, 101, 111, 145),
    )
    for row in range(4):
        draw.line(
            (16, 1780 + row * 34, 275, 1725 + row * 34),
            fill=(206, 197, 195, 130),
            width=2,
        )
    draw.ellipse((912, 1490, 1125, 1703), fill=(2, 5, 12, 235), outline=(72, 83, 101, 255), width=8)
    draw.ellipse((934, 1512, 1103, 1682), fill=(13, 19, 31, 255), outline=(121, 86, 53, 210), width=5)
    draw.rounded_rectangle((934, 1580, 1097, 1900), radius=30, fill=(11, 17, 28, 245), outline=(65, 78, 99, 230), width=5)
    draw.arc((912, 1475, 1120, 1690), 185, 345, fill=(116, 129, 147, 255), width=9)
    for leaf in range(6):
        leaf_x = 915 + (leaf % 3) * 44
        leaf_y = 225 + (leaf // 3) * 38
        draw.ellipse((leaf_x, leaf_y, leaf_x + 72, leaf_y + 148), fill=(25, 83, 67, 145))
    image = Image.alpha_composite(image, desk)

    # Neon frame and bloom around the glass job card.
    glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_draw.rounded_rectangle((100, 250, 980, 1748), radius=72, outline=(*theme.primary, 220), width=8)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(28))
    image = Image.alpha_composite(image, glow_layer)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (116, 270, 964, 1728),
        radius=64,
        fill=(7, 13, 25, 247),
        outline=(69, 101, 149, 235),
        width=3,
    )

    neon = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    neon_draw = ImageDraw.Draw(neon)
    neon_draw.rounded_rectangle((109, 276, 971, 1720), radius=68, outline=(21, 190, 255, 205), width=5)
    neon_draw.arc((100, 290, 985, 1730), 75, 168, fill=(255, 183, 38, 245), width=7)
    neon_draw.arc((100, 290, 985, 1730), 245, 330, fill=(156, 71, 255, 220), width=6)
    neon = neon.filter(ImageFilter.GaussianBlur(10))
    image = Image.alpha_composite(image, neon)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (116, 270, 964, 1728),
        radius=64,
        outline=(74, 151, 221, 235),
        width=3,
    )

    # Logo tile with soft shadow and a compact Google-style mark when no logo is supplied.
    logo_size = 252
    logo_left = (width - logo_size) // 2
    logo_top = 292
    tile_shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(tile_shadow).rounded_rectangle(
        (logo_left - 5, logo_top + 12, logo_left + logo_size + 5, logo_top + logo_size + 22),
        radius=54,
        fill=(0, 0, 0, 165),
    )
    tile_shadow = tile_shadow.filter(ImageFilter.GaussianBlur(18))
    image = Image.alpha_composite(image, tile_shadow)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (logo_left, logo_top, logo_left + logo_size, logo_top + logo_size),
        radius=48,
        fill=(247, 249, 255, 255),
        outline=(211, 225, 248, 255),
        width=3,
    )
    logo_drawn = False
    if brand_image_path and os.path.isfile(brand_image_path):
        try:
            with Image.open(brand_image_path) as source:
                logo = ImageOps.contain(
                    source.convert("RGBA"),
                    (logo_size - 60, logo_size - 60),
                    method=Image.Resampling.LANCZOS,
                )
            image.alpha_composite(
                logo,
                (
                    logo_left + (logo_size - logo.width) // 2,
                    logo_top + (logo_size - logo.height) // 2,
                ),
            )
            logo_drawn = True
        except (OSError, ValueError) as error:
            print(f"Could not render supplied company logo: {error}")
    if not logo_drawn and company.casefold() == "google":
        draw = ImageDraw.Draw(image)
        mark_box = (logo_left + 58, logo_top + 58, logo_left + 194, logo_top + 194)
        draw.arc(mark_box, 35, 325, fill=(66, 133, 244, 255), width=34)
        draw.arc(mark_box, 215, 270, fill=(234, 67, 53, 255), width=34)
        draw.arc(mark_box, 150, 215, fill=(251, 188, 5, 255), width=34)
        draw.arc(mark_box, 90, 150, fill=(52, 168, 83, 255), width=34)
        draw.rectangle((logo_left + 128, logo_top + 112, logo_left + 204, logo_top + 146), fill=(66, 133, 244, 255))
    elif not logo_drawn:
        draw = ImageDraw.Draw(image)
        initial = company[:1].upper()
        initial_font = get_font(106, True)
        draw.text(
            (width // 2, logo_top + logo_size // 2),
            initial,
            font=initial_font,
            fill=theme.primary,
            anchor="mm",
        )

    draw = ImageDraw.Draw(image)
    company_font_size = 56
    company_font = get_font(company_font_size, True)
    while text_width(draw, company, company_font) > 650 and company_font_size > 36:
        company_font_size -= 2
        company_font = get_font(company_font_size, True)
    company_width = text_width(draw, company, company_font)
    company_left = (width - company_width) // 2
    draw.text((company_left, 575), company, font=company_font, fill=WHITE)
    if company.casefold() == "google":
        badge_x = company_left + company_width + 18
        draw.ellipse((badge_x, 590, badge_x + 34, 624), fill=(32, 161, 242, 255))
        draw.line([(badge_x + 9, 607), (badge_x + 16, 614), (badge_x + 27, 600)], fill=WHITE, width=4)
    center_text(draw, tagline, 644, get_font(25, True), (157, 175, 203, 255))

    accent_colors = ((94, 158, 255), (255, 85, 105), (255, 193, 42), (131, 73, 255))
    details = (
        ("ROLE", job_title, role_note, accent_colors[0]),
        ("LOCATION", location, location_note, accent_colors[1]),
        ("CTC", ctc.replace("₹", "INR "), ctc_note, accent_colors[2]),
        ("EXPERIENCE", experience, experience_note, accent_colors[2]),
    )
    cell_positions = ((145, 704), (558, 704), (145, 875), (558, 875))
    for (label, value, note, accent), (left, top) in zip(details, cell_positions):
        draw.rounded_rectangle(
            (left, top, left + 377, top + 150),
            radius=27,
            fill=(17, 27, 44, 255),
            outline=(42, 55, 76, 255),
            width=2,
        )
        icon_box = (left + 22, top + 35, left + 69, top + 82)
        draw.rounded_rectangle(icon_box, radius=15, fill=(*accent, 255))
        icon_center_x = (icon_box[0] + icon_box[2]) // 2
        icon_center_y = (icon_box[1] + icon_box[3]) // 2
        ink = (8, 14, 27, 255)
        if label == "ROLE":
            draw.rounded_rectangle((icon_center_x - 12, icon_center_y - 6, icon_center_x + 12, icon_center_y + 10), radius=3, outline=ink, width=3)
            draw.arc((icon_center_x - 7, icon_center_y - 13, icon_center_x + 7, icon_center_y + 1), 180, 360, fill=ink, width=3)
        elif label == "LOCATION":
            draw.ellipse((icon_center_x - 9, icon_center_y - 13, icon_center_x + 9, icon_center_y + 5), outline=ink, width=3)
            draw.ellipse((icon_center_x - 3, icon_center_y - 7, icon_center_x + 3, icon_center_y - 1), fill=ink)
            draw.polygon([(icon_center_x - 7, icon_center_y + 1), (icon_center_x + 7, icon_center_y + 1), (icon_center_x, icon_center_y + 14)], fill=ink)
        elif label == "CTC":
            for coin_y in (icon_center_y - 7, icon_center_y, icon_center_y + 7):
                draw.ellipse((icon_center_x - 12, coin_y - 4, icon_center_x + 3, coin_y + 4), outline=ink, width=2)
            draw.line((icon_center_x + 5, icon_center_y - 10, icon_center_x + 12, icon_center_y - 10), fill=ink, width=3)
            draw.line((icon_center_x + 5, icon_center_y - 3, icon_center_x + 12, icon_center_y - 3), fill=ink, width=3)
            draw.line((icon_center_x + 5, icon_center_y + 4, icon_center_x + 12, icon_center_y + 4), fill=ink, width=3)
        else:
            for bar_index, bar_height in enumerate((11, 18, 25)):
                bar_left = icon_center_x - 14 + bar_index * 11
                draw.rounded_rectangle((bar_left, icon_center_y + 11 - bar_height, bar_left + 7, icon_center_y + 11), radius=2, fill=ink)
        draw.text((left + 88, top + 20), label, font=get_font(18, True), fill=(158, 174, 199, 255))
        value_font = get_font(23, True)
        value_lines = wrap_text(draw, value, value_font, 260)[:2]
        for line_index, line in enumerate(value_lines):
            draw.text((left + 88, top + 50 + line_index * 29), line, font=value_font, fill=WHITE)
        if note:
            draw.text((left + 88, top + 113), note, font=get_font(16), fill=(148, 163, 186, 255))

    draw.rounded_rectangle((145, 1049, 935, 1166), radius=26, fill=(14, 25, 42, 255), outline=(38, 52, 74, 255), width=2)
    draw.rounded_rectangle((168, 1070, 202, 1104), radius=8, fill=(127, 67, 255, 255))
    for skill_line_y in (1079, 1087, 1095):
        draw.line((177, skill_line_y, 193, skill_line_y), fill=WHITE, width=2)
    draw.text((221, 1067), "KEY SKILLS", font=get_font(20, True), fill=(166, 182, 207, 255))
    skill_values = [value.strip() for value in re.split(r"[·,|/]+", skills) if value.strip()]
    chip_x, chip_y = 220, 1110
    chip_font = get_font(14, True)
    for skill in skill_values[:5]:
        chip_width = min(text_width(draw, skill, chip_font) + 32, 300)
        if chip_x + chip_width > 920:
            chip_x = 220
            chip_y += 37
        draw.rounded_rectangle((chip_x, chip_y, chip_x + chip_width, chip_y + 31), radius=16, fill=(28, 54, 82, 255))
        draw.text((chip_x + 16, chip_y + 8), skill, font=chip_font, fill=(224, 234, 249, 255))
        chip_x += chip_width + 8

    draw.rounded_rectangle((145, 1184, 935, 1370), radius=25, fill=(10, 20, 36, 255), outline=(34, 49, 72, 255), width=2)
    draw.rounded_rectangle((168, 1210, 202, 1244), radius=8, fill=(66, 115, 255, 255))
    draw.polygon([(185, 1215), (200, 1222), (185, 1229), (170, 1222)], fill=WHITE)
    draw.polygon([(175, 1225), (195, 1225), (192, 1234), (178, 1234)], fill=WHITE)
    draw.text((221, 1207), "ELIGIBILITY", font=get_font(20, True), fill=(166, 182, 207, 255))
    eligibility_font = get_font(21, True)
    for line_index, line in enumerate(wrap_text(draw, eligibility, eligibility_font, 660)[:2]):
        draw.text((221, 1243 + line_index * 28), line, font=eligibility_font, fill=(220, 229, 245, 255))
    if job_type:
        draw.text((221, 1322), f"JOB TYPE   {job_type}", font=get_font(17, True), fill=(148, 166, 193, 255))
    if posted_on:
        draw.text((592, 1322), f"POSTED   {posted_on}", font=get_font(17, True), fill=(148, 166, 193, 255))

    qr = Image.open(io.BytesIO(qr_png)).convert("RGB")
    qr = qr.resize((176, 176), Image.Resampling.NEAREST)
    qr_left, qr_top = 171, 1440
    draw.rounded_rectangle((qr_left - 13, qr_top - 13, qr_left + 189, qr_top + 189), radius=20, fill=WHITE)
    image.alpha_composite(qr.convert("RGBA"), (qr_left, qr_top))
    draw = ImageDraw.Draw(image)
    apply_box = (398, 1461, 893, 1598)
    draw.rounded_rectangle(apply_box, radius=38, fill=(14, 121, 235, 255), outline=(42, 226, 255, 255), width=4)
    draw.rounded_rectangle((apply_box[0] - 6, apply_box[1] - 6, apply_box[2] + 6, apply_box[3] + 6), radius=42, outline=(47, 173, 255, 170), width=3)
    center_x = (apply_box[0] + apply_box[2]) // 2
    draw.text((center_x, 1503), "SCAN TO APPLY", font=get_font(29, True), fill=WHITE, anchor="mm")
    draw.text((center_x, 1545), "QR CODE  ·  OPEN CAREERS", font=get_font(16, True), fill=(210, 238, 255, 255), anchor="mm")

    # Hand-drawn style notes echo the supplied reference around the card.
    notes = [
        ("NEW\nJOB ALERT", (28, 40), 22, -8),
        ("SAVE &\nAPPLY LATER", (852, 48), 17, 4),
        ("DREAM\nJOB?", (14, 915), 19, 82),
        ("WORK AT\nGOOGLE", (975, 720), 16, 96),
        ("MORE JOB\nUPDATES", (32, 1805), 16, -5),
    ]
    for text, (x, y), size, angle in notes:
        note_font = get_font(size, True)
        note_image = Image.new("RGBA", (210, 76), (0, 0, 0, 0))
        note_draw = ImageDraw.Draw(note_image)
        note_draw.multiline_text((4, 2), text, font=note_font, fill=(235, 239, 247, 255), spacing=2, align="center")
        note_image = note_image.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        image.alpha_composite(note_image, (x, y))
    draw = ImageDraw.Draw(image)
    draw.line([(31, 133), (108, 118), (184, 105)], fill=(255, 169, 42, 255), width=4)
    draw.line([(890, 157), (930, 139), (955, 113)], fill=(255, 193, 42, 255), width=4)
    draw.arc((852, 98, 1005, 230), 210, 315, fill=(173, 190, 225, 255), width=3)
    draw.line([(25, 1005), (90, 1031), (110, 1060)], fill=(35, 200, 235, 255), width=4)
    draw.line([(934, 1713), (975, 1744), (990, 1784)], fill=(34, 192, 228, 255), width=4)
    draw.arc((906, 1708, 1015, 1825), 300, 65, fill=(226, 232, 243, 255), width=3)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    image.convert("RGB").save(output_path, format="PNG", optimize=True)
    return output_path


# ============================================================
# MAIN REUSABLE FUNCTION
# ============================================================

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
    demo_mode=False,
    reel_style="reference",
):
    job_title = job_title or DISPLAY_DEFAULTS["job_title"]
    company = company or DISPLAY_DEFAULTS["company"]
    location = location or DISPLAY_DEFAULTS["location"]
    ctc = ctc or DISPLAY_DEFAULTS["ctc"]
    eligibility = eligibility or DISPLAY_DEFAULTS["eligibility"]
    skills = skills or DISPLAY_DEFAULTS["skills"]

    safe_company = re.sub(r"[^a-zA-Z0-9]+", "_", str(company)).strip("_") or "company"
    safe_role = re.sub(r"[^a-zA-Z0-9]+", "_", str(job_title)).strip("_") or "job"
    suffix = f"_{job_id}" if job_id else ""
    prefix = f"{safe_company}_{safe_role}{suffix}"

    card_path = os.path.join(OUTPUT_DIR, f"{prefix}_card.png")
    video_path = os.path.join(OUTPUT_DIR, f"{prefix}_reel.mp4")
    caption_path = os.path.join(OUTPUT_DIR, f"{prefix}_caption.txt")
    logo_path = brand_image_path
    if not logo_path:
        logo_path = download_logo(
            company,
            os.path.join(OUTPUT_DIR, f"{prefix}_company_logo.png"),
        )
    theme = create_brand_theme(company, job_title, job_id, logo_path)

    print("\n==========================================")
    print(f"Creating: {job_title} @ {company}")
    print("==========================================")

    content_duration = DURATION - (QR_END_CARD_DURATION if application_link else 0)
    timeline = _concept_timeline(reel_style, content_duration)
    scene_images = []
    temporary_paths = []
    for index, (phase, duration) in enumerate(timeline):
        scene_path = os.path.join(OUTPUT_DIR, f"{prefix}_scene_{index}.png")
        _create_concept_frame(
            style=reel_style,
            phase=phase,
            company=company,
            job_title=job_title,
            location=location,
            ctc=ctc,
            eligibility=eligibility,
            experience=experience or "Not specified",
            skills=skills,
            job_description=job_description,
            logo_path=logo_path,
            theme=theme,
        ).save(scene_path)
        temporary_paths.append(scene_path)
        scene_images.append((scene_path, duration))

    still_background = Image.fromarray(
        animated_background_frame(0, theme, size=(WIDTH, HEIGHT))
    ).convert("RGBA")
    preview_scene_path = (
        scene_images[1][0]
        if reel_style == "reference" and len(scene_images) > 1
        else scene_images[0][0]
    )
    still = Image.alpha_composite(
        still_background,
        Image.open(preview_scene_path).convert("RGBA"),
    )
    still.convert("RGB").save(card_path, quality=95)
    try:
        create_video(
            scene_images[0][0],
            video_path,
            background_audio_path=background_audio_path,
            application_link=application_link,
            theme=theme,
            demo_mode=demo_mode,
            scene_images=scene_images,
        )
    finally:
        for temporary_path in temporary_paths:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

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

    print("\n==========================================")
    print("DONE 🎉")
    print(f"🎨 Card    : {card_path}")
    print(f"🎬 Reel    : {video_path}")
    print(f"📝 Caption : {caption_path}")
    print("==========================================")

    return {
        "card": card_path,
        "video": video_path,
        "caption": caption_path,
        "caption_text": caption,
    }

def main():
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


if __name__ == "__main__":
    main()