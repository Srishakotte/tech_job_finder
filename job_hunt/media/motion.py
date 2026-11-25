"""Animate a layered job card (see card.py) into a short, low-memory Reel.

Timeline (default 7 s @ 24 fps, 720x1280):
  0.0-2.2 s  elements enter one after another (fade / rise / slide / pop)
  2.2-7.0 s  hold: slow background zoom, QR scan-line sweep, comment card pulse

Everything is composited with Pillow from small per-element tiles, so peak RAM
stays far below Render Free's 512 MB.
"""

from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image, ImageDraw

from .card import CardLayers, WIDTH, HEIGHT

RENDER_W = int(os.getenv("REEL_RENDER_WIDTH", "720"))
RENDER_H = RENDER_W * 16 // 9
FPS = int(os.getenv("REEL_FPS", "24"))
DURATION = float(os.getenv("REEL_DURATION_SECONDS", "7"))
ENTER = 0.5  # seconds each element takes to settle
COVER_SECONDS = 3.0  # a frame where everything is visible (Instagram thumb_offset)


def _ease(p):
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def _ease_back(p):
    p = min(1.0, max(0.0, p))
    c = 1.4
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


class _Sprite:
    def __init__(self, region, scale):
        x1, y1, x2, y2 = region.box
        self.x, self.y = x1 * scale, y1 * scale
        w, h = max(1, round((x2 - x1) * scale)), max(1, round((y2 - y1) * scale))
        self.tile = region.tile.resize((w, h), Image.Resampling.LANCZOS)
        self.alpha = self.tile.getchannel("A")
        self.effect, self.delay, self.loop = region.effect, region.delay, region.loop
        self.focus = None
        if region.focus:
            fx1, fy1, fx2, fy2 = region.focus
            self.focus = (fx1 * scale - self.x, fy1 * scale - self.y, fx2 * scale - self.x, fy2 * scale - self.y)
        self.scale = scale

    def _with_alpha(self, tile, a):
        if a >= 0.999:
            return tile
        out = tile.copy()
        out.putalpha(self.alpha.point(lambda v: int(v * a)) if tile is self.tile
                     else tile.getchannel("A").point(lambda v: int(v * a)))
        return out

    def draw(self, frame, t):
        p = (t - self.delay) / ENTER
        if p <= 0:
            return
        e = _ease(p)
        dx = dy = 0.0
        zoom = 1.0
        travel = 60 * self.scale
        if self.effect == "rise":
            dy = (1 - e) * travel
        elif self.effect == "slide_left":
            dx = -(1 - e) * travel
        elif self.effect == "slide_right":
            dx = (1 - e) * travel
        elif self.effect == "pop":
            zoom = 0.82 + 0.18 * _ease_back(p)
        settled = p >= 1
        if settled and self.loop == "pulse":
            zoom = 1 + 0.018 * (0.5 - 0.5 * math.cos((t - self.delay - ENTER) * 2 * math.pi / 1.6))

        tile = self.tile
        if abs(zoom - 1) > 1e-3:
            w, h = tile.size
            nw, nh = max(1, round(w * zoom)), max(1, round(h * zoom))
            tile = tile.resize((nw, nh), Image.Resampling.BILINEAR)
            dx -= (nw - w) / 2
            dy -= (nh - h) / 2
        tile = self._with_alpha(tile, e)
        frame.alpha_composite(tile, (int(round(self.x + dx)), int(round(self.y + dy))))

        if settled and self.loop == "scan" and self.focus:
            self._scan(frame, t - self.delay - ENTER)

    def _scan(self, frame, since):
        period, sweep = 2.4, 1.1
        phase = since % period
        if phase > sweep:
            return
        fx1, fy1, fx2, fy2 = self.focus
        h = fy2 - fy1
        cy = fy1 + h * _ease(phase / sweep)
        band = 26 * self.scale
        w = int(fx2 - fx1)
        bar = Image.new("RGBA", (w, int(band * 2)), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bar)
        for i in range(bar.height):
            a = int(110 * (1 - abs(i - band) / band) ** 2)
            bd.line((0, i, w, i), fill=(0, 98, 255, a))
        bd.line((0, int(band), w, int(band)), fill=(0, 98, 255, 230), width=max(2, int(3 * self.scale)))
        frame.alpha_composite(bar, (int(self.x + fx1), int(self.y + cy - band)))
        bar.close()


def build_frame_function(layers: CardLayers, duration=DURATION):
    scale = RENDER_W / WIDTH
    # Background is rendered slightly oversized for a slow Ken Burns push-in.
    over = 1.06
    bg = layers.background.resize((round(RENDER_W * over), round(RENDER_H * over)), Image.Resampling.LANCZOS)
    sprites = [_Sprite(r, scale) for r in layers.regions]

    def frame_at(t):
        z = 1 + (over - 1) * (t / max(duration, 0.01))
        cw, ch = bg.width / z, bg.height / z
        left, top = (bg.width - cw) / 2, (bg.height - ch) / 2
        frame = bg.resize((RENDER_W, RENDER_H), Image.Resampling.BILINEAR,
                          box=(left, top, left + cw, top + ch)).convert("RGBA")
        for sprite in sprites:
            sprite.draw(frame, t)
        arr = np.asarray(frame.convert("RGB"))
        frame.close()
        return arr

    return frame_at
