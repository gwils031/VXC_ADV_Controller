"""VXC Controller + Auto-Merge GUI for FlowTracker2 ADV data integration.

Note: ADV data comes from FlowTracker2 software exports (every ~1 minute),
not through direct program connection.
"""

import logging
import time
import yaml
import queue
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QSpinBox, QComboBox, QMessageBox,
    QGroupBox, QGridLayout, QTextEdit, QDoubleSpinBox, QLineEdit,
    QApplication, QSlider
)
from PyQt5.QtCore import Qt, QTimer, QObject, QThread, pyqtSignal
from PyQt5.QtGui import QFont

from ..controllers.vxc_controller import VXCController
from ..utils.serial_utils import list_available_ports
from .auto_merge_tab import AutoMergeTab
from .live_data_tab import LiveDataTab
from .cross_section_tab import CrossSectionTab
from .cross_section_view_tab import CrossSectionViewTab
from ..data.vxc_position_logger import VXCPositionLogger
from ..data.boundary_manager import BoundaryManager

logger = logging.getLogger(__name__)


class VXCConnectWorker(QObject):
    """Background worker for VXC auto-detect and connection."""

    connected = pyqtSignal(object, str)
    failed = pyqtSignal(str)

    def __init__(self, selected_port: Optional[str], baudrate: int, timeout: float = 1.0):
        super().__init__()
        self.selected_port = selected_port
        self.baudrate = baudrate
        self.timeout = timeout

    def run(self):
        port_entries = list_available_ports()
        tried = []

        ordered_ports = []
        if self.selected_port:
            selected = next((p for p in port_entries if p[0] == self.selected_port), None)
            if selected:
                ordered_ports.append(selected)
            else:
                ordered_ports.append((self.selected_port, ""))
        ordered_ports.extend([p for p in port_entries if p not in ordered_ports])

        for port, desc in ordered_ports:
            if not self._is_likely_vxc_port(desc):
                tried.append(f"{port} (skipped: {desc})")
                continue
            tried.append(port)
            controller = self._try_connect_port(port)
            if controller is not None:
                self.connected.emit(controller, port)
                return

        self.failed.emit(f"VXC controller not found. Tried: {', '.join(tried)}")

    def _try_connect_port(self, port: str) -> Optional[VXCController]:
        controller = VXCController(port, self.baudrate, timeout=self.timeout)
        if not controller.connect():
            controller.close()
            return None

        status = controller.verify_status()
        if status is None:
            controller.close()
            return None

        return controller

    def _is_likely_vxc_port(self, description: str) -> bool:
        """Heuristic filter to avoid Bluetooth/virtual ports that can hang on open."""
        if not description:
            return True
        desc = description.lower()
        if "bluetooth" in desc or "bt" in desc:
            return False
        if "usb" in desc or "ftdi" in desc or "serial" in desc:
            return True
        return True


class VXCPositionWorker(QObject):
    """Background worker for polling VXC positions."""

    position_updated = pyqtSignal(int, int)
    error = pyqtSignal(str)
    fatal_error = pyqtSignal(str)  # Emitted when port is unrecoverable

    def __init__(self, controller: VXCController, interval_sec: float = 1.0):
        super().__init__()
        self.controller = controller
        self.interval_sec = interval_sec
        self._running = False
        self._error_backoff_sec = 1.0
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5

    def start(self):
        self._running = True
        while self._running:
            try:
                x = self.controller.get_position(motor=2)
                y = self.controller.get_position(motor=1)
                if x is not None and y is not None:
                    self.position_updated.emit(x, y)
                    self._consecutive_errors = 0
                else:
                    self._consecutive_errors += 1
                    self.error.emit("No position response")
                    if self._consecutive_errors >= self._max_consecutive_errors or self.controller.port_dead:
                        self.fatal_error.emit("Port unresponsive — disconnecting automatically")
                        self._running = False
                        break
                    time.sleep(self._error_backoff_sec)
            except Exception as e:
                self._consecutive_errors += 1
                self.error.emit(str(e))
                if self._consecutive_errors >= self._max_consecutive_errors:
                    self.fatal_error.emit(f"Too many errors: {e}")
                    self._running = False
                    break
                time.sleep(self._error_backoff_sec)
            time.sleep(self.interval_sec)

    def stop(self):
        self._running = False


class VXCLogWorker(QObject):
    """Background worker to write VXC position logs with continuous timestamps."""

    error = pyqtSignal(str)
    stopped = pyqtSignal()  # Emitted when worker stops

    def __init__(self, logger: VXCPositionLogger, controller: VXCController, write_interval_sec: float = 0.5):
        super().__init__()
        self.logger = logger
        self.controller = controller
        self.write_interval_sec = write_interval_sec
        self._running = False
        self._heartbeat_counter = 0  # For health monitoring

    def start(self):
        """Run continuous VXC position logging with robust error handling."""
        self._running = True
        
        # Move start_logging() into try/except - CRITICAL FIX
        try:
            # Start logging file
            if not hasattr(self.logger, 'current_file') or self.logger.current_file is None:
                self.logger.start_logging()
        except Exception as e:
            logger.error(f"Failed to start VXC logging: {e}")
            self.error.emit(f"Failed to start logging: {e}")
            self._running = False
            self.stopped.emit()
            return
        
        # Main logging loop with comprehensive error handling
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        while self._running:
            try:
                self._heartbeat_counter += 1
                
                # Poll current VXC position
                x = self.controller.get_position(motor=2)  # X axis
                y = self.controller.get_position(motor=1)  # Y axis
                
                if x is not None and y is not None:
                    # Write current position with timestamp
                    self.logger.log_position(x_steps=x, y_steps=y, quality="GOOD")
                    consecutive_errors = 0  # Reset error counter on success
                else:
                    # VXC not responding - log (0,0) to maintain timeline
                    logger.warning("VXC position unavailable, logging (0,0)")
                    self.logger.log_position(x_steps=0, y_steps=0, quality="VXC Moving")
                    consecutive_errors += 1
                    
            except Exception as e:
                consecutive_errors += 1
                error_msg = f"VXC logging error (#{consecutive_errors}): {e}"
                logger.error(error_msg)
                self.error.emit(error_msg)
                
                # Try to log error position to maintain timeline
                try:
                    self.logger.log_position(x_steps=0, y_steps=0, quality="VXC Moving")
                except:
                    pass
                
                # If too many consecutive errors, stop logging
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"VXC logging stopped after {max_consecutive_errors} consecutive errors")
                    self.error.emit(f"CRITICAL: Stopped after {max_consecutive_errors} consecutive errors")
                    break
            
            # Sleep before next poll
            time.sleep(self.write_interval_sec)
        
        # Cleanup when loop exits
        try:
            self.logger.stop_logging()
        except:
            pass
        
        self._running = False
        self.stopped.emit()
        logger.warning("VXC logging worker stopped")

    def stop(self):
        """Stop the logging worker."""
        self._running = False
    
    def get_heartbeat(self) -> int:
        """Get heartbeat counter for health monitoring."""
        return self._heartbeat_counter


class SliderJogWorker(QObject):
    """Background worker for slider-commanded X-then-Y jog moves.

    Offloads blocking serial I/O to a QThread so the GUI remains fully
    responsive during moves that can take tens of seconds.
    """

    progress = pyqtSignal(str)
    completed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, controller, delta_x: int, delta_y: int, speed: int = 2000):
        super().__init__()
        self.controller = controller
        self.delta_x = delta_x
        self.delta_y = delta_y
        self.speed = speed

    def run(self):
        """Execute X-first, then Y movement in the background thread."""
        try:
            if self.delta_x != 0:
                self.progress.emit(f"Moving X axis ({self.delta_x:+d} steps)...")
                timeout = abs(self.delta_x) / max(self.speed, 1) + 3.0
                old_timeout = self.controller.timeout
                self.controller.timeout = max(timeout, 3.0)
                success = self.controller.step_motor(
                    motor=2, steps=self.delta_x, speed=self.speed,
                    acceleration=2, wait=True,
                )
                self.controller.timeout = old_timeout
                if not success:
                    self.failed.emit("X axis movement timed out or failed")
                    return

            if self.delta_y != 0:
                self.progress.emit(f"Moving Y axis ({self.delta_y:+d} steps)...")
                timeout = abs(self.delta_y) / max(self.speed, 1) + 3.0
                old_timeout = self.controller.timeout
                self.controller.timeout = max(timeout, 3.0)
                success = self.controller.step_motor(
                    motor=1, steps=self.delta_y, speed=self.speed,
                    acceleration=2, wait=True,
                )
                self.controller.timeout = old_timeout
                if not success:
                    self.failed.emit("Y axis movement timed out or failed")
                    return

            self.completed.emit()

        except Exception as e:
            self.failed.emit(str(e))


