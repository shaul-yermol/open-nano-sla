#!/usr/bin/env python3
"""
Touch-screen calibration script for XPT2046 + ILI9341 LCD (240×320).

Displays crosshair targets one at a time.  Touch each target with a stylus.
After all points are collected the script computes calibration values and
saves them to  touch_cal.json  in the same directory.

Usage:
    python3 touch-test.py
"""

import json
import os
import time
from time import sleep

import board
import busio
import digitalio
from gpiozero import Button as GpioButton

import adafruit_rgb_display.ili9341 as ili9341
from PIL import Image, ImageDraw, ImageFont

from xpt2046 import Touch

# ── hardware pins ────────────────────────────────────────────────────────
DISPLAY_CS = board.D8
TOUCH_CS   = board.D7
DC_PIN     = board.D1
TOUCH_IRQ  = 3            # GPIO number for gpiozero Button

SCREEN_W   = 240
SCREEN_H   = 320
ROTATION   = 180

# Margin (px) from the screen edge where calibration targets are placed.
MARGIN = 30

# How many raw samples to average per target point
SAMPLES_PER_POINT = 8

# Path to save calibration data
CAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "touch_cal.json")

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ── calibration target positions (screen coords) ────────────────────────
#  top-left,  top-right,  bottom-right,  bottom-left
CAL_POINTS = [
    (MARGIN,              MARGIN),
    (SCREEN_W - MARGIN,   MARGIN),
    (SCREEN_W - MARGIN,   SCREEN_H - MARGIN),
    (MARGIN,              SCREEN_H - MARGIN),
]


