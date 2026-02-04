import serial
import time

# ────────────────────────────────────────────────
# Configuration – change COM port as needed
# Windows:   "COM3", "COM4", ...
# Linux/macOS: "/dev/ttyUSB0", "/dev/ttyACM0", ...
# ────────────────────────────────────────────────
PORT = "COM8"           # ← change this
BAUDRATE = 57600
TIMEOUT = 0.5

def send_command(ser, cmd: str, wait_ms=100):
    """Send command and add CR (carriage return)"""
    full_cmd = cmd.strip() + "\r"
    ser.write(full_cmd.encode('ascii'))
    print(f"→ {cmd}")
    time.sleep(wait_ms / 1000.0)   # small delay helps reliability

def read_response(ser):
    """Read any response (echo or status)"""
    response = ser.read(ser.in_waiting or 100).decode('ascii', errors='ignore').strip()
    if response:
        print(f"← {response}")
    return response

# ────────────────────────────────────────────────
# Main example
# ────────────────────────────────────────────────
try:
    with serial.Serial(
        port=PORT,
        baudrate=BAUDRATE,
        bytesize=8,
        parity='N',
        stopbits=1,
        timeout=TIMEOUT
    ) as ser:

        print(f"Connected to VXC at {PORT} @ {BAUDRATE} baud\n")

        # 1. Wake up / make sure controller is responding
        send_command(ser, "E", 200)         # Enter online mode (echo on)
        read_response(ser)

        # 2. Optional: set speed & acceleration for motor 1 (C)
        send_command(ser, "C S5")           # Set speed = 5 (example value)
        send_command(ser, "C A1000")        # Set acceleration (pulses/sec²)

        # 3. Move motor 1 (C) +2000 steps (positive direction)
        send_command(ser, "C I +2000")      # Index +2000 steps

        # Wait until move is finished
        print("Moving...")
        time.sleep(3.0)                     # ← crude wait; better to poll status

        # 4. Move motor 1 back -2000 steps
        send_command(ser, "C I -2000")

        # 5. Optional: quick status check
        send_command(ser, "Q")              # Query status
        read_response(ser)

        # 6. Go offline / quiet mode when finished
        send_command(ser, "X", 100)

        print("\nExample sequence finished.")

except serial.SerialException as e:
    print(f"Serial error: {e}")
except Exception as e:
    print(f"Error: {e}")
finally:
    print("Done.")