class FindOriginWorker(QObject):
    """Background worker to move both axes to origin (0,0) position."""

    progress = pyqtSignal(str)
    completed = pyqtSignal(dict)  # Returns dict with x_min and y_min values
    failed = pyqtSignal(str)

    def __init__(
        self,
        controller: VXCController,
        step_size: int,
        speed: int,
        max_seconds: float,
    ):
        super().__init__()
        self.controller = controller
        self.step_size = step_size
        self.speed = speed
        self.max_seconds = max_seconds

    def run(self):
        """Move X to origin first, then Y to origin."""
        results = {}
        
        # Find X origin (min)
        self.progress.emit("Finding X-axis origin...")
        x_result = self._find_axis_limit(axis="X", direction=-1)
        if x_result is None:
            self.failed.emit("Failed to find X-axis origin")
            return
        results['x_min_m'] = x_result
        
        # Small pause between axes
        time.sleep(0.5)
        
        # Find Y origin (min)
        self.progress.emit("Finding Y-axis origin...")
        y_result = self._find_axis_limit(axis="Y", direction=-1)
        if y_result is None:
            self.failed.emit("Failed to find Y-axis origin")
            return
        results['y_min_m'] = y_result
        
        self.progress.emit("Origin found successfully!")
        self.completed.emit(results)

    def _find_axis_limit(self, axis: str, direction: int):
        """Find a single axis limit. Returns position in steps or None on failure."""
        motor = 2 if axis == "X" else 1
        start_time = time.time()
        iteration = 0
        stall_count = 0
        no_response_count = 0
        original_timeout = self.controller.timeout
        
        # Set timeout long enough for single move + buffer
        move_timeout = (abs(self.step_size) / max(self.speed, 1)) + 3.0
        self.controller.timeout = max(move_timeout, 5.0)
        
        last_pos = self.controller.get_position(motor=motor)
        if last_pos is None:
            self.controller.timeout = original_timeout
            return None

        while True:
            iteration += 1
            elapsed = time.time() - start_time
            
            # Check global timeout
            if elapsed > self.max_seconds:
                self.controller.timeout = original_timeout
                return None

            # Report progress
            self.progress.emit(
                f"{axis} origin search: iteration {iteration}, pos={last_pos} ({elapsed:.0f}s)"
            )

            # Move motor and wait for completion
            moved = self.controller.step_motor(
                motor=motor,
                steps=direction * self.step_size,
                speed=self.speed,
                acceleration=2,
                wait=True,
            )
            
            if not moved:
                self.controller.timeout = original_timeout
                return None

            if self.controller.last_command_error:
                self.controller.timeout = original_timeout
                return None

            # Check if we hit limit switch (fault status)
            status = self.controller.verify_status()
            if status == "F":
                # Hit physical stop! Success!
                self.progress.emit(f"{axis} origin found (limit switch)")
                self.controller.timeout = original_timeout
                return last_pos

            # Get current position to check for stall
            current_pos = None
            for _ in range(3):
                current_pos = self.controller.get_position(motor=motor)
                if current_pos is not None:
                    break
                time.sleep(0.2)
                
            if current_pos is None:
                no_response_count += 1
                if no_response_count >= 3:
                    # Lost communication, assume we're at boundary
                    self.controller.timeout = original_timeout
                    return last_pos
                continue

            no_response_count = 0

            # Check for mechanical stall (position not changing)
            if current_pos == last_pos:
                stall_count += 1
            else:
                stall_count = 0

            last_pos = current_pos

            # If stalled for 3 consecutive moves, we've hit the limit
            if stall_count >= 3:
                self.progress.emit(f"{axis} origin found (mechanical stall)")
                self.controller.timeout = original_timeout
                return last_pos


class BoundaryFindWorker(QObject):
    """Background worker to move an axis toward a physical stop."""

    progress = pyqtSignal(str)
    completed = pyqtSignal(str, str, int)
    failed = pyqtSignal(str)

    def __init__(
        self,
        controller: VXCController,
        axis: str,
        direction: int,
        step_size: int,
        speed: int,
        max_seconds: float,
    ):
        super().__init__()
        self.controller = controller
        self.axis = axis
        self.direction = direction
        self.step_size = step_size
        self.speed = speed
        self.max_seconds = max_seconds

    def run(self):
        motor = 2 if self.axis == "X" else 1
        start_time = time.time()
        iteration = 0
        stall_count = 0
        no_response_count = 0
        original_timeout = self.controller.timeout
        # Set timeout long enough for single move + buffer
        move_timeout = (abs(self.step_size) / max(self.speed, 1)) + 3.0
        self.controller.timeout = max(move_timeout, 5.0)
        
        last_pos = self.controller.get_position(motor=motor)

        if last_pos is None:
            self.failed.emit(f"No position response for {self.axis}-axis")
            self.controller.timeout = original_timeout
            return

        while True:
            iteration += 1
            elapsed = time.time() - start_time
            
            # Check global timeout
            if elapsed > self.max_seconds:
                self.failed.emit(f"Timeout finding {self.axis} boundary after {iteration} iterations")
                self.controller.timeout = original_timeout
                return

            # Report progress with iteration count
            self.progress.emit(
                f"{self.axis} {self._direction_label()} iteration {iteration}, pos={last_pos} ({elapsed:.0f}s)"
            )

            # Move motor and WAIT for completion
            moved = self.controller.step_motor(
                motor=motor,
                steps=self.direction * self.step_size,
                speed=self.speed,
                acceleration=2,
                wait=True,  # Wait for VXC completion signal
            )
            
            if not moved:
                self.failed.emit(f"Move failed while finding {self.axis} boundary")
                self.controller.timeout = original_timeout
                return

            if self.controller.last_command_error:
                self.failed.emit(
                    f"Command error while moving {self.axis}: {self.controller.last_command_error}"
                )
                self.controller.timeout = original_timeout
                return

            # Now check if we hit limit switch (fault status)
            status = self.controller.verify_status()
            if status == "F":
                # Hit physical stop! Success!
                self.progress.emit(f"{self.axis} {self._direction_label()} found limit switch!")
                self.completed.emit(self.axis, self._direction_label(), last_pos)
                self.controller.timeout = original_timeout
                return

            # Get current position to check for stall
            current_pos = None
            for _ in range(3):
                current_pos = self.controller.get_position(motor=motor)
                if current_pos is not None:
                    break
                time.sleep(0.2)
                
            if current_pos is None:
                no_response_count += 1
                if no_response_count >= 3:
                    # Lost communication, assume we're at boundary
                    self.progress.emit(f"{self.axis} {self._direction_label()} lost position signal")
                    self.completed.emit(self.axis, self._direction_label(), last_pos)
                    self.controller.timeout = original_timeout
                    return
                continue

            no_response_count = 0

            # Check for mechanical stall (position not changing)
            if current_pos == last_pos:
                stall_count += 1
            else:
                stall_count = 0

            last_pos = current_pos

            # If stalled for 3 consecutive moves, we've hit the limit
            if stall_count >= 3:
                self.progress.emit(f"{self.axis} {self._direction_label()} detected mechanical stall")
                self.completed.emit(self.axis, self._direction_label(), last_pos)
                self.controller.timeout = original_timeout
                return

    def _direction_label(self) -> str:
        return "Min" if self.direction < 0 else "Max"


