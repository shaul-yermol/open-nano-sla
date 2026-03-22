#!/usr/bin/env python3
"""
Generate simple icon PNGs for the SLA printer main-menu buttons.

Run once to create the icons/ directory and its contents:
    python3 generate_icons.py

Each icon is 48×48 pixels, white on transparent background.
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont

ICON_SIZE = 48
ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
COLOR = (255, 255, 255, 255)        # white, fully opaque
TRANSPARENT = (0, 0, 0, 0)


def _new() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), TRANSPARENT)
    return img, ImageDraw.Draw(img)


def _save(img: Image.Image, name: str):
    os.makedirs(ICONS_DIR, exist_ok=True)
    path = os.path.join(ICONS_DIR, name)
    img.save(path)
    print(f"  saved {path}")


# ── PRINT icon: stacked layers (3D-print metaphor) ──────────────────────
def gen_print():
    img, d = _new()
    # Three horizontal bars, getting wider toward the bottom
    for i, (y, half_w) in enumerate([(12, 8), (22, 13), (32, 18)]):
        x_c = ICON_SIZE // 2
        d.rounded_rectangle(
            [x_c - half_w, y, x_c + half_w, y + 6],
            radius=2, fill=COLOR,
        )
    # Small downward arrow at top (nozzle)
    cx = ICON_SIZE // 2
    d.polygon([(cx - 4, 6), (cx + 4, 6), (cx, 12)], fill=COLOR)
    _save(img, "print.png")


# ── MOVE UP icon: upward arrow ──────────────────────────────────────────
def gen_move_up():
    img, d = _new()
    cx, cy = ICON_SIZE // 2, ICON_SIZE // 2
    # Arrow shaft
    shaft_hw = 4
    d.rectangle([cx - shaft_hw, cy - 2, cx + shaft_hw, cy + 16], fill=COLOR)
    # Arrow head
    d.polygon([
        (cx, cy - 18),
        (cx - 14, cy),
        (cx + 14, cy),
    ], fill=COLOR)
    _save(img, "move_up.png")


# ── MOVE DOWN icon: downward arrow ─────────────────────────────────────
def gen_move_down():
    img, d = _new()
    cx, cy = ICON_SIZE // 2, ICON_SIZE // 2
    # Arrow shaft
    shaft_hw = 4
    d.rectangle([cx - shaft_hw, cy - 16, cx + shaft_hw, cy + 2], fill=COLOR)
    # Arrow head
    d.polygon([
        (cx, cy + 18),
        (cx - 14, cy),
        (cx + 14, cy),
    ], fill=COLOR)
    _save(img, "move_down.png")


# ── HOME icon: house shape ─────────────────────────────────────────────
def gen_home():
    img, d = _new()
    cx = ICON_SIZE // 2
    # Roof (triangle)
    d.polygon([
        (cx, 4),
        (4, 22),
        (ICON_SIZE - 4, 22),
    ], fill=COLOR)
    # Walls (rectangle)
    d.rectangle([10, 22, ICON_SIZE - 10, 42], fill=COLOR)
    # Door (dark cutout)
    d.rectangle([cx - 5, 28, cx + 5, 42], fill=TRANSPARENT)
    _save(img, "home.png")


# ── FLOOD icon: sun / UV light rays ───────────────────────────────────
def gen_flood():
    img, d = _new()
    cx, cy = ICON_SIZE // 2, ICON_SIZE // 2
    # Central circle
    r = 8
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLOR)
    # Rays
    ray_inner = 12
    ray_outer = 20
    for angle_deg in range(0, 360, 45):
        a = math.radians(angle_deg)
        x0 = cx + ray_inner * math.cos(a)
        y0 = cy + ray_inner * math.sin(a)
        x1 = cx + ray_outer * math.cos(a)
        y1 = cy + ray_outer * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=COLOR, width=3)
    _save(img, "flood.png")


# ── TEST icon: check-list / wrench ────────────────────────────────────
def gen_test():
    img, d = _new()
    # Three horizontal lines with small checkboxes
    for i, y in enumerate([8, 20, 32]):
        # checkbox outline
        d.rectangle([6, y, 16, y + 10], outline=COLOR, width=2)
        # check mark inside
        d.line([(8, y + 5), (10, y + 8), (14, y + 2)], fill=COLOR, width=2)
        # text line
        d.rectangle([22, y + 2, 42, y + 8], fill=COLOR)
    _save(img, "test.png")


# ── main ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Generating icons …")
    gen_print()
    gen_move_up()
    gen_move_down()
    gen_home()
    gen_flood()
    gen_test()
    print("Done.")
