# Copilot Instructions for open-nano-dlp

## Project Overview
This project is a motor controller and print management system for a custom SLA 3D printer, primarily targeting Raspberry Pi hardware. It orchestrates Z-axis movement, UV light control, and print sequencing via G-code commands, using GPIO pins and named pipes for inter-process communication.

## Development Environment
- **Working Environment**: Code runs on a Raspberry Pi, which is mounted to the `remote/` folder in this workspace
- The `remote/open-nano-dlp/` directory contains the actual runtime code on the Pi
- Local files in the root directory are for development/testing; deploy changes to `remote/` for actual hardware execution

## Key Components
- `mc.py`: Main motor controller (local development version). Handles G-code parsing, stepper motor control, endstop logic, and UV light switching.
- `remote/open-nano-dlp/mc.py`: Runtime motor controller on the Raspberry Pi. Communicates via named pipes (`/tmp/mcin` for input, `/tmp/mcout` for status).
- `print.py`: Print manager. Sends G-code commands to `mc.py` and monitors status responses. Handles print sequencing and error management.
- `send_gcode_udp.py`: Utility for sending G-code commands to the controller via UDP (for remote or networked control).
- `convert_image.py`: Image conversion utility for print preparation.

## Developer Workflows
- **Start pigpiod daemon**: `sudo pigpiod` (required before running motor controller)
- **Start motor controller on Pi**: `python3 remote/open-nano-dlp/mc.py --pipe` (or SSH to Pi and run from `/home/pi/...`)
- **Send G-code command**: `echo "G1 Z10" > /tmp/mcin`
- **Monitor status**: `cat /tmp/mcout` or `tail -f /tmp/mcout`
- **Run print sequence**: Use `print.py` to automate layer-by-layer printing
- **Test queue system**: `test_queue_system.py` simulates G-code queuing and execution logic (local testing without GPIO)
- **Send G-code via UDP**: `python3 send_gcode_udp.py "G1 Z10" --host <raspberry_pi_ip> --port <port>`
- **Deploy changes**: Copy updated files to `remote/open-nano-dlp/` or sync to the Pi directly
- **Manual GPIO control**: Use `pigs` commands directly (e.g., `pigs w 26 1` to turn on UV light)

## G-code Command Patterns
- Movement: `G0 Z<pos> F<speed>`, `G1 Z<pos> F<speed>`
- Homing: `G28` (bottom), `G27` (top)
- Motor enable/disable: `M17`, `M18`, `M84`
- UV light: `M3`/`M4` (on), `M5` (off)
- Status: `M119`
- Dwell: `G4 P<ms>`

## Hardware Integration
- GPIO pin mapping is hardcoded in `mc.py` (see README for details).
- Motor control uses **pigpio** daemon (`pigpiod`) via the `pigs` command-line interface.
- Endstop and UV light logic is implemented via `pigs` commands for reading/writing GPIO.
- Status and error messages are written to `/tmp/mcout` for monitoring.
- **Requires pigpiod daemon to be running**: `sudo pigpiod` (start daemon before running mc.py)

## Logging & Debugging
- Logging uses syslog by default; falls back to console if unavailable.
- Use `--log-level` and `--log-file` options in `mc.py` and `print.py` for debugging.

## Project-Specific Conventions
- All inter-process communication uses named pipes (`/tmp/mcin`, `/tmp/mcout`).
- G-code commands are queued and executed sequentially; status and errors are reported in plain text.
- Hardware configuration (GPIO, microstepping, etc.) is documented in the README and hardcoded in scripts.
- No build system; scripts are run directly with Python 3.

## Example Workflow
```bash
# On the Pi (via remote mount or SSH)
python3 remote/open-nano-dlp/mc.py --pipe --log-level DEBUG

# From local machine
python3 print.py

# Monitor status (on Pi or via remote mount)
cat /tmp/mcout
```

## References
- See `README.md` for hardware setup, command examples, and troubleshooting.
- Key scripts: `mc.py`, `print.py`, `send_gcode_udp.py`, `convert_image.py`, `test_queue_system.py`
- Hardware configs: `SLA/config.txt`, `ScrHandle/config.ini`, etc.

---
If any section is unclear or missing, please provide feedback to improve these instructions.