class WorkspaceCalibrateWorker(QObject):
    """Background worker to calibrate all workspace boundaries (X/Y min/max)."""

    progress = pyqtSignal(str)
    completed = pyqtSignal(dict)  # Returns dict with x_min_steps, x_max_steps, y_min_steps, y_max_steps
    failed = pyqtSignal(str)

    def __init__(
        self,
        controller: VXCController,
        step_size: int,
        speed: int,
        max_seconds: float,
    ):
        super().__init__()
        self.controller = controller
        self.step_size = step_size
        self.speed = speed
        self.max_seconds = max_seconds

    def run(self):
        """Find all four workspace boundaries in sequence and zero at minimums."""
        try:
            # Find X minimum (absolute position)
            self.progress.emit("===== STARTING X-AXIS MINIMUM DETECTION =====")
            x_min_raw = self._find_axis_limit(axis="X", direction=-1)
            if x_min_raw is None:
                self.failed.emit("Failed to find X-axis minimum")
                return
            self.progress.emit(f">>> X minimum found at: {x_min_raw} steps")
            time.sleep(0.5)
            
            # Find X maximum (absolute position)
            self.progress.emit("===== STARTING X-AXIS MAXIMUM DETECTION =====")
            x_max_raw = self._find_axis_limit(axis="X", direction=1)
            if x_max_raw is None:
                self.failed.emit("Failed to find X-axis maximum")
                return
            self.progress.emit(f">>> X maximum found at: {x_max_raw} steps")
            time.sleep(0.5)
            
            # Calculate X range
            x_range = x_max_raw - x_min_raw
            self.progress.emit(f">>> X-axis range calculated: {x_range} steps (from {x_min_raw} to {x_max_raw})")
            
            # Find Y minimum (absolute position)
            self.progress.emit("===== STARTING Y-AXIS MINIMUM DETECTION =====")
            y_min_raw = self._find_axis_limit(axis="Y", direction=-1)
            if y_min_raw is None:
                self.failed.emit("Failed to find Y-axis minimum")
                return
            self.progress.emit(f">>> Y minimum found at: {y_min_raw} steps")
            time.sleep(0.5)
            
            # Find Y maximum (absolute position)
            self.progress.emit("===== STARTING Y-AXIS MAXIMUM DETECTION =====")
            y_max_raw = self._find_axis_limit(axis="Y", direction=1)
            if y_max_raw is None:
                self.failed.emit("Failed to find Y-axis maximum")
                return
            self.progress.emit(f">>> Y maximum found at: {y_max_raw} steps")
            time.sleep(0.5)
            
            # Calculate ranges
            x_range = abs(x_max_raw - x_min_raw)
            y_range = abs(y_max_raw - y_min_raw)
            self.progress.emit(f">>> Y-axis range calculated: {y_range} steps (from {y_min_raw} to {y_max_raw})")
            self.progress.emit(f">>> Travel ranges: X={x_range} steps, Y={y_range} steps")

            # Return to X minimum before zeroing so origin = physical min
            self.progress.emit("===== RETURNING TO X MINIMUM =====")
            x_return = self._find_axis_limit(axis="X", direction=-1)
            if x_return is None:
                self.failed.emit("Failed to return to X minimum")
                return
            self.progress.emit(f">>> Returned to X minimum at: {x_return} steps")
            time.sleep(0.5)

            # Return to Y minimum
            self.progress.emit("===== RETURNING TO Y MINIMUM =====")
            y_return = self._find_axis_limit(axis="Y", direction=-1)
            if y_return is None:
                self.failed.emit("Failed to return to Y minimum")
                return
            self.progress.emit(f">>> Returned to Y minimum at: {y_return} steps")
            time.sleep(0.5)

            # Zero position at the minimum (origin) so 0,0 = physical min
            self.progress.emit("===== ZEROING POSITION AT MINIMUM (ORIGIN) =====")
            self.controller.zero_position()
            time.sleep(0.5)
            
            # Verify zeroing
            x_verify = self.controller.get_position(motor=2)
            y_verify = self.controller.get_position(motor=1)
            self.progress.emit(f"Position after zeroing: X={x_verify}, Y={y_verify}")
            
            # Build results: origin = 0, max = full travel range
            results = {
                'x_min_steps': 0,
                'x_max_steps': x_range,
                'y_min_steps': 0,
                'y_max_steps': y_range
            }
            
            self.progress.emit(f"===== CALIBRATION COMPLETE =====")
            self.progress.emit(f"Final boundaries: X=[0, {x_range}], Y=[0, {y_range}]")
            self.completed.emit(results)
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self.progress.emit(f"Exception occurred: {error_details}")
            self.failed.emit(f"Workspace calibration error: {str(e)}")

    def _find_axis_limit(self, axis: str, direction: int):
        """Find a single axis limit. Returns position in steps or None on failure."""
        motor = 2 if axis == "X" else 1
        start_time = time.time()
        iteration = 0
        stall_count = 0
        no_response_count = 0
        original_timeout = self.controller.timeout
        
        # Set timeout long enough for single move + buffer
        move_timeout = (abs(self.step_size) / max(self.speed, 1)) + 3.0
        self.controller.timeout = max(move_timeout, 5.0)
        
        last_pos = self.controller.get_position(motor=motor)
        if last_pos is None:
            self.controller.timeout = original_timeout
            return None

        dir_label = "Min" if direction < 0 else "Max"
        self.progress.emit(f"{axis} {dir_label}: starting at position {last_pos}")

        while True:
            iteration += 1
            elapsed = time.time() - start_time
            
            # Check global timeout
            if elapsed > self.max_seconds:
                self.progress.emit(f"{axis} {dir_label}: TIMEOUT after {elapsed:.0f}s")
                self.controller.timeout = original_timeout
                return None

            # Report progress
            self.progress.emit(
                f"{axis} {dir_label}: iteration {iteration}, pos={last_pos} ({elapsed:.0f}s)"
            )

            # Move motor and wait for completion
            moved = self.controller.step_motor(
                motor=motor,
                steps=direction * self.step_size,
                speed=self.speed,
                acceleration=2,
                wait=True,
            )
            
            if not moved:
                self.progress.emit(f"{axis} {dir_label}: Move command failed")
                self.controller.timeout = original_timeout
                return None

            if self.controller.last_command_error:
                self.progress.emit(f"{axis} {dir_label}: Command error: {self.controller.last_command_error}")
                self.controller.timeout = original_timeout
                return None

            # Get current position AFTER the move
            current_pos = None
            for attempt in range(3):
                current_pos = self.controller.get_position(motor=motor)
                if current_pos is not None:
                    break
                time.sleep(0.2)
                
            if current_pos is None:
                no_response_count += 1
                self.progress.emit(f"{axis} {dir_label}: No position response (count: {no_response_count})")
                if no_response_count >= 3:
                    # Lost communication, return last known position
                    self.progress.emit(f"{axis} {dir_label}: Lost communication at {last_pos}")
                    self.controller.timeout = original_timeout
                    return last_pos
                continue

            no_response_count = 0

            # Check if we hit limit switch (fault status) AFTER getting position
            status = self.controller.verify_status()
            if status == "F":
                # Hit physical stop! Return CURRENT position
                self.progress.emit(f"{axis} {dir_label}: LIMIT SWITCH detected at position {current_pos}")
                self.controller.timeout = original_timeout
                return current_pos

            # Check for mechanical stall (position not changing)
            if current_pos == last_pos:
                stall_count += 1
                self.progress.emit(f"{axis} {dir_label}: Stall detected (count: {stall_count}, pos: {current_pos})")
                
                # If stalled for 3 consecutive moves, we've hit the limit
                if stall_count >= 3:
                    self.progress.emit(f"{axis} {dir_label}: MECHANICAL STALL confirmed at position {current_pos}")
                    self.controller.timeout = original_timeout
                    return current_pos
            else:
                stall_count = 0
                self.progress.emit(f"{axis} {dir_label}: Moved from {last_pos} to {current_pos} (delta: {current_pos - last_pos})")

            last_pos = current_pos

    def _move_to_position(self, motor: int, target_position: int) -> bool:
        """Move motor to a specific absolute position.
        
        Args:
            motor: Motor number (1=Y, 2=X)
            target_position: Target position in steps
            
        Returns:
            True if move succeeded, False otherwise
        """
        axis_name = "X" if motor == 2 else "Y"
        
        # Get current position
        current_pos = self.controller.get_position(motor=motor)
        if current_pos is None:
            self.progress.emit(f"ERROR: Cannot get current {axis_name} position")
            return False
        
        # Calculate steps needed
        steps_to_move = target_position - current_pos
        
        self.progress.emit(f"{axis_name}: Current={current_pos}, Target={target_position}, Delta={steps_to_move:+d}")
        
        if abs(steps_to_move) < 10:
            # Already at target
            self.progress.emit(f"{axis_name}: Already at target position (within 10 steps)")
            return True
        
        # Move to target
        self.progress.emit(f"Moving {axis_name}: {current_pos} → {target_position} ({steps_to_move:+d} steps)")
        
        success = self.controller.step_motor(
            motor=motor,
            steps=steps_to_move,
            speed=self.speed,
            acceleration=2,
            wait=True
        )
        
        if not success:
            self.progress.emit(f"ERROR: step_motor() returned False for {axis_name}")
            return False
        
        # Verify we reached the target
        final_pos = self.controller.get_position(motor=motor)
        if final_pos is None:
            self.progress.emit(f"WARNING: Cannot verify final {axis_name} position")
            return False  # Consider this a failure
        
        position_error = abs(final_pos - target_position)
        self.progress.emit(f"{axis_name}: Final position={final_pos}, Error={position_error} steps")
        
        if position_error > 100:
            self.progress.emit(f"WARNING: Large position error ({position_error} steps) for {axis_name}")
            # Still return True if the move command succeeded, as the error might be acceptable
        
        return True


