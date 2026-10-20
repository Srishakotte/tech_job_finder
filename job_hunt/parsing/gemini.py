import os
import json
import re

from ..config import load_environment
from google import genai


load_environment()

print("🔑 Loading Gemini API key...")

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is missing from .env"
    )

client = genai.Client(
    api_key=API_KEY
)

print("✅ Gemini client initialized!")


URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+",
    re.IGNORECASE
)


def extract_urls(text: str):
    """
    Extract only useful job/application URLs.

    DO NOT open or read these URLs.

    Ignore social/community links such as:
    - WhatsApp
    - Instagram
    - Telegram
    - Facebook
    - LinkedIn
    - YouTube
    """

    urls = URL_PATTERN.findall(text)

    ignored_domains = [
        "whatsapp.com",
        "wa.me",
        "instagram.com",
        "instagr.am",
        "telegram.me",
        "t.me",
        "facebook.com",
        "fb.com",
        "linkedin.com",
        "youtube.com",
        "youtu.be",
    ]

    useful_urls = []

    for url in urls:
        url = url.rstrip(".,);]}>")

        lower_url = url.lower()

        if any(
            domain in lower_url
            for domain in ignored_domains
        ):
            print(f"🚫 Ignoring non-job URL: {url}")
            continue

        if url not in useful_urls:
            useful_urls.append(url)

    return useful_urls


def _clean_json(raw: str) -> str:

    raw = raw.strip()

    if raw.startswith("```"):
        raw = re.sub(
            r"^```(?:json)?\s*",
            "",
            raw,
            flags=re.IGNORECASE
        )

        raw = re.sub(
            r"\s*```$",
            "",
            raw
        )

    return raw.strip()


def _build_prompt(text: str, urls: list[str]) -> str:

    url_section = ""

    if urls:
        url_section = f"""

APPLICATION URL(S) FOUND IN THE TELEGRAM POST:

{chr(10).join(urls)}

IMPORTANT:

- Do NOT open these URLs.
- Do NOT use URL Context.
- Do NOT browse or read the application page.
- These URLs are only being extracted so they can be shown as
  the application link.
- Use the Telegram post itself as the ONLY source of job information.
"""

    return f"""

You are an expert job-post extraction agent.

Your job is to turn a raw Telegram job post into accurate,
structured data for an Instagram job advertisement.

IMPORTANT SOURCE RULE:

Use ONLY the information contained in the original Telegram
job post.

DO NOT:
- Open any URLs.
- Browse application pages.
- Use URL Context.
- Use Google Search.
- Search the internet.
- Read external sources.
- Try to retrieve information from the application link.

The Telegram message is the ONLY source of actual job information.

FIRST:

1. Read the entire Telegram job post.
2. Identify the company.
3. Identify the role/job title.
4. Identify the location.
5. Identify eligibility.
6. Identify skills/technologies.
7. Identify job description.
8. Identify company description if explicitly provided.
9. Identify salary/CTC if explicitly mentioned.
10. Identify the application URL.

CTC RULES:

If the actual CTC/salary is explicitly mentioned in the
Telegram post:

- Use the stated CTC exactly.
- Set ctc_source to "explicit".

If CTC is NOT mentioned:

- DO NOT search the internet.
- DO NOT open the application link.
- Give a reasonable EXPECTED CTC based only on the information
  available in the Telegram post, such as:
    - company
    - job title
    - location
    - experience level
    - internship/fresher status
    - skills
- This is NOT the company's confirmed salary.
- Set ctc_source to "estimated".
- Prefer a RANGE rather than one exact number.

IMPORTANT:

An estimated CTC must NEVER be presented as an actual
company-offered salary.

Example:

"₹8–12 LPA"

should become:

"ctc": "₹8–12 LPA",
"ctc_source": "estimated"

If there is genuinely not enough information even to make a
reasonable estimate:

"ctc": null,
"ctc_source": "not_available"

LOCATION RULES:

- Extract the actual location stated in the Telegram post.
- If the post clearly indicates an India job but does not state
  a city, use "India".
- Do not invent a specific city.
- Do not assume an international location is India.

JOB TITLE:

- Extract the actual role from the Telegram post.
- If the post says something vague like "IBM hiring" and no
  specific role is mentioned, use null.
- DO NOT open the application URL to find the title.
- DO NOT invent a role title.

SKILLS:

- Extract skills/technologies explicitly mentioned in the
  Telegram post.
- Do not add generic skills merely because they are common
  for the role.
- If no skills are mentioned, return [].

ELIGIBILITY:

- Extract eligibility exactly from the Telegram post.
- Include degree, branch, batch, experience and other
  requirements when available.

DESCRIPTIONS:

- job_description should summarize the actual role using ONLY
  information found in the Telegram post.
- company_description should ONLY be populated if the Telegram
  post actually provides company information.
- Never invent a generic company description.

URL RULES:

- Extract the actual job/application URL from the Telegram post.
- NEVER use WhatsApp links as application_link.
- NEVER use Instagram links as application_link.
- NEVER use Telegram links as application_link.
- NEVER use Facebook links as application_link.
- NEVER use LinkedIn links as application_link.
- NEVER use YouTube links as application_link.
- Only use URLs that remain after the URL filtering step.

Return ONLY valid JSON with EXACTLY these fields:

{{
    "company": null,
    "job_title": null,
    "location": null,
    "ctc": null,
    "ctc_source": "explicit | estimated | not_available",
    "eligibility": null,
    "skills": [],
    "job_description": null,
    "company_description": null,
    "application_link": null,
    "source_used": "post"
}}

Rules for missing values:

- Missing text field = null.
- skills = [] when unavailable.
- application_link = actual useful application URL if present.
- source_used MUST always be "post".

{url_section}

ORIGINAL TELEGRAM JOB POST:

{text}

"""


