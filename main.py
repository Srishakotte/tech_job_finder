"""Compatibility entry point for the standalone Reel-generation demo."""

from job_hunt.media.reel import create_job_post


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
