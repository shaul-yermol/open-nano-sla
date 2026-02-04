# Set static IP for Raspberry Pi via cmdline.txt

Example of /boot/cmdline.txt:
ip=192.168.5.100::192.168.5.101:255.255.255.0:rpi:eth0:off

# Wnable WIFI via cmdline.txt

nmcli networking on
nmcli device wifi connect 3C:84:6A:58:4C:27 password "your-password"
sudo nmcli device wifi connect 00:B8:C2:B1:13:42 password
sudo route del 192.168.5.101

# Toggle UV light via GPIO
gpioset GPIO26=0

# Reading endstop state
## TOP:
gpiomon GPIO25
## BOTTOM:
gpiomon GPIO13

# Step motor driver:
DRV8825
1/32 microstepping
STEP = GPIO23
DIR = GPIO22
ENABLE=GPIO24 (active low)


```
# Enable driver
gpioset GPIO24=0
# Step forward 100 steps
for i in `seq 100`; do gpioset -t 1,1,0 GPIO23=1; done
# Step backward 100 steps
for i in `seq 100`; do gpioset -t 1,1 GPIO23=0; gpioset -t 1,1 GPIO23=1; done
# Disable driver
gpioset GPIO24=1
```

# Show images on HDMI display
sudo apt-get install fbi
sudo fbi -T 2 -d /dev/fb0 -noverbose [imagefile.jpg] 

# NEXTION
Connected to GPIO14 (TX) and GPIO15 (RX) - instead of serial console (UART)
1. Disable serial console in raspi-config
2. Enable serial port hardware in raspi-config
3. Add to /boot/config.txt:
   enable_uart=1
   dtoverlay=disable-bt
4. Disable bluetooth to free up UART:
   sudo systemctl disable hciuart
5. Reboot

# G-code Commands Supported by Motor Controller

The motor controller (`mc.py`) supports the following G-code commands:

## Movement Commands

### G0, G1 - Linear Move
**Syntax:** `G0 Z<position> F<speed>` or `G1 Z<position> F<speed>`

- **Z**: Z-axis position in millimeters (relative movement)
  - Positive values move UP
  - Negative values move DOWN  
- **F**: Feed rate (speed) in microseconds between steps (optional, default: 600)

**Examples:**
```gcode
G1 Z10        # Move up 10mm at default speed
G0 Z-5 F400   # Move down 5mm at 400µs speed
G1 Z2.5       # Move up 2.5mm
```

## Homing Commands

### G28 - Home to Bottom Endstop
**Syntax:** `G28` or `G28 Z`

Moves the Z-axis down until the bottom endstop is triggered, then performs precision homing sequence.

**Examples:**
```gcode
G28           # Home to bottom endstop
G28 Z         # Home Z-axis to bottom
```

### G27 - Park/Home to Top Endstop  
**Syntax:** `G27` or `G27 Z`

Moves the Z-axis up until the top endstop is triggered, then performs precision homing sequence.

**Examples:**
```gcode
G27           # Park at top endstop
G27 Z         # Home Z-axis to top
```

## Timing Commands

### G4 - Dwell/Pause
**Syntax:** `G4 P<time>`

- **P**: Pause time in milliseconds

**Examples:**
```gcode
G4 P1000      # Pause for 1 second (1000ms)
G4 P500       # Pause for 0.5 seconds
```

## Motor Control Commands

### M17 - Enable Motors
**Syntax:** `M17`

Enables the stepper motor (sets ENABLE pin low).

### M18, M84 - Disable Motors
**Syntax:** `M18` or `M84`

Disables the stepper motor (sets ENABLE pin high). Motor will lose holding torque.

## UV Light Control Commands

### M3, M4 - UV Light On
**Syntax:** `M3` or `M4`

Turns on the UV light (sets UV_LIGHT_PIN high).

### M5 - UV Light Off
**Syntax:** `M5`

Turns off the UV light (sets UV_LIGHT_PIN low).

## Status Commands

### M119 - Report Endstop Status
**Syntax:** `M119`

Reports the current state of both endstops:
- **TRIGGERED**: Endstop is activated
- **OPEN**: Endstop is not activated

**Example Output:**
```
Top endstop (GPIO25): OPEN
Bottom endstop (GPIO13): TRIGGERED
```

