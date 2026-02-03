"""Velmex VXC XY Stage Controller with ASCII command protocol."""

import serial
import time
import logging
from typing import Tuple, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class MotionAxis(Enum):
    """Motion axis identifiers."""
    X = "X"
    Y = "Y"
    Z = "Z"
    R = "R"


class VXCController:
    """Controller for Velmex VXC XY stage via USB/Serial.
    
    Communicates using ASCII command protocol at 9600 baud, 8N1.
    Supports absolute/relative positioning, velocity control, and motion queries.
    """
    
    # Motion timing constants
    SERIAL_TIMEOUT = 2.0
    MOTION_POLL_INTERVAL = 0.1  # seconds
    MOTION_TIMEOUT = 60.0  # seconds
    
    # Retry configuration (exponential backoff)
    RETRY_DELAYS = [0.5, 1.0, 2.0]  # seconds per attempt
    
    def __init__(self, port: str, baudrate: int = 9600, line_ending: str = "\r", init_commands: Optional[list[str]] = None):
        """Initialize VXC controller connection.
        
        Args:
            port: COM port name (e.g., 'COM3')
            baudrate: Serial connection speed (default 9600)
            line_ending: Line ending appended to commands (default "\\r")
            init_commands: Optional list of ID/handshake commands
        """
        self.port = port
        self.baudrate = baudrate
        self.line_ending = line_ending
        self.init_commands = init_commands or []
        self.serial = None
        self.connected = False
        self._current_position = {"X": 0, "Y": 0, "Z": 0, "R": 0}
        
    def connect(self) -> bool:
        """Establish serial connection to VXC controller.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Opening serial port {self.port} @ {self.baudrate} baud, timeout={self.SERIAL_TIMEOUT}s, line_ending={repr(self.line_ending)}")
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.SERIAL_TIMEOUT
            )
            logger.info(f"Serial port opened successfully. Waiting 0.5s for controller to initialize...")
            time.sleep(0.5)  # Allow controller to initialize
            
            # Clear any residual data
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            logger.info("Serial buffers cleared. Verifying connection...")
            
            # Try init commands (if provided) or position query to verify connection
            if self._verify_connection():
                return True

            self.connected = False
            logger.error("VXC not responding to queries")
            return False
                
        except serial.SerialException as e:
            logger.error(f"Failed to connect to VXC on {self.port}: {e}")
            self.connected = False
            return False
    
    def disconnect(self) -> None:
        """Close serial connection and stop motion."""
        if self.connected:
            try:
                self.stop_motion()
                time.sleep(0.2)
                if self.serial:
                    self.serial.close()
                self.connected = False
                logger.info("VXC disconnected")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
    
    def _send_command(self, command: str, retry_count: int = 0) -> Optional[str]:
        """Send ASCII command and retrieve response with exponential backoff retry.
        
        Args:
            command: ASCII command string (without CR)
            retry_count: Current retry attempt (internal)
            
        Returns:
            Response string or None if all retries exhausted
        """
        if not self.connected and retry_count == 0:
            # Allow commands during connection verification
            pass
        elif not self.serial:
            logger.error("VXC serial port not open")
            return None
        
        try:
            # Send command with configured line ending
            cmd_bytes = (command + self.line_ending).encode('ascii')
            logger.debug(f"Sending {len(cmd_bytes)} bytes: {repr(cmd_bytes)} (command: '{command}')")
            self.serial.write(cmd_bytes)
            self.serial.flush()
            
            # Small delay to allow device to process and respond
            time.sleep(0.1)
            
            # Read response
            response = self._read_response()
            if response is not None:
                logger.debug(f"Received: {repr(response)}")
                return response
            else:
                # Retry with exponential backoff
                if retry_count < len(self.RETRY_DELAYS):
                    delay = self.RETRY_DELAYS[retry_count]
                    logger.warning(f"No response to '{command}', retrying in {delay}s (attempt {retry_count + 2}/4)")
                    time.sleep(delay)
                    return self._send_command(command, retry_count + 1)
                else:
                    logger.error(f"Command '{command}' failed after 3 retries")
                    return None
                    
        except serial.SerialException as e:
            logger.error(f"Serial error sending command '{command}': {e}")
            self.connected = False
            return None

    def _verify_connection(self) -> bool:
        """Verify connection by running init commands or position query."""
        # Try explicit init commands first
        logger.info(f"Testing init commands: {self.init_commands}")
        for cmd in self.init_commands:
            logger.info(f"Sending init command: '{cmd}'")
            response = self._send_command(cmd)
            logger.info(f"  Response: {repr(response)}")
            if response is not None and response != "":
                self.connected = True
                logger.info(f"VXC connected on {self.port} @ {self.baudrate} baud. Init '{cmd}' -> {response}")
                return True

        # Try simple commands to verify any response
        logger.info("Init commands failed or empty. Trying test commands: ['?V', 'P', 'F', 'V']")
        for test_cmd in ["?V", "P", "F", "V"]:
            logger.info(f"Sending test command: '{test_cmd}'")
            response = self._send_command(test_cmd)
            logger.info(f"  Response: {repr(response)}")
            if response is not None and response != "":
                self.connected = True
                logger.info(f"VXC connected on {self.port} @ {self.baudrate} baud. Test '{test_cmd}' -> {response}")
                return True
        
        logger.error("All connection verification attempts failed - no response from device")
        return False
    
    def _read_response(self) -> Optional[str]:
        """Read single-line response from controller (terminated by CR).
        
        Returns:
            Response string (without CR) or None if timeout
        """
        try:
            # Check how many bytes are waiting
            waiting = self.serial.in_waiting
            logger.debug(f"Bytes waiting in buffer: {waiting}")
            
            # Try readline first (for line-terminated responses)
            response = self.serial.readline()
            logger.debug(f"readline() returned {len(response)} bytes: {repr(response)}")
            if response:
                decoded = response.decode('ascii', errors='ignore').strip()
                if decoded:
                    logger.debug(f"Decoded line-terminated response: '{decoded}'")
                    return decoded
            
            # If no line-terminated response, try reading any available bytes
            # (for devices that respond with single bytes or partial responses)
            remaining = self.serial.read_all()
            logger.debug(f"read_all() returned {len(remaining)} bytes: {repr(remaining)}")
            if remaining:
                decoded = remaining.decode('ascii', errors='ignore').strip()
                if decoded:
                    logger.debug(f"Decoded raw response: '{decoded}'")
                    return decoded
                # Even if decode produces empty string, we got bytes - treat as success
                logger.debug(f"Got bytes but empty decode, returning repr")
                return repr(remaining)
            
            logger.debug("No data received (timeout)")
            return None
        except serial.SerialException as e:
            logger.error(f"Serial exception during read: {e}")
            return None
    
    def move_absolute(self, x: Optional[int] = None, y: Optional[int] = None, 
                     z: Optional[int] = None, r: Optional[int] = None) -> bool:
        """Move to absolute position (in steps).
        
        Args:
            x, y, z, r: Target positions (None to skip axis)
            
        Returns:
            True if command accepted, False otherwise
        """
        parts = []
        if x is not None:
            parts.append(f"{x}")
            self._current_position["X"] = x
        if y is not None:
            parts.append(f"{y}")
            self._current_position["Y"] = y
        if z is not None:
            parts.append(f"{z}")
            self._current_position["Z"] = z
        if r is not None:
            parts.append(f"{r}")
            self._current_position["R"] = r
        
        if not parts:
            logger.warning("move_absolute called with no axes specified")
            return False
        
        # VXC uses I (Index) command for single motor moves
        # For X axis (Motor 1), send: I<steps>
        # Note: This controller appears to be single-axis, treating x as Motor 1
        if x is not None:
            command = f"I{x}"
            response = self._send_command(command)
            if response:
                logger.info(f"Absolute move to X={x}: sent")
                return True
        
        return False
    
    def move_relative(self, dx: Optional[int] = None, dy: Optional[int] = None,
                     dz: Optional[int] = None, dr: Optional[int] = None) -> bool:
        """Move relative distance (in steps).
        
        Args:
            dx, dy, dz, dr: Relative movements (None to skip axis)
            
        Returns:
            True if command accepted, False otherwise
        """
        parts = []
        if dx is not None:
            parts.append(f"{dx}")
            self._current_position["X"] += dx
        if dy is not None:
            parts.append(f"{dy}")
            self._current_position["Y"] += dy
        if dz is not None:
            parts.append(f"{dz}")
            self._current_position["Z"] += dz
        if dr is not None:
            parts.append(f"{dr}")
            self._current_position["R"] += dr
        
        if not parts:
            logger.warning("move_relative called with no axes specified")
            return False
        
        # VXC uses I (Index) command for relative moves
        # Positive = forward, Negative = backward
        if dx is not None:
            command = f"I{dx}"
            response = self._send_command(command)
            if response:
                logger.info(f"Relative move dX={dx}: sent")
                return True
        
        return False
    
    def set_speed(self, x_speed: Optional[int] = None, y_speed: Optional[int] = None) -> bool:
        """Set motor speed (steps per second).
        
        Args:
            x_speed, y_speed: Speed in steps/sec (None to skip)
            
        Returns:
            True if command accepted
        """
        parts = []
        if x_speed is not None:
            parts.append(f"{x_speed}")
        if y_speed is not None:
            parts.append(f"{y_speed}")
        
        if not parts:
            return True  # No-op if no speeds specified
        
        # VXC uses S<speed> format (1-6000 steps/sec)
        if x_speed is not None:
            command = f"S{x_speed}"
            response = self._send_command(command)
            return response is not None
        
        return True
    
    def set_acceleration(self, x_accel: Optional[int] = None, 
                        y_accel: Optional[int] = None) -> bool:
        """Set motor acceleration (steps per second squared).
        
        Args:
            x_accel, y_accel: Acceleration in steps/sec² (None to skip)
            
        Returns:
            True if command accepted
        """
        parts = []
        if x_accel is not None:
            parts.append(f"{x_accel}")
        if y_accel is not None:
            parts.append(f"{y_accel}")
        
        if not parts:
            return True
        
        command = "A," + ",".join(parts)
        response = self._send_command(command)
        return response is not None
    
    def stop_motion(self) -> bool:
        """Emergency stop of all motion.
        
        Returns:
            True if command sent successfully
        """
        response = self._send_command("K")
        if response is not None:
            logger.info("Motion stopped")
            return True
        return False
    
    def get_position(self) -> Optional[dict]:
        """Query current motor position (Motor 1 = X axis).
        
        Returns:
            Dict with keys 'X', 'Y', 'Z', 'R' in steps, or None if error
        """
        # VXC uses X command to read Motor 1 position
        response = self._send_command("X")
        if response is None:
            return None
        
        try:
            # Response should be a single integer (position in steps)
            position = int(response.strip())
            pos = {
                "X": position,
                "Y": 0,  # VXC appears to be single-axis
                "Z": 0,
                "R": 0,
            }
            self._current_position.update(pos)
            return pos
        except (ValueError, IndexError) as e:
            logger.error(f"Failed to parse position response '{response}': {e}")
        
        return None
    
    def is_motion_complete(self) -> Optional[bool]:
        """Check if current motion is complete.
        
        Returns:
            True if motion done (Ready), False if in progress (Busy), None if error
        """
        # VXC uses V command for status: R=Ready, B=Busy, F=Fault
        response = self._send_command("V")
        if response is None:
            return None
        
        # Parse status: R=Ready (motion complete), B=Busy, F=Fault
        if "R" in response.upper():
            return True
        elif "B" in response.upper():
            return False
        elif "F" in response.upper():
            logger.warning("VXC reports fault status")
            return None
        
        # Fallback: try parsing as integer (some controllers return 0/1)
        try:
            status = int(response.strip())
            return status == 0
        except ValueError:
            logger.error(f"Failed to parse motion status '{response}'")
            return None
    
    def wait_for_motion_complete(self, timeout: Optional[float] = None) -> bool:
        """Block until motion completes or timeout.
        
        Args:
            timeout: Maximum wait time in seconds (None for default)
            
        Returns:
            True if motion completed, False if timeout
        """
        if timeout is None:
            timeout = self.MOTION_TIMEOUT
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            is_complete = self.is_motion_complete()
            if is_complete is True:
                logger.info("Motion complete")
                return True
            elif is_complete is False:
                time.sleep(self.MOTION_POLL_INTERVAL)
            else:
                # Error querying status
                return False
        
        logger.warning(f"Motion wait timeout after {timeout}s")
        return False
    
    def clear_controller(self) -> bool:
        """Clear controller state.
        
        Returns:
            True if successful
        """
        response = self._send_command("C")
        if response is not None:
            logger.info("Controller cleared")
            return True
        return False
