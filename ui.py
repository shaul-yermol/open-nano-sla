"""
UI module for the SLA printer's 240x320 LCD display.
Provides a generic Button class and screen-drawing helpers.
"""
from __future__ import annotations

import glob
import os
from PIL import Image, ImageDraw, ImageFont

# Display dimensions (portrait orientation)
SCREEN_W = 240
SCREEN_H = 320

# Default font path – DejaVu Sans is available on Raspberry Pi OS
_DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Directory where icon PNGs live (next to this module)
_ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


class Button:
    """A rectangular button that can be drawn on a PIL ImageDraw canvas."""

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        label: str,
        bg_color=(60, 60, 60),
        fg_color=(255, 255, 255),
        border_color=(180, 180, 180),
        border_width: int = 2,
        font: ImageFont.FreeTypeFont | None = None,
        font_size: int = 14,
        icon_path: str | None = None,
        label_font: ImageFont.FreeTypeFont | None = None,
        label_font_size: int = 10,
    ):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.label = label
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.border_color = border_color
        self.border_width = border_width
        self.font = font or ImageFont.truetype(_DEFAULT_FONT_PATH, font_size)

        # Icon support: load an external PNG image
        self.icon: Image.Image | None = None
        if icon_path and os.path.isfile(icon_path):
            self.icon = Image.open(icon_path).convert("RGBA")

        # Smaller font used for the label when an icon is present
        self.label_font = label_font or ImageFont.truetype(_DEFAULT_FONT_PATH, label_font_size)

    # ---- hit-testing (useful when touch is wired up later) ---------------
    def contains(self, px: int, py: int) -> bool:
        """Return True if pixel coordinate (px, py) falls inside the button."""
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    # ---- drawing ---------------------------------------------------------
    def draw(self, canvas: ImageDraw.ImageDraw, target_image: Image.Image | None = None):
        """Render the button onto *canvas*.

        If the button carries an icon, *target_image* must be the underlying
        PIL Image so that the icon can be composited with transparency.
        """
        x0, y0 = self.x, self.y
        x1, y1 = x0 + self.w - 1, y0 + self.h - 1

        # filled background
        canvas.rectangle([x0, y0, x1, y1], fill=self.bg_color)

        # border (drawn as nested rectangles for controllable width)
        for i in range(self.border_width):
            canvas.rectangle(
                [x0 + i, y0 + i, x1 - i, y1 - i],
                outline=self.border_color,
            )

        if self.icon is not None:
            # ---- icon + small label at bottom ----
            label_font = self.label_font
            lbbox = label_font.getbbox(self.label)
            lw = lbbox[2] - lbbox[0]
            lh = lbbox[3] - lbbox[1]
            label_margin = 4  # px above bottom edge

            # Available space for the icon (above the label)
            icon_area_h = self.h - lh - label_margin - self.border_width * 2 - 4
            icon_area_w = self.w - self.border_width * 2 - 4

            # Resize icon to fit, preserving aspect ratio
            iw, ih = self.icon.size
            scale = min(icon_area_w / iw, icon_area_h / ih, 1.0)
            new_w, new_h = int(iw * scale), int(ih * scale)
            icon_resized = self.icon.resize((new_w, new_h), Image.LANCZOS)

            # Centre the icon horizontally, vertically within icon area
            ix = x0 + (self.w - new_w) // 2
            iy = y0 + self.border_width + 2 + (icon_area_h - new_h) // 2

            # Paste with alpha mask for transparency
            if target_image is not None:
                target_image.paste(icon_resized, (ix, iy), icon_resized)
            else:
                # Fallback: paste without alpha (loses transparency)
                canvas.bitmap((ix, iy), icon_resized.convert("1"), fill=self.fg_color)

            # Small label centred at the bottom
            lx = x0 + (self.w - lw) // 2
            ly = y1 - lh - label_margin
            canvas.text((lx, ly), self.label, font=label_font, fill=self.fg_color)
        else:
            # ---- text-only: centred label ----
            bbox = self.font.getbbox(self.label)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = x0 + (self.w - tw) // 2
            ty = y0 + (self.h - th) // 2
            canvas.text((tx, ty), self.label, font=self.font, fill=self.fg_color)


# ---------------------------------------------------------------------------
# Main-menu layout: 6 buttons in a 2-column × 3-row grid
# ---------------------------------------------------------------------------

