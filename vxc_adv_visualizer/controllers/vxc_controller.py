"""Velmex VXC Stepping Motor Controller with ASCII command protocol."""

import serial
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class VXCController:
    """Controller for Velmex VXC Stepping Motor Controller via USB/Serial.
    
    Communicates using ASCII command protocol at 9600 baud, 8N1.
    Commands are sent with CR line ending.
    """
    
    def __init__(self, port: str, baudrate: int = 9600, line_ending: str = "\r", 
                 init_commands: Optional[list[str]] = None, timeout: float = 1.0):
        """Initialize VXC Controller connection.
        
        Args:
            port: COM port name (e.g., 'COM8')
            baudrate: Serial connection speed (default 9600)
            line_ending: Line ending for commands (default "\r")
            init_commands: Optional list of verification commands
            timeout: Serial read timeout in seconds (default 1.0)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.line_ending = line_ending
        self.init_commands = init_commands or ["V", "X"]
        self.serial = None
        self.connected = False
        self.online = False
        self._current_position = {"X": 0, "Y": 0, "Z": 0, "R": 0}
    
    def connect(self) -> bool:
        """Establish serial connection to VXC controller.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Connecting to {self.port} @ {self.baudrate} baud, timeout={self.timeout}s")
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            time.sleep(0.5)  # Allow controller to initialize
            
            # Clear buffers
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            
            # Verify connection
            if self._verify_connection():
                self.connected = True
                logger.info(f"✓ Connected to VXC on {self.port} @ {self.baudrate} baud")
                return True
            
            logger.error("VXC not responding to verification commands")
            self.connected = False
            return False
                
        except serial.SerialException as e:
            logger.error(f"✗ Failed to connect to VXC on {self.port}: {e}")
            self.connected = False
            return False
    
    def disconnect(self) -> None:
        """Close serial connection."""
        if self.connected:
            try:
                self.kill_motion()
                time.sleep(0.2)
                if self.serial and self.serial.is_open:
                    self.serial.close()
                self.connected = False
                logger.info("✓ Disconnected")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
    
    def _verify_connection(self) -> bool:
        """Verify connection by sending init commands."""
        for cmd in self.init_commands:
            response = self.send_command(cmd, wait_response=True)
            if response:
                logger.info(f"✓ Verified with '{cmd}' -> {repr(response)}")
                return True
        
        logger.error("All verification commands failed")
        return False
    
    def send_command(self, command: str, wait_response: bool = False) -> Optional[str]:
        """Send command to VXC controller.
        
        Args:
            command: Command string (without line ending)
            wait_response: If True, wait for and return response
            
        Returns:
            Response string if wait_response=True, otherwise None
        """
        if not self.serial or not self.serial.is_open:
            logger.error("✗ Not connected")
            return None
        
        try:
            # Clear input buffer before sending
            self.serial.reset_input_buffer()
            
            # Send command with line ending
            cmd_bytes = (command + self.line_ending).encode('ascii')
            self.serial.write(cmd_bytes)
            self.serial.flush()
            logger.debug(f"Sent: '{command}'")
            
            if wait_response:
                return self._read_response()
            
            return None
            
        except serial.SerialException as e:
            logger.error(f"✗ Serial error: {e}")
            self.connected = False
            return None
    
    def _read_response(self) -> Optional[str]:
        """Read response from device.
        
        Returns:
            Response string or None if timeout/error
        """
        try:
            # Wait for data with timeout
            start_time = time.time()
            response = b""
            
            while time.time() - start_time < self.timeout:
                if self.serial.in_waiting > 0:
                    byte = self.serial.read(1)
                    if not byte:
                        continue
                    
                    response += byte
                    
                    # Check for end-of-response markers
                    if b'\r' in response or len(response) > 100:
                        break
                
                time.sleep(0.01)  # Small delay to avoid busy-waiting
            
            if response:
                decoded = response.decode('ascii', errors='ignore').strip()
                logger.debug(f"Received: {repr(decoded)}")
                return decoded if decoded else None
            
            return None
            
        except Exception as e:
            logger.error(f"✗ Read error: {e}")
            return None
    
    # ==================== Control Methods ====================
    
    def go_online(self, echo: bool = False) -> None:
        """Put VXC in Online mode for programmatic control.
        
        Args:
            echo: If True, enable echo (E command), if False disable echo (F command)
        """
        command = 'E' if echo else 'F'
        self.send_command(command)
        self.online = True
        logger.info(f"✓ Online mode {'(echo on)' if echo else '(echo off)'}")
        time.sleep(0.1)
    
    def go_offline(self) -> None:
        """Put VXC in Offline/Jog mode."""
        self.send_command('Q')
        self.online = False
        logger.info("✓ Offline mode (Jog)")
    
    def clear_program(self) -> None:
        """Clear all commands from current program."""
        self.send_command('C')
        logger.info("✓ Program cleared")
    
    def zero_position(self) -> None:
        """Zero all motor positions."""
        self.send_command('N')
        logger.info("✓ Position zeroed")
    
    def stop_motor(self) -> None:
        """Decelerate motor to stop (smooth stop)."""
        self.send_command('D')
        logger.info("✓ Stop command sent (decelerate)")
    
    def kill_motion(self) -> None:
        """Immediately stop all motion (hard stop)."""
        self.send_command('K')
        logger.info("✓ Kill command sent (immediate stop)")
    
    # ==================== Status and Query Methods ====================
    
    def verify_status(self) -> Optional[str]:
        """Verify controller status.
        
        Returns:
            'R' = Ready, 'B' = Busy, 'J' = Jog mode, 'F' = Fault, or None
        """
        response = self.send_command('V', wait_response=True)
        
        status_map = {
            'R': 'Ready',
            'B': 'Busy',
            'J': 'Jog mode',
            'F': 'Fault'
        }
        
        if response and response.strip() in status_map:
            status_text = status_map[response.strip()]
            logger.info(f"✓ Status: {status_text}")
            return response.strip()
        else:
            logger.warning(f"Unknown status: {response}")
            return None
    
    def get_position(self, motor: int = 1) -> Optional[int]:
        """Get current motor position.
        
        Args:
            motor: Motor number (1=X, 2=Y, 3=Z, 4=T)
            
        Returns:
            Position as integer, or None if error
        """
        position_commands = {1: 'X', 2: 'Y', 3: 'Z', 4: 'T'}
        
        if motor not in position_commands:
            logger.error(f"✗ Invalid motor number: {motor}")
            return None
        
        response = self.send_command(position_commands[motor], wait_response=True)
        
        if response:
            try:
                position = int(response.strip())
                logger.info(f"✓ Motor {motor} position: {position}")
                self._current_position[position_commands[motor]] = position
                return position
            except ValueError:
                logger.error(f"✗ Invalid position response: {response}")
                return None
        return None
    
    def is_motion_complete(self) -> Optional[bool]:
        """Check if current motion is complete.
        
        Returns:
            True if ready, False if busy, None if error
        """
        response = self.send_command('V', wait_response=True)
        if response is None:
            return None
        
        if "R" in response.upper():
            return True
        elif "B" in response.upper():
            return False
        
        return None
    
    def wait_for_motion_complete(self, timeout: float = 30.0) -> bool:
        """Block until motion completes or timeout.
        
        Args:
            timeout: Maximum wait time in seconds (default 30)
            
        Returns:
            True if motion completed, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            is_complete = self.is_motion_complete()
            if is_complete is True:
                logger.info("✓ Motion complete")
                return True
            elif is_complete is False:
                time.sleep(0.1)  # Poll every 100ms
            else:
                # Error querying status
                return False
        
        logger.warning(f"✗ Motion timeout after {timeout}s")
        return False
    
    # ==================== Motion Methods ====================
    
    def step_motor(self, motor: int = 1, steps: int = 400, 
                   speed: int = 2000, acceleration: int = 2, wait: bool = True) -> bool:
        """Step motor a specified number of steps.
        
        Args:
            motor: Motor number (1-4)
            steps: Number of steps (positive or negative)
            speed: Speed in steps/second (1-6000)
            acceleration: Acceleration value (0-127)
            wait: Wait for movement to complete
            
        Returns:
            True if successful, False otherwise
        """
        # Clear previous commands
        self.clear_program()
        
        # Set acceleration: A{motor}M{value},
        accel_cmd = f'A{motor}M{acceleration},'
        self.send_command(accel_cmd)
        
        # Set speed: S{motor}M{value},
        speed_cmd = f'S{motor}M{speed},'
        self.send_command(speed_cmd)
        
        # Set index: I{motor}M{value},
        index_cmd = f'I{motor}M{steps},'
        self.send_command(index_cmd)
        
        logger.info(f"✓ Commands queued: Motor {motor}, {steps} steps @ {speed} steps/sec, accel {acceleration}")
        
        # Run program
        self.send_command('R')
        
        if wait:
            return self.wait_for_motion_complete(timeout=30.0)
        
        return True
    
    def move_absolute(self, x: Optional[int] = None, y: Optional[int] = None, 
                     z: Optional[int] = None, r: Optional[int] = None) -> bool:
        """Move to absolute position (in steps).
        
        Args:
            x, y, z, r: Target positions (None to skip axis)
            
        Returns:
            True if command successful, False otherwise
        """
        # Use motor 1 (X axis) as primary
        if x is not None:
            return self.step_motor(motor=1, steps=x, speed=2000, acceleration=2)
        
        logger.warning("move_absolute called with no position specified")
        return False
    
    def move_relative(self, dx: Optional[int] = None, dy: Optional[int] = None,
                     dz: Optional[int] = None, dr: Optional[int] = None) -> bool:
        """Move relative distance (in steps).
        
        Args:
            dx, dy, dz, dr: Relative movements (None to skip axis)
            
        Returns:
            True if command successful, False otherwise
        """
        if dx is not None:
            return self.step_motor(motor=1, steps=dx, speed=2000, acceleration=2)
        
        logger.warning("move_relative called with no movement specified")
        return False
    
    def set_speed(self, speed: int) -> bool:
        """Set motor speed (steps per second).
        
        Args:
            speed: Speed in steps/sec (1-6000)
            
        Returns:
            True if successful
        """
        command = f'S{speed}'
        response = self.send_command(command)
        return response is not None
    
    def set_acceleration(self, acceleration: int) -> bool:
        """Set motor acceleration.
        
        Args:
            acceleration: Acceleration value (0-127)
            
        Returns:
            True if successful
        """
        command = f'A{acceleration}'
        response = self.send_command(command)
        return response is not None
