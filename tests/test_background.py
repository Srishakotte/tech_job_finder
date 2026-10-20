import colorsys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from job_hunt.media.background import (
    animated_background_frame,
    create_brand_theme,
)
from job_hunt.media.reel import (
    REEL_TEMPLATES,
    _create_concept_frame,
    _concept_timeline,
    create_static_job_reel,
    create_template_previews,
)


class BrandBackgroundTests(unittest.TestCase):
    def test_background_is_repeatable_for_the_same_job(self):
        theme = create_brand_theme("Acme", "Software Engineer", "job-1")

        first = animated_background_frame(0, theme, size=(270, 480))
        second = animated_background_frame(0, theme, size=(270, 480))

        self.assertEqual(first.shape, (480, 270, 3))
        self.assertEqual(first.dtype.name, "uint8")
        self.assertTrue((first == second).all())

    def test_background_varies_between_jobs_for_the_same_company(self):
        first_theme = create_brand_theme("Acme", "Software Engineer", "job-1")
        second_theme = create_brand_theme("Acme", "Data Analyst", "job-2")

        first = animated_background_frame(0, first_theme, size=(270, 480))
        second = animated_background_frame(0, second_theme, size=(270, 480))

        self.assertFalse((first == second).all())

    def test_logo_color_drives_the_brand_accent(self):
        with tempfile.TemporaryDirectory() as directory:
            logo_path = Path(directory) / "logo.png"
            Image.new("RGB", (40, 40), (20, 160, 220)).save(logo_path)

            theme = create_brand_theme(
                "Acme",
                "Software Engineer",
                "job-1",
                str(logo_path),
            )

        expected_hue = colorsys.rgb_to_hsv(20 / 255, 160 / 255, 220 / 255)[0]
        actual_hue = colorsys.rgb_to_hsv(
            *(channel / 255 for channel in theme.primary)
        )[0]
        self.assertLess(abs(expected_hue - actual_hue), 0.03)

    def test_google_and_microsoft_use_their_brand_palettes(self):
        google = create_brand_theme("Google", "Software Engineer", "google-demo")
        microsoft = create_brand_theme(
            "Microsoft",
            "Software Engineer",
            "microsoft-demo",
        )

        self.assertEqual(google.primary, (66, 133, 244))
        self.assertEqual(microsoft.primary, (0, 164, 239))
        self.assertEqual(len(google.accents), 4)
        self.assertEqual(len(microsoft.accents), 4)

    def test_each_concept_timeline_fills_the_content_before_qr(self):
        for style in (
            "reference",
            "logo_reveal",
            "salary_first",
            "job_unlock",
            "guess_company",
        ):
            with self.subTest(style=style):
                timeline = _concept_timeline(style, 13)
                self.assertAlmostEqual(sum(duration for _, duration in timeline), 13)

    def test_each_template_timeline_fills_the_content_before_qr(self):
        for style, _ in REEL_TEMPLATES:
            with self.subTest(style=style):
                timeline = _concept_timeline(style, 13)
                self.assertEqual(timeline, [(style, 13)])

    def test_existing_concept_phases_still_render(self):
        theme = create_brand_theme("Google", "Software Engineer", "concept-test")
        for style in ("logo_reveal", "salary_first", "job_unlock", "guess_company"):
            for phase, _ in _concept_timeline(style, 13):
                with self.subTest(style=style, phase=phase):
                    frame = _create_concept_frame(
                        style=style,
                        phase=phase,
                        company="Google",
                        job_title="Software Engineer",
                        location="Hyderabad, India",
                        ctc="₹25–40 LPA",
                        eligibility="B.Tech CSE, 2026 graduates",
                        experience="0–2 years",
                        skills="Python · React · Cloud",
                        job_description="Build products for everyone.",
                        logo_path=None,
                        theme=theme,
                    )
                    self.assertEqual(frame.size, (1080, 1920))

    def test_all_eleven_previews_are_generated_as_phone_sized_pngs(self):
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory) / "output"
            output_directory.mkdir()
            logo_path = Path(directory) / "logo.png"
            Image.new("RGB", (60, 60), (30, 100, 210)).save(logo_path)

            with patch("job_hunt.media.reel.OUTPUT_DIR", str(output_directory)):
                previews = create_template_previews(
                    company="Microsoft",
                    job_title="Software Engineer",
                    location="Hyderabad, India",
                    ctc="₹15–25 LPA",
                    eligibility="B.Tech CSE, 2026 graduates",
                    experience="0–2 years",
                    skills="Python · React · Azure",
                    brand_image_path=str(logo_path),
                    job_id="gallery-test",
                )

            self.assertEqual(len(previews), 11)
            self.assertEqual([item["style"] for item in previews], [item[0] for item in REEL_TEMPLATES])
            for preview in previews:
                with self.subTest(style=preview["style"]):
                    self.assertTrue(Path(preview["path"]).is_file())
                    with Image.open(preview["path"]) as image:
                        self.assertEqual(image.format, "PNG")
                        self.assertEqual(image.size, (1080, 1920))

    def test_static_reel_is_one_png_with_qr_and_rejects_invalid_links(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "static-reel.png"
            result = create_static_job_reel(
                company="Google",
                job_title="Software Engineer",
                location="Bengaluru, India",
                ctc="₹55–70 LPA",
                eligibility="B.Tech / M.Tech (CS/IT or related)",
                experience="0–2 years · Freshers eligible",
                skills=["DSA", "System Design", "C++ / Java / Python"],
                application_link="https://careers.google.com/jobs/results/",
                output_path=str(output_path),
                posted_on="14 Oct 2026",
            )

            self.assertEqual(result, str(output_path))
            with Image.open(result) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1080, 1920))
                qr_region = image.convert("L").crop((150, 1420, 375, 1655))
                self.assertLess(qr_region.getextrema()[0], 32)
                self.assertGreater(qr_region.getextrema()[1], 240)

            with self.assertRaises(ValueError):
                create_static_job_reel(
                    company="Google",
                    job_title="Software Engineer",
                    location="Bengaluru, India",
                    ctc="₹55–70 LPA",
                    eligibility="B.Tech / M.Tech",
                    experience="0–2 years",
                    skills=["Python"],
                    application_link="not-a-valid-url",
                    output_path=str(Path(directory) / "invalid.png"),
                )


if __name__ == "__main__":
    unittest.main()