# Button labels, symbolic names, and icon filenames
MAIN_MENU_ITEMS = [
    ("PRINT",     "print",     "print.png"),
    ("MOVE UP",   "move_up",   "move_up.png"),
    ("MOVE DN",   "move_down", "move_down.png"),
    ("HOME",      "home",      "home.png"),
    ("FLOOD",     "flood",     "flood.png"),
    ("TEST",      "test",      "test.png"),
]

BTN_SIZE = 80       # pixels, square
COLS     = 2
ROWS     = 3

# Compute even spacing
_GAP_X = (SCREEN_W - COLS * BTN_SIZE) // (COLS + 1)   # ≈ 26 px
_GAP_Y = (SCREEN_H - ROWS * BTN_SIZE) // (ROWS + 1)   # 20 px


def _make_main_menu_buttons() -> list[Button]:
    """Create the six main-menu Button objects, positioned in a 2×3 grid."""
    buttons: list[Button] = []
    font = ImageFont.truetype(_DEFAULT_FONT_PATH, 14)
    label_font = ImageFont.truetype(_DEFAULT_FONT_PATH, 10)

    for idx, (label, _name, icon_file) in enumerate(MAIN_MENU_ITEMS):
        col = idx % COLS
        row = idx // COLS
        bx = _GAP_X + col * (BTN_SIZE + _GAP_X)
        by = _GAP_Y + row * (BTN_SIZE + _GAP_Y)
        icon_path = os.path.join(_ICONS_DIR, icon_file)
        buttons.append(
            Button(
                x=bx, y=by,
                w=BTN_SIZE, h=BTN_SIZE,
                label=label,
                font=font,
                icon_path=icon_path,
                label_font=label_font,
            )
        )
    return buttons


# ---------------------------------------------------------------------------
# Screen – a named collection of buttons that can be drawn & hit-tested
# ---------------------------------------------------------------------------

class Screen:
    """A UI screen: a title (optional) and a list of buttons."""

    def __init__(self, name: str, buttons: list[Button], title: str = ""):
        self.name = name
        self.buttons = buttons
        self.title = title

    def draw(self, canvas: ImageDraw.ImageDraw, image: Image.Image | None = None):
        """Clear the canvas, draw an optional title, and draw all buttons."""
        canvas.rectangle([0, 0, SCREEN_W - 1, SCREEN_H - 1], fill=(0, 0, 0))

        if self.title:
            font = ImageFont.truetype(_DEFAULT_FONT_PATH, 16)
            bbox = font.getbbox(self.title)
            tw = bbox[2] - bbox[0]
            tx = (SCREEN_W - tw) // 2
            canvas.text((tx, 6), self.title, font=font, fill=(255, 255, 255))

        for btn in self.buttons:
            btn.draw(canvas, target_image=image)

    def hit_test(self, px: int, py: int) -> Button | None:
        """Return the button at (px, py), or None."""
        for btn in self.buttons:
            if btn.contains(px, py):
                return btn
        return None


# ---------------------------------------------------------------------------
# Main menu screen
# ---------------------------------------------------------------------------

main_menu_buttons: list[Button] = _make_main_menu_buttons()
main_menu = Screen("main", main_menu_buttons)


# Convenience wrapper kept for backward compat
def draw_main_menu(canvas: ImageDraw.ImageDraw, image: Image.Image | None = None):
    main_menu.draw(canvas, image)


# ---------------------------------------------------------------------------
# Move-Up submenu: 0.1 mm, 1 mm, 10 mm, BACK
# ---------------------------------------------------------------------------

def _make_move_up_buttons() -> list[Button]:
    """4 buttons stacked vertically, centred on screen."""
    labels = ["0.1 mm", "1 mm", "10 mm", "BACK"]
    names  = ["move_0.1", "move_1", "move_10", "back"]
    btn_w, btn_h = 160, 50
    gap = 15
    total_h = len(labels) * btn_h + (len(labels) - 1) * gap
    start_y = (SCREEN_H - total_h) // 2
    start_x = (SCREEN_W - btn_w) // 2
    font = ImageFont.truetype(_DEFAULT_FONT_PATH, 18)

    buttons: list[Button] = []
    for i, (label, name) in enumerate(zip(labels, names)):
        by = start_y + i * (btn_h + gap)
        bg = (80, 40, 40) if name == "back" else (60, 60, 60)
        buttons.append(
            Button(x=start_x, y=by, w=btn_w, h=btn_h,
                   label=label, font=font, bg_color=bg)
        )
    return buttons


move_up_buttons: list[Button] = _make_move_up_buttons()
move_up_menu = Screen("move_up", move_up_buttons, title="MOVE UP")
move_down_menu = Screen("move_down", move_up_buttons, title="MOVE DOWN")  # reuse same buttons


