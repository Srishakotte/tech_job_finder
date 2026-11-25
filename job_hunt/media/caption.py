"""Instagram caption: hook, job details, call to action, trust lines, 30 hashtags.

Instagram allows at most 30 hashtags per post; more makes the publish fail (or
the caption get stripped), so we fill exactly up to 30, most specific first:
company -> role -> location -> batch/experience -> broad reach tags.
"""

from __future__ import annotations

import os
import re

from .card import clean, hook_lines, with_defaults

MAX_HASHTAGS = 30

BROAD_TAGS = [
    "#jobs", "#hiring", "#jobalert", "#jobsearch", "#jobopenings", "#nowhiring",
    "#jobsinindia", "#careers", "#jobseekers", "#jobvacancy", "#offcampus",
    "#offcampusdrive", "#placements", "#mncjobs", "#jobupdates", "#career",
    "#jobhunt", "#recruitment", "#jobopportunity", "#indiajobs", "#latestjobs",
    "#careergrowth", "#jobsforyou", "#jobpost", "#explore", "#trending", "#viral",
]
ROLE_TAGS = [
    (r"software|developer|sde|engineer|programmer|full ?stack|backend|frontend",
     ["#softwareengineer", "#softwarejobs", "#itjobs", "#techjobs", "#developerjobs", "#coding"]),
    (r"machine learning|\bml\b|\bai\b|scientist|data science",
     ["#datascience", "#machinelearning", "#aijobs", "#datajobs"]),
    (r"data|analyst|analytics",
     ["#dataanalyst", "#analystjobs", "#datajobs", "#analytics"]),
    (r"test|qa|quality",
     ["#softwaretesting", "#qajobs", "#testingjobs", "#automationtesting", "#itjobs"]),
    (r"devops|cloud|sre|site reliability|aws|azure",
     ["#devops", "#cloudjobs", "#awsjobs", "#itjobs", "#techjobs"]),
    (r"support|service desk|bpo|customer|process associate",
     ["#bpojobs", "#customersupport", "#nonitjobs", "#voiceprocess"]),
    (r"product|business analyst|consult",
     ["#productmanagement", "#businessanalyst", "#consultingjobs"]),
    (r"design|ui|ux",
     ["#uiuxjobs", "#designjobs", "#uxdesign"]),
    (r"intern",
     ["#internship", "#internships", "#paidinternship", "#studentjobs", "#internshipopportunity"]),
]
CITY_TAGS = {
    "bangalore": "bangalore", "bengaluru": "bangalore", "hyderabad": "hyderabad",
    "pune": "pune", "chennai": "chennai", "mumbai": "mumbai", "delhi": "delhi",
    "noida": "noida", "gurgaon": "gurgaon", "gurugram": "gurgaon", "kolkata": "kolkata",
    "ahmedabad": "ahmedabad", "kochi": "kochi", "coimbatore": "coimbatore",
    "chandigarh": "chandigarh", "jaipur": "jaipur", "indore": "indore",
}


def _tag(text):
    word = re.sub(r"[^a-z0-9]", "", str(text).lower())
    return f"#{word}" if len(word) > 1 else None


def build_hashtags(d, defaulted):
    tags = []
    add = lambda *items: tags.extend(t for t in items if t)

    company = _tag(d["company"])
    if company:
        add(company, f"{company}jobs", f"{company}careers", f"{company}hiring")
    role_blob = f"{d['job_title']} {d['job_type']}".lower()
    if "job_title" not in defaulted:
        add(_tag(d["job_title"]) if len(d["job_title"]) <= 28 else None)
    for pattern, items in ROLE_TAGS:
        if re.search(pattern, role_blob):
            add(*items)
    loc = d["location"].lower()
    for key, city in CITY_TAGS.items():
        if key in loc:
            add(f"#{city}jobs", f"#jobsin{city}", f"#{city}")
    if re.search(r"remote|work from home|wfh", loc):
        add("#workfromhome", "#remotejobs", "#wfhjobs")
    blob = f"{d['experience']} {d['eligibility']}".lower()
    for year in sorted(set(re.findall(r"\b(20(?:2[3-9]))\b", blob))):
        add(f"#{year}batch", f"#batch{year}")
    if "fresher" in blob or "experience" in defaulted or re.search(r"\b0\s*[-–to]", blob):
        add("#freshers", "#fresherjobs", "#freshersjobs", "#graduatejobs")
    if re.search(r"b\.?\s?tech|b\.?e\b|engineering", blob):
        add("#btechjobs", "#engineeringjobs")
    for skill in re.split(r"[,·|/;]+", d.get("skills") or "")[:4]:
        add(_tag(skill) if 2 < len(skill.strip()) <= 20 else None)
    add(*BROAD_TAGS)
    return list(dict.fromkeys(tags))[:MAX_HASHTAGS]


def build_caption(company, job_title, location, ctc, eligibility, experience, skills,
                  job_type=None, application_link=None, keyword=None, handle=None):
    d, defaulted = with_defaults({
        "company": company, "job_title": job_title, "location": location, "ctc": ctc,
        "eligibility": eligibility, "experience": experience, "skills": skills, "job_type": job_type,
    })
    handle = clean(handle if handle is not None else os.getenv("BRAND_HANDLE"))
    line1, line2 = hook_lines(d, defaulted)
    if keyword and application_link:
        cta = [f"💬 Comment \"{keyword}\" and get the apply link in your DM instantly",
               "📲 Or scan the QR code in the reel"]
    else:
        cta = ["📲 Scan the QR code in the reel to apply"]
    show_link = os.getenv("CAPTION_INCLUDE_LINK", "false").strip().lower() in {"1", "true", "yes"}

    lines = [
        f"🚨 {line1} | {line2} 🚨",
        "",
        f"🏢 Company: {d['company'] or 'Top MNC'}",
        f"📌 Role: {d['job_title']}",
        f"🧾 Job Type: {d['job_type']}",
        f"🎓 Qualification: {d['eligibility']}",
        f"💼 Experience: {d['experience']}",
        f"💰 Salary: {d['ctc']}",
        f"📍 Location: {d['location']}",
        f"🛠 Skills: {d['skills']}" if d["skills"] else None,
        "",
        *cta,
        f"🔗 {application_link}" if show_link and application_link else None,
        "",
        "✅ 100% free. We never charge any fee for jobs.",
        "⚠️ Always apply through the official careers page and verify details there.",
        "",
        "💾 Save this post & share it with a friend who needs a job 🙌",
        f"🔔 Follow {handle} for daily off-campus drives, internships & jobs" if handle
        else "🔔 Follow for daily off-campus drives, internships & jobs",
        "",
        ".",
        ".",
        " ".join(build_hashtags(d, defaulted)),
    ]
    caption = "\n".join(l for l in lines if l is not None)
    return re.sub(r"\n{3,}", "\n\n", caption).strip()[:2200]
