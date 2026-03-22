#!/usr/bin/env python3
import os
import sys
import json
import time
import glob
import subprocess
import struct
import numpy as np
from PIL import Image
import logging
import logging.handlers
import select
import signal

mc_control_pipe = '/tmp/mcin'
mc_status_pipe = '/tmp/mcout'

ui_control_pipe = '/tmp/uiin'
ui_status_pipe = '/tmp/uiout'


raise_Z_amount = 10

# Configure logging with syslog
def setup_logging(log_level='INFO', use_syslog=True):
    """Setup logging configuration with syslog support"""
    numeric_level = getattr(logging, log_level.upper(), logging.DEBUG)
    
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
                fmt='print.py[%(process)d]: %(name)s - %(levelname)s - %(message)s'
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
        root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)

# Initialize logger (will be reconfigured in main if needed)
logger = setup_logging()

# Global flag for graceful shutdown
shutdown_requested = False

def cleanup() -> None:
	"""Cleanup function to turn off UV light and disable motor"""
	logger.info("Performing cleanup...")
	try:
		# Turn off UV light
		logger.info("Turning off UV light...")
		send_gcode('M5')
		time.sleep(0.5)  # Ensure UV is fully off
		
		# Kill any fbi processes
		subprocess.run(['sudo', 'pkill', 'fbi'], check=False)
		
		# Disable motor
		logger.info("Disabling motor...")
		send_gcode('M18')
		
		logger.info("Cleanup complete.")
	except Exception as e:
		logger.error(f"Error during cleanup: {e}")

def signal_handler(signum, frame):
	"""Handle interrupt signals for graceful shutdown"""
	global shutdown_requested
	
	signal_name = signal.Signals(signum).name
	logger.warning(f"Received signal {signal_name} ({signum}), initiating graceful shutdown...")
	
	shutdown_requested = True
	cleanup()
	
	logger.info("Exiting...")
	sys.exit(-1 * signum)

def send_gcode(command, timeout=60):
	"""Send G-code command to mc.py and wait for response"""
	logger.debug(f"Sending G-code command: {command}")
	with open(mc_control_pipe, 'w') as pipe:
		pipe.write(command + '\n')
	start = time.time()
	while time.time() - start < timeout:
		try:
			with open(mc_status_pipe, 'r') as status:
				logger.debug("Opened status pipe for reading")
				logger.debug("Waiting for response from mc.py...")
				rlist,wlist,xlist = select.select([status], [], [], 1)
				logger.debug(f"Select result: {rlist}")
				if not rlist:
					continue
				logger.debug("Response available, reading...")
				while line := status.readline():
					logger.debug(f"Received from mc.py: {line}")
					if 'ERROR' in line:
						return False
					if 'OK' in line:
						return True
				status.close()
				continue
		except Exception as e:
			logger.debug("Exception reading status pipe: " + str(e))
			time.sleep(1)
			continue
	return False

def send_ui(command, timeout=1):
	"""Send a command to display.py via UI pipe.

	Uses the same protocol as send_gcode but with a short timeout
	since the UI is non-critical.  Returns True on OK, False otherwise.
	Failures are logged but never abort the print.
	"""
	try:
		logger.debug(f"Sending UI command: {command}")
		with open(ui_control_pipe, 'w') as pipe:
			pipe.write(command + '\n')
		start = time.time()
		while time.time() - start < timeout:
			try:
				with open(ui_status_pipe, 'r') as status:
					rlist, _, _ = select.select([status], [], [], 0.5)
					if not rlist:
						continue
					while line := status.readline():
						logger.debug(f"Received from UI: {line.strip()}")
						if 'OK' in line:
							return True
						if 'ERROR' in line:
							return False
					continue
			except Exception as e:
				logger.debug(f"Exception reading UI status pipe: {e}")
				break
	except Exception as e:
		logger.debug(f"Failed to send UI command: {e}")
	return False

def get_png_dimensions(image_path):
	"""Get PNG dimensions by reading only the header, without loading full image"""
	try:
		with open(image_path, 'rb') as f:
			# Check PNG signature (first 8 bytes)
			signature = f.read(8)
			if signature != b'\x89PNG\r\n\x1a\n':
				return None, None, f"Not a valid PNG file"
			
			# Read IHDR chunk (next 25 bytes: 4 length + 4 type + 13 data + 4 crc)
			length_bytes = f.read(4)
			chunk_type = f.read(4)
			
			if chunk_type != b'IHDR':
				return None, None, f"Invalid PNG header"
			
			# Read width and height (first 8 bytes of IHDR data)
			width_bytes = f.read(4)
			height_bytes = f.read(4)
			
			width = struct.unpack('>I', width_bytes)[0]  # Big endian unsigned int
			height = struct.unpack('>I', height_bytes)[0]
			
			return width, height, None
			
	except Exception as e:
		return None, None, f"Error reading PNG header: {e}"

