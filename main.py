import os
import io
import re
import requests
import numpy as np

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoClip
from moviepy.audio.fx import AudioLoop

# ============================================================
# SETTINGS
# ============================================================

WIDTH = 1080
HEIGHT = 1920
DURATION = 18
OUTPUT_DIR = "output"

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

    if skills:
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
        "COMMENT  'LINK'  TO  APPLY",
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
    comment_dm_enabled=False,
    experience=None,
):
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (70, 250, WIDTH - 70, 1665),
        radius=54,
        fill=(8, 15, 32, 226),
        outline=(148, 163, 184, 120),
        width=3,
    )
    draw.rounded_rectangle((70, 250, WIDTH - 70, 267), radius=8, fill=BLUE)

    logo = brand_image_path
    if not logo:
        logo = download_logo(
            company,
            os.path.join(OUTPUT_DIR, "company_logo.png"),
        )
    logo_box = (450, 325, 630, 505)
    draw.ellipse(logo_box, fill=(30, 41, 59, 255), outline=(96, 165, 250, 255), width=4)
    if logo and os.path.isfile(logo):
        try:
            with Image.open(logo) as source:
                logo_image = ImageOps.contain(
                    source.convert("RGBA"),
                    (142, 142),
                    method=Image.Resampling.LANCZOS,
                )
            image.alpha_composite(
                logo_image,
                (
                    (WIDTH - logo_image.width) // 2,
                    415 - logo_image.height // 2,
                ),
            )
            draw = ImageDraw.Draw(image)
        except (OSError, ValueError) as error:
            print(f"⚠ Could not use company image in Reel: {error}")
            logo = None
    if not logo:
        initial = str(company or "C")[:1].upper()
        center_text(draw, initial, 370, get_font(78, True), WHITE)

    company_font = get_font(38, True)
    for index, line in enumerate(wrap_text(draw, company, company_font, 780)[:2]):
        center_text(draw, line, 535 + index * 48, company_font, (203, 213, 225, 255))

    draw.rounded_rectangle((320, 655, 760, 715), radius=30, fill=(37, 99, 235, 235))
    center_text(draw, "HIRING NOW", 670, get_font(28, True), WHITE)
    title_font = get_font(68, True)
    title_lines = wrap_text(draw, job_title, title_font, 830)
    title_y = 735
    for line in title_lines[:3]:
        center_text(draw, line, title_y, title_font, WHITE)
        title_y += 70

    details = [
        ("LOCATION", location or "Not specified"),
        ("EXPERIENCE", experience or "See job description"),
    ]
    if ctc:
        details.append(("SALARY", str(ctc).replace("₹", "INR ")))

    details_y = max(960, title_y + 12)
    row_height = 88
    for index, (label, value) in enumerate(details):
        top = details_y + index * (row_height + 12)
        draw.rounded_rectangle(
            (125, top, WIDTH - 125, top + row_height),
            radius=28,
            fill=(30, 41, 59, 245),
            outline=(71, 85, 105, 255),
            width=2,
        )
        draw.text((160, top + 10), label, font=get_font(19, True), fill=(147, 197, 253, 255))
        value_font = get_font(29, True)
        value_lines = wrap_text(draw, value, value_font, 730)
        for line_index, line in enumerate(value_lines[:2]):
            draw.text(
                (160, top + 39 + line_index * 33),
                line,
                font=value_font,
                fill=WHITE,
            )

    description_y = details_y + len(details) * (row_height + 12) + 20
    draw.text(
        (145, description_y),
        "ABOUT THE ROLE",
        font=get_font(22, True),
        fill=(147, 197, 253, 255),
    )
    description = re.sub(r"\s+", " ", job_description or "Explore this opportunity and its requirements.").strip()
    description_font = get_font(25)
    description_lines = wrap_text(draw, description, description_font, 790)
    for index, line in enumerate(description_lines[:3]):
        draw.text(
            (145, description_y + 38 + index * 34),
            line,
            font=description_font,
            fill=(226, 232, 240, 255),
        )

    cta_top = 1480
    draw.rounded_rectangle(
        (125, cta_top, WIDTH - 125, cta_top + 150),
        radius=38,
        fill=(37, 99, 235, 250),
    )
    center_text(draw, "COMMENT APPLY  ↓", cta_top + 26, get_font(39, True), WHITE)
    center_text(
        draw,
        "GET THE APPLICATION LINK IN DM",
        cta_top + 88,
        get_font(24, True),
        WHITE,
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
    comment_dm_enabled=False,
):
    tag_candidates = [
        *detect_category(job_title)[:2],
        *get_experience_tags(eligibility)[:1],
        *get_location_tags(location)[:1],
        *get_company_tags(company)[:1],
    ]
    hashtags = " ".join(dict.fromkeys(tag_candidates))

    ctc_label = "EST. CTC" if ctc_source == "estimated" else "CTC"
    link_cta = (
        "Comment APPLY and we’ll automatically DM you the application link."
        if comment_dm_enabled
        else "Comment APPLY to request the application link; we’ll send it by DM."
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

    caption = "\n".join(sections)

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(caption)

    print(f"✓ Caption saved: {output_path}")
    return caption

def add_application_link_to_caption(caption_path, application_link):
    with open(caption_path, "r", encoding="utf-8") as file:
        lines = file.read().splitlines()

    cta_prefixes = ("Comment APPLY", "Comment LINK")
    cta_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith(cta_prefixes)
        ),
        None,
    )
    if cta_index is None:
        raise ValueError("Could not find the application-link section in the caption.")

    cleaned_lines = []
    for line in lines:
        if line.startswith("🔗 Apply here:"):
            if cleaned_lines and not cleaned_lines[-1]:
                cleaned_lines.pop()
            continue
        cleaned_lines.append(line)
    lines = cleaned_lines
    cta_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith(cta_prefixes)
    )
    lines[cta_index + 1:cta_index + 1] = [
        "",
        f"🔗 Apply here: {application_link}",
    ]

    caption = "\n".join(lines)
    with open(caption_path, "w", encoding="utf-8") as file:
        file.write(caption)

    return caption

