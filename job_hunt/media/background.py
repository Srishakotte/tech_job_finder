import colorsys
import hashlib
import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw


BACKGROUND_WIDTH = 270
BACKGROUND_HEIGHT = 480

FALLBACK_COLORS = (
    (48, 142, 255),
    (0, 190, 170),
    (255, 125, 72),
    (158, 108, 255),
    (232, 76, 130),
    (105, 190, 92),
    (255, 184, 64),
    (68, 190, 220),
)

COMPANY_PALETTES = {
    "google": (
        (66, 133, 244),
        (234, 67, 53),
        (251, 188, 5),
        (52, 168, 83),
    ),
    "microsoft": (
        (0, 164, 239),
        (242, 80, 34),
        (127, 186, 0),
        (255, 185, 0),
    ),
}


@dataclass(frozen=True)
class BrandTheme:
    primary: tuple[int, int, int]
    secondary: tuple[int, int, int]
    seed: int
    accents: tuple[tuple[int, int, int], ...] = ()


def _logo_color(logo_path):
    if not logo_path:
        return None

    try:
        with Image.open(logo_path) as source:
            image = source.convert("RGBA")
            image.thumbnail((64, 64), Image.Resampling.LANCZOS)
            colors = Counter()
            for red, green, blue, alpha in image.getdata():
                if alpha < 96:
                    continue
                hue, saturation, value = colorsys.rgb_to_hsv(
                    red / 255,
                    green / 255,
                    blue / 255,
                )
                if saturation < 0.28 or value < 0.18 or value > 0.96:
                    continue
                bucket = (red // 16 * 16, green // 16 * 16, blue // 16 * 16)
                colors[bucket] += 1
    except OSError:
        return None

    if not colors:
        return None

    def score(item):
        color, count = item
        saturation = colorsys.rgb_to_hsv(*(channel / 255 for channel in color))[1]
        return count * saturation

    red, green, blue = max(colors.items(), key=score)[0]
    hue, _, _ = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    return tuple(
        round(channel * 255)
        for channel in colorsys.hsv_to_rgb(hue, 0.78, 0.96)
    )


def create_brand_theme(company, job_title, job_id=None, logo_path=None):
    identity = f"{company}|{job_title}|{job_id or ''}".casefold()
    seed = int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:4], "big")
    company_key = str(company or "").casefold().strip()
    accents = COMPANY_PALETTES.get(company_key, ())
    primary = accents[0] if accents else (
        _logo_color(logo_path) or FALLBACK_COLORS[seed % len(FALLBACK_COLORS)]
    )
    secondary = (
        tuple(round(channel * 0.72) for channel in primary)
        if accents
        else FALLBACK_COLORS[(seed >> 8) % len(FALLBACK_COLORS)]
    )
    if secondary == primary:
        secondary = FALLBACK_COLORS[(seed + 1) % len(FALLBACK_COLORS)]
    return BrandTheme(
        primary=primary,
        secondary=secondary,
        seed=seed,
        accents=accents,
    )


def animated_background_frame(time_seconds, theme, size=(1080, 1920)):
    width, height = BACKGROUND_WIDTH, BACKGROUND_HEIGHT
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    x /= width
    y /= height

    phase = (theme.seed % 1000) / 1000 * math.tau
    progress = time_seconds / 18
    primary_x = 0.22 + 0.42 * (0.5 + 0.5 * np.sin(math.tau * progress + phase))
    primary_y = 0.25 + 0.3 * np.sin(math.tau * progress + phase + 1.1)
    secondary_x = 0.78 - 0.38 * progress
    primary_glow = np.exp(
        -(((x - primary_x) / 0.62) ** 2 + ((y - primary_y) / 0.48) ** 2) * 2.3
    )
    secondary_glow = np.exp(
        -(((x - secondary_x) / 0.48) ** 2 + ((y - 0.78) / 0.36) ** 2) * 2.8
    )

    frame = np.empty((height, width, 3), dtype=np.float32)
    frame[:, :, 0] = 7 + 10 * y
    frame[:, :, 1] = 10 + 8 * y
    frame[:, :, 2] = 22 + 14 * y
    for channel in range(3):
        frame[:, :, channel] += (
            theme.primary[channel] * primary_glow * 0.2
            + theme.secondary[channel] * secondary_glow * 0.12
        )
    frame = np.clip(frame, 0, 255).astype(np.uint8)

    background = Image.fromarray(frame).convert("RGBA")
    details = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(details)
    primary = (*theme.primary, 30)
    secondary = (*theme.secondary, 25)
    ring_x = -int(width * (0.2 + (theme.seed % 23) / 100))
    ring_y = int(height * (0.17 + (theme.seed % 19) / 100))
    for ring in range(3):
        inset = ring * 14
        draw.ellipse(
            (
                ring_x - inset,
                ring_y - inset,
                ring_x + 190 + inset,
                ring_y + 190 + inset,
            ),
            outline=primary,
            width=1,
        )

    accent_x = int(width * (0.64 + (theme.seed % 17) / 100))
    for row in range(8):
        for column in range(5):
            dot_x = accent_x + column * 9
            dot_y = height - 125 + row * 9
            if dot_x < width and dot_y < height:
                draw.ellipse((dot_x, dot_y, dot_x + 1, dot_y + 1), fill=secondary)
    draw.line(
        (0, int(height * 0.68), width, int(height * 0.48)),
        fill=(*theme.primary, 18),
        width=1,
    )
    background = Image.alpha_composite(background, details).convert("RGB")
    return np.asarray(
        background.resize(size, Image.Resampling.BILINEAR)
    )