def grayscale_to_rgb_channels(input_path, output_path):
	"""
	Convert a grayscale image (stored in RGB format) to an RGB image where
	each R, G, B channel corresponds to consecutive pixels from the original image.
	"""
	try:
		# Load the image
		with Image.open(input_path) as img:
			# Convert to RGB if not already
			if img.mode != 'RGB':
				img = img.convert('RGB')
			
			# Convert to numpy array
			img_array = np.array(img)
			height, width, channels = img_array.shape
			
			# Since it's grayscale in RGB format, we can just take the red channel
			# (all channels should be the same for grayscale)
			grayscale_data = img_array[:, :, 0].flatten()
			
			# Calculate new dimensions
			# We need to group every 3 pixels into RGB channels
			total_pixels = len(grayscale_data)
			rgb_pixels = total_pixels // 3
			
			if total_pixels % 3 != 0:
				logger.warning(f"Image has {total_pixels} pixels, which is not divisible by 3.")
				logger.warning(f"Using {rgb_pixels * 3} pixels, discarding the last {total_pixels % 3} pixels.")
			
			# Reshape to group every 3 consecutive pixels
			rgb_data = grayscale_data[:rgb_pixels * 3].reshape(-1, 3)

			new_width = width // 3
			new_height = height

			# Reshape to the new image dimensions
			output_array = rgb_data.reshape(new_height, new_width, 3)
			
			# Create and save the image
			output_img = Image.fromarray(output_array.astype(np.uint8))
			output_img.save(output_path)
			
			return True
			
	except Exception as e:
		logger.error(f"Error converting image: {e}")
		return False

def preprocess_images(folder):
	"""
	Preprocess PNG images in folder:
	- Check dimensions
	- Convert 1620x2560 images to 540x2560 using grayscale_to_rgb_channels
	- Fail if images are not 1620x2560 or 540x2560
	"""
	png_files = sorted(glob.glob(os.path.join(folder, '*.png')))
	if not png_files:
		logger.error('No PNG files found in folder')
		return False
	
	logger.info(f"Preprocessing {len(png_files)} PNG files...")
	
	processed_files = []
	
	for i, image_path in enumerate(png_files):
		logger.info(f"Checking image {i+1}/{len(png_files)}: {os.path.basename(image_path)}")
		
		width, height, error = get_png_dimensions(image_path)
		if error:
			logger.error(f"  ❌ Error: {error}")
			return False
		
		logger.info(f"  Size: {width}x{height}")
		
		# Check if image needs conversion (1620x2560 -> 540x2560)
		if width == 1620 and height == 2560:
			# Create converted filename
			base_name = os.path.splitext(os.path.basename(image_path))[0]
			converted_path = os.path.join(folder, f"{base_name}_converted.png")
			
			# Check if converted version already exists
			if os.path.exists(converted_path):
				logger.info(f"  ✅ Converted version already exists -> {os.path.basename(converted_path)}")
				#processed_files.append(converted_path)
				continue  # Skip adding converted version to processed_files for now
			else:
				logger.info(f"  🔄 Converting from 1620x2560 to 540x2560...")
				
				if grayscale_to_rgb_channels(image_path, converted_path):
					logger.info(f"  ✅ Converted successfully -> {os.path.basename(converted_path)}")
					processed_files.append(converted_path)
				else:
					logger.error(f"  ❌ Conversion failed")
					return False
				
		# Check if image is already correct size (540x2560)
		elif width == 540 and height == 2560:
			logger.info(f"  ✅ Correct dimensions")
			processed_files.append(image_path)
			
		# Invalid dimensions
		else:
			logger.error(f"  ❌ Invalid dimensions. Expected 1620x2560 (for conversion) or 540x2560 (ready)")
			return False
	
	logger.info(f"\n✅ Preprocessing complete! {len(processed_files)} images ready for printing.")
	return processed_files

def show_image(image_path):
	"""Show image on HDMI using fbi tool"""
	try:
		# stop the fbi process to avoid multiple instances
		subprocess.run(['sudo', 'pkill', 'fbi'], check=False)

		logger.debug(f"Displaying image: {image_path}")
		result = subprocess.run([
			'sudo', 'fbi', '-T', '2', '-d', '/dev/fb0', '-noverbose', image_path
		], capture_output=True, text=True, check=True)
		
		# Log stdout if any
		if result.stdout:
			logger.debug(f"fbi stdout: {result.stdout.strip()}")
		
		# Log stderr if any (fbi often outputs status to stderr)
		if result.stderr:
			logger.info(f"fbi: {result.stderr.strip()}")
			
		logger.debug(f"Successfully displayed image: {os.path.basename(image_path)}")
		
	except subprocess.CalledProcessError as e:
		logger.error(f"Failed to display image {image_path}: {e}")
		if e.stdout:
			logger.error(f"fbi stdout: {e.stdout.strip()}")
		if e.stderr:
			logger.error(f"fbi stderr: {e.stderr.strip()}")
		raise

