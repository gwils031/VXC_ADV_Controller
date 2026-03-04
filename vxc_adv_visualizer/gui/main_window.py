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
from ..data.vxc_position_logger import VXCPositionLogger

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

    def __init__(self, controller: VXCController, interval_sec: float = 1.0):
        super().__init__()
        self.controller = controller
        self.interval_sec = interval_sec
        self._running = False
        self._error_backoff_sec = 1.0

    def start(self):
        self._running = True
        while self._running:
            try:
                x = self.controller.get_position(motor=2)
                y = self.controller.get_position(motor=1)
                if x is not None and y is not None:
                    self.position_updated.emit(x, y)
                else:
                    self.error.emit("No position response")
                    time.sleep(self._error_backoff_sec)
            except Exception as e:
                self.error.emit(str(e))
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
                    self.logger.log_position(x_steps=0, y_steps=0, quality="NO_RESPONSE")
                    consecutive_errors += 1
                    
            except Exception as e:
                consecutive_errors += 1
                error_msg = f"VXC logging error (#{consecutive_errors}): {e}"
                logger.error(error_msg)
                self.error.emit(error_msg)
                
                # Try to log error position to maintain timeline
                try:
                    self.logger.log_position(x_steps=0, y_steps=0, quality="ERROR")
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

        # Live Data tab
        self.live_data_tab = LiveDataTab()
        self.tabs.addTab(self.live_data_tab, "Live Data")

        # Cross-Section Automation tab
        self.cross_section_tab = CrossSectionTab(
            vxc_controller=self.vxc,
            vxc_logger=self.vxc_logger
        )
        self.tabs.addTab(self.cross_section_tab, "Cross-Section")

        # Auto-update Live Data from averaged output
        self.auto_merge_tab.averaged_file_ready.connect(self.live_data_tab.update_from_avg_file)
        
        main_layout.addWidget(self.tabs)
        central_widget.setLayout(main_layout)
        
        # Populate ports on startup
        self._refresh_ports()
    
    def _create_vxc_tab(self) -> QWidget:
        """Create VXC controller tab."""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Connection section
        conn_group = QGroupBox("VXC Connection")
        conn_layout = QHBoxLayout()
        
        conn_layout.addWidget(QLabel("Port:"))
        self.vxc_port_combo = QComboBox()
        conn_layout.addWidget(self.vxc_port_combo)
        
        self.vxc_status_label = QLabel("Not Connected")
        self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
        conn_layout.addWidget(self.vxc_status_label)

        self.vxc_autodetect_btn = QPushButton("Auto Detect VXC")
        self.vxc_autodetect_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        self.vxc_autodetect_btn.clicked.connect(self._auto_detect_vxc)
        conn_layout.addWidget(self.vxc_autodetect_btn)
        
        self.vxc_disconnect_btn = QPushButton("Disconnect")
        self.vxc_disconnect_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        self.vxc_disconnect_btn.clicked.connect(self._disconnect_vxc)
        self.vxc_disconnect_btn.setEnabled(False)
        conn_layout.addWidget(self.vxc_disconnect_btn)
        
        conn_layout.addStretch()
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)
        
        # Position display
        pos_group = QGroupBox("Current Position")
        pos_layout = QHBoxLayout()
        
        self.vxc_x_label = QLabel("X: --- m")
        self.vxc_x_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        pos_layout.addWidget(self.vxc_x_label)
        
        pos_layout.addSpacing(20)
        
        self.vxc_y_label = QLabel("Y: --- m")
        self.vxc_y_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        pos_layout.addWidget(self.vxc_y_label)
        
        pos_layout.addStretch()
        pos_group.setLayout(pos_layout)
        layout.addWidget(pos_group)
        
        # Jog controls
        jog_group = QGroupBox("Jog Controls")
        jog_layout = QVBoxLayout()
        
        # Step size selection
        step_layout = QHBoxLayout()
        step_layout.addWidget(QLabel("Jog Distance:"))
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
        jog_group.setLayout(jog_layout)
        layout.addWidget(jog_group)
        
        # Jog to position controls (Minimal Viable)
        jog_to_group = QGroupBox("Jog to Position (X→Y)")
        jog_to_layout = QVBoxLayout()
        
        # Instructions
        info_label = QLabel("1. Connect VXC Controller\n2. Drag sliders to target\n3. Click Go")
        info_label.setStyleSheet("color: #6c757d; font-size: 10pt; padding: 5px; background: #f8f9fa; border-radius: 3px;")
        jog_to_layout.addWidget(info_label)
        
        # Plane dimensions (from measurement area)
        # Origin (0,0) is at bottom-LEFT
        # X axis: from 0 to 165654 (~1.0519 m wide, positive rightward)
        # Y axis: from 0 to 57651 (~0.3661 m tall, positive upward)
        self.plane_x_max_distance = 165654  # maximum distance from origin
        self.plane_y_max_distance = 57651
        
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
        self.jog_go_btn = QPushButton("GO (Y first, then X)")
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
        layout.addWidget(jog_to_group)

        # Boundary capture
        boundary_group = QGroupBox("Origin Calibration")
        boundary_layout = QVBoxLayout()

        self.find_origin_btn = QPushButton("Find Origin (0,0)")
        self.find_origin_btn.setStyleSheet(
            "QPushButton { background-color: #007bff; color: white; font-weight: bold; "
            "font-size: 12px; padding: 10px; } "
            "QPushButton:hover { background-color: #0056b3; }"
        )
        self.find_origin_btn.setMinimumHeight(50)
        self.find_origin_btn.clicked.connect(self._start_find_origin)
        boundary_layout.addWidget(self.find_origin_btn)

        self.boundary_status_label = QLabel("Status: Idle")
        self.boundary_status_label.setStyleSheet("color: #555; font-weight: bold;")
        boundary_layout.addWidget(self.boundary_status_label)

        self.boundary_values_label = QLabel(self._format_boundary_values())
        self.boundary_values_label.setStyleSheet("color: #555;")
        boundary_layout.addWidget(self.boundary_values_label)

        self.boundary_save_btn = QPushButton("Save Origin Position")
        self.boundary_save_btn.clicked.connect(self._save_boundaries)
        boundary_layout.addWidget(self.boundary_save_btn)

        boundary_group.setLayout(boundary_layout)
        layout.addWidget(boundary_group)
        
        # Action buttons
        btn_layout = QVBoxLayout()
        
        zero_btn = QPushButton("Zero Position")
        zero_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        zero_btn.setMinimumHeight(40)
        zero_btn.clicked.connect(self._vxc_zero)
        
        # Center buttons horizontally
        btn_container = QHBoxLayout()
        btn_container.addStretch()
        
        btn_vertical = QVBoxLayout()
        btn_vertical.addWidget(zero_btn)
        
        btn_container.addLayout(btn_vertical)
        btn_container.addStretch()
        
        layout.addLayout(btn_container)
        
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
        
        self.boundary_values_label.setText(self._format_boundary_values())
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
        self.boundary_values_label.setText(self._format_boundary_values())
        self.boundary_status_label.setText(f"Status: {axis} {label} captured")
        self._set_boundary_ui_enabled(True)

    def _on_boundary_failed(self, message: str):
        self.boundary_status_label.setText("Status: Idle")
        self._set_boundary_ui_enabled(True)
        QMessageBox.critical(self, "Boundary Error", message)

    def _cleanup_boundary_worker(self):
        self.boundary_worker = None
        self.boundary_thread = None

    def _set_boundary_ui_enabled(self, enabled: bool):
        self.find_origin_btn.setEnabled(enabled)
        self.boundary_save_btn.setEnabled(enabled)

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
