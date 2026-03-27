import json
import os
import sys
import time
import select
import busio
import digitalio
from board import SCK, MOSI, MISO, D8, D7, D1, D2
import subprocess
import zipfile

from gpiozero import Button as GpioButton

from adafruit_rgb_display import color565
import adafruit_rgb_display.ili9341 as ili9341

from PIL import Image, ImageDraw, ImageFont

from xpt2046 import Touch
from ui import screens, Screen, SCREEN_W, SCREEN_H, print_screen, confirm_screen, printing_screen

import logging
import logging.handlers

# Configure logging with syslog
def setup_logging(log_level='DEBUG', use_syslog=True):
    """Setup logging configuration with syslog support"""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Get root logger and set level
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    if use_syslog:
        # Create syslog handler
        try:
            syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
            # Set format for syslog (no timestamp needed, syslog adds it)
            syslog_formatter = logging.Formatter(
                fmt='display.py[%(process)d]: %(name)s - %(levelname)s - %(message)s'
            )
            syslog_handler.setFormatter(syslog_formatter)
            root_logger.addHandler(syslog_handler)
        except Exception as e:
            # Fallback to console if syslog fails
            logger.warning(f"Could not connect to syslog, using console: {e}")
            use_syslog = False
    
    if not use_syslog:
        # Create console handler as fallback
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)8s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)

# Initialize logger (will be reconfigured in main if needed)
logger = setup_logging()


# ── Load touch calibration (if available) ────────────────────────────────
_CAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "touch_cal.json")
_touch_cal = {}
if os.path.isfile(_CAL_FILE):
    with open(_CAL_FILE) as f:
        _touch_cal = json.load(f)
    logger.info(f"Loaded touch calibration: {_touch_cal}")
else:
    logger.warning("No touch_cal.json found – using defaults.  Run touch-test.py to calibrate.")


# ── SPI bus ──────────────────────────────────────────────────────────────
spi = busio.SPI(clock=SCK, MOSI=MOSI, MISO=MISO)

# ── Display (ILI9341) ───────────────────────────────────────────────────
DISPLAY_CS = D8
DC_PIN = D1

disp = ili9341.ILI9341(spi, cs=digitalio.DigitalInOut(DISPLAY_CS),
                          dc=digitalio.DigitalInOut(DC_PIN))

width = disp.width
height = disp.height
image = Image.new("RGB", (SCREEN_W, SCREEN_H))
draw = ImageDraw.Draw(image)

rotation = 180

# ── Touch controller (XPT2046, shares SPI, separate CS on D7) ───────────
touch_cs = digitalio.DigitalInOut(D7)
touch_irq = GpioButton(3, bounce_time = 0.15)           # GPIO3 interrupt pin


# ── Screen navigation ────────────────────────────────────────────────────
current_screen: Screen = screens["main"]


def show_screen(name: str):
    """Switch to a different screen and refresh the display."""
    global current_screen
    if name == "print":
        print_screen.refresh_files()
    current_screen = screens[name]
    current_screen.draw(draw, image)
    disp.image(image, rotation)

def on_move(distance_mm: float):
    """Return a function that moves the Z axis by the given distance."""
    logging.info(f"Moving Z by {distance_mm} mm")

flood_state = False
test_state = False

def on_led(led_name: str):
    """Toggle the given LED."""
    global flood_state, test_state
    if led_name == "FLOOD":
        flood_state = not flood_state
        logging.info(f"Toggling LED: {led_name} to {'ON' if flood_state else 'OFF'}")
    elif led_name == "TEST":
        test_state = not test_state
        logging.info(f"Toggling LED: {led_name} to {'ON' if test_state else 'OFF'}")