# ---------------------------------------------------------------------------
# Print screen: list .sl1 files from /mnt, with paging
# ---------------------------------------------------------------------------

PRINT_SCAN_DIR = "/mnt"
_PRINT_BTN_W = 220
_PRINT_BTN_H = 36
_PRINT_BTN_GAP = 6
_PRINT_TITLE_H = 28            # space reserved for the title
_PRINT_BACK_H = 40             # height of BACK / nav buttons
_PRINT_NAV_GAP = 6
# How many file rows fit between the title and the bottom nav bar
_PRINT_LIST_TOP = _PRINT_TITLE_H + 4
_PRINT_NAV_BOTTOM_Y = SCREEN_H - _PRINT_BACK_H - 4
_PRINT_FILES_PER_PAGE = (_PRINT_NAV_BOTTOM_Y - _PRINT_LIST_TOP) // (_PRINT_BTN_H + _PRINT_BTN_GAP)


def _scan_sl1_files(root: str = PRINT_SCAN_DIR) -> list[str]:
    """Return sorted list of full paths to .sl1 files under *root*."""
    pattern = os.path.join(root, "**", "*.sl1")
    return sorted(glob.glob(pattern, recursive=True))


class PrintScreen(Screen):
    """Scrollable file-list screen for selecting a .sl1 file to print."""

    def __init__(self):
        super().__init__(name="print", buttons=[], title="SELECT FILE")
        self.files: list[str] = []      # full paths
        self.page = 0
        self.selected_file: str | None = None
        self._rebuild()

    # -- public API --------------------------------------------------------

    def refresh_files(self):
        """Re-scan /mnt and rebuild the button list (call before showing)."""
        self.files = _scan_sl1_files()
        self.page = 0
        self._rebuild()

    @property
    def total_pages(self) -> int:
        if not self.files:
            return 1
        return (len(self.files) + _PRINT_FILES_PER_PAGE - 1) // _PRINT_FILES_PER_PAGE

    def page_up(self):
        if self.page > 0:
            self.page -= 1
            self._rebuild()

    def page_down(self):
        if self.page < self.total_pages - 1:
            self.page += 1
            self._rebuild()

    # -- internals ---------------------------------------------------------

    def _rebuild(self):
        """Recreate the button list for the current page."""
        font = ImageFont.truetype(_DEFAULT_FONT_PATH, 13)
        nav_font = ImageFont.truetype(_DEFAULT_FONT_PATH, 14)

        buttons: list[Button] = []
        start = self.page * _PRINT_FILES_PER_PAGE
        end = start + _PRINT_FILES_PER_PAGE
        page_files = self.files[start:end]

        bx = (SCREEN_W - _PRINT_BTN_W) // 2

        for i, fpath in enumerate(page_files):
            by = _PRINT_LIST_TOP + i * (_PRINT_BTN_H + _PRINT_BTN_GAP)
            label = os.path.basename(fpath)
            # Truncate long filenames to fit the button width
            if len(label) > 26:
                label = label[:23] + "..."
            buttons.append(
                Button(x=bx, y=by, w=_PRINT_BTN_W, h=_PRINT_BTN_H,
                       label=label, font=font, bg_color=(50, 50, 70))
            )

        if not page_files:
            # Show a "no files" placeholder (not touchable, just visual)
            buttons.append(
                Button(x=bx, y=_PRINT_LIST_TOP + 20,
                       w=_PRINT_BTN_W, h=_PRINT_BTN_H,
                       label="No .sl1 files found",
                       font=font, bg_color=(40, 40, 40),
                       fg_color=(120, 120, 120))
            )

        # ── bottom navigation row: [<]  BACK  [>] ──────────────────────
        nav_y = _PRINT_NAV_BOTTOM_Y
        back_w = 100
        arrow_w = 50

        # PAGE UP  (<)
        if self.total_pages > 1:
            buttons.append(
                Button(x=4, y=nav_y, w=arrow_w, h=_PRINT_BACK_H,
                       label="<", font=nav_font, bg_color=(60, 60, 60))
            )
        # BACK (centre)
        back_x = (SCREEN_W - back_w) // 2
        buttons.append(
            Button(x=back_x, y=nav_y, w=back_w, h=_PRINT_BACK_H,
                   label="BACK", font=nav_font, bg_color=(80, 40, 40))
        )
        # PAGE DOWN  (>)
        if self.total_pages > 1:
            buttons.append(
                Button(x=SCREEN_W - arrow_w - 4, y=nav_y,
                       w=arrow_w, h=_PRINT_BACK_H,
                       label=">", font=nav_font, bg_color=(60, 60, 60))
            )

        self.buttons = buttons

    def draw(self, canvas: ImageDraw.ImageDraw, image: Image.Image | None = None):
        """Draw the screen with a page indicator in the title."""
        # Update title with page info
        if self.total_pages > 1:
            self.title = f"SELECT FILE  ({self.page + 1}/{self.total_pages})"
        else:
            self.title = "SELECT FILE"
        super().draw(canvas, image)