# ── helpers ──────────────────────────────────────────────────────────────
def draw_target(draw_ctx, img, disp, sx, sy, msg=""):
    """Clear screen and draw a crosshair at (sx, sy) with optional message."""
    draw_ctx.rectangle([0, 0, SCREEN_W - 1, SCREEN_H - 1], fill=(0, 0, 0))

    arm = 12
    color = (255, 80, 80)
    # horizontal line
    draw_ctx.line([(sx - arm, sy), (sx + arm, sy)], fill=color, width=2)
    # vertical line
    draw_ctx.line([(sx, sy - arm), (sx, sy + arm)], fill=color, width=2)
    # small centre dot
    draw_ctx.ellipse([(sx - 3, sy - 3), (sx + 3, sy + 3)], fill=(255, 255, 255))

    if msg:
        font = ImageFont.truetype(FONT_PATH, 14)
        bbox = font.getbbox(msg)
        tw = bbox[2] - bbox[0]
        tx = (SCREEN_W - tw) // 2
        draw_ctx.text((tx, SCREEN_H // 2 + 40), msg, font=font, fill=(200, 200, 200))

    disp.image(img, ROTATION)


def collect_raw_samples(touch_ctrl, n=SAMPLES_PER_POINT):
    """Block until *n* valid raw samples are gathered; return averaged (x, y)."""
    xs, ys = [], []
    print(f"  Collecting {n} samples …", end="", flush=True)
    while len(xs) < n:
        raw = touch_ctrl.raw_touch()
        if raw is not None:
            xs.append(raw[0])
            ys.append(raw[1])
            print(".", end="", flush=True)
        sleep(0.05)
    print(" done")
    return sum(xs) // n, sum(ys) // n


# ── main ─────────────────────────────────────────────────────────────────
def main():
    # ── SPI + display ────────────────────────────────────────────────────
    spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI, MISO=board.MISO)
    disp = ili9341.ILI9341(
        spi,
        cs=digitalio.DigitalInOut(DISPLAY_CS),
        dc=digitalio.DigitalInOut(DC_PIN),
    )
    img = Image.new("RGB", (SCREEN_W, SCREEN_H))
    drw = ImageDraw.Draw(img)

    # ── touch (no interrupt handler – we poll raw values) ────────────────
    touch_cs = digitalio.DigitalInOut(TOUCH_CS)
    xpt = Touch(spi, cs=touch_cs)   # no int_pin → polling only

    # ── run calibration ──────────────────────────────────────────────────
    raw_points = []   # list of (raw_x, raw_y) matching CAL_POINTS order

    for idx, (sx, sy) in enumerate(CAL_POINTS):
        label = f"Touch target {idx + 1}/{len(CAL_POINTS)}"
        draw_target(drw, img, disp, sx, sy, msg=label)
        print(f"\n▶ {label}  screen=({sx}, {sy})")

        # Wait for the user to lift any current touch first
        while xpt.raw_touch() is not None:
            sleep(0.05)
        sleep(0.3)        # brief pause so user can reposition

        raw_x, raw_y = collect_raw_samples(xpt)
        raw_points.append((raw_x, raw_y))
        print(f"  Raw average: ({raw_x}, {raw_y})")

        # Wait for release before moving to next point
        sleep(0.5)

    # ── compute calibration ──────────────────────────────────────────────
    # CAL_POINTS screen coords → raw coords collected
    # We solve a simple linear mapping:
    #   screen_x = raw_x * x_mult + x_off   (and similarly for y)
    #
    # From the 4-point pairs we can get min/max raw values that correspond
    # to the screen edges (0 and SCREEN_W-1, 0 and SCREEN_H-1).

    # Separate the raw values by which screen-edge they're near
    raw_at_left   = [r[0] for r, s in zip(raw_points, CAL_POINTS) if s[0] == MARGIN]
    raw_at_right  = [r[0] for r, s in zip(raw_points, CAL_POINTS) if s[0] == SCREEN_W - MARGIN]
    raw_at_top    = [r[1] for r, s in zip(raw_points, CAL_POINTS) if s[1] == MARGIN]
    raw_at_bottom = [r[1] for r, s in zip(raw_points, CAL_POINTS) if s[1] == SCREEN_H - MARGIN]

    avg_raw_left   = sum(raw_at_left)   // len(raw_at_left)
    avg_raw_right  = sum(raw_at_right)  // len(raw_at_right)
    avg_raw_top    = sum(raw_at_top)    // len(raw_at_top)
    avg_raw_bottom = sum(raw_at_bottom) // len(raw_at_bottom)

    # Extrapolate from MARGIN inward to the true 0 / max edges
    # raw_per_pixel_x = (avg_raw_right - avg_raw_left) / (SCREEN_W - 2*MARGIN)
    raw_per_px_x = (avg_raw_right - avg_raw_left) / (SCREEN_W - 2 * MARGIN)
    raw_per_px_y = (avg_raw_bottom - avg_raw_top) / (SCREEN_H - 2 * MARGIN)

    x_min = int(avg_raw_left  - MARGIN * raw_per_px_x)
    x_max = int(avg_raw_right + MARGIN * raw_per_px_x)
    y_min = int(avg_raw_top   - MARGIN * raw_per_px_y)
    y_max = int(avg_raw_bottom + MARGIN * raw_per_px_y)

    # Ensure min ≤ max (touch sensor axis may be inverted vs screen axis)
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min

    cal = {
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "raw_points": raw_points,
        "screen_points": CAL_POINTS,
    }

    with open(CAL_FILE, "w") as f:
        json.dump(cal, f, indent=2)

    print(f"\n✓ Calibration saved to {CAL_FILE}")
    print(f"  x_min={x_min}  x_max={x_max}  y_min={y_min}  y_max={y_max}")

    # ── show result on screen ────────────────────────────────────────────
    drw.rectangle([0, 0, SCREEN_W - 1, SCREEN_H - 1], fill=(0, 0, 0))
    font = ImageFont.truetype(FONT_PATH, 14)
    drw.text((10, 40), "Calibration done!", font=font, fill=(0, 255, 0))
    drw.text((10, 70), f"x: {x_min} .. {x_max}", font=font, fill=(255, 255, 255))
    drw.text((10, 95), f"y: {y_min} .. {y_max}", font=font, fill=(255, 255, 255))
    drw.text((10, 130), f"Saved: touch_cal.json", font=font, fill=(180, 180, 180))
    disp.image(img, ROTATION)


if __name__ == "__main__":
    main()