def on_print(file_path: str) -> bool:
    """Start printing the given file."""
    logging.info(f"Starting print job: {file_path}")
   
    # Verify the file exists before attempting to print
    if not os.path.isfile(file_path):
        logging.error(f"File not found: {file_path}")
        return False
    
    # verify the file has a .sl1 extension
    if not file_path.lower().endswith('.sl1'):
        logging.error(f"Invalid file type (expected .sl1): {file_path}")
        return False

    try:

        # Get the filename without path and extension for display/logging purposes
        filename = os.path.basename(file_path)
        logging.info(f"Preparing to print file: {filename}")

        # Unzip the file if it's a .sl1 archive:        
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            # Extract to /tmp/ + filename without extension
            extract_path = os.path.join("/tmp", os.path.splitext(filename)[0])
            zip_ref.extractall(extract_path)
            logging.info(f"Extracted {filename} to {extract_path}")
        
        # run print.py in a subprocess and continue immediately (print.py will communicate back via the UI pipe)
        subprocess.Popen(["python3", "print.py", "--log-level=DEBUG", "--dry-run", extract_path])
        logging.info(f"Started print.py subprocess for: {extract_path}")

        # subprocess.run(["path/to/printer_command", file_path])
        # For this example, we'll just log the action.
        logging.info(f"Print command executed for: {file_path}")
    
    except zipfile.BadZipFile:
        logging.error(f"File is not a valid zip archive: {file_path}")
        return False
    except Exception as e:
        logging.error(f"Error starting print job for {file_path}: {e}")
        return False

    return True

# ── Confirmation helpers ─────────────────────────────────────────────────

def _show_confirm(title: str, message: str, action_name: str,
                  action_data=None):
    """Configure and show the generic confirmation screen."""
    confirm_screen.configure(title, message, action_name, action_data)
    show_screen("confirm")

def _on_confirm_yes():
    """Dispatch based on what the confirm screen was shown for."""
    name = confirm_screen.action_name
    data = confirm_screen.action_data
    if name == "print_file":
        logging.info(f"Starting print: {data}")
        printing_screen.start(filename=data)
        if on_print(data):
            show_screen("printing")
        else:
            show_screen("main")
    elif name == "flood":
        on_led("FLOOD")
        show_screen("main")
    elif name == "test":
        on_led("TEST")
        show_screen("main")
    else:
        logging.warning(f"Unknown confirm action: {name}")
        show_screen("main")

def _on_confirm_no():
    """Return to the screen that triggered the confirmation."""
    name = confirm_screen.action_name
    if name == "print_file":
        show_screen("print")
    else:
        show_screen("main")

# ── Button-action mapping ────────────────────────────────────────────────
#  Maps (screen_name, button_label) → action.
#  An action can be a screen name (str) to navigate to,
#  or a callable for future functionality.

def _print_page_up():
    print_screen.page_up()
    print_screen.draw(draw, image)
    disp.image(image, rotation)

def _print_page_down():
    print_screen.page_down()
    print_screen.draw(draw, image)
    disp.image(image, rotation)

def _on_file_selected(filename: str):
    """Called when the user taps a .sl1 filename on the print screen."""
    for fpath in print_screen.files:
        if os.path.basename(fpath) == filename or filename in os.path.basename(fpath):
            print_screen.selected_file = fpath
            break
    _show_confirm(
        title="PRINT",
        message=f"Start printing?\n\n{filename}",
        action_name="print_file",
        action_data=print_screen.selected_file,
    )

BUTTON_ACTIONS = {
    ("main",    "MOVE UP"):  "move_up",
    ("main",    "MOVE DN"):  "move_down",

    ("main",    "FLOOD"):    lambda: _show_confirm("FLOOD", "Turn flood light\nON/OFF?", "flood"),
    ("main",    "TEST"):     lambda: _show_confirm("TEST", "Turn test light\nON/OFF?", "test"),

    ("main",    "PRINT"):    "print",

    ("move_up", "0.1 mm"):   lambda: on_move(0.1),
    ("move_up", "1 mm"):     lambda: on_move(1.0),
    ("move_up", "10 mm"):    lambda: on_move(10.0),
    ("move_up", "BACK"):     "main",

    ("move_down", "0.1 mm"): lambda: on_move(-0.1),
    ("move_down", "1 mm"):   lambda: on_move(-1.0),
    ("move_down", "10 mm"):  lambda: on_move(-10.0),
    ("move_down", "BACK"):   "main",

    ("print",   "BACK"):     "main",
    ("print",   "<"):        _print_page_up,
    ("print",   ">"):        _print_page_down,

    ("confirm", "YES"):      _on_confirm_yes,
    ("confirm", "NO"):       _on_confirm_no,

    ("printing", "CANCEL"):  "main",
}


