import unittest

from job_hunt.parsing.job_post import parse_job_post


class JobPostParserTests(unittest.TestCase):
    def test_company_name_label_is_parsed_with_hyphenated_job_post(self):
        post = """Company Name: HackerRank

- Role: Software Development Engineer Intern
- Location: Bangalore
- Employment Type: Full time
- Duration: 6-month full-time onsite internship (Jan - June 2027)

Apply Link: https://www.hackerrank.com/careers/job?id=8229735"""

        parsed = parse_job_post(post)

        self.assertEqual(parsed["company"], "HackerRank")
        self.assertEqual(parsed["job_title"], "Software Development Engineer Intern")
        self.assertEqual(parsed["location"], "Bangalore")
        self.assertEqual(
            parsed["application_link"],
            "https://www.hackerrank.com/careers/job?id=8229735",
        )


if __name__ == "__main__":
    unittest.main()