class MainWindow(QMainWindow):
    """VXC Controller + Auto-Merge GUI for FlowTracker2 data integration."""

    STEPS_PER_INCH = 4000.0
    METERS_PER_FOOT = 0.3048
    METERS_PER_INCH = 0.0254
    
    def __init__(self, config_dir: str = "./config"):
        """Initialize main window.
        
        Args:
            config_dir: Configuration directory path
        """
        super().__init__()
        self.config_dir = config_dir
        
        # Load configs
        self.vxc_config = self._load_config("vxc_config.yaml")
        self.experiment_config = self._load_config("experiment_config.yaml")
        
        # Initialize boundary manager
        experiment_config_path = Path(self.config_dir) / "experiment_config.yaml"
        if not experiment_config_path.exists():
            experiment_config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"
        self.boundary_manager = BoundaryManager(experiment_config_path)
        self.boundaries = self.boundary_manager.boundaries
        
        # Hardware
        self.vxc: Optional[VXCController] = None
        
        # VXC Position Logger for auto-merge
        self.vxc_logger: Optional[VXCPositionLogger] = None
        
        # UI state
        self._closing = False
        self.jog_axis = None
        self.jog_direction = 0
        self.jog_repeat_delay_ms = 300
        self.jog_repeat_active = False
        self.jog_distances_m = [0.00635, 0.0127, 0.01905, 0.0254]
        self.slider_being_adjusted = False  # Track if user is interacting with sliders
        self.vxc_connect_thread: Optional[QThread] = None
        self.vxc_connect_worker: Optional[VXCConnectWorker] = None
        self.vxc_connecting = False
        self.vxc_poll_thread: Optional[QThread] = None
        self.vxc_poll_worker: Optional[VXCPositionWorker] = None
        self.vxc_log_thread: Optional[QThread] = None
        self.vxc_log_worker: Optional[VXCLogWorker] = None
        self.boundary_thread: Optional[QThread] = None
        self.boundary_worker: Optional[BoundaryFindWorker] = None
        self.slider_jog_thread: Optional[QThread] = None
        self.slider_jog_worker: Optional[SliderJogWorker] = None
        self.boundary_limits = self.experiment_config.get("boundaries", {})
        self.boundary_max_seconds = 180.0  # Increased to handle full workspace traversal
        self.boundary_step_size = 4000
        self.boundary_speed = 2000
        
        # Setup UI
        self.setWindowTitle("VXC Controller + ADV Auto-Merge")
        self.setGeometry(100, 100, 1200, 800)
        
        self._setup_ui()
        self._setup_timers()
        
        logger.info("MainWindow initialized")
    
    def _load_config(self, filename: str) -> dict:
        """Load YAML configuration file.
        
        Args:
            filename: Config file name
            
        Returns:
            Configuration dictionary
        """
        config_path = Path(self.config_dir) / filename
        if not config_path.exists():
            config_path = Path(__file__).resolve().parents[1] / "config" / filename
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load {filename}: {e}")
            return {}
    
    def _setup_ui(self):
        """Setup user interface."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        
        # Tab widget
        self.tabs = QTabWidget()
        
        # VXC Controller tab
        self.tabs.addTab(self._create_vxc_tab(), "VXC Controller")
        
        # Auto-Merge tab
        self.auto_merge_tab = AutoMergeTab(vxc_logger=self.vxc_logger)
        self.tabs.addTab(self.auto_merge_tab, "Auto-Merge")

        # Live Data tab (with boundaries)
        self.live_data_tab = LiveDataTab(boundaries=self.boundaries)
        self.tabs.addTab(self.live_data_tab, "Live Data")

        # Cross-Section Automation tab (with boundaries)
        self.cross_section_tab = CrossSectionTab(
            vxc_controller=self.vxc,
            vxc_logger=self.vxc_logger,
            boundaries=self.boundaries
        )
        self.tabs.addTab(self.cross_section_tab, "Cross-Section")

        # Cross-Section View tab (velocity visualization with session import)
        self.cross_section_view_tab = CrossSectionViewTab(boundaries=self.boundaries)
        self.tabs.addTab(self.cross_section_view_tab, "Cross-Section View")

        # Auto-update Live Data and Cross-Section View from averaged output
        self.auto_merge_tab.averaged_file_ready.connect(self.live_data_tab.update_from_avg_file)
        self.auto_merge_tab.averaged_file_ready.connect(self.cross_section_view_tab.update_from_avg_file)
        
        main_layout.addWidget(self.tabs)
        central_widget.setLayout(main_layout)
        
        # Populate ports on startup
        self._refresh_ports()
    
    def _create_vxc_tab(self) -> QWidget:
        """Create VXC controller tab."""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # Quick workflow hint
        workflow_hint = QLabel(
            "Workflow: 1) Connect controller  2) Verify live position  3) Move stage  4) Calibrate when needed"
        )
        workflow_hint.setStyleSheet(
            "color: #37474f; background: #eef3f6; border: 1px solid #d7e2e8; "
            "border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(workflow_hint)

        # Connection section
        conn_group = QGroupBox("1) Connect VXC")
        conn_layout = QGridLayout()
        conn_layout.setHorizontalSpacing(10)
        conn_layout.setVerticalSpacing(8)

        conn_layout.addWidget(QLabel("Serial Port:"), 0, 0)
        self.vxc_port_combo = QComboBox()
        conn_layout.addWidget(self.vxc_port_combo, 0, 1)

        conn_layout.addWidget(QLabel("Connection:"), 0, 2)
        self.vxc_status_label = QLabel("Not Connected")
        self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
        conn_layout.addWidget(self.vxc_status_label, 0, 3)

        self.vxc_autodetect_btn = QPushButton("Connect / Auto Detect")
        self.vxc_autodetect_btn.setStyleSheet(
            "QPushButton { background-color: #1f7a8c; color: white; font-weight: bold; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #186474; }"
        )
        self.vxc_autodetect_btn.clicked.connect(self._auto_detect_vxc)
        conn_layout.addWidget(self.vxc_autodetect_btn, 1, 1)

        self.vxc_disconnect_btn = QPushButton("Disconnect")
        self.vxc_disconnect_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        self.vxc_disconnect_btn.clicked.connect(self._disconnect_vxc)
        self.vxc_disconnect_btn.setEnabled(False)
        conn_layout.addWidget(self.vxc_disconnect_btn, 1, 2)

        connect_tip = QLabel("Tip: use Auto Detect first; manual port selection is still available.")
        connect_tip.setStyleSheet("color: #546e7a; font-size: 9pt;")
        conn_layout.addWidget(connect_tip, 2, 0, 1, 4)

        conn_layout.setColumnStretch(1, 1)
        conn_layout.setColumnStretch(3, 1)
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # Position display
        pos_group = QGroupBox("2) Live Position")
        pos_layout = QHBoxLayout()

        self.vxc_x_label = QLabel("X: --- m")
        self.vxc_x_label.setStyleSheet(
            "font-size: 18pt; font-weight: bold; color: #102a43; "
            "background: #f7fafc; border: 1px solid #d9e2ec; border-radius: 4px; padding: 8px 12px;"
        )
        pos_layout.addWidget(self.vxc_x_label)

        pos_layout.addSpacing(20)

        self.vxc_y_label = QLabel("Y: --- m")
        self.vxc_y_label.setStyleSheet(
            "font-size: 18pt; font-weight: bold; color: #102a43; "
            "background: #f7fafc; border: 1px solid #d9e2ec; border-radius: 4px; padding: 8px 12px;"
        )
        pos_layout.addWidget(self.vxc_y_label)

        pos_layout.addStretch()
        pos_group.setLayout(pos_layout)
        layout.addWidget(pos_group)

        # Movement controls
        movement_group = QGroupBox("3) Motion Controls")
        movement_layout = QHBoxLayout()
        movement_layout.setSpacing(12)

        # Manual jog controls
        jog_group = QGroupBox("Manual Jog")
        jog_layout = QVBoxLayout()

        # Step size selection
        step_layout = QHBoxLayout()
        step_layout.addWidget(QLabel("Jog Step:"))
        self.vxc_step_combo = QComboBox()
        self.vxc_step_combo.addItems(["6.35 mm", "12.7 mm", "19.05 mm", "25.4 mm"])
        self.vxc_step_combo.setCurrentIndex(1)
        step_layout.addWidget(self.vxc_step_combo)
        step_layout.addStretch()
        jog_layout.addLayout(step_layout)

        # Arrow buttons in grid
        arrows_layout = QGridLayout()

        # Y+ button
        self.jog_y_plus = QPushButton("Y+")
        self.jog_y_plus.setStyleSheet("QPushButton:hover { background-color: #b3d9ff; }")
        self.jog_y_plus.setMinimumHeight(60)
        self.jog_y_plus.pressed.connect(lambda: self._jog_start('Y', 1))
        self.jog_y_plus.released.connect(self._jog_stop)
        arrows_layout.addWidget(self.jog_y_plus, 0, 1)
        
        # X- button
        self.jog_x_minus = QPushButton("X-")
        self.jog_x_minus.setStyleSheet("QPushButton:hover { background-color: #b3d9ff; }")
        self.jog_x_minus.setMinimumHeight(60)
        self.jog_x_minus.pressed.connect(lambda: self._jog_start('X', -1))
        self.jog_x_minus.released.connect(self._jog_stop)
        arrows_layout.addWidget(self.jog_x_minus, 1, 0)
        
        # X+ button
        self.jog_x_plus = QPushButton("X+")
        self.jog_x_plus.setStyleSheet("QPushButton:hover { background-color: #b3d9ff; }")
        self.jog_x_plus.setMinimumHeight(60)
        self.jog_x_plus.pressed.connect(lambda: self._jog_start('X', 1))
        self.jog_x_plus.released.connect(self._jog_stop)
        arrows_layout.addWidget(self.jog_x_plus, 1, 2)
        
        # Y- button
        self.jog_y_minus = QPushButton("Y-")
        self.jog_y_minus.setStyleSheet("QPushButton:hover { background-color: #b3d9ff; }")
        self.jog_y_minus.setMinimumHeight(60)
        self.jog_y_minus.pressed.connect(lambda: self._jog_start('Y', -1))
        self.jog_y_minus.released.connect(self._jog_stop)
        arrows_layout.addWidget(self.jog_y_minus, 2, 1)
        
        arrows_layout.setHorizontalSpacing(10)
        arrows_layout.setVerticalSpacing(10)
        arrows_layout.setColumnStretch(0, 1)
        arrows_layout.setColumnStretch(1, 1)
        arrows_layout.setColumnStretch(2, 1)

        jog_layout.addLayout(arrows_layout)

        jog_hint = QLabel("Press and hold arrows for incremental movement.")
        jog_hint.setStyleSheet("color: #546e7a; font-size: 9pt;")
        jog_layout.addWidget(jog_hint)
        jog_group.setLayout(jog_layout)

        # Jog to position controls
        jog_to_group = QGroupBox("Move To Absolute Position")
        jog_to_layout = QVBoxLayout()

        # Instructions
        info_label = QLabel("1. Connect VXC\n2. Drag sliders to target location\n3. Click Move To Target")
        info_label.setStyleSheet(
            "color: #455a64; font-size: 10pt; padding: 6px; "
            "background: #f5f7fa; border: 1px solid #dfe7ee; border-radius: 3px;"
        )
        jog_to_layout.addWidget(info_label)

        # Plane dimensions (from boundary manager)
        # Origin (0,0) is at bottom-LEFT
        # X axis: positive rightward
        # Y axis: positive upward
        # Note: boundaries loaded from experiment_config.yaml or defaults (165654, 57651)
        self.plane_x_max_distance = self.boundaries['x_max_steps']
        self.plane_y_max_distance = self.boundaries['y_max_steps']
        
        # X position slider (absolute position across flume)
        x_slider_layout = QVBoxLayout()
        x_label_row = QHBoxLayout()
        x_label_row.addWidget(QLabel("X Position in Flume:"))
        self.x_position_label = QLabel("At origin (0 mm)")
        self.x_position_label.setStyleSheet("font-weight: bold; color: #007bff;")
        x_label_row.addWidget(self.x_position_label)
        x_label_row.addStretch()
        x_slider_layout.addLayout(x_label_row)
        
        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.setMinimum(0)
        self.x_slider.setMaximum(self.plane_x_max_distance)
        self.x_slider.setValue(0)
        self.x_slider.setEnabled(False)
        self.x_slider.valueChanged.connect(self._update_x_label)
        self.x_slider.sliderPressed.connect(self._on_slider_pressed)
        self.x_slider.sliderReleased.connect(self._on_slider_released)
        x_slider_layout.addWidget(self.x_slider)
        
        x_max_mm = self._steps_to_mm(self.plane_x_max_distance)
        x_range_label = QLabel(f"Left=Origin (0 mm) | Right=Far Side ({x_max_mm:.1f} mm)")
        x_range_label.setStyleSheet("color: #6c757d; font-size: 9pt;")
        x_slider_layout.addWidget(x_range_label)
        jog_to_layout.addLayout(x_slider_layout)

        # Y position slider (absolute height in flume)
        y_slider_layout = QVBoxLayout()
        y_label_row = QHBoxLayout()
        y_label_row.addWidget(QLabel("Y Position (Depth):"))
        self.y_position_label = QLabel("At bottom (0 mm)")
        self.y_position_label.setStyleSheet("font-weight: bold; color: #007bff;")
        y_label_row.addWidget(self.y_position_label)
        y_label_row.addStretch()
        y_slider_layout.addLayout(y_label_row)
        
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setMinimum(0)
        self.y_slider.setMaximum(self.plane_y_max_distance)
        self.y_slider.setValue(0)
        self.y_slider.setEnabled(False)
        self.y_slider.valueChanged.connect(self._update_y_label)
        self.y_slider.sliderPressed.connect(self._on_slider_pressed)
        self.y_slider.sliderReleased.connect(self._on_slider_released)
        y_slider_layout.addWidget(self.y_slider)
        
        y_max_mm = self._steps_to_mm(self.plane_y_max_distance)
        y_range_label = QLabel(f"Bottom=0 mm | Top={y_max_mm:.1f} mm")
        y_range_label.setStyleSheet("color: #6c757d; font-size: 9pt;")
        y_slider_layout.addWidget(y_range_label)
        jog_to_layout.addLayout(y_slider_layout)

        # Go button
        self.jog_go_btn = QPushButton("Move To Target")
        self.jog_go_btn.setStyleSheet("""
            QPushButton { 
                background-color: #28a745; 
                color: white; 
                font-weight: bold; 
                padding: 12px;
                font-size: 13px;
            }
            QPushButton:hover { 
                background-color: #218838; 
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        self.jog_go_btn.setMinimumHeight(50)
        self.jog_go_btn.setEnabled(False)
        self.jog_go_btn.clicked.connect(self._jog_to_position)
        jog_to_layout.addWidget(self.jog_go_btn)

        # Status label
        self.jog_to_status = QLabel("Ready")
        self.jog_to_status.setStyleSheet("color: #28a745; font-weight: bold;")
        jog_to_layout.addWidget(self.jog_to_status)

        jog_to_group.setLayout(jog_to_layout)
        movement_layout.addWidget(jog_group, 1)
        movement_layout.addWidget(jog_to_group, 2)
        movement_group.setLayout(movement_layout)
        layout.addWidget(movement_group)

        # Workspace calibration and maintenance
        boundary_group = QGroupBox("4) Calibration & Maintenance")
        boundary_layout = QVBoxLayout()

        # Display current workspace bounds
        self.workspace_bounds_label = QLabel(self._format_workspace_bounds())
        self.workspace_bounds_label.setStyleSheet(
            "color: #455a64; font-weight: bold; padding: 6px; "
            "background: #f5f7fa; border: 1px solid #dfe7ee; border-radius: 3px;"
        )
        boundary_layout.addWidget(self.workspace_bounds_label)

        # Calibrate workspace button
        self.calibrate_workspace_btn = QPushButton("Calibrate Workspace Bounds")
        self.calibrate_workspace_btn.setStyleSheet(
            "QPushButton { background-color: #ff8c00; color: white; font-weight: bold; "
            "font-size: 12px; padding: 10px; } "
            "QPushButton:hover { background-color: #ff6f00; } "
            "QPushButton:disabled { background-color: #cccccc; color: #666666; }"
        )
        self.calibrate_workspace_btn.setMinimumHeight(50)
        self.calibrate_workspace_btn.clicked.connect(self._start_workspace_calibration)
        boundary_layout.addWidget(self.calibrate_workspace_btn)

        # Legacy origin finding (kept for compatibility)
        self.find_origin_btn = QPushButton("Advanced: Find Origin (0,0) Only")
        self.find_origin_btn.setStyleSheet(
            "QPushButton { background-color: #6c757d; color: white; font-weight: bold; "
            "font-size: 10px; padding: 8px; } "
            "QPushButton:hover { background-color: #5a6268; }"
        )
        self.find_origin_btn.setMinimumHeight(40)
        self.find_origin_btn.clicked.connect(self._start_find_origin)
        boundary_layout.addWidget(self.find_origin_btn)

        self.boundary_status_label = QLabel("Status: Idle")
        self.boundary_status_label.setStyleSheet("color: #555; font-weight: bold;")
        boundary_layout.addWidget(self.boundary_status_label)

        zero_btn = QPushButton("Zero Position")
        zero_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        zero_btn.setMinimumHeight(38)
        zero_btn.clicked.connect(self._vxc_zero)
        boundary_layout.addWidget(zero_btn)

        boundary_group.setLayout(boundary_layout)
        layout.addWidget(boundary_group)

        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def _setup_timers(self):
        """Setup update timers."""
        # VXC position update timer
        self.vxc_timer = QTimer()
        self.vxc_timer.timeout.connect(self._update_vxc_position)
        
        # VXC jogging timer
        self.jog_timer = QTimer()
        self.jog_timer.timeout.connect(self._jog_update)
    
    def _refresh_ports(self):
        """Refresh available serial ports."""
        ports = list_available_ports()
        port_names = [p[0] for p in ports]  # p is tuple (port, description)
        
        # Update VXC combo
        current_vxc = self.vxc_port_combo.currentText()
        self.vxc_port_combo.clear()
        self.vxc_port_combo.addItems(port_names)
        if current_vxc in port_names:
            self.vxc_port_combo.setCurrentText(current_vxc)
        elif self.vxc_config.get('port') in port_names:
            self.vxc_port_combo.setCurrentText(self.vxc_config['port'])
        
        logger.info(f"Found {len(ports)} serial ports")
    
    # ========== VXC Methods ==========
    
    def _disconnect_vxc(self):
        """Disconnect VXC."""
        if self.vxc is None:
            return
            
        # Disconnect
        self.vxc_timer.stop()
        self._stop_slider_jog()
        self._stop_vxc_polling()
        self._stop_vxc_logging()
        self.jog_timer.stop()
        
        # Stop VXC logging if active
        if self.vxc_logger is not None:
            try:
                if hasattr(self.vxc_logger, 'current_file') and self.vxc_logger.current_file:
                    self.vxc_logger.stop_logging()
            except Exception as e:
                logger.error(f"Error stopping VXC logger: {e}")
            self.vxc_logger = None
        
        try:
            self.vxc.close()
        except Exception as e:
            logger.error(f"Error closing VXC: {e}")
        self.vxc = None
        
        # Update cross-section tab's controller reference
        if hasattr(self, 'cross_section_tab'):
            self.cross_section_tab.vxc = None
        
        self.vxc_status_label.setText("Not Connected")
        self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.vxc_disconnect_btn.setEnabled(False)
        self.vxc_x_label.setText("X: ---")
        self.vxc_y_label.setText("Y: ---")
        
        # Reset jog to position controls
        self.slider_being_adjusted = False
        self.x_slider.setValue(0)
        self.y_slider.setValue(0)
        self.x_slider.setEnabled(False)
        self.y_slider.setEnabled(False)
        self.jog_go_btn.setEnabled(False)
        self.jog_to_status.setText("Connect VXC first")
        self.jog_to_status.setStyleSheet("color: #dc3545; font-weight: bold;")
        
        logger.info("VXC disconnected")

    def _auto_detect_vxc(self):
        """Start auto-detect connection in the background."""
        if self.vxc_connecting:
            return
        self._begin_vxc_connect(None)

    def _begin_vxc_connect(self, selected_port: Optional[str]):
        """Begin VXC connection in a background thread."""
        self.vxc_connecting = True
        self.vxc_autodetect_btn.setEnabled(False)
        self.vxc_disconnect_btn.setEnabled(False)
        self.vxc_status_label.setText("Connecting...")
        self.vxc_status_label.setStyleSheet("color: #c27c00; font-weight: bold;")

        baudrate = self.vxc_config.get('baudrate', 57600)
        self.vxc_connect_thread = QThread()
        self.vxc_connect_worker = VXCConnectWorker(selected_port, baudrate)
        self.vxc_connect_worker.moveToThread(self.vxc_connect_thread)
        self.vxc_connect_thread.started.connect(self.vxc_connect_worker.run)
        self.vxc_connect_worker.connected.connect(self._on_vxc_connected)
        self.vxc_connect_worker.failed.connect(self._on_vxc_connect_failed)
        self.vxc_connect_worker.connected.connect(self.vxc_connect_thread.quit)
        self.vxc_connect_worker.failed.connect(self.vxc_connect_thread.quit)
        self.vxc_connect_thread.finished.connect(self._cleanup_vxc_connect_worker)
        self.vxc_connect_thread.start()

    def _cleanup_vxc_connect_worker(self):
        self.vxc_connect_worker = None
        self.vxc_connect_thread = None

    def _on_vxc_connected(self, controller: VXCController, port: str):
        self.vxc = controller
        
        # Update cross-section tab's controller reference
        if hasattr(self, 'cross_section_tab'):
            self.cross_section_tab.vxc = controller
        
        self.vxc_port_combo.setCurrentText(port)
        self.vxc_status_label.setText(f"Connected: {port}")
        self.vxc_status_label.setStyleSheet("color: green; font-weight: bold;")
        self.vxc_disconnect_btn.setEnabled(True)
        self._start_vxc_polling()

        vxc_log_dir = Path(self.auto_merge_tab.vxc_dir_edit.text()).resolve()
        vxc_log_dir.mkdir(parents=True, exist_ok=True)
        self.vxc_logger = VXCPositionLogger(output_dir=str(vxc_log_dir))
        self.auto_merge_tab.set_vxc_logger(self.vxc_logger)
        logger.info("VXC position logger initialized")
        self.auto_merge_tab._log_activity(f"VXC log folder: {vxc_log_dir}", "info")

        self._start_vxc_logging()

        # Auto-start logging if monitoring is already enabled
        self.auto_merge_tab.handle_vxc_connected()

        self._update_vxc_position()
        self.vxc_connecting = False
        self.vxc_autodetect_btn.setEnabled(True)
        
        # Enable jog to position controls
        self.x_slider.setEnabled(True)
        self.y_slider.setEnabled(True)
        self.jog_go_btn.setEnabled(True)
        self.jog_to_status.setText("Ready to jog")
        self.jog_to_status.setStyleSheet("color: #28a745; font-weight: bold;")

    def _on_vxc_connect_failed(self, message: str):
        self.vxc = None
        self.vxc_status_label.setText("Not Connected")
        self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.vxc_disconnect_btn.setEnabled(False)
        self.vxc_connecting = False
        self.vxc_autodetect_btn.setEnabled(True)
        QMessageBox.critical(self, "Connection Error", message)

    def _start_vxc_polling(self):
        if self.vxc is None or self.vxc_poll_thread is not None:
            return
        self.vxc_poll_thread = QThread()
        self.vxc_poll_worker = VXCPositionWorker(self.vxc, interval_sec=1.0)
        self.vxc_poll_worker.moveToThread(self.vxc_poll_thread)
        self.vxc_poll_thread.started.connect(self.vxc_poll_worker.start)
        self.vxc_poll_worker.position_updated.connect(self._apply_vxc_position)
        self.vxc_poll_worker.error.connect(self._on_vxc_position_error)
        self.vxc_poll_worker.fatal_error.connect(self._on_vxc_fatal_error)
        self.vxc_poll_thread.start()

    def _stop_vxc_polling(self):
        if self.vxc_poll_worker is not None:
            self.vxc_poll_worker.stop()
        if self.vxc_poll_thread is not None:
            self.vxc_poll_thread.quit()
            self.vxc_poll_thread.wait(1000)
        self.vxc_poll_worker = None
        self.vxc_poll_thread = None

    def _start_vxc_logging(self):
        if self.vxc_logger is None or self.vxc is None or self.vxc_log_thread is not None:
            return
        self.vxc_log_thread = QThread()
        # Increased logging rate to 5 Hz (0.2s) for better ADV sample coverage
        self.vxc_log_worker = VXCLogWorker(self.vxc_logger, self.vxc, write_interval_sec=0.2)
        self.vxc_log_worker.moveToThread(self.vxc_log_thread)
        self.vxc_log_thread.started.connect(self.vxc_log_worker.start)
        self.vxc_log_worker.error.connect(self._on_vxc_log_error)
        self.vxc_log_worker.stopped.connect(self._on_vxc_log_stopped)
        self.vxc_log_thread.finished.connect(self._on_vxc_thread_finished)
        self.vxc_log_thread.start()
        logger.info("VXC position logging thread started")
        
        # Start health monitoring timer
        if not hasattr(self, 'vxc_log_health_timer'):
            self.vxc_log_health_timer = QTimer()
            self.vxc_log_health_timer.timeout.connect(self._check_vxc_log_health)
        self.vxc_log_health_timer.start(10000)  # Check every 10 seconds
        self._last_heartbeat = 0

    def _stop_vxc_logging(self):
        # Stop health monitoring
        if hasattr(self, 'vxc_log_health_timer'):
            self.vxc_log_health_timer.stop()
        
        if self.vxc_log_worker is not None:
            self.vxc_log_worker.stop()
        if self.vxc_log_thread is not None:
            self.vxc_log_thread.quit()
            self.vxc_log_thread.wait(2000)  # Wait up to 2 seconds
        self.vxc_log_worker = None
        self.vxc_log_thread = None
    
    def _update_vxc_position(self):
        """Update VXC position display."""
        if self.vxc is None or self._closing:
            return
        
        try:
            x = self.vxc.get_position(motor=2)  # Motor 2 = X axis
            y = self.vxc.get_position(motor=1)  # Motor 1 = Y axis
            if x is not None and y is not None:
                self._apply_vxc_position(x, y)
        except Exception as e:
            logger.error(f"Failed to get VXC position: {e}")

    def _apply_vxc_position(self, x_steps: int, y_steps: int):
        x_m = self._steps_to_meters(x_steps)
        y_m = self._steps_to_meters(y_steps)
        self.vxc_x_label.setText(f"X: {x_m:.4f} m")
        self.vxc_y_label.setText(f"Y: {y_m:.4f} m")

        # Update live data tab with current position
        self.live_data_tab.update_current_position(x_m, y_m)
        
        # Update jog sliders to reflect current position
        # Origin (0,0) is bottom-LEFT, positive steps go right and up
        # X axis: step position ranges from 0 to 165654 (positive rightward)
        # Y axis: step position ranges from 0 to 57651 (positive upward)
        x_distance = x_steps  # X is already positive
        y_distance = y_steps  # Y is already positive
        
        # Only update sliders if user is not currently adjusting them
        if not self.slider_being_adjusted:
            # Block signals to prevent triggering valueChanged
            self.x_slider.blockSignals(True)
            self.y_slider.blockSignals(True)
            
            self.x_slider.setValue(x_distance)
            self.y_slider.setValue(y_distance)
            
            self.x_slider.blockSignals(False)
            self.y_slider.blockSignals(False)
            
            # Update labels to show position in flume
            self._update_x_label(x_distance)
            self._update_y_label(y_distance)
        
        # VXCLogWorker now polls positions directly - no need to enqueue

    def _on_vxc_log_error(self, message: str):
        logger.error(f"VXC log worker error: {message}")
    
    def _check_vxc_log_health(self):
        """Check if VXC logging worker is still alive."""
        if self.vxc_log_worker is None:
            return
        
        current_heartbeat = self.vxc_log_worker.get_heartbeat()
        
        if current_heartbeat == self._last_heartbeat:
            # Heartbeat hasn't changed - worker might be stalled
            logger.error(f"VXC logging worker appears to be stalled! (heartbeat stuck at {current_heartbeat})")
            self._on_vxc_log_error("WATCHDOG: Worker heartbeat stopped - logging may have crashed")
        else:
            # Worker is alive and healthy
            self._last_heartbeat = current_heartbeat
            logger.debug(f"VXC logging health check OK (heartbeat: {current_heartbeat})")
    
    def _on_vxc_log_stopped(self):
        """Handle VXC logging worker stopped signal."""
        logger.warning("VXC logging worker has stopped")
    
    def _on_vxc_thread_finished(self):
        """Handle VXC logging thread finished signal."""
        logger.info("VXC logging thread finished")
        self.vxc_log_thread = None

    def _on_vxc_position_error(self, message: str):
        logger.warning(f"VXC position polling error: {message}")

    def _on_vxc_fatal_error(self, message: str):
        """Port is unrecoverable — auto-disconnect and notify the user."""
        logger.error(f"VXC fatal error, auto-disconnecting: {message}")
        self._disconnect_vxc()
        self.vxc_status_label.setText("Disconnected (port error)")
        self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
        QMessageBox.critical(
            self,
            "VXC Connection Lost",
            f"The VXC port became unresponsive and was disconnected automatically.\n\n"
            f"Detail: {message}\n\n"
            "Check the USB cable and click \"Auto Detect VXC\" to reconnect."
        )

    def _start_find_origin(self):
        """Start automated origin (0,0) finding process."""
        if self.vxc is None:
            QMessageBox.warning(self, "Not Connected", "Connect to VXC before finding origin.")
            return

        prompt = (
            "Auto-move to origin (0,0)?\n\n"
            "The stage will move X-axis to its minimum limit, then Y-axis to its minimum limit.\n"
            "This will find the bottom-left corner of the workspace."
        )
        reply = QMessageBox.question(self, "Find Origin", prompt, QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        if self.boundary_thread:
            return

        self._set_boundary_ui_enabled(False)
        self.boundary_status_label.setText("Status: Finding origin...")

        self.boundary_thread = QThread()
        self.boundary_worker = FindOriginWorker(
            controller=self.vxc,
            step_size=self.boundary_step_size,
            speed=self.boundary_speed,
            max_seconds=self.boundary_max_seconds,
        )
        self.boundary_worker.moveToThread(self.boundary_thread)
        self.boundary_thread.started.connect(self.boundary_worker.run)
        self.boundary_worker.progress.connect(self._on_origin_progress)
        self.boundary_worker.completed.connect(self._on_origin_completed)
        self.boundary_worker.failed.connect(self._on_origin_failed)
        self.boundary_worker.completed.connect(self.boundary_thread.quit)
        self.boundary_worker.failed.connect(self.boundary_thread.quit)
        self.boundary_thread.finished.connect(self._cleanup_boundary_worker)
        self.boundary_thread.start()

    def _start_boundary_find(self, axis: str, direction: int):
        if self.vxc is None:
            QMessageBox.warning(self, "Not Connected", "Connect to VXC before finding boundaries.")
            return

        prompt = (
            f"Auto-move {axis} axis toward the {'Min' if direction < 0 else 'Max'} stop?\n\n"
            "The stage will move until it hits the physical stop."
        )
        reply = QMessageBox.question(self, "Find Boundary", prompt, QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        if self.boundary_thread:
            return

        self._set_boundary_ui_enabled(False)
        self.boundary_status_label.setText(f"Status: Finding {axis} {'Min' if direction < 0 else 'Max'}...")

        self.boundary_thread = QThread()
        self.boundary_worker = BoundaryFindWorker(
            controller=self.vxc,
            axis=axis,
            direction=direction,
            step_size=self.boundary_step_size,
            speed=self.boundary_speed,
            max_seconds=self.boundary_max_seconds,
        )
        self.boundary_worker.moveToThread(self.boundary_thread)
        self.boundary_thread.started.connect(self.boundary_worker.run)
        self.boundary_worker.progress.connect(self._on_boundary_progress)
        self.boundary_worker.completed.connect(self._on_boundary_completed)
        self.boundary_worker.failed.connect(self._on_boundary_failed)
        self.boundary_worker.completed.connect(self.boundary_thread.quit)
        self.boundary_worker.failed.connect(self.boundary_thread.quit)
        self.boundary_thread.finished.connect(self._cleanup_boundary_worker)
        self.boundary_thread.start()

    def _on_origin_progress(self, message: str):
        self.boundary_status_label.setText(f"Status: {message}")

    def _on_origin_completed(self, results: dict):
        """Handle completion of origin finding."""
        # Convert steps to meters and store
        for key, steps in results.items():
            meters = self._steps_to_meters(steps)
            self.boundary_limits[key] = meters
        
        self.boundary_status_label.setText("Status: Origin (0,0) captured successfully!")
        self._set_boundary_ui_enabled(True)
        QMessageBox.information(self, "Origin Found", 
                               f"Origin located at:\n"
                               f"X: {self.boundary_limits.get('x_min_m', 0):.4f} m\n"
                               f"Y: {self.boundary_limits.get('y_min_m', 0):.4f} m")

    def _on_origin_failed(self, message: str):
        self.boundary_status_label.setText("Status: Origin finding failed")
        self._set_boundary_ui_enabled(True)
        QMessageBox.critical(self, "Origin Error", message)

    def _on_boundary_progress(self, message: str):
        self.boundary_status_label.setText(f"Status: {message}")

    def _on_boundary_completed(self, axis: str, label: str, steps: int):
        meters = self._steps_to_meters(steps)
        key = f"{axis.lower()}_{label.lower()}_m"
        self.boundary_limits[key] = meters
        self.boundary_status_label.setText(f"Status: {axis} {label} captured")
        self._set_boundary_ui_enabled(True)

    def _on_boundary_failed(self, message: str):
        self.boundary_status_label.setText("Status: Idle")
        self._set_boundary_ui_enabled(True)
        QMessageBox.critical(self, "Boundary Error", message)

    def _start_workspace_calibration(self):
        """Start full workspace calibration (all 4 boundaries)."""
        if self.vxc is None:
            QMessageBox.warning(self, "Not Connected", "Connect to VXC before calibrating workspace.")
            return

        prompt = (
            "Calibrate Workspace Boundaries?\n\n"
            "This will move both axes to all physical limits (min and max).\n"
            "The process will take several minutes.\n\n"
            "⚠ Ensure the workspace is clear and safe for automatic movement."
        )
        reply = QMessageBox.question(self, "Calibrate Workspace", prompt, 
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        if self.boundary_thread:
            return

        self._set_boundary_ui_enabled(False)
        self.boundary_status_label.setText("Status: Calibrating workspace...")

        self.boundary_thread = QThread()
        self.boundary_worker = WorkspaceCalibrateWorker(
            controller=self.vxc,
            step_size=self.boundary_step_size,
            speed=self.boundary_speed,
            max_seconds=self.boundary_max_seconds,
        )
        self.boundary_worker.moveToThread(self.boundary_thread)
        self.boundary_thread.started.connect(self.boundary_worker.run)
        self.boundary_worker.progress.connect(self._on_workspace_calibrate_progress)
        self.boundary_worker.completed.connect(self._on_workspace_calibrate_completed)
        self.boundary_worker.failed.connect(self._on_workspace_calibrate_failed)
        self.boundary_worker.completed.connect(self.boundary_thread.quit)
        self.boundary_worker.failed.connect(self.boundary_thread.quit)
        self.boundary_thread.finished.connect(self._cleanup_boundary_worker)
        self.boundary_thread.start()

    def _on_workspace_calibrate_progress(self, message: str):
        self.boundary_status_label.setText(f"Status: {message}")

    def _on_workspace_calibrate_completed(self, boundaries: dict):
        """Handle completion of workspace calibration."""
        # Save boundaries using BoundaryManager
        if self.boundary_manager.save_boundaries(boundaries):
            # Update internal boundaries dict
            self.boundaries = boundaries
            self.boundary_manager.update_boundaries(boundaries)
            
            # Update UI elements that depend on boundaries
            self.plane_x_max_distance = boundaries['x_max_steps']
            self.plane_y_max_distance = boundaries['y_max_steps']
            
            # Update sliders
            self.x_slider.setMaximum(self.plane_x_max_distance)
            self.y_slider.setMaximum(self.plane_y_max_distance)
            
            # Update boundary display
            self.workspace_bounds_label.setText(self._format_workspace_bounds())
            self.boundary_status_label.setText("Status: Workspace calibrated successfully!")
            
            # Notify tabs of boundary update
            self._emit_boundary_update()
            
            x_min_m, x_max_m, y_min_m, y_max_m = self.boundary_manager.get_all_ranges_m()
            QMessageBox.information(
                self, "Calibration Complete", 
                f"Workspace boundaries calibrated:\n\n"
                f"X: {x_min_m:.4f} m to {x_max_m:.4f} m\n"
                f"Y: {y_min_m:.4f} m to {y_max_m:.4f} m\n\n"
                f"Saved to experiment_config.yaml"
            )
        else:
            QMessageBox.warning(
                self, "Save Failed",
                "Workspace calibrated but failed to save to config file."
            )
        
        self._set_boundary_ui_enabled(True)

    def _on_workspace_calibrate_failed(self, message: str):
        self.boundary_status_label.setText("Status: Calibration failed")
        self._set_boundary_ui_enabled(True)
        QMessageBox.critical(self, "Calibration Error", message)

    def _emit_boundary_update(self):
        """Notify tabs that boundaries have been updated."""
        # Update Live Data tab
        if hasattr(self, 'live_data_tab'):
            self.live_data_tab.update_boundaries(self.boundaries)
        
        # Update Cross-Section tab
        if hasattr(self, 'cross_section_tab'):
            self.cross_section_tab.update_boundaries(self.boundaries)

        # Update Cross-Section View tab
        if hasattr(self, 'cross_section_view_tab'):
            self.cross_section_view_tab.update_boundaries(self.boundaries)

    def _format_workspace_bounds(self) -> str:
        """Format workspace bounds for display."""
        x_min_m, x_max_m, y_min_m, y_max_m = self.boundary_manager.get_all_ranges_m()
        return (
            f"X: {x_min_m:.3f} – {x_max_m:.3f} m  |  "
            f"Y: {y_min_m:.3f} – {y_max_m:.3f} m"
        )

    def _cleanup_boundary_worker(self):
        self.boundary_worker = None
        self.boundary_thread = None

    def _set_boundary_ui_enabled(self, enabled: bool):
        self.find_origin_btn.setEnabled(enabled)
        self.calibrate_workspace_btn.setEnabled(enabled)

    def _format_boundary_values(self) -> str:
        x_min = self.boundary_limits.get("x_min_m")
        y_min = self.boundary_limits.get("y_min_m")
        if x_min is not None and y_min is not None:
            return f"Origin: X = {x_min:.4f} m, Y = {y_min:.4f} m"
        else:
            return "Origin: (not set)"

    def _save_boundaries(self):
        config_path = Path(self.config_dir) / "experiment_config.yaml"
        try:
            config = {}
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}

            config["boundaries"] = self.boundary_limits
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, sort_keys=False)

            QMessageBox.information(self, "Boundaries Saved", f"Saved to {config_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save boundaries:\n{e}")

    def _steps_to_meters(self, steps: float) -> float:
        inches = steps / self.STEPS_PER_INCH
        feet = inches / 12.0
        return feet * self.METERS_PER_FOOT
    
    def _steps_to_mm(self, steps: float) -> float:
        """Convert steps to millimeters."""
        inches = steps / self.STEPS_PER_INCH
        return inches * 25.4  # 25.4 mm per inch
    
    def _jog_start(self, axis: str, direction: int):
        """Start jogging VXC.
        
        Args:
            axis: 'X' or 'Y'
            direction: 1 for positive, -1 for negative
        """
        if self.vxc is None:
            return
        
        self.jog_axis = axis
        self.jog_direction = direction
        self._jog_step_once()
        self.jog_repeat_active = True
        QTimer.singleShot(self.jog_repeat_delay_ms, self._start_jog_repeat_if_active)
    
    def _jog_stop(self):
        """Stop jogging VXC."""
        self.jog_timer.stop()
        self.jog_axis = None
        self.jog_direction = 0
        self.jog_repeat_active = False

    def _start_jog_repeat_if_active(self):
        """Start repeat jogging if the button is still held."""
        if self.jog_repeat_active and self.jog_axis is not None:
            self.jog_timer.start(100)  # Jog every 100ms
    
    def _jog_update(self):
        """Execute one jog step."""
        if self.vxc is None or self.jog_axis is None:
            return

        self._jog_step_once()

    def _jog_step_once(self):
        """Execute a single jog step based on current UI settings."""
        if self.vxc is None or self.jog_axis is None:
            return
        
        # Get jog distance in meters
        step_index = self.vxc_step_combo.currentIndex()
        if step_index < 0 or step_index >= len(self.jog_distances_m):
            distance_m = self.jog_distances_m[1]
        else:
            distance_m = self.jog_distances_m[step_index]

        steps_per_meter = self.STEPS_PER_INCH / self.METERS_PER_INCH
        step = int(round(distance_m * steps_per_meter))
        
        # Apply direction
        step = step * self.jog_direction
        
        try:
            # Convert axis letter to motor number
            motor = 2 if self.jog_axis == 'X' else 1
            self.vxc.step_motor(motor=motor, steps=step)
        except Exception as e:
            logger.error(f"Jog failed: {e}")
            self._jog_stop()
    
    def _on_slider_pressed(self):
        """Called when user starts adjusting a slider."""
        self.slider_being_adjusted = True
        # Temporarily disconnect position updates to prevent slider from snapping back
        if self.vxc_poll_worker is not None:
            try:
                self.vxc_poll_worker.position_updated.disconnect(self._apply_vxc_position)
                logger.debug("Slider adjustment started - disconnected position updates")
            except:
                pass  # Already disconnected
    
    def _on_slider_released(self):
        """Called when user releases a slider."""
        self.slider_being_adjusted = False
        # Don't reconnect immediately - let slider stay at user's chosen position
        # Signal will reconnect after jog completes
        logger.debug("Slider adjustment ended - keeping position until jog")
    
    def _update_x_label(self, value: int):
        """Update X position label when slider changes."""
        mm = self._steps_to_mm(value)
        if value == 0:
            self.x_position_label.setText("At origin (0 mm)")
        elif value == self.plane_x_max_distance:
            self.x_position_label.setText(f"At far side ({mm:.1f} mm)")
        else:
            pct = (value / self.plane_x_max_distance) * 100
            self.x_position_label.setText(f"{mm:.1f} mm ({pct:.0f}% across)")
    
    def _update_y_label(self, value: int):
        """Update Y position label when slider changes."""
        mm = self._steps_to_mm(value)
        if value == 0:
            self.y_position_label.setText("At bottom (0 mm)")
        elif value == self.plane_y_max_distance:
            self.y_position_label.setText(f"At top ({mm:.1f} mm)")
        else:
            pct = (value / self.plane_y_max_distance) * 100
            self.y_position_label.setText(f"{mm:.1f} mm ({pct:.0f}% up)")
    
    def _jog_to_position(self):
        """Start a non-blocking slider-commanded jog (X first, then Y).

        All serial I/O is offloaded to a background QThread so the GUI
        stays responsive during moves that can take tens of seconds.
        """
        if self.vxc is None:
            QMessageBox.warning(self, "Not Connected", "VXC is not connected.")
            return

        if self.slider_jog_thread is not None:
            return  # Already jogging — ignore second press

        target_x = self.x_slider.value()
        target_y = self.y_slider.value()

        # Read current position — fast single query, acceptable on GUI thread
        current_x = self.vxc.get_position(motor=2)
        current_y = self.vxc.get_position(motor=1)

        if current_x is None or current_y is None:
            QMessageBox.critical(self, "Position Error", "Cannot read current VXC position.")
            return

        delta_x = target_x - current_x
        delta_y = target_y - current_y

        if delta_x == 0 and delta_y == 0:
            self.jog_to_status.setText("Already at target position")
            return

        logger.info(f"Slider jog: ({current_x},{current_y}) -> ({target_x},{target_y}), "
                    f"delta X={delta_x:+d} Y={delta_y:+d}")

        # Disable GO button and update status for the duration of the move
        self.jog_go_btn.setEnabled(False)
        first_msg = (f"Moving X axis ({delta_x:+d} steps)..."
                     if delta_x != 0 else f"Moving Y axis ({delta_y:+d} steps)...")
        self.jog_to_status.setText(first_msg)
        self.jog_to_status.setStyleSheet("color: #007bff; font-weight: bold;")

        # Disconnect live position->slider update so it doesn't fight the
        # moving slider handle while the jog is in progress
        if self.vxc_poll_worker is not None:
            try:
                self.vxc_poll_worker.position_updated.disconnect(self._apply_vxc_position)
            except Exception:
                pass

        # Build and start the background worker
        self.slider_jog_thread = QThread()
        self.slider_jog_worker = SliderJogWorker(self.vxc, delta_x, delta_y)
        self.slider_jog_worker.moveToThread(self.slider_jog_thread)
        self.slider_jog_thread.started.connect(self.slider_jog_worker.run)
        self.slider_jog_worker.progress.connect(self._on_slider_jog_progress)
        self.slider_jog_worker.completed.connect(self._on_slider_jog_completed)
        self.slider_jog_worker.failed.connect(self._on_slider_jog_failed)
        self.slider_jog_worker.completed.connect(self.slider_jog_thread.quit)
        self.slider_jog_worker.failed.connect(self.slider_jog_thread.quit)
        self.slider_jog_thread.finished.connect(self._cleanup_slider_jog_worker)
        self.slider_jog_thread.start()

    def _on_slider_jog_progress(self, message: str):
        """Relay background worker status text to the status label."""
        self.jog_to_status.setText(message)

    def _on_slider_jog_completed(self):
        """Handle successful jog completion."""
        self.jog_to_status.setText("Move complete!")
        self.jog_to_status.setStyleSheet("color: #28a745; font-weight: bold;")
        logger.info("Slider jog completed successfully")
        QTimer.singleShot(2000, lambda: self.jog_to_status.setText("Ready"))
        QTimer.singleShot(2000, lambda: self.jog_to_status.setStyleSheet("color: #28a745;"))

    def _on_slider_jog_failed(self, error: str):
        """Handle jog failure."""
        self.jog_to_status.setText("Move failed")
        self.jog_to_status.setStyleSheet("color: #dc3545; font-weight: bold;")
        logger.error(f"Slider jog failed: {error}")
        QMessageBox.critical(self, "Jog Failed", f"Movement failed:\n{error}")

    def _cleanup_slider_jog_worker(self):
        """Called when the jog thread finishes — re-enables UI and reconnects signals."""
        self.slider_jog_worker = None
        self.slider_jog_thread = None
        self.slider_being_adjusted = False

        # Re-enable GO button if still connected
        if self.vxc is not None:
            self.jog_go_btn.setEnabled(True)

        # Reconnect position updates -> sliders.
        # UniqueConnection silently ignores duplicate connects.
        if self.vxc_poll_worker is not None:
            try:
                self.vxc_poll_worker.position_updated.connect(
                    self._apply_vxc_position, Qt.UniqueConnection
                )
            except Exception:
                pass

    def _stop_slider_jog(self):
        """Abort any in-progress slider jog and clean up the thread."""
        if self.slider_jog_thread is not None:
            self.slider_jog_thread.quit()
            self.slider_jog_thread.wait(2000)
        self.slider_jog_worker = None
        self.slider_jog_thread = None
    
    def _vxc_zero(self):
        """Zero VXC position."""
        if self.vxc is None:
            QMessageBox.warning(self, "Not Connected", "VXC is not connected.")
            return
        
        reply = QMessageBox.question(
            self, "Zero Position",
            "Set current position as (0, 0)?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Zero vertical (Y) axis first (motor 1), then horizontal (X) axis (motor 2)
                # VXC only allows one command at a time
                self.vxc.send_command('N1')  # Zero motor 1 (Y axis)
                time.sleep(0.1)
                self.vxc.send_command('N2')  # Zero motor 2 (X axis)
                logger.info("VXC position zeroed (Y then X)")
                self._update_vxc_position()
            except Exception as e:
                QMessageBox.critical(self, "Zero Error", f"Failed to zero VXC:\n{e}")
                logger.error(f"VXC zero failed: {e}")
    
    def _vxc_stop(self):
        """Emergency stop VXC - immediately halt all motion."""
        if self.vxc is None:
            return
        
        try:
            # Immediately kill all motion (no deceleration)
            self.vxc.kill_motion()
            
            # Stop jogging timer if active
            self._jog_stop()
            
            # Clear any pending commands
            self.vxc.clear_program()
            
            logger.warning("VXC EMERGENCY STOP - All motion halted")
            QMessageBox.information(self, "Emergency Stop", "All VXC motion stopped immediately.")
        except Exception as e:
            logger.error(f"VXC emergency stop failed: {e}")
            QMessageBox.critical(self, "Stop Error", f"Emergency stop failed:\n{e}")
    
    def closeEvent(self, event):
        """Handle window close."""
        self._closing = True
        
        # Stop timers
        self.vxc_timer.stop()
        self.jog_timer.stop()
        self._stop_slider_jog()
        self._stop_vxc_polling()
        self._stop_vxc_logging()
        
        # Cleanup auto-merge tab
        if hasattr(self, 'auto_merge_tab'):
            self.auto_merge_tab.cleanup()
        
        # Stop VXC position logging if active
        if self.vxc_logger is not None:
            try:
                if hasattr(self.vxc_logger, 'current_file') and self.vxc_logger.current_file:
                    self.vxc_logger.stop_logging()
            except Exception as e:
                logger.error(f"Error stopping VXC logger: {e}")
        
        # Disconnect hardware
        if self.vxc is not None:
            try:
                self.vxc.close()
            except Exception as e:
                logger.error(f"Error closing VXC: {e}")
        
        logger.info("MainWindow closed")
        event.accept()
