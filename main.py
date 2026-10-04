import os
import io
import re
import requests

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from moviepy import AudioFileClip, ImageClip, concatenate_videoclips
from moviepy.audio.fx import AudioLoop

# ============================================================
# SETTINGS
# ============================================================

WIDTH = 1080
HEIGHT = 1920
DURATION = 10
SCENE_DURATION = 2.5
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

    title_font = get_font(68, True)
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
):
    image = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 20), fill=BLUE)
    draw.ellipse((760, -280, 1260, 220), fill=(37, 99, 235))
    draw.ellipse((-260, 1420, 250, 1930), fill=(124, 58, 237))

    scene_label = f"JOB ALERT  /  {scene_number + 1:02d}"
    draw.rounded_rectangle((72, 100, 420, 162), radius=28, fill=BLUE)
    draw.text((102, 117), scene_label, font=get_font(25, True), fill=WHITE)

    if scene_number == 0:
        if brand_image_path and os.path.isfile(brand_image_path):
            try:
                with Image.open(brand_image_path) as source:
                    cover = ImageOps.fit(
                        source.convert("RGB"),
                        (900, 610),
                        method=Image.Resampling.LANCZOS,
                    )
                image.paste(cover, (90, 230))
                draw = ImageDraw.Draw(image)
                draw.rounded_rectangle(
                    (90, 230, 990, 840),
                    radius=38,
                    outline=WHITE,
                    width=3,
                )
            except (OSError, ValueError) as error:
                print(f"⚠ Could not use supplied Reel image: {error}")

        draw.text((82, 925), "HIRING NOW", font=get_font(34, True), fill=(147, 197, 253))
        title_lines = wrap_text(draw, job_title, get_font(78, True), 900)
        y = 1000
        for line in title_lines[:2]:
            draw.text((78, y), line, font=get_font(78, True), fill=WHITE)
            y += 100
        draw.text((84, y + 12), str(company), font=get_font(43, True), fill=(203, 213, 225))
        draw.rounded_rectangle((72, 1555, 1008, 1660), radius=34, fill=(30, 41, 59))
        draw.text((110, 1584), f"LOCATION  ·  {location}", font=get_font(35, True), fill=WHITE)
        draw.text((82, 1770), "Watch for the role details  →", font=get_font(27), fill=(191, 219, 254))

    elif scene_number == 1:
        draw.text((82, 310), "THE ROLE", font=get_font(32, True), fill=(147, 197, 253))
        title_lines = wrap_text(draw, job_title, get_font(67, True), 900)
        y = 375
        for line in title_lines[:3]:
            draw.text((78, y), line, font=get_font(67, True), fill=WHITE)
            y += 86

        facts = [
            ("COMPANY", company),
            ("LOCATION", location),
            ("COMPENSATION", str(ctc).replace("₹", "INR ") if ctc else ctc),
        ]
        y += 30
        for label, value in facts:
            draw.rounded_rectangle((72, y, 1008, y + 185), radius=32, fill=(30, 41, 59))
            draw.text((112, y + 28), label, font=get_font(23, True), fill=(147, 197, 253))
            lines = wrap_text(draw, value or "Not provided", get_font(38, True), 820)
            for index, line in enumerate(lines[:2]):
                draw.text((112, y + 76 + index * 47), line, font=get_font(38, True), fill=WHITE)
            y += 215
        draw.text((82, 1770), "Check the official careers page before applying.", font=get_font(25), fill=(203, 213, 225))

    elif scene_number == 2:
        draw.text((82, 310), "QUICK FIT CHECK", font=get_font(32, True), fill=(147, 197, 253))
        draw.text((78, 390), "Could this role be for you?", font=get_font(52, True), fill=WHITE)

        if eligibility:
            draw.rounded_rectangle((72, 530, 1008, 790), radius=34, fill=(30, 41, 59))
            draw.text((112, 568), "ELIGIBILITY", font=get_font(24, True), fill=(147, 197, 253))
            lines = wrap_text(draw, eligibility, get_font(37, True), 820)
            for index, line in enumerate(lines[:3]):
                draw.text((112, 625 + index * 48), line, font=get_font(37, True), fill=WHITE)

        if skills:
            draw.rounded_rectangle((72, 830, 1008, 1170), radius=34, fill=(30, 41, 59))
            draw.text((112, 870), "SKILLS MENTIONED", font=get_font(24, True), fill=(147, 197, 253))
            lines = wrap_text(draw, skills, get_font(37, True), 820)
            for index, line in enumerate(lines[:4]):
                draw.text((112, 928 + index * 48), line, font=get_font(37, True), fill=WHITE)

        description = job_description or "Review the role requirements and application details."
        lines = wrap_text(draw, description, get_font(30), 850)
        for index, line in enumerate(lines[:5]):
            draw.text((92, 1270 + index * 48), line, font=get_font(30), fill=(203, 213, 225))
        draw.text((82, 1770), "Save this Reel to check the details later.", font=get_font(27, True), fill=(203, 213, 225))

    else:
        draw.text((82, 380), "READY TO APPLY?", font=get_font(37, True), fill=(147, 197, 253))
        title_lines = wrap_text(draw, job_title, get_font(65, True), 900)
        y = 470
        for line in title_lines[:2]:
            draw.text((78, y), line, font=get_font(65, True), fill=WHITE)
            y += 85
        draw.text((82, y + 30), str(company), font=get_font(43, True), fill=(203, 213, 225))
        draw.rounded_rectangle((72, 1120, 1008, 1320), radius=48, fill=BLUE)
        draw.text((151, 1177), "COMMENT  LINK  BELOW", font=get_font(43, True), fill=WHITE)
        dm_message = (
            "Automated DM link is active"
            if comment_dm_enabled
            else "We’ll send the link by DM"
        )
        draw.text((140, 1240), dm_message, font=get_font(27, True), fill=WHITE)
        draw.text((82, 1475), f"LOCATION  ·  {location}", font=get_font(33, True), fill=(203, 213, 225))
        draw.text((82, 1770), "Follow for more job and internship updates.", font=get_font(26), fill=(203, 213, 225))

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
        "Comment LINK and we’ll automatically DM you the application link."
        if comment_dm_enabled
        else "Comment LINK to request the application link; we’ll send it by DM."
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

    if skills:
        sections.extend(["", "🛠️ KEY SKILLS", skills])

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

    cta_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Comment LINK")),
        None,
    )
    if cta_index is None:
        raise ValueError("Could not find the application-link section in the caption.")

    lines = [line for line in lines if not line.startswith("🔗 Apply here:")]
    cta_index = next(
        index for index, line in enumerate(lines) if line.startswith("Comment LINK")
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
    scene_images=None,
    background_audio_path=None,
):
    image_paths = scene_images or [image_path]
    clips = [
        ImageClip(scene_path).with_duration(
            SCENE_DURATION if scene_images else DURATION
        )
        for scene_path in image_paths
    ]
    final_clip = concatenate_videoclips(clips, method="compose")
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
        for clip in clips:
            clip.close()
    print(f"✓ Video created: {output_path}")

# ============================================================
# MAIN REUSABLE FUNCTION
# ============================================================

def create_job_post(
    job_title=None,
    company=None,
    location=None,
    ctc=None,
    eligibility=None,
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

    create_job_card(
        job_title=job_title,
        company=company,
        location=location,
        ctc=ctc,
        eligibility=eligibility,
        skills=skills,
        output_path=card_path,
        ctc_source=ctc_source,
        brand_image_path=brand_image_path,
    )

    scene_paths = []
    for scene_number in range(4):
        scene_path = os.path.join(OUTPUT_DIR, f"{prefix}_scene_{scene_number + 1}.png")
        create_reel_scene(
            scene_number=scene_number,
            job_title=job_title,
            company=company,
            location=location,
            ctc=ctc,
            eligibility=eligibility,
            skills=skills,
            job_description=job_description,
            brand_image_path=brand_image_path,
            comment_dm_enabled=comment_dm_enabled,
        ).save(scene_path)
        scene_paths.append(scene_path)

    try:
        create_video(
            card_path,
            video_path,
            scene_images=scene_paths,
            background_audio_path=background_audio_path,
        )
    finally:
        for scene_path in scene_paths:
            if os.path.exists(scene_path):
                os.remove(scene_path)

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
    