print_screen = PrintScreen()


# ---------------------------------------------------------------------------
# Generic confirmation screen: title + message + YES / NO buttons
# ---------------------------------------------------------------------------

class ConfirmScreen(Screen):
    """A reusable confirmation dialog with a message and YES / NO buttons.

    Set *message* and *action_name* before showing.  The caller checks
    ``confirm_screen.action_name`` to decide what to do when YES is pressed.
    """

    YES_LABEL = "YES"
    NO_LABEL  = "NO"

    def __init__(self):
        super().__init__(name="confirm", buttons=[], title="CONFIRM")
        self.message = ""           # multi-line text displayed in the centre
        self.action_name = ""       # opaque tag the caller can inspect
        self.action_data = None     # arbitrary payload (e.g. file path)
        self._rebuild()

    def configure(self, title: str, message: str,
                  action_name: str, action_data=None):
        """Prepare the dialog before showing it."""
        self.title = title
        self.message = message
        self.action_name = action_name
        self.action_data = action_data
        self._rebuild()

    def _rebuild(self):
        font = ImageFont.truetype(_DEFAULT_FONT_PATH, 14)
        btn_font = ImageFont.truetype(_DEFAULT_FONT_PATH, 18)

        btn_w, btn_h = 90, 50
        gap = 30
        total_w = 2 * btn_w + gap
        start_x = (SCREEN_W - total_w) // 2
        btn_y = SCREEN_H - btn_h - 20

        buttons = [
            Button(x=start_x, y=btn_y, w=btn_w, h=btn_h,
                   label=self.YES_LABEL, font=btn_font,
                   bg_color=(40, 100, 40)),
            Button(x=start_x + btn_w + gap, y=btn_y, w=btn_w, h=btn_h,
                   label=self.NO_LABEL, font=btn_font,
                   bg_color=(100, 40, 40)),
        ]
        self.buttons = buttons

    def draw(self, canvas: ImageDraw.ImageDraw, image: Image.Image | None = None):
        """Draw the confirmation screen with the message text."""
        # Draw title + buttons via parent
        super().draw(canvas, image)

        # Draw the message block centred between title and buttons
        if self.message:
            font = ImageFont.truetype(_DEFAULT_FONT_PATH, 13)
            lines = self.message.split("\n")
            line_h = 18
            total_text_h = len(lines) * line_h
            # vertical centre between title bar (≈30px) and buttons (btn_y)
            btn_y = self.buttons[0].y if self.buttons else SCREEN_H - 70
            text_area_top = 34
            text_area_h = btn_y - text_area_top - 10
            start_y = text_area_top + (text_area_h - total_text_h) // 2

            for i, line in enumerate(lines):
                bbox = font.getbbox(line)
                tw = bbox[2] - bbox[0]
                tx = (SCREEN_W - tw) // 2
                ty = start_y + i * line_h
                canvas.text((tx, ty), line, font=font, fill=(220, 220, 220))


confirm_screen = ConfirmScreen()

# ---------------------------------------------------------------------------
# Printing-in-progress screen
# ---------------------------------------------------------------------------