def read_config(folder):
	config_path = os.path.join(folder, 'config.json')
	if not os.path.exists(config_path):
		logger.error(f"Missing config.json in {folder}")
		os.abort()
	
	config = None
	with open(config_path) as f:
		config = json.load(f)

	if config is None:
		logger.error(f"Invalid config.json in {folder}")
		os.abort()
    
    # check config keys
	required_keys = ['expTime', 'expTimeFirst', 'layerHeight']
	for key in required_keys:
		if key not in config:
			logger.error(f"Missing '{key}' in config.json")
			os.abort()

	exp_time = float(config.get('expTime', 5))
	exp_time_first = float(config.get('expTimeFirst', exp_time))
	layer_height = float(config.get('layerHeight', 0.05))

	return exp_time, exp_time_first, layer_height

def main(args):

	folder = args.folder
	dry_run = args.dry_run

	exp_time, exp_time_first, layer_height = read_config(folder)

	# Preprocess images - check dimensions and convert if needed
	processed_files = preprocess_images(folder)
	if not processed_files:
		logger.error("Image preprocessing failed!")
		os.abort()

	# Home motor
	# if not send_gcode('G28'):
	# 	logger.error('Failed to home motor')
	# 	os.abort()
	
	for i, image_path in enumerate(processed_files):

		logger.info(f"Printing layer {i}/{len(processed_files)}: {os.path.basename(image_path)}")

		# Update UI with current layer progress
		send_ui(f"LAYER {i} {len(processed_files)}")

		# Show image on HDMI
		if not dry_run:
			
			show_image(image_path)
			# Sleep 1.5s to ensure image is fully displayed
			time.sleep(1.5)
			# UV ON
			if not send_gcode('M3'):
				logger.error('Failed to turn UV ON')
				os.abort()
			# Exposure
			sleep_time = exp_time_first if i == 0 else exp_time
			logger.info(f"  Exposing for {sleep_time} seconds...")
			time.sleep(sleep_time)
			# UV OFF
			if not send_gcode('M5'):
				logger.error('Failed to turn UV OFF')
				os.abort()
		# Sleep 0.5s to ensure UV is fully off
		time.sleep(0.5)

		if not send_gcode(f'G1 Z{raise_Z_amount}'):
			logger.error('Failed to raise Z')
			os.abort()
		down_dist = raise_Z_amount - layer_height
		if not send_gcode(f'G1 Z-{down_dist}'):
			logger.error('Failed to lower Z')
			os.abort()

	# Disable motor
	send_gcode('M18')
	send_ui(f"DONE {len(processed_files)}")
	logger.info('Print sequence complete.')

if __name__ == '__main__':
	import argparse
	
	# Parse command line arguments
	parser = argparse.ArgumentParser(description="3D Print Sequence Controller")
	parser.add_argument("folder", help="Path to folder containing config.json and PNG files")
	parser.add_argument("--log-level", type=str, default="INFO", 
	                    choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
	                    help="Set the logging level (default: INFO)")
	parser.add_argument("--use-console", action="store_true",
	                    help="Use console logging instead of syslog", default=False)
	parser.add_argument("--preprocess-only", action="store_true",
	                    help="Only preprocess images without printing", default=False)
	parser.add_argument("--dry-run", action="store_true",
	                    help="Perform a dry run without UV and with minimal exposure time", default=False)
	parser.add_argument("--daemonize", action="store_true",
	                    help="Run as a daemon in the background", default=False)
	args = parser.parse_args()
	
	# Setup logging with specified level (use syslog by default)
	use_syslog = not args.use_console
	logger = setup_logging(log_level=args.log_level, use_syslog=use_syslog)
	
	# Register signal handlers for graceful shutdown
	signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
	signal.signal(signal.SIGTERM, signal_handler)  # Termination signal
	signal.signal(signal.SIGABRT, signal_handler)   # Abort signal
	
	logger.info("=" * 50)
	logger.info("3D Print Sequence Starting")
	logger.info(f"Print folder: {args.folder}")
	logger.info(f"Log level: {args.log_level}")
	logger.info(f"Logging to: {'syslog' if use_syslog else 'console'}")
	logger.info("=" * 50)
	
	if args.preprocess_only:
		# Only preprocess images
		if preprocess_images(args.folder):
			logger.info("Image preprocessing completed successfully.")
			sys.exit(0)
		else:
			logger.error("Image preprocessing failed.")
			os.abort()

	main(args)