def on_touch(x, y):
    """Handle a touch event – map to screen coordinates and check buttons."""
    logging.debug(f"Touch coordinates: ({x}, {y})")

    x = SCREEN_W - 1 - x
    # y axis does not need flipping
    btn = current_screen.hit_test(x, y)
    if btn:
        print(f"[{current_screen.name}] Button pressed: {btn.label} (touch @ {x},{y})")
        action = BUTTON_ACTIONS.get((current_screen.name, btn.label))
        if isinstance(action, str):
            show_screen(action)
        elif callable(action):
            action()
        elif current_screen.name == "print" and btn.label not in ("BACK", "<", ">", "No .sl1 files found"):
            # Dynamic file button on the print screen
            _on_file_selected(btn.label)
    else:
        print(f"Touch @ {x},{y} – no button")


xpt = Touch(spi, cs=touch_cs, int_pin=touch_irq, int_handler=on_touch,
            **{k: v for k, v in _touch_cal.items()
               if k in ("x_min", "x_max", "y_min", "y_max")})

# ── UI command pipes (print.py → display.py) ────────────────────────────
UI_CONTROL_PIPE = '/tmp/uiin'
UI_STATUS_PIPE  = '/tmp/uiout'

def create_named_pipe(pipe_path="/tmp/mcin"):
    """Create a named pipe (FIFO) for G-code input"""
    try:
        # Remove existing pipe if it exists
        if os.path.exists(pipe_path):
            os.unlink(pipe_path)
        
        # Create named pipe
        os.mkfifo(pipe_path)
        logger.info(f"Created named pipe: {pipe_path}")
        
        # Set permissions so other processes can write to it
        os.chmod(pipe_path, 0o666)
        
        return True
    except Exception as e:
        logger.error(f"Error creating named pipe {pipe_path}: {e}")
        return False

create_named_pipe(UI_CONTROL_PIPE)
create_named_pipe(UI_STATUS_PIPE)

def _handle_ui_command(line: str):
    """Process one command received from print.py via the UI pipe."""
    line = line.strip()
    logging.debug(f"Received UI command: {line}")
    if not line:
        return

    parts = line.split()
    cmd = parts[0]

    if cmd == "LAYER" and len(parts) >= 3:
        current = int(parts[1])
        total = int(parts[2])
        logging.info(f"UI: layer {current}/{total}")
        printing_screen.set_progress(current_layer=current, total_layers=total)
        # Refresh screen if printing screen is active
        printing_screen.draw(draw, image)
        disp.image(image, rotation)
        _ui_respond("OK")

    elif cmd == "DONE":
        logging.info("UI: print done")
        printing_screen.set_progress(
            current_layer=printing_screen.total_layers,
            status="DONE")
        printing_screen.draw(draw, image)
        disp.image(image, rotation)
        _ui_respond("OK")

    else:
        logging.warning(f"UI: unknown command: {line}")
        _ui_respond("ERROR unknown command")


def _ui_respond(msg: str):
    """Write a response to the UI status pipe."""
    try:
        with open(UI_STATUS_PIPE, 'w') as f:
            f.write(msg + '\n')
    except Exception as e:
        logging.error(f"Failed to write UI status pipe: {e}")


# ── Draw the initial screen and push to the display ─────────────────────
show_screen("main")

# ── Main loop: poll the UI pipe for commands ─────────────────────────────
while True:
    try:
        # Open pipe in non-blocking read mode
        fd = os.open(UI_CONTROL_PIPE, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'r') as pipe:
            rlist, _, _ = select.select([pipe], [], [], 1.0)  # timeout of 1 second
            if rlist:
                logging.debug("UI pipe has data to read")
                for line in pipe:
                    _handle_ui_command(line)
    except OSError:
        # No writer on the pipe yet – that's fine
        continue
    except Exception as e:
        logging.error(f"Error reading UI pipe: {e}")
        continue

