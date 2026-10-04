import re
from urllib.parse import urlparse

# ============================================================
# LOCAL JOB POST PARSER
# No Gemini/API/web calls.
# ============================================================

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

IGNORED_DOMAINS = {
    "whatsapp.com", "wa.me",
    "instagram.com", "instagr.am",
    "telegram.me", "t.me",
    "facebook.com", "fb.com",
    "linkedin.com",
    "youtube.com", "youtu.be",
}

INDIAN_CITIES = [
    "Hyderabad", "Bangalore", "Bengaluru", "Pune", "Chennai",
    "Mumbai", "Delhi", "New Delhi", "Gurgaon", "Gurugram",
    "Noida", "Kolkata", "Ahmedabad", "Jaipur", "Kochi",
    "Coimbatore", "Indore", "Mysore", "Mysuru", "Remote",
]

KNOWN_COMPANIES = [
    "Microsoft", "Google", "Amazon", "Apple", "Meta", "Netflix",
    "Adobe", "Salesforce", "Oracle", "ServiceNow", "Deloitte",
    "Accenture", "Infosys", "TCS", "Wipro", "Flipkart", "Swiggy",
    "Zomato", "Uber", "Atlassian", "NVIDIA", "Visa", "Mastercard",
    "D. E. Shaw", "Goldman Sachs", "Morgan Stanley", "JPMorgan",
    "JP Morgan", "Qualcomm", "Intel", "Cisco", "IBM", "SAP",
    "PayPal", "Stripe", "Twilio", "Canonical",
]

ROLE_PATTERNS = [
    r"(?im)^(?:job\s*title|role|position|designation|opening)\s*[:\-]\s*(.+)$",
    r"(?im)^(?:hiring\s+for|looking\s+for)\s*[:\-]?\s*(.+)$",
]

ROLE_KEYWORDS = [
    "Software Engineer", "Software Developer", "SDE", "SDE I", "SDE II",
    "Frontend Developer", "Frontend Engineer", "Backend Developer",
    "Backend Engineer", "Full Stack Developer", "Full Stack Engineer",
    "Data Analyst", "Data Scientist", "Machine Learning Engineer",
    "AI Engineer", "DevOps Engineer", "QA Engineer", "Test Engineer",
    "Cloud Engineer", "Security Engineer", "Product Manager",
    "Product Analyst", "Business Analyst", "UI/UX Designer",
    "Web Developer", "Mobile Developer", "Android Developer",
    "iOS Developer", "Intern", "Software Intern", "Engineering Intern",
]

SKILLS = [
    "Python", "Java", "C++", "C#", "JavaScript", "TypeScript",
    "React", "React.js", "Node.js", "Express", "Angular", "Vue",
    "Next.js", "HTML", "CSS", "SQL", "MySQL", "PostgreSQL",
    "MongoDB", "Redis", "AWS", "Azure", "GCP", "Docker",
    "Kubernetes", "Git", "GitHub", "Linux", "REST API", "GraphQL",
    "Machine Learning", "Deep Learning", "Artificial Intelligence",
    "TensorFlow", "PyTorch", "Pandas", "NumPy", "Spring", "Django",
    "Flask", "FastAPI", "Kafka", "Jenkins", "CI/CD", "Terraform",
]

def clean(value):
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value.strip(" -:|•")

def is_ignored_url(url):
    try:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in IGNORED_DOMAINS)
    except Exception:
        return True

def extract_urls(text):
    useful = []
    for url in URL_PATTERN.findall(text):
        url = url.rstrip(".,);]}>")
        if is_ignored_url(url):
            print(f"🚫 Ignoring social URL: {url}")
            continue
        if url not in useful:
            useful.append(url)
    return useful