def _fmt_time(seconds: int) -> str:
    """Format seconds as HH:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


class PrintingScreen(Screen):
    """Displays live printing status: file, layer progress, and timing.

    Call ``update()`` periodically to refresh the displayed values.
    The screen has a single CANCEL button.
    """

    CANCEL_LABEL = "CANCEL"

    def __init__(self):
        super().__init__(name="printing", buttons=[], title="PRINTING")
        # ── public state – set these before / during the print ──
        self.filename: str = ""
        self.status: str = "OK"             # "OK" or "ERROR"
        self.total_layers: int = 0
        self.current_layer: int = 0
        self.start_time: float = 0.0        # time.time() when print began
        self.estimated_total: int = 0        # total estimated seconds
        self._build_buttons()

    # -- public helpers ----------------------------------------------------

    def start(self, filename: str, total_layers: int = 0,
              estimated_total: int = 0):
        """Reset state for a new print job."""
        import time as _time
        self.filename = os.path.basename(filename)
        self.status = "OK"
        self.total_layers = total_layers
        self.current_layer = 0
        self.start_time = _time.time()
        self.estimated_total = estimated_total

    def set_progress(self, current_layer: int, total_layers: int | None = None,
                     status: str | None = None):
        """Update progress (called from the print loop)."""
        self.current_layer = current_layer
        if total_layers is not None:
            self.total_layers = total_layers
        if status is not None:
            self.status = status

    # -- drawing -----------------------------------------------------------

    def _build_buttons(self):
        font = ImageFont.truetype(_DEFAULT_FONT_PATH, 16)
        btn_w, btn_h = 140, 44
        bx = (SCREEN_W - btn_w) // 2
        by = SCREEN_H - btn_h - 12
        self.buttons = [
            Button(x=bx, y=by, w=btn_w, h=btn_h,
                   label=self.CANCEL_LABEL, font=font,
                   bg_color=(120, 30, 30)),
        ]

    def draw(self, canvas: ImageDraw.ImageDraw, image: Image.Image | None = None):
        """Draw the printing status screen."""
        import time as _time

        # background + title + CANCEL button
        super().draw(canvas, image)

        font      = ImageFont.truetype(_DEFAULT_FONT_PATH, 13)
        val_font  = ImageFont.truetype(_DEFAULT_FONT_PATH, 15)
        big_font  = ImageFont.truetype(_DEFAULT_FONT_PATH, 20)

        y = 34
        lh = 22          # line height for label rows
        vlh = 26         # line height for value rows
        left = 12        # left margin
        val_x = 12       # value indent

        # ── file name ────────────────────────────────────────────────
        canvas.text((left, y), "File:", font=font, fill=(160, 160, 160))
        y += lh
        # truncate if too long
        fname = self.filename
        if len(fname) > 28:
            fname = fname[:25] + "..."
        canvas.text((val_x, y), fname, font=val_font, fill=(255, 255, 255))
        y += vlh + 4

        # ── status ───────────────────────────────────────────────────
        status_color = (0, 220, 0) if self.status == "OK" else (255, 40, 40)
        canvas.text((left, y), "Status:", font=font, fill=(160, 160, 160))
        canvas.text((left + 60, y), self.status, font=val_font, fill=status_color)
        y += vlh + 4

        # ── layer progress ───────────────────────────────────────────
        canvas.text((left, y), "Layer:", font=font, fill=(160, 160, 160))
        y += lh
        layer_str = f"{self.current_layer} / {self.total_layers}" if self.total_layers else str(self.current_layer)
        canvas.text((val_x, y), layer_str, font=big_font, fill=(255, 255, 255))
        y += vlh + 8

        # ── progress bar ─────────────────────────────────────────────
        bar_x, bar_w, bar_h = 12, SCREEN_W - 24, 14
        canvas.rectangle([bar_x, y, bar_x + bar_w, y + bar_h],
                         outline=(120, 120, 120))
        if self.total_layers > 0:
            fill_w = int(bar_w * self.current_layer / self.total_layers)
            if fill_w > 0:
                canvas.rectangle([bar_x + 1, y + 1,
                                  bar_x + fill_w - 1, y + bar_h - 1],
                                 fill=(0, 180, 0))
        y += bar_h + 10

        # ── elapsed / estimated time ─────────────────────────────────
        elapsed = int(_time.time() - self.start_time) if self.start_time else 0
        canvas.text((left, y), "Elapsed:", font=font, fill=(160, 160, 160))
        canvas.text((left + 75, y), _fmt_time(elapsed), font=val_font,
                    fill=(255, 255, 255))
        y += vlh

        canvas.text((left, y), "Est. total:", font=font, fill=(160, 160, 160))
        self.estimated_total = int(self.total_layers * elapsed / self.current_layer) if self.current_layer > 0 else 0
        est_str = _fmt_time(self.estimated_total) if self.estimated_total else "--:--:--"
        canvas.text((left + 95, y), est_str, font=val_font,
                    fill=(255, 255, 255))


printing_screen = PrintingScreen()


# ---------------------------------------------------------------------------
# Registry: look up any screen by name
# ---------------------------------------------------------------------------

screens: dict[str, Screen] = {
    "main":      main_menu,
    "move_up":   move_up_menu,
    "move_down": move_down_menu,
    "print":     print_screen,
    "confirm":   confirm_screen,
    "printing":  printing_screen,
}
