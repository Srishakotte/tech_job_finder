import os
import io
import re
import requests

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import ImageClip

# ============================================================
# SETTINGS
# ============================================================

WIDTH = 1080
HEIGHT = 1920
DURATION = 3
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

    # Logo
    logo_path = os.path.join(OUTPUT_DIR, "company_logo.png")
    logo = download_logo(company, logo_path)

    if logo:
        logo_img = Image.open(logo).convert("RGBA")
        logo_x = (WIDTH - logo_img.width) // 2
        logo_y = 130
        padding = 35

        draw.rounded_rectangle(
            (
                logo_x - padding,
                logo_y - padding,
                logo_x + logo_img.width + padding,
                logo_y + logo_img.height + padding,
            ),
            radius=35,
            fill=WHITE,
            outline=BORDER,
            width=2,
        )
        image.paste(logo_img, (logo_x, logo_y), logo_img)
    else:
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
            str(ctc),
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
):
    tags = []
    tags.extend(detect_category(job_title))
    tags.extend(get_experience_tags(eligibility))
    tags.extend(get_location_tags(location))
    tags.extend(get_company_tags(company))
    tags.extend(get_skill_tags(skills))

    tags.extend([
        "#hiring",
        "#jobopening",
        "#jobopportunity",
        "#jobsearch",
        "#careers",
        "#jobhunt",
        "#applynow",
    ])

    unique_tags = []
    for tag in tags:
        if tag.lower() not in [x.lower() for x in unique_tags]:
            unique_tags.append(tag)

    unique_tags = unique_tags[:20]
    hashtag_text = " ".join(unique_tags)

    ctc_label = "EST. CTC" if ctc_source == "estimated" else "CTC"

    sections = [
        '💬 COMMENT "LINK" 👇',
        "Get the application link in your DMs!",
        "",
        f"🚨 {job_title} @ {company}",
        "",
        f"📍 {location}",
    ]

    if ctc:
        sections.append(f"💰 {ctc_label}: {ctc}")

    if eligibility:
        sections.append(f"🎓 Eligibility: {eligibility}")

    if job_description:
        sections.extend(["", "💼 ABOUT THE ROLE", job_description])

    if company_description:
        sections.extend([
            "",
            f"🏢 ABOUT {str(company).upper()}",
            company_description,
        ])

    if skills:
        sections.extend(["", "🛠️ KEY SKILLS", skills])

    sections.extend([
        "",
        "🔥 Interested in this opportunity?",
        "",
        "Comment **LINK** below and get the application details.",
        "",
        "📌 Save this post so you don't miss the deadline.",
        "📤 Share it with a friend who's job hunting!",
        "",
        f"🔎 {job_title} jobs | {company} careers | {location} jobs | hiring | tech careers | job opportunities",
        "",
        hashtag_text,
    ])

    caption = "\n".join(sections)

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(caption)

    print(f"✓ Caption saved: {output_path}")
    return caption

def add_application_link_to_caption(caption_path, application_link):
    with open(caption_path, "r", encoding="utf-8") as file:
        lines = file.read().splitlines()

    cta = "Comment **LINK** below and get the application details."
    if cta not in lines:
        raise ValueError("Could not find the application-link section in the caption.")

    lines = [line for line in lines if not line.startswith("🔗 Apply here:")]
    cta_index = lines.index(cta)
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

def create_video(image_path, output_path):
    clip = ImageClip(image_path).with_duration(DURATION)
    clip.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio=False,
        preset="medium",
    )
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
):
    job_title = job_title or DISPLAY_DEFAULTS["job_title"]
    company = company or DISPLAY_DEFAULTS["company"]
    location = location or DISPLAY_DEFAULTS["location"]
    ctc = ctc or DISPLAY_DEFAULTS["ctc"]
    eligibility = eligibility or DISPLAY_DEFAULTS["eligibility"]
    skills = skills or DISPLAY_DEFAULTS["skills"]

    safe_company = re.sub(r"[^a-zA-Z0-9]+", "_", str(company)).strip("_") or "company"
    safe_role = re.sub(r"[^a-zA-Z0-9]+", "_", str(job_title)).strip("_") or "job"
    prefix = f"{safe_company}_{safe_role}"

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
    )

    create_video(card_path, video_path)

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
    