def parse_job_post(text: str) -> dict:

    print("\n" + "=" * 55)
    print("🤖 GEMINI JOB EXTRACTION STARTED")
    print("=" * 55)

    urls = extract_urls(text)

    if urls:
        print("🔗 Useful URL(s) detected:")
        for url in urls:
            print(f"   • {url}")

        print(
            "ℹ️ URLs will NOT be opened. "
            "Gemini is using Telegram text only."
        )

    else:
        print("🔗 No useful application URL detected.")

    prompt = _build_prompt(text, urls)

    try:

        print("📤 Sending ONLY Telegram post to Gemini...")
        print("⏳ Gemini is extracting job information...")

        interaction = client.interactions.create(
            model="gemini-2-flash",
            input=prompt
        )

        print("✅ Gemini response received!")

        raw = interaction.output_text.strip()

        print("📦 Raw Gemini response:")
        print(raw)

        print("🔍 Parsing JSON...")

        raw = _clean_json(raw)

        result = json.loads(raw)

        # -----------------------------
        # Normalize schema
        # -----------------------------

        if not isinstance(result.get("skills"), list):
            result["skills"] = []

        # Never allow Gemini to return a filtered/social URL.
        if result.get("application_link"):
            application_url = result["application_link"].lower()

            ignored_domains = [
                "whatsapp.com",
                "wa.me",
                "instagram.com",
                "instagr.am",
                "telegram.me",
                "t.me",
                "facebook.com",
                "fb.com",
                "linkedin.com",
                "youtube.com",
                "youtu.be",
            ]

            if any(
                domain in application_url
                for domain in ignored_domains
            ):
                print(
                    "🚫 Gemini returned a social URL. "
                    "Removing it."
                )

                result["application_link"] = None

        # If Gemini did not select a URL, use the first
        # already-filtered useful URL.
        if (
            result.get("application_link") is None
            and urls
        ):
            result["application_link"] = urls[0]

        # Location fallback.
        if not result.get("location"):
            result["location"] = "India"

        # CTC source normalization.
        if result.get("ctc"):
            if result.get("ctc_source") not in [
                "explicit",
                "estimated"
            ]:
                result["ctc_source"] = "explicit"
        else:
            result["ctc_source"] = "not_available"

        # This version NEVER reads external sources.
        result["source_used"] = "post"

        print("✅ JSON parsed successfully!")

        print("📋 FINAL PARSED JOB DATA:")

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False
            )
        )

        print("=" * 55)

        return result

    except Exception as e:

        print("❌ GEMINI ERROR:")
        print(type(e).__name__)
        print(str(e))
        print("=" * 55)

        raise