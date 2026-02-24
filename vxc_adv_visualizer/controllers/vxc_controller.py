"""Velmex VXC XY Stage Controller with ASCII command protocol.

Simple implementation matching reference code exactly.
"""

import serial
import time
import logging
import re
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class VXCController:
    """Controller for Velmex VXC XY stage via USB/Serial.
    
    Simple ASCII command protocol matching Velmex documentation.
    """
    
    def __init__(self, port: str = 'COM8', baudrate: int = 57600, timeout: float = 1):
        """Initialize VXC controller connection.
        
        Args:
            port: COM port name (default: 'COM8')
            baudrate: Baud rate (default: 57600)
            timeout: Serial timeout in seconds (default: 1)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.online = False
        self.last_command_error: Optional[str] = None
        self.lock = threading.Lock()
        
        # Remember successful terminator for position queries (optimization)
        self._position_terminator = ''  # Will be determined on first success
        self._position_terminator_locked = False
        
    def connect(self) -> bool:
        """Establish serial connection to VXC controller.
        
        Returns:
            True if connection successful
        """
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            time.sleep(0.1)  # Allow connection to stabilize
            logger.info(f"Connected to {self.port} at {self.baudrate} baud")
            
            # Go online with echo off
            self.go_online(echo=False)
            
            return True
        except serial.SerialException as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def disconnect(self) -> None:
        """Close serial connection."""
        if self.ser and self.ser.is_open:
            self.go_offline()
            self.ser.close()
            logger.info("Disconnected")
    
    def close(self) -> None:
        """Alias for disconnect() for compatibility."""
        self.disconnect()
    
    def send_command(
        self,
        command: str,
        wait_for_response: bool = False,
        response_type: str = 'ready',
        terminator: str = ''
    ) -> Optional[str]:
        """Send command to VXC controller.
        
        Args:
            command: Command string to send
            wait_for_response: Whether to wait for a response
            response_type: Type of response expected ('ready', 'value', 'status')
            terminator: Optional command terminator (e.g. '\r' or '\r\n')
            
        Returns:
            Response string if wait_for_response=True, otherwise None
        """
        if not self.ser or not self.ser.is_open:
            logger.error("Not connected")
            return None
        
        try:
            with self.lock:
                self.last_command_error = None
                # Clear any pending data - both input and output buffers
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                time.sleep(0.02)  # 20ms delay to ensure buffers are truly clear
                
                # Drain any residual data that arrived after buffer reset
                while self.ser.in_waiting > 0:
                    self.ser.read(self.ser.in_waiting)
                    time.sleep(0.005)

                # Send command
                self.ser.write((command + terminator).encode('ascii'))
                self.ser.flush()
                logger.debug(f"→ {command}")

                if wait_for_response:
                    response = ""
                    start_time = time.time()

                    while True:
                        if self.ser.in_waiting > 0:
                            char = self.ser.read(1).decode('ascii', errors='ignore')
                            response += char

                            # Check for completion characters
                            if response_type == 'ready' and '^' in response:
                                break
                            elif response_type == 'value' and ('\r' in response or '^' in response):
                                break
                            elif response_type == 'status' and char in ['B', 'R', 'J', 'b', 'F']:
                                break

                        # Timeout check
                        if time.time() - start_time > self.timeout:
                            logger.warning(f"Timeout waiting for response to '{command}' (timeout={self.timeout:.1f}s, elapsed={time.time()-start_time:.2f}s)")
                            break

                    elapsed = time.time() - start_time
                    logger.debug(f"← {response.strip()} ({elapsed:.3f}s)")
                    return response.strip()

                return None
            
        except Exception as e:
            self.last_command_error = str(e)
            logger.error(f"Command error: {e}")
            return None
    
    def go_online(self, echo: bool = False) -> None:
        """Put VXC in Online mode.
        
        Args:
            echo: If True, use 'E' (echo on), if False use 'F' (echo off)
        """
        command = 'E' if echo else 'F'
        self.send_command(command)
        self.online = True
        logger.info(f"Online mode {'(echo on)' if echo else '(echo off)'}")
        time.sleep(0.1)
    
    def go_offline(self) -> None:
        """Put VXC in Offline/Jog mode."""
        if self.online:
            self.send_command('Q')
            self.online = False
            logger.info("Offline mode (Jog)")
    
    def clear_program(self) -> None:
        """Clear all commands from current program."""
        self.send_command('C')
        logger.debug("Program cleared")
    
    def verify_status(self) -> Optional[str]:
        """Verify controller status.
        
        Returns:
            'R' = Ready, 'B' = Busy, 'J' = Jog mode, 'b' = Jogging, 'F' = Fault
        """
        response = self.send_command('V', wait_for_response=True, response_type='status')
        
        status_map = {
            'R': 'Ready',
            'B': 'Busy',
            'J': 'Jog mode',
            'b': 'Jogging',
            'F': 'Fault'
        }
        
        if response and response in status_map:
            logger.info(f"Status: {status_map[response]}")
            return response
        else:
            logger.warning(f"Unknown status: {response}")
            return None
    
    def get_position(self, motor: int = 1) -> Optional[int]:
        """Get current motor position with optimized terminator handling.
        
        Args:
            motor: Motor number (1-4)
            
        Returns:
            Position as integer, or None if error
        """
        position_commands = {1: 'X', 2: 'Y', 3: 'Z', 4: 'T'}
        
        if motor not in position_commands:
            logger.error(f"Invalid motor number: {motor}")
            return None
        
        # If we've determined the working terminator, try it first (optimization)
        if self._position_terminator_locked:
            response = self.send_command(
                position_commands[motor],
                wait_for_response=True,
                response_type='value',
                terminator=self._position_terminator
            )
            
            if response:
                return self._parse_position_response(response, motor)
            # If it failed, fall back to trying all terminators
            else:
                logger.warning(f"Cached terminator failed for motor {motor}, trying all terminators")
                self._position_terminator_locked = False  # Reset to re-learn
        
        # Try all terminators to find one that works
        response = None
        terminators = ['', '\r', '\r\n', '\n']
        for terminator in terminators:
            response = self.send_command(
                position_commands[motor],
                wait_for_response=True,
                response_type='value',
                terminator=terminator
            )
            if response:
                # Lock in this terminator for future use
                if not self._position_terminator_locked:
                    self._position_terminator = terminator
                    self._position_terminator_locked = True
                    logger.info(f"Locked position query terminator: {repr(terminator)}")
                
                return self._parse_position_response(response, motor)
            time.sleep(0.05)
        
        logger.warning(f"No position response for motor {motor}")
        return None
    
    def _parse_position_response(self, response: str, motor: int) -> Optional[int]:
        """Parse position from response string.
        
        Args:
            response: Response string from controller
            motor: Motor number for logging
            
        Returns:
            Position as integer, or None if cannot parse
        """
        try:
            position = int(response.strip())
            logger.debug(f"Motor {motor} position: {position}")
            return position
        except ValueError:
            match = re.search(r"-?\d+", response)
            if match:
                position = int(match.group(0))
                logger.debug(f"Motor {motor} position (parsed): {position}")
                return position
            logger.error(f"Invalid position response: {response}")
            return None
    
    def zero_position(self) -> None:
        """Zero all motor positions."""
        self.send_command('N')
        logger.info("Position zeroed")
    
    def step_motor(self, motor: int = 1, steps: int = 400, speed: int = 2000, 
                   acceleration: int = 2, wait: bool = True) -> bool:
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
        if not self.online:
            logger.error("Must be online to send motion commands")
            return False
        
        # Log the exact parameters for diagnostics
        logger.info(f"step_motor called: motor={motor}, steps={steps:+d}, speed={speed}, accel={acceleration}, timeout={self.timeout:.1f}s")
        
        # Clear previous commands
        self.clear_program()
        
        # Set acceleration
        accel_cmd = f'A{motor}M{acceleration},'
        self.send_command(accel_cmd)
        
        # Set speed
        speed_cmd = f'S{motor}M{speed},'
        self.send_command(speed_cmd)
        
        # Set index (step) command
        index_cmd = f'I{motor}M{steps},'
        self.send_command(index_cmd)
        
        logger.info(f"Commands queued: Motor {motor}, {steps:+d} steps @ {speed} steps/sec")
        
        # Run the program
        response = self.send_command('R', wait_for_response=wait, response_type='ready')
        
        if wait:
            if response and '^' in response:
                logger.info(f"Movement complete: Motor {motor} moved {steps:+d} steps successfully")
                return True
            elif response and 'F' in response:
                logger.error(f"Movement FAILED: Controller in FAULT state (response: {response})")
                return False
            elif response:
                logger.warning(f"Movement uncertain: Unexpected response '{response}' (no '^' found)")
                return False
            else:
                logger.error(f"Movement FAILED: No response from controller (timeout={self.timeout:.1f}s)")
                return False
        
        return True
    
    def stop_motor(self) -> None:
        """Decelerate motor to stop."""
        self.send_command('D')
        logger.info("Stop command sent (decelerate)")
    
    def kill_motion(self) -> None:
        """Immediately stop all motion."""
        self.send_command('K')
        logger.info("Kill command sent (immediate stop)")
    
    # ========== Compatibility methods for GUI ==========
    
    def move_absolute(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        """Move to absolute position.
        
        Args:
            x: Target X position in steps
            y: Target Y position in steps
        """
        if x is not None:
            current_x = self.get_position(motor=1)
            if current_x is not None:
                dx = int(x - current_x)
                if dx != 0:
                    self.step_motor(motor=1, steps=dx)
        
        if y is not None:
            current_y = self.get_position(motor=2)
            if current_y is not None:
                dy = int(y - current_y)
                if dy != 0:
                    self.step_motor(motor=2, steps=dy)
    
    def jog_to(self, target_x: int, target_y: int, speed: int = 2000, acceleration: int = 2) -> bool:
        """Jog to target position: X axis first, then Y axis.
        
        Moves the stage from its current position to the target position by:
        1. Moving along X axis to target X position
        2. Then moving along Y axis to target Y position
        
        Args:
            target_x: Target X position in steps
            target_y: Target Y position in steps
            speed: Movement speed in steps/second (1-6000, default: 2000)
            acceleration: Acceleration value (0-127, default: 2)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.online:
            logger.error("Must be online to jog")
            return False
        
        # Check controller status before moving
        status = self.verify_status()
        if status == 'B':
            logger.warning("Controller reports BUSY status before jog - waiting 2s")
            time.sleep(2.0)
            status = self.verify_status()
        if status == 'F':
            logger.error("Cannot jog: Controller in FAULT state")
            return False
        if status not in ['R', 'J']:
            logger.warning(f"Controller status unclear before jog: '{status}'")
        
        # Save original timeout
        original_timeout = self.timeout
        
        # Get current position (Motor 2 = X-axis, Motor 1 = Y-axis)
        current_x = self.get_position(motor=2)
        current_y = self.get_position(motor=1)
        
        if current_x is None or current_y is None:
            logger.error("Cannot jog: unable to read current position")
            return False
        
        # Calculate required movement
        dx = target_x - current_x
        dy = target_y - current_y
        
        logger.info(f"=== JOG START: ({current_x}, {current_y}) → ({target_x}, {target_y}) ===")
        logger.info(f"Movement delta: X={dx:+d} steps, Y={dy:+d} steps")
        
        # Calculate timeout with enhanced safety margins:
        # Base time + 8 second buffer + 2x safety multiplier, minimum 10 seconds
        safety_multiplier = 2.0
        max_move_time_x = ((abs(dx) / max(speed, 1)) + 8.0) * safety_multiplier if dx != 0 else 0
        max_move_time_y = ((abs(dy) / max(speed, 1)) + 8.0) * safety_multiplier if dy != 0 else 0
        max_move_time_x = max(max_move_time_x, 10.0) if dx != 0 else 0
        max_move_time_y = max(max_move_time_y, 10.0) if dy != 0 else 0
        
        logger.info(f"Calculated timeouts: X={max_move_time_x:.1f}s, Y={max_move_time_y:.1f}s")
        
        try:
            # Move X axis first (Motor 2)
            if dx != 0:
                logger.info(f"[X-AXIS] Moving Motor 2: {dx:+d} steps (timeout: {max_move_time_x:.1f}s)")
                # Set timeout for this movement
                self.timeout = max_move_time_x
                move_start = time.time()
                
                if not self.step_motor(motor=2, steps=dx, speed=speed, acceleration=acceleration, wait=True):
                    logger.error(f"[X-AXIS] Movement FAILED after {time.time()-move_start:.2f}s")
                    self.timeout = original_timeout
                    return False
                    
                logger.info(f"[X-AXIS] Movement complete in {time.time()-move_start:.2f}s")
                time.sleep(0.15)  # Brief pause between axes
            else:
                logger.info("[X-AXIS] Already at target position")
            
            # Then move Y axis (Motor 1)
            if dy != 0:
                logger.info(f"[Y-AXIS] Moving Motor 1: {dy:+d} steps (timeout: {max_move_time_y:.1f}s)")
                # Set timeout for this movement
                self.timeout = max_move_time_y
                move_start = time.time()
                
                if not self.step_motor(motor=1, steps=dy, speed=speed, acceleration=acceleration, wait=True):
                    logger.error(f"[Y-AXIS] Movement FAILED after {time.time()-move_start:.2f}s")
                    self.timeout = original_timeout
                    return False
                    
                logger.info(f"[Y-AXIS] Movement complete in {time.time()-move_start:.2f}s")
                time.sleep(0.15)  # Brief pause after movement
            else:
                logger.info("[Y-AXIS] Already at target position")
            
            # Verify final position
            final_x = self.get_position(motor=2)
            final_y = self.get_position(motor=1)
            if final_x is not None and final_y is not None:
                logger.info(f"=== JOG COMPLETE: Final position ({final_x}, {final_y}) ===")
                pos_error_x = abs(final_x - target_x)
                pos_error_y = abs(final_y - target_y)
                if pos_error_x > 10 or pos_error_y > 10:
                    logger.warning(f"Position error exceeds tolerance: X_err={pos_error_x}, Y_err={pos_error_y}")
            else:
                logger.warning("=== JOG COMPLETE: Could not verify final position ===")
            
            return True
            
        finally:
            # Always restore original timeout
            self.timeout = original_timeout