# ============================================================
# VIDEO
# ============================================================

def create_video(
    image_path,
    output_path,
    background_audio_path=None,
):
    background_clip = VideoClip(
        frame_function=_animated_background_frame,
        duration=DURATION,
    ).resized((WIDTH, HEIGHT))
    overlay_clip = ImageClip(image_path, transparent=True).with_duration(DURATION)
    final_clip = CompositeVideoClip(
        [background_clip, overlay_clip],
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
        background_clip.close()
        overlay_clip.close()
    print(f"✓ Video created: {output_path}")


def _animated_background_frame(time_seconds):
    width, height = 270, 480
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    x /= width
    y /= height
    drift = time_seconds / DURATION
    glow_x = 0.25 + 0.5 * (0.5 + 0.5 * np.sin(2 * np.pi * drift))
    glow_y = 0.35 + 0.28 * np.sin(2 * np.pi * drift + 1.2)
    glow = np.exp(-(((x - glow_x) / 0.62) ** 2 + ((y - glow_y) / 0.40) ** 2) * 2.5)
    secondary = np.exp(
        -(((x - (0.82 - 0.35 * drift)) / 0.45) ** 2
          + ((y - 0.82) / 0.36) ** 2) * 3.0
    )

    frame = np.empty((height, width, 3), dtype=np.float32)
    frame[:, :, 0] = 8 + 17 * glow + 14 * secondary
    frame[:, :, 1] = 13 + 30 * glow + 8 * secondary
    frame[:, :, 2] = 29 + 78 * glow + 55 * secondary
    frame = np.clip(frame, 0, 255).astype(np.uint8)
    return np.asarray(
        Image.fromarray(frame, mode="RGB").resize(
            (WIDTH, HEIGHT),
            Image.Resampling.BILINEAR,
        )
    )

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
    comment_dm_enabled=False,
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

    print("\n==========================================")
    print(f"Creating: {job_title} @ {company}")
    print("==========================================")

    overlay_path = os.path.join(OUTPUT_DIR, f"{prefix}_overlay.png")
    create_reel_scene(
        scene_number=0,
        job_title=job_title,
        company=company,
        location=location,
        ctc=ctc,
        eligibility=eligibility,
        skills=None,
        job_description=job_description,
        brand_image_path=brand_image_path,
        comment_dm_enabled=comment_dm_enabled,
        experience=experience,
    ).save(overlay_path)
    still_background = Image.fromarray(_animated_background_frame(0)).convert("RGBA")
    still = Image.alpha_composite(still_background, Image.open(overlay_path).convert("RGBA"))
    still.convert("RGB").save(card_path, quality=95)
    try:
        create_video(
            overlay_path,
            video_path,
            background_audio_path=background_audio_path,
        )
    finally:
        if os.path.exists(overlay_path):
            os.remove(overlay_path)

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
        comment_dm_enabled=comment_dm_enabled,
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
    