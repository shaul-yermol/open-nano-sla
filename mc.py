#!/usr/bin/env python3

# This is a motor controller module for a robot using GPIO pins to control motors.
import subprocess
import time
import argparse
import re
import os
import sys
import queue
import threading
from dataclasses import dataclass
from typing import Optional
from threading import Lock
import logging
import logging.handlers
import errno
import posix

# Configure logging with syslog
def setup_logging(log_level='INFO', use_syslog=True):
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
                fmt='mc.py[%(process)d]: %(name)s - %(levelname)s - %(message)s'
            )
            syslog_handler.setFormatter(syslog_formatter)
            root_logger.addHandler(syslog_handler)
        except Exception as e:
            # Fallback to console if syslog fails
            print(f"Warning: Could not connect to syslog, using console: {e}")
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

# Helper functions for pigpio pigs interface
def pigs_cmd(*args):
    """Execute a pigs command and return the output"""
    try:
        result = subprocess.run(['pigs'] + list(map(str, args)), 
                              capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"pigs command failed: {' '.join(map(str, args))}, error: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"pigs command exception: {e}")
        return None

def gpio_write(pin, value):
    """Write to a GPIO pin using pigs (w command)"""
    return pigs_cmd('w', pin, 1 if value else 0)

def gpio_read(pin):
    """Read from a GPIO pin using pigs (r command)"""
    result = pigs_cmd('r', pin)
    return int(result) if result is not None else None

def gpio_mode(pin, mode):
    """Set GPIO pin mode using pigs (m command)
    mode: 'r' for read/input, 'w' for write/output
    """
    return pigs_cmd('m', pin, mode)

# Define GPIO pins for motor control (BCM numbering)
MOTOR_DIR_PIN = 22
MOTOR_STP_PIN = 23
MOTOR_EN_PIN = 24

# Define endstop pins (BCM numbering)
TOP_ENDSTOP_PIN = 25
BOTTOM_ENDSTOP_PIN = 13

#Define GPIO pins for UV light control (BCM numbering)
UV_LIGHT_PIN = 26

# Define directions
directions = ["u", "d"]

#define physical parameters
revolution_mm = 2.0                         # 2mm per revolution
microstepping = 1.0                         # 1/1
full_steps_per_rev = 200.0 * microstepping  # Full steps per revolution for the stepper motor

# Initialize GPIO pins using pigs
def init_gpio():
    """Initialize GPIO pins for motor control, endstops, and UV light"""
    logger.info("Initializing GPIO pins with pigpio...")
    
    # Set motor control pins as outputs
    gpio_mode(MOTOR_DIR_PIN, 'w')
    gpio_mode(MOTOR_STP_PIN, 'w')
    gpio_mode(MOTOR_EN_PIN, 'w')
    
    # Set endstop pins as inputs with pull-up
    gpio_mode(TOP_ENDSTOP_PIN, 'r')
    gpio_mode(BOTTOM_ENDSTOP_PIN, 'r')
    pigs_cmd('pud', TOP_ENDSTOP_PIN, 'u')     # Set pull-up
    pigs_cmd('pud', BOTTOM_ENDSTOP_PIN, 'u')  # Set pull-up
    
    # Set UV light pin as output
    gpio_mode(UV_LIGHT_PIN, 'w')
    
    # Initialize pin states
    gpio_write(MOTOR_DIR_PIN, 0)  # Direction low
    gpio_write(MOTOR_STP_PIN, 0)  # Step low
    gpio_write(MOTOR_EN_PIN, 1)   # Motor disabled (active low)
    gpio_write(UV_LIGHT_PIN, 0)   # UV light off
    
    logger.info("GPIO initialization complete")

# Initialize GPIO on module load
init_gpio()

# Data class for G-code commands
@dataclass
class GCodeCommand:
    line: str
    line_number: int
    timestamp: float

# Global variables
status_pipe = None
g_gcode_queue = queue.Queue()
g_stop_threads = threading.Event()
g_pause_execution = threading.Event()
g_immediate_stop = threading.Event()

def init_status_pipe(pipe_path):
    """Initialize the status output pipe"""
    global status_pipe
    logger.info(f"Initializing status output pipe: {pipe_path}")
    if pipe_path:
        try:
            # Create the named pipe if it doesn't exist
            if not os.path.exists(pipe_path):
                os.mkfifo(pipe_path)
                os.chmod(pipe_path, 0o666)
                logger.info(f"Created status output pipe: {pipe_path}")
            status_pipe = pipe_path
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize status pipe {pipe_path}: {e}")
            status_pipe = None
            return False
    return False

def write_status(message):
    """Write status message to output pipe if available"""
    global status_pipe
    if status_pipe:
        try:
            pipe = posix.open(status_pipe, posix.O_RDWR)
            # write to pipe
            logger.debug(f"Writing to status pipe: {message}")
            os.write(pipe, f"{message}\n".encode())
            os.close(pipe)
        except Exception as e:
            logger.warning(f"Failed to write to status pipe: {e}")
            # Try to reinitialize the pipe
            status_pipe = None

def parse_gcode(gcode_line):
    """Parse a G-code line and extract command and parameters"""
    # Remove whitespace and convert to uppercase
    gcode_line = gcode_line.strip().upper()
    
    # Extract command (G0, G1, etc.)
    command_match = re.match(r'^([GM]\d+)', gcode_line)
    if not command_match:
        return None, {}
    
    command = command_match.group(1)
    
    # Extract parameters (X, Y, Z, F, etc.)
    params_line = gcode_line[len(command):].strip()
    params = {}
    param_pattern = r'([A-Z])(-?\d*\.?\d+)'
    matches = re.findall(param_pattern, params_line)

    for param, value in matches:
        try:
            # Try to convert to float, fallback to int if no decimal
            if '.' in value:
                params[param] = float(value)
            else:
                params[param] = int(value)
        except ValueError:
            params[param] = value
    
    return command, params

def execute_gcode(gcode_line, default_speed=500):
    """Execute a G-code command"""
    command, params = parse_gcode(gcode_line)
    
    if not command:
        logger.error(f"Invalid G-code: {gcode_line}")
        write_status("ERROR")
        return False
    
    logger.info(f"Executing G-code: {gcode_line}")
    logger.debug(f"Command: {command}, Parameters: {params}")
    write_status(f"EXEC:{gcode_line}")

    success = False

    if 'F' in params:
        speed = params['F']
    else:
        speed = default_speed

    # Extract Z parameter for vertical movement
    if 'Z' in params:
        z_pos = params['Z']
    else:
        z_pos = None
    
    if command in ['G0', 'G1']:  # Linear move (rapid or controlled)
        if z_pos is not None:
            
            # Convert Z position to steps (assuming current position is 0)
            # For now, we'll treat Z as relative movement in mm
            z_mm = float(z_pos)
            z_steps = round(abs(z_mm) * (full_steps_per_rev / revolution_mm))
            logger.debug(f"Z movement: {z_mm}mm -> {z_steps} steps at full_steps_per_rev {full_steps_per_rev}, revolution_mm {revolution_mm}")
            # Determine direction
            direction = "u" if z_mm > 0 else "d"

            logger.info(f"Moving Z-axis: {z_mm}mm ({z_steps} steps) in direction '{direction}' at speed {speed}us")
            
            # Execute movement with endstop protection
            steps_moved = move_motor(direction, z_steps, int(speed), use_endstops=True, disable_at_end=False)
            write_status(f"MOVE_COMPLETE:{direction}:{z_mm}mm:{steps_moved}steps")
            
            success = True
        else:
            logger.warning("No Z parameter found in G-code command")
            success = False
    
    elif command == 'G28' or command == 'G27':  # Home command or Park toolhead
        axis = params.get('Z', None)
        all_axis = params.get('X', None) is None and params.get('Y', None) is None

        if axis is not None or all_axis:  # G28 Z or G28 (home all)
            logger.info("Homing Z-axis...")
            if (command == 'G27'):
                direction = 'u'
            if (command == 'G28'):
                direction = 'd'
            logger.info(f"Homing direction: {direction}, speed: {speed}")
            home_motor(speed, direction)
            write_status(f"HOME_COMPLETE:{direction}")
            success = True
        else:
            logger.warning("G28: Only Z-axis homing supported")
            success = False
    
    elif command == 'M17':  # Enable motors
        logger.info("Enabling motor...")
        gpio_write(MOTOR_EN_PIN, 0)  # Active low
        write_status("MOTOR_ENABLED")
        success = True
    
    elif command == 'M18' or command == 'M84':  # Disable motors
        logger.info("Disabling motor...")
        gpio_write(MOTOR_EN_PIN, 1)  # Active low
        write_status("MOTOR_DISABLED")
        success = True

    elif command == 'G4':  # Dwell
        if 'P' in params:
            dwell_time = params['P'] / 1000.0  # Convert milliseconds to seconds
            logger.info(f"Dwelling for {dwell_time} seconds...")
            for i in range(int(dwell_time * 10)):
                if g_immediate_stop.is_set():
                    logger.warning("Immediate stop requested during dwell")
                    break
                time.sleep(0.1)
            success = True
        else:
            logger.error("G4: Missing P parameter for dwell time")
            success = False
    
    elif command == 'M3' or command == 'M4':  # UV light on
        gpio_write(UV_LIGHT_PIN, 1)
        logger.info("UV light turned ON")
        write_status("UV_ON")
        success = True

    elif command == 'M5':  # UV light off
        gpio_write(UV_LIGHT_PIN, 0)
        logger.info("UV light turned OFF")
        write_status("UV_OFF")
        success = True

    elif command == 'M119':  # Report endstop status
        top_state = "TRIGGERED" if top_triggered() else "OPEN"
        bottom_state = "TRIGGERED" if bottom_triggered() else "OPEN"
        logger.info(f"Top endstop (GPIO{TOP_ENDSTOP_PIN}): {top_state}")
        logger.info(f"Bottom endstop (GPIO{BOTTOM_ENDSTOP_PIN}): {bottom_state}")
        write_status(f"ENDSTOPS:TOP={top_state},BOTTOM={bottom_state}")
        success = True

    else:
        logger.error(f"Unsupported G-code command: {command}")
        write_status("ERROR: UNSUPPORTED_COMMAND")
        success = False
    
    # Report final execution status
    if success:
        write_status("OK")
    else:
        write_status("ERROR")
    
    return success


def top_triggered() -> bool:
    """Check if the top endstop is triggered"""
    # Active low: triggered when the pin reads low (0)
    value = gpio_read(TOP_ENDSTOP_PIN)
    return value == 0 if value is not None else False

def bottom_triggered() -> bool:
    """Check if the bottom endstop is triggered"""
    # Active low: triggered when the pin reads low (0)
    value = gpio_read(BOTTOM_ENDSTOP_PIN)
    return value == 0 if value is not None else False

def check_endstops():
    """Check and print current endstop states"""
    top_state = "TRIGGERED" if top_triggered() else "OPEN"
    bottom_state = "TRIGGERED" if bottom_triggered() else "OPEN"
    logger.info(f"Top endstop (GPIO{TOP_ENDSTOP_PIN}): {top_state}")
    logger.info(f"Bottom endstop (GPIO{BOTTOM_ENDSTOP_PIN}): {bottom_state}")
    return top_triggered(), bottom_triggered()

def home_motor(speed=500, direction="d"):

    disable_at_end = True

    """Home the motor by moving to bottom endstop"""
    logger.info(f"Homing motor to {direction} endstop...")
    steps_moved = move_motor(direction, 999999, speed, disable_at_end)  # Move until endstop
    logger.info(f"Motor homed to {direction} endstop after {steps_moved} steps.")

    slow_speed = speed * 1

    # Move up a bit in opposite direction to avoid constant endstop triggering
    if direction == "d":
        steps_moved = move_motor("u", int(full_steps_per_rev), slow_speed, disable_at_end)
    else:
        steps_moved = move_motor("d", int(full_steps_per_rev), slow_speed, disable_at_end)

    time.sleep(0.25)
    # Move slowly again to re-engage endstop
    steps_moved = move_motor(direction, int(1.1 * full_steps_per_rev), slow_speed, disable_at_end)

    time.sleep(0.25)

    if direction == "d":
        steps_moved = move_motor("u", int(full_steps_per_rev), slow_speed, disable_at_end)
    else:
        steps_moved = move_motor("d", int(full_steps_per_rev), slow_speed, disable_at_end)

    time.sleep(0.25)
    # Move slowly again to re-engage endstop
    steps_moved = move_motor(direction, int(1.1 * full_steps_per_rev), slow_speed, disable_at_end)

    time.sleep(0.25)

    logger.info(f"Homing complete. Motor position is now at {direction} endstop.")
    return steps_moved

def move_motor(direction, steps, speed, use_endstops, disable_at_end=False):

    _top_triggered = top_triggered()
    _bottom_triggered = bottom_triggered()

    steps_moved = 0

    # Set motor direction
    if direction == "u":
        gpio_write(MOTOR_DIR_PIN, 0)
        endstop = TOP_ENDSTOP_PIN
    else:
        gpio_write(MOTOR_DIR_PIN, 1)
        endstop = BOTTOM_ENDSTOP_PIN

    # Enable motor (active low)
    gpio_write(MOTOR_EN_PIN, 0)

    proc_command = f"proc tag 123 w {MOTOR_STP_PIN} 1 mics {speed} w {MOTOR_STP_PIN} 0 mics {speed} r {endstop} jnz 321 dcr p0 jnz 123 tag 321"
    proc_id = pigs_cmd(proc_command)
    pigs_cmd('procr', proc_id, steps)  # Run procedure

    while True:
        time.sleep(0.1)  # Sleep briefly to avoid busy waiting
        procp = pigs_cmd('procp', proc_id).split()  # Check procedure status
        if g_immediate_stop.is_set():
            logger.warning("Immediate stop requested")
            pigs_cmd('procs', proc_id)  # Stop procedure
            break        
        if len(procp) < 11:
            logger.error("Failed to get procedure status")
            break
        status = procp[0]
        steps_remaining = int(procp[1])
        logger.debug(f"Procedure status: {status}, steps remaining: {steps_remaining}")
        if status != '2':
            steps_moved = steps - steps_remaining
            logger.debug(f"Steps moved so far: {steps_moved}")
            break

    pigs_cmd('procd', proc_id)  # Delete procedure

    # Disable motor (active low)
    if disable_at_end:
        gpio_write(MOTOR_EN_PIN, 1)
    
    if steps_moved == steps:
        logger.info(f"Moved {direction} for {steps} steps at speed {speed}us")
    else:
        logger.info(f"Movement stopped early at {steps_moved}/{steps} steps due to endstop")
    
    return steps_moved

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

def read_gcode_from_pipe(pipe_path="/tmp/mcin"):
    """Read G-code commands from named pipe and add them to the queue"""
    logger.info(f"Reading G-code from named pipe: {pipe_path}")
    
    line_number = 1
    
    try:
        # Open the named pipe for reading
        while not g_stop_threads.is_set():
            with open(pipe_path, 'r') as pipe:
                try:
                    logger.debug("Waiting for G-code command...")
                    # Read line from pipe (blocking)
                    line = pipe.readline()
                    
                    # If readline returns empty string, pipe was closed by writer
                    if not line:
                        logger.debug("Pipe closed by writer, reopening...")
                        continue
                    
                    line = line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith(';') or line.startswith('#'):
                        continue
                    
                    logger.info(f"Received G-code[{line_number}]: {line}")
                    
                    # Create command object and add to queue
                    command = GCodeCommand(
                        line=line,
                        line_number=line_number,
                        timestamp=time.time()
                    )
                    g_gcode_queue.put(command)
                    # write_status(f"QUEUED:{line}")
                    
                    line_number += 1
                    
                except KeyboardInterrupt:
                    logger.info("Stopping G-code pipe reader...")
                    break
                    
    except Exception as e:
        logger.error(f"Error reading G-code from pipe {pipe_path}: {e}")
    
    logger.info("G-code pipe reader stopped.")

def process_gcode_queue(default_speed=500):
    """Process G-code commands from the queue"""
    logger.info("Starting G-code queue processor...")
    
    while not g_stop_threads.is_set():
        try:
            # Get command from queue with timeout
            try:
                command = g_gcode_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            logger.info(f"Processing G-code[{command.line_number}]: {command.line} (queue size: {g_gcode_queue.qsize()})")
            
            # Execute the G-code command
            success = execute_gcode(command.line, default_speed)
            
            if success:
                logger.info(f"✓ Line {command.line_number}: Command executed successfully")
            else:
                logger.error(f"✗ Line {command.line_number}: Command failed")

            logger.debug(f"Queue size after processing: {g_gcode_queue.qsize()}")

        except KeyboardInterrupt:
            logger.info("Stopping G-code queue processor...")
            break
        except Exception as e:
            logger.error(f"Error processing G-code command: {e}")
            # Still mark task as done to prevent queue from hanging
            try:
                g_gcode_queue.task_done()
            except ValueError:
                pass  # task_done() called too many times

    logger.info("G-code queue processor stopped.")

def get_queue_status():
    """Get current queue status"""
    return {
        'queue_size': g_gcode_queue.qsize(),
        'threads_stopped': g_stop_threads.is_set()
    }

def execute_gcode_from_pipe_with_queue(pipe_path="/tmp/mcin", default_speed=500):
    """Start both pipe reader and queue processor threads"""
    logger.info("Starting G-code service with queue...")
    logger.info("Send G-code commands to the pipe using: echo 'G1 Z10' > /tmp/mcin")
    logger.info("Press Ctrl+C to stop the service")
    
    # Reset stop event
    g_stop_threads.clear()
    
    # Start reader thread
    reader_thread = threading.Thread(
        target=read_gcode_from_pipe,
        args=(pipe_path,),
        daemon=True
    )
    
    # Start processor thread  
    processor_thread = threading.Thread(
        target=process_gcode_queue,
        args=(default_speed,),
        daemon=True
    )
    
    try:
        reader_thread.start()
        processor_thread.start()
        
        logger.info("G-code service threads started")
        
        # Wait for threads to finish or keyboard interrupt
        while reader_thread.is_alive() or processor_thread.is_alive():
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        logger.info("Shutting down G-code service...")
        g_stop_threads.set()
        
        # Wait for threads to finish
        reader_thread.join(timeout=2.0)
        processor_thread.join(timeout=2.0)
        
        logger.info("G-code service stopped.")

if __name__ == "__main__":
    # parser for command line arguments
    parser = argparse.ArgumentParser(description="Motor Controller with Endstop Support")
    parser.add_argument("-t", "--time", type=int, default=500, help="Delay between steps (in microseconds)")
    parser.add_argument("--check", action="store_true", help="Check endstop status")
    parser.add_argument("--home", action="store_true", help="Home motor to bottom endstop")
    parser.add_argument("--unhome", action="store_true", help="Unhome motor by moving up a bit")
    parser.add_argument("--pipe", action="store_true", help="Create named pipe /tmp/mcin and read G-code commands from it (uses queue system)")
    parser.add_argument("--pipe-path", type=str, default="/tmp/mcin", help="Path for the named pipe (default: /tmp/mcin)")
    parser.add_argument("--status-pipe", type=str, default="/tmp/mcout", help="Path for the status output pipe (default: /tmp/mcout)")
    parser.add_argument("--log-level", type=str, default="INFO", 
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="Set the logging level (default: INFO)")
    parser.add_argument("--use-console", action="store_true", 
                        help="Use console logging instead of syslog")
    args = parser.parse_args()

    # Configure logging with the specified level (use syslog by default)
    use_syslog = not args.use_console
    logger = setup_logging(args.log_level, use_syslog)
    
    # Log startup information
    logger.info("=" * 50)
    logger.info("Motor Controller Starting Up")
    logger.info(f"Log level: {args.log_level}")
    logger.info(f"Logging to: {'syslog' if use_syslog else 'console'}")
    logger.info(f"Status pipe: {args.status_pipe}")
    if hasattr(args, 'pipe_path'):
        logger.info(f"Input pipe: {args.pipe_path}")
    logger.info("=" * 50)

    # Initialize status output pipe
    init_status_pipe(args.status_pipe)

    if args.check:
        check_endstops()
        write_status("OK")
    elif args.home:
        home_motor(args.time)
        write_status("OK") 
    elif args.unhome:
        home_motor(args.time, "u")
        write_status("OK")
    elif args.pipe:
        # Create the named pipe and start service
        if not create_named_pipe(args.pipe_path):
            logger.error("Failed to create named pipe.")
            exit(-1)
        try:
            execute_gcode_from_pipe_with_queue(args.pipe_path, args.time)
        except Exception as e:
            logger.error(f"Error running G-code service: {e}")
        finally:
            # Clean up: remove the named pipes
            if os.path.exists(args.pipe_path):
                os.unlink(args.pipe_path)
                logger.info(f"Removed named pipe: {args.pipe_path}")
            
            # Close status pipe
            if status_pipe:
                status_pipe.close()
    else:
        parser.print_help()
    
    # Final cleanup - close status pipe if still open
    if status_pipe:
        status_pipe.close()