## Usage Examples

### Basic Print Sequence
```gcode
M17           # Enable motor
G28           # Home to bottom
G1 Z0.1 F400  # Move to first layer height
M3            # Turn on UV light
G4 P5000      # Expose for 5 seconds
M5            # Turn off UV light
G1 Z0.1       # Move up one layer
M18           # Disable motor
```

### Status Check Sequence
```gcode
M119          # Check endstop status
M17           # Enable motor
G1 Z1         # Small test move
M119          # Check status again
M18           # Disable motor
```

## Command Interface

Commands can be sent to the motor controller via:
- **Named pipe**: `/tmp/mcin` (default)
- **Status output**: `/tmp/mcout` (default)

### Sending Commands
```bash
# Single command
echo "G1 Z10" > /tmp/mcin

# Multiple commands
cat << EOF > /tmp/mcin
M17
G28
G1 Z5
M18
EOF
```

### Monitoring Status
```bash
# Monitor status output
cat /tmp/mcout

# Or tail for continuous monitoring
tail -f /tmp/mcout
```

## Motor Controller Configuration

### Command Line Options
```bash
python3 mc.py --help
```

**Available Options:**
- `--check`: Check endstop status and exit
- `--home`: Home motor to bottom endstop and exit
- `--unhome`: Home motor to top endstop and exit  
- `--pipe`: Start G-code pipe service (main mode)
- `--pipe-path PATH`: Set input pipe path (default: `/tmp/mcin`)
- `--status-pipe PATH`: Set status output pipe path (default: `/tmp/mcout`)
- `--log-level LEVEL`: Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `--log-file FILE`: Log to file in addition to console
- `-t TIME`: Set step delay in microseconds (default: 600)

### Usage Examples
```bash
# Start with debug logging
python3 mc.py --pipe --log-level DEBUG

# Use custom pipe paths
python3 mc.py --pipe --pipe-path /tmp/my_gcode --status-pipe /tmp/my_status

# Log to file with INFO level
python3 mc.py --pipe --log-file /var/log/motor.log --log-level INFO

# Quick endstop check
python3 mc.py --check

# Home the motor
python3 mc.py --home
```

### Hardware Configuration

**GPIO Pin Mapping:**
- **STEP**: GPIO23 (Step signal)
- **DIR**: GPIO22 (Direction signal) 
- **ENABLE**: GPIO24 (Enable signal, active low)
- **TOP_ENDSTOP**: GPIO25 (Top limit switch)
- **BOTTOM_ENDSTOP**: GPIO13 (Bottom limit switch)
- **UV_LIGHT**: GPIO26 (UV light control)

**Physical Parameters:**
- **Revolution**: 2mm per revolution
- **Microstepping**: 1/1 (full step)
- **Steps per revolution**: 200 steps

### Status Output Format

The status pipe outputs the following message types:

**Command Execution:**
```
EXEC:<gcode_command>     # Command started
OK                       # Command completed successfully  
ERROR                    # Command failed
```

**Movement Status:**
```
MOVE_COMPLETE:<direction>:<distance>mm:<steps>steps
HOME_COMPLETE:<direction>
```

**Queue Status:**
```
QUEUED:<gcode_command>   # Command added to queue
```

### Error Handling

**Common Error Messages:**
- `Invalid G-code: <command>` - Unrecognized command format
- `Unsupported G-code command: <command>` - Command not implemented  
- `No Z parameter found in G-code command` - Missing required Z parameter
- `G4: Missing P parameter for dwell time` - Missing required P parameter
- `G28: Only Z-axis homing supported` - X/Y homing not supported


## pigpio pigs interface

### Write to pin:

> pigs w 26 1
> pigs w 26 0

### Create and transmit waveform:

> pigs wvnew
> pigs wvag 0x800000 0x0 600 0x0 0x800000 600
2
> pigs wvcre
0
> pigs wvtxr 0
5
> pigs wvhlt

### Endstop control:

> pigs m 25 r
> pigs m 13 r
> pigs fg 25 100
> pigs fg 13 100
> pigs procr 1
> pigs procr 1
> pigs proc wait 0x2002000 w 24 1
> pigs proc 2