def labelled_value(text, labels):
    label_pattern = "|".join(re.escape(x) for x in labels)
    patterns = [
        rf"(?im)^\s*(?:{label_pattern})\s*[:\-]\s*(.+?)\s*$",
        rf"(?im)(?:{label_pattern})\s*[:\-]\s*([^\n|]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return clean(m.group(1))
    return None

def detect_company(text):
    explicit = labelled_value(text, ["company", "organization", "org", "employer"])
    if explicit:
        return explicit

    low = text.lower()
    matches = []
    for company in KNOWN_COMPANIES:
        if company.lower() in low:
            matches.append(company)

    if matches:
        # Prefer the first occurrence in the post.
        positions = [(low.find(c.lower()), c) for c in matches]
        return min(positions)[1]

    # Common "X hiring" / "hiring at X" patterns.
    patterns = [
        r"(?i)\bhiring\s+(?:at|@)\s+([A-Za-z][A-Za-z0-9 .&-]{1,50})",
        r"(?i)\b([A-Za-z][A-Za-z0-9 .&-]{1,40})\s+(?:is\s+)?hiring\b",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            candidate = clean(m.group(1))
            if candidate and len(candidate.split()) <= 5:
                return candidate

    return None

def detect_job_title(text):
    explicit = labelled_value(
        text,
        ["job title", "role", "position", "designation", "opening", "job role"]
    )
    if explicit:
        return explicit

    for role in sorted(ROLE_KEYWORDS, key=len, reverse=True):
        if re.search(r"(?i)(?<!\w)" + re.escape(role) + r"(?!\w)", text):
            return role

    return None

def detect_location(text):
    explicit = labelled_value(
        text,
        ["location", "job location", "work location", "based in", "location(s)"]
    )
    if explicit:
        return explicit

    low = text.lower()
    found = []
    for city in INDIAN_CITIES:
        pos = low.find(city.lower())
        if pos >= 0:
            found.append((pos, city))

    if found:
        found.sort()
        return found[0][1]

    if re.search(r"(?i)\bindia\b", text):
        return "India"

    return None

def detect_ctc(text):
    labels = ["ctc", "salary", "package", "compensation", "pay", "stipend"]
    explicit = labelled_value(text, labels)

    if explicit:
        m = re.search(
            r"(?:₹\s*)?\d+(?:\.\d+)?\s*(?:-|–|—|to)\s*(?:₹\s*)?\d+(?:\.\d+)?\s*(?:LPA|L|lakhs?|lacs?)",
            explicit,
            re.I,
        )
        if m:
            return clean(m.group(0)), "explicit"

        m = re.search(
            r"(?:₹\s*)?\d+(?:\.\d+)?\s*(?:LPA|L|lakhs?|lacs?)",
            explicit,
            re.I,
        )
        if m:
            return clean(m.group(0)), "explicit"

        # Keep useful text such as "10-12 LPA + bonus".
        if re.search(r"\d", explicit):
            return explicit, "explicit"

    # Search the whole post for salary-like expressions.
    patterns = [
        r"(?:₹\s*)?\d+(?:\.\d+)?\s*(?:-|–|—|to)\s*(?:₹\s*)?\d+(?:\.\d+)?\s*(?:LPA|L|lakhs?|lacs?)",
        r"(?:₹\s*)?\d+(?:\.\d+)?\s*(?:LPA|L|lakhs?|lacs?)",
        r"₹\s*\d[\d,]*(?:\.\d+)?",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return clean(m.group(0)), "explicit"

    return None, "not_available"

def detect_eligibility(text):
    explicit = labelled_value(
        text,
        ["eligibility", "qualification", "qualifications",
         "who can apply", "eligible", "requirements", "education"]
    )
    if explicit:
        return explicit

    pieces = []
    patterns = [
        r"(?i)\b(?:B\.?Tech|B\.?E\.?|M\.?Tech|M\.?E\.?|MCA|BCA|MBA)\b[^.\n]{0,80}",
        r"(?i)\b(?:20(?:24|25|26|27))\s*(?:graduates?|batch)\b",
        r"(?i)\b(?:freshers?|0\s*[-–to]\s*\d+\s*years?)\b",
        r"(?i)\b\d+\+?\s*(?:years?|yrs?)\s*(?:of\s*)?experience\b",
    ]
    for p in patterns:
        for m in re.finditer(p, text):
            value = clean(m.group(0))
            if value and value not in pieces:
                pieces.append(value)

    return " · ".join(pieces) if pieces else None

def detect_experience(text):
    explicit = labelled_value(
        text,
        ["experience", "work experience", "years of experience", "seniority"]
    )
    if explicit:
        return explicit

    patterns = [
        r"(?i)\b(?:freshers?|entry[- ]level|early career)\b",
        r"(?i)\b\d+\s*[-–to]+\s*\d+\s*(?:years?|yrs?)\s*(?:of\s*)?experience\b",
        r"(?i)\b\d+\+?\s*(?:years?|yrs?)\s*(?:of\s*)?experience\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean(match.group(0))
    return None

def detect_skills(text):
    found = []
    low = text.lower()
    for skill in sorted(SKILLS, key=len, reverse=True):
        if re.search(r"(?i)(?<!\w)" + re.escape(skill) + r"(?!\w)", text):
            if skill.lower() not in [x.lower() for x in found]:
                found.append(skill)
    return found

def detect_description(text):
    explicit = labelled_value(
        text,
        ["job description", "description", "about the role", "responsibilities"]
    )
    if explicit:
        return explicit

    # Collect lines that look like prose, excluding obvious metadata.
    lines = [clean(x) for x in text.splitlines()]
    useful = []
    skip_words = (
        "http://", "https://", "eligibility:", "location:", "ctc:",
        "salary:", "skills:", "role:", "position:", "apply:", "company:"
    )
    for line in lines:
        if not line or len(line) < 35:
            continue
        if line.lower().startswith(skip_words):
            continue
        if len(line) <= 300:
            useful.append(line)

    if useful:
        return " ".join(useful[:2])

    return None

def detect_company_description(text):
    return labelled_value(
        text,
        ["company description", "about company", "about the company"]
    )

def parse_job_post(text):
    print("\n" + "=" * 55)
    print("🧩 LOCAL JOB PARSER STARTED")
    print("=" * 55)

    urls = extract_urls(text)

    company = detect_company(text)
    job_title = detect_job_title(text)
    location = detect_location(text)
    ctc, ctc_source = detect_ctc(text)
    eligibility = detect_eligibility(text)
    experience = detect_experience(text)
    skills = detect_skills(text)
    job_description = detect_description(text)
    company_description = detect_company_description(text)

    result = {
        "company": company,
        "job_title": job_title,
        "location": location,
        "ctc": ctc,
        "ctc_source": ctc_source,
        "eligibility": eligibility,
        "experience": experience,
        "skills": skills,
        "job_description": job_description,
        "company_description": company_description,
        "application_link": urls[0] if urls else None,
        "source_used": "post",
    }

    print("📋 PARSED DATA:")
    for key, value in result.items():
        print(f"  {key}: {value}")

    print("=" * 55)
    return result

def apply_correction(data, correction_text):
    """
    Lightweight correction helper.

    Examples:
      company = IBM
      role: Software Engineer
      ctc 12 LPA
      location Hyderabad
    """
    updated = dict(data)

    field_patterns = {
        "company": ["company"],
        "job_title": ["job title", "job", "role", "position", "designation"],
        "location": ["location", "city"],
        "ctc": ["ctc", "salary", "package"],
        "eligibility": ["eligibility", "qualification", "batch"],
        "experience": ["experience", "work experience"],
        "application_link": ["link", "url", "apply"],
    }

    for field, labels in field_patterns.items():
        label_pattern = "|".join(re.escape(x) for x in labels)
        m = re.search(
            rf"(?i)(?:^|\n)\s*(?:{label_pattern})\s*[:=]\s*(.+?)\s*(?=\n|$)",
            correction_text,
        )
        if m:
            value = clean(m.group(1))
            if field == "application_link" and value and is_ignored_url(value):
                value = None
            updated[field] = value

    # Skills can be corrected as comma/pipe separated text.
    m = re.search(r"(?i)(?:^|\n)\s*skills?\s*[:=]\s*(.+?)\s*(?=\n|$)", correction_text)
    if m:
        updated["skills"] = [
            clean(x) for x in re.split(r"[,|·]+", m.group(1)) if clean(x)
        ]

    # Simple natural correction: "ctc is 12 LPA".
    if not updated.get("ctc"):
        m = re.search(
            r"(?i)\b(?:ctc|salary|package)\s+(?:is\s+)?(.+?)(?:\s*$|\n)",
            correction_text,
        )
        if m:
            updated["ctc"] = clean(m.group(1))
            updated["ctc_source"] = "explicit"

    return updated
