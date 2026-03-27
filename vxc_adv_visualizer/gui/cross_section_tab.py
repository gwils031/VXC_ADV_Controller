"""
Cross-Section Measurement Automation Tab

Automates ADV measurements along user-defined routes in the flume cross-section.
Supports vertical line scans, horizontal line scans, and XY grid patterns.
"""

import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import numpy as np
import yaml
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import QObject, QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton,
    QLabel, QDoubleSpinBox, QSpinBox, QPushButton, QProgressBar,
    QMessageBox, QButtonGroup, QGridLayout, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt5.QtGui import QColor

from .range_slider import QRangeSlider

logger = logging.getLogger(__name__)


class CrossSectionWorker(QObject):
    """Worker thread for automated cross-section measurements."""
    
    progress = pyqtSignal(int, int)  # current, total
    position_reached = pyqtSignal(float, float, int)  # x_m, y_m, index
    completed = pyqtSignal()
    error = pyqtSignal(str)
    position_error = pyqtSignal(str)  # Recoverable error — user can skip or stop
    status_update = pyqtSignal(str)
    eta_update = pyqtSignal(float, float, int, int)  # elapsed_sec, remaining_sec, current_pos, total_pos
    run_finished = pyqtSignal()  # Emitted on every run exit path so UI can cleanly shut down the thread
    
    def __init__(self, controller, positions: List[Dict[str, float]], 
                 dwell_time_sec: float, settling_time_sec: float = 2.0, speed: int = 2000):
        super().__init__()
        self.controller = controller
        self.positions = positions
        self.dwell_time_sec = dwell_time_sec
        self.settling_time_sec = settling_time_sec
        self.speed = speed  # steps per second
        self._running = True
        self._paused = False
        self._waiting_for_decision = False  # True while blocked waiting for skip/stop
        self._skip_current = False          # Set by skip_position() to continue the loop
        self.start_time = None
    
    def _estimate_movement_time(self, current_pos: Dict, target_pos: Dict) -> float:
        """Estimate time to move from current to target position.
        
        Args:
            current_pos: Current position dict with 'x_steps' and 'y_steps'
            target_pos: Target position dict with 'x_steps' and 'y_steps'
            
        Returns:
            Estimated time in seconds
        """
        dx = abs(target_pos['x_steps'] - current_pos['x_steps'])
        dy = abs(target_pos['y_steps'] - current_pos['y_steps'])
        
        # VXC moves X first, then Y sequentially
        x_time = dx / self.speed if dx > 0 else 0
        y_time = dy / self.speed if dy > 0 else 0
        
        # Add buffer for acceleration/deceleration (10% overhead)
        total_time = (x_time + y_time) * 1.1
        
        # Add minimum time for command processing
        total_time += 0.5  # 500ms for commands/verification
        
        return total_time
    
    def run(self):
        """Execute automated measurement sequence."""
        try:
            self.start_time = time.time()
            total = len(self.positions)
            
            # Calculate initial total estimated time
            total_estimated_time = 0.0
            for i in range(len(self.positions)):
                if i == 0:
                    # Estimate from current position to first position
                    current_x = self.controller.get_position(motor=2)
                    current_y = self.controller.get_position(motor=1)
                    if current_x is not None and current_y is not None:
                        current_dict = {'x_steps': current_x, 'y_steps': current_y}
                        total_estimated_time += self._estimate_movement_time(current_dict, self.positions[0])
                else:
                    total_estimated_time += self._estimate_movement_time(self.positions[i-1], self.positions[i])
                
                total_estimated_time += self.settling_time_sec + self.dwell_time_sec
            
            for i, pos in enumerate(self.positions):
                if not self._running:
                    self.status_update.emit("Stopped by user")
                    break
                
                while self._paused:
                    time.sleep(0.1)
                    if not self._running:
                        self.status_update.emit("Stopped by user")
                        return
                
                x_m = pos['x_m']
                y_m = pos['y_m']
                x_steps = pos['x_steps']
                y_steps = pos['y_steps']
                
                logger.info(f"\n{'='*80}")
                logger.info(f"POSITION {i+1}/{total}: Target X={x_m:.4f}m ({x_steps} steps), Y={y_m:.4f}m ({y_steps} steps)")
                logger.info(f"{'='*80}")
                
                # Calculate time remaining
                elapsed = time.time() - self.start_time
                
                # Estimate remaining time based on remaining positions
                remaining_time = 0.0
                current_dict = {'x_steps': x_steps, 'y_steps': y_steps}
                for j in range(i, len(self.positions)):
                    if j > i:
                        remaining_time += self._estimate_movement_time(self.positions[j-1], self.positions[j])
                    remaining_time += self.settling_time_sec + self.dwell_time_sec
                
                # Emit ETA update
                self.eta_update.emit(elapsed, remaining_time, i+1, total)
                
                self.status_update.emit(f"Moving to position {i+1}/{total}: X={x_m:.4f}m, Y={y_m:.4f}m")
                
                # Move to position with retry logic (Motor 2=X, Motor 1=Y)
                max_retries = 3
                success = False
                
                for attempt in range(max_retries):
                    if attempt > 0:
                        retry_delay = 2 ** (attempt - 1)  # Exponential backoff: 1s, 2s, 4s
                        logger.warning(f"Retry attempt {attempt+1}/{max_retries} for position {i+1} (after {retry_delay}s delay)")
                        time.sleep(retry_delay)
                        # Re-verify controller status
                        status = self.controller.verify_status()
                        logger.info(f"Controller status before retry: {status}")
                    
                    success = self.controller.jog_to(x_steps, y_steps)
                    
                    if success:
                        if attempt > 0:
                            logger.info(f"Position {i+1} succeeded on retry attempt {attempt+1}")
                        break
                    else:
                        logger.warning(f"Position {i+1} attempt {attempt+1} failed")
                
                if not success:
                    error_msg = f"Failed to move to position {i+1} after {max_retries} attempts: X={x_m:.4f}m, Y={y_m:.4f}m (steps: X={x_steps}, Y={y_steps})"
                    logger.error(error_msg)
                    # Log controller state for diagnostics
                    status = self.controller.verify_status()
                    logger.error(f"Final controller status: {status}")
                    self._waiting_for_decision = True
                    self._skip_current = False
                    self.position_error.emit(error_msg)
                    while self._waiting_for_decision and self._running:
                        time.sleep(0.1)
                    if not self._running:
                        self.status_update.emit("Stopped by user")
                        break
                    logger.info(f"Position {i+1} skipped by user after move failure — continuing scan")
                    self.progress.emit(i + 1, total)
                    continue
                
                # Verify position reached with tolerance checking
                actual_x = self.controller.get_position(motor=2)
                actual_y = self.controller.get_position(motor=1)
                
                if actual_x is None or actual_y is None:
                    error_msg = f"Failed to verify position {i+1} - could not read actual position"
                    logger.error(error_msg)
                    self.error.emit(error_msg)
                    break
                
                # Check position accuracy with two-tier tolerance:
                #   Warning  (±100 steps, ~0.6 mm) — log and continue
                #   Hard error (±500 steps, ~3 mm) — stop scan
                TOLERANCE_WARN  = 100   # steps (~0.6 mm at 157 480 steps/m)
                TOLERANCE_ERROR = 500   # steps (~3.2 mm)
                pos_error_x = abs(actual_x - x_steps)
                pos_error_y = abs(actual_y - y_steps)
                logger.info(f"Position verification: Target=({x_steps}, {y_steps}), Actual=({actual_x}, {actual_y}), Error=({pos_error_x}, {pos_error_y})")
                
                if pos_error_x > TOLERANCE_ERROR or pos_error_y > TOLERANCE_ERROR:
                    error_msg = (f"Position {i+1} accuracy error: X_err={pos_error_x} steps, "
                                 f"Y_err={pos_error_y} steps (hard limit: ±{TOLERANCE_ERROR})")
                    logger.error(error_msg)
                    self._waiting_for_decision = True
                    self._skip_current = False
                    self.position_error.emit(error_msg)
                    while self._waiting_for_decision and self._running:
                        time.sleep(0.1)
                    if not self._running:
                        self.status_update.emit("Stopped by user")
                        break
                    logger.info(f"Position {i+1} skipped by user — continuing scan")
                    self.progress.emit(i + 1, total)
                    continue
                elif pos_error_x > TOLERANCE_WARN or pos_error_y > TOLERANCE_WARN:
                    warn_msg = (f"Position {i+1} accuracy warning: X_err={pos_error_x} steps, "
                                f"Y_err={pos_error_y} steps (warning limit: ±{TOLERANCE_WARN}) — continuing")
                    logger.warning(warn_msg)
                    self.status_update.emit(warn_msg)
                
                # Allow settling time for water disturbance
                if self.settling_time_sec > 0:
                    self.status_update.emit(f"Position {i+1}/{total} reached, settling for {self.settling_time_sec:.1f}s...")
                    time.sleep(self.settling_time_sec)
                
                # Emit position reached
                self.position_reached.emit(x_m, y_m, i)
                
                # Wait for data collection
                self.status_update.emit(f"Position {i+1}/{total}: Collecting data for {self.dwell_time_sec:.1f}s...")
                
                # Check for stop during dwell time (check every 0.5s)
                elapsed = 0.0
                check_interval = 0.5
                while elapsed < self.dwell_time_sec:
                    if not self._running:
                        self.status_update.emit("Stopped by user")
                        return
                    
                    while self._paused:
                        time.sleep(0.1)
                        if not self._running:
                            self.status_update.emit("Stopped by user")
                            return
                    
                    sleep_time = min(check_interval, self.dwell_time_sec - elapsed)
                    time.sleep(sleep_time)
                    elapsed += sleep_time
                
                # Update progress
                self.progress.emit(i + 1, total)
            
            if self._running:
                self.status_update.emit("Cross-section scan completed successfully")
                self.completed.emit()
            
        except Exception as e:
            error_msg = f"Automation error: {e}"
            logger.exception(error_msg)
            self.error.emit(error_msg)
        finally:
            self.run_finished.emit()
    
    def stop(self):
        """Stop the automation."""
        self._running = False
        self._paused = False
        self._waiting_for_decision = False  # Unblock any wait loop
    
    def pause(self):
        """Pause the automation."""
        self._paused = True
    
    def resume(self):
        """Resume the automation."""
        self._paused = False

    def skip_position(self):
        """Skip the current position and continue the scan."""
        self._skip_current = True
        self._waiting_for_decision = False


class CrossSectionTab(QWidget):
    """Tab for automated cross-section measurement control."""
    
    # Hardware constants
    STEPS_PER_INCH = 4000.0
    METERS_PER_FOOT = 0.3048
    
    def __init__(self, vxc_controller, vxc_logger=None, boundaries: dict = None):
        super().__init__()
        self.vxc = vxc_controller
        self.vxc_logger = vxc_logger
        
        # Set boundaries (use defaults if not provided)
        if boundaries is None:
            boundaries = {
                'x_min_steps': 0,
                'x_max_steps': 165654,
                'y_min_steps': 0,
                'y_max_steps': 57651
            }
        self.boundaries = boundaries
        self.X_MAX_STEPS = boundaries['x_max_steps']
        self.Y_MAX_STEPS = boundaries['y_max_steps']
        
        self.worker = None
        self.worker_thread = None
        self.calculated_positions = []
        self.completed_positions = []
        self._run_outcome = "idle"
        
        # ETA tracking
        self.eta_timer = QTimer()
        self.eta_timer.timeout.connect(self._update_eta_display)
        self.automation_start_time = None
        self.estimated_remaining_sec = 0.0
        self.last_eta_update_time = None
        self.pause_start_time = None
        self.total_pause_time = 0.0
        
        # Load configuration defaults
        self._load_config()
        
        # Setup UI
        self._setup_ui()
        
        logger.info("CrossSectionTab initialized")
    
    def _load_config(self):
        """Load default values from configuration file."""
        config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"
        
        # Defaults if config not found
        self.default_dwell_time = 60.0
        self.default_settling_time = 2.0
        self.default_vertical_points = 10
        self.default_horizontal_points = 15
        self.default_grid_x_points = 10
        self.default_grid_y_points = 8
        
        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            
            automation = config.get("automation", {})
            self.default_dwell_time = float(automation.get("default_dwell_time_sec", 60.0))
            self.default_settling_time = float(automation.get("movement_settling_time_sec", 2.0))
            self.default_vertical_points = int(automation.get("default_vertical_points", 10))
            self.default_horizontal_points = int(automation.get("default_horizontal_points", 15))
            self.default_grid_x_points = int(automation.get("default_grid_x_points", 10))
            self.default_grid_y_points = int(automation.get("default_grid_y_points", 8))
            
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    
    def _setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        # Route Configuration Section
        route_group = self._create_route_config_group()
        layout.addWidget(route_group)

        # Live route summary strip
        summary_group = self._create_summary_group()
        layout.addWidget(summary_group)
        
        # Automation Control Section
        control_group = self._create_control_group()
        layout.addWidget(control_group)
        
        # Route Preview Section
        preview_group = self._create_preview_group()
        layout.addWidget(preview_group, stretch=1)
        
        self.setLayout(layout)
        self._refresh_route_summary()
    
    def _create_route_config_group(self) -> QGroupBox:
        """Create route configuration UI group."""
        group = QGroupBox("Route Configuration")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        workflow_hint = QLabel("1) Select mode  2) Set range and point density  3) Set timing  4) Calculate route")
        workflow_hint.setStyleSheet("color: #495057; font-size: 9pt;")
        layout.addWidget(workflow_hint)

        card_style = (
            "QFrame {"
            " background-color: #f8f9fa;"
            " border: 1px solid #dee2e6;"
            " border-radius: 4px;"
            " padding: 6px;"
            "}"
        )
        
        # Scan type selection
        mode_card = QFrame()
        mode_card.setStyleSheet(card_style)
        mode_card_layout = QVBoxLayout(mode_card)
        mode_card_layout.setContentsMargins(8, 6, 8, 6)
        mode_card_layout.setSpacing(6)

        mode_title = QLabel("Scan Mode")
        mode_title.setStyleSheet("font-weight: bold; color: #212529;")
        mode_card_layout.addWidget(mode_title)

        scan_layout = QHBoxLayout()
        scan_layout.addWidget(QLabel("Scan Type:"))
        
        self.scan_type_group = QButtonGroup(self)
        self.vertical_radio = QRadioButton("Vertical Line")
        self.horizontal_radio = QRadioButton("Horizontal Line")
        self.grid_radio = QRadioButton("XY Grid")
        
        self.scan_type_group.addButton(self.vertical_radio, 0)
        self.scan_type_group.addButton(self.horizontal_radio, 1)
        self.scan_type_group.addButton(self.grid_radio, 2)
        
        self.vertical_radio.setChecked(True)
        self.vertical_radio.toggled.connect(self._on_scan_type_changed)
        self.horizontal_radio.toggled.connect(self._on_scan_type_changed)
        self.grid_radio.toggled.connect(self._on_scan_type_changed)
        
        scan_layout.addWidget(self.vertical_radio)
        scan_layout.addWidget(self.horizontal_radio)
        scan_layout.addWidget(self.grid_radio)
        scan_layout.addStretch()

        mode_card_layout.addLayout(scan_layout)
        layout.addWidget(mode_card)
        
        # Position input fields (dynamic based on scan type)
        self.position_grid = QGridLayout()
        self.position_grid.setHorizontalSpacing(10)
        self.position_grid.setVerticalSpacing(6)
        
        # Workspace limits for reference
        x_max_m = self._steps_to_meters(self.X_MAX_STEPS)
        y_max_m = self._steps_to_meters(self.Y_MAX_STEPS)

        range_card = QFrame()
        range_card.setStyleSheet(card_style)
        range_card_layout = QVBoxLayout(range_card)
        range_card_layout.setContentsMargins(8, 6, 8, 6)
        range_card_layout.setSpacing(6)

        range_title = QLabel("Scan Area and Point Density")
        range_title.setStyleSheet("font-weight: bold; color: #212529;")
        range_card_layout.addWidget(range_title)
        
        info_text = f"Workspace: X: 0 to {x_max_m:.4f} m, Y: 0 to {y_max_m:.4f} m"
        self.workspace_label = QLabel(info_text)
        self.workspace_label.setStyleSheet("color: #666; font-size: 9pt;")
        range_card_layout.addWidget(self.workspace_label)
        
        # Vertical line inputs
        self.x_fixed_label = QLabel("X Position (m):")
        self.x_fixed_spin = QDoubleSpinBox()
        self.x_fixed_spin.setRange(0.0, x_max_m)
        self.x_fixed_spin.setDecimals(4)
        self.x_fixed_spin.setSingleStep(0.01)
        self.x_fixed_spin.setValue(x_max_m / 2.0)
        
        # Y Range slider (replaces Y Start and Y End spin boxes)
        self.y_range_label = QLabel("Y Range (m):")
        self.y_range_slider = QRangeSlider(orientation=Qt.Horizontal)
        self.y_range_slider.setRange(0.0, y_max_m)
        self.y_range_slider.setValues(0.0, y_max_m)
        self.y_range_slider.setDecimals(4)
        self.y_range_slider.rangeChanged.connect(self._update_y_range_label)
        
        self.y_range_value_label = QLabel(f"0.0000 m → {y_max_m:.4f} m")
        self.y_range_value_label.setStyleSheet("font-weight: bold; color: #007bff;")
        
        self.y_points_label = QLabel("Y Point Count:")
        self.y_points_spin = QSpinBox()
        self.y_points_spin.setRange(2, 100)
        self.y_points_spin.setValue(self.default_vertical_points)
        
        # Horizontal line inputs
        self.y_fixed_label = QLabel("Y Position (m):")
        self.y_fixed_spin = QDoubleSpinBox()
        self.y_fixed_spin.setRange(0.0, y_max_m)
        self.y_fixed_spin.setDecimals(4)
        self.y_fixed_spin.setSingleStep(0.01)
        self.y_fixed_spin.setValue(y_max_m / 2.0)
        
        # X Range slider (replaces X Start and X End spin boxes)
        self.x_range_label = QLabel("X Range (m):")
        self.x_range_slider = QRangeSlider(orientation=Qt.Horizontal)
        self.x_range_slider.setRange(0.0, x_max_m)
        self.x_range_slider.setValues(0.0, x_max_m)
        self.x_range_slider.setDecimals(4)
        self.x_range_slider.rangeChanged.connect(self._update_x_range_label)
        
        self.x_range_value_label = QLabel(f"0.0000 m → {x_max_m:.4f} m")
        self.x_range_value_label.setStyleSheet("font-weight: bold; color: #007bff;")
        
        self.x_points_label = QLabel("X Point Count:")
        self.x_points_spin = QSpinBox()
        self.x_points_spin.setRange(2, 100)
        self.x_points_spin.setValue(self.default_horizontal_points)
        
        # Grid inputs (reuse horizontal and vertical controls)
        self.grid_x_points_spin = QSpinBox()
        self.grid_x_points_spin.setRange(2, 50)
        self.grid_x_points_spin.setValue(self.default_grid_x_points)
        
        self.grid_y_points_spin = QSpinBox()
        self.grid_y_points_spin.setRange(2, 50)
        self.grid_y_points_spin.setValue(self.default_grid_y_points)

        self.x_fixed_spin.valueChanged.connect(lambda _: self._refresh_route_summary())
        self.y_fixed_spin.valueChanged.connect(lambda _: self._refresh_route_summary())
        self.x_points_spin.valueChanged.connect(lambda _: self._refresh_route_summary())
        self.y_points_spin.valueChanged.connect(lambda _: self._refresh_route_summary())
        self.grid_x_points_spin.valueChanged.connect(lambda _: self._refresh_route_summary())
        self.grid_y_points_spin.valueChanged.connect(lambda _: self._refresh_route_summary())
        
        # Add to position grid (will be shown/hidden based on scan type)
        range_card_layout.addLayout(self.position_grid)
        layout.addWidget(range_card)
        
        # Timing configuration
        timing_card = QFrame()
        timing_card.setStyleSheet(card_style)
        timing_card_layout = QVBoxLayout(timing_card)
        timing_card_layout.setContentsMargins(8, 6, 8, 6)
        timing_card_layout.setSpacing(6)

        timing_title = QLabel("Timing")
        timing_title.setStyleSheet("font-weight: bold; color: #212529;")
        timing_card_layout.addWidget(timing_title)

        timing_layout = QHBoxLayout()
        timing_layout.addWidget(QLabel("Dwell Time (seconds/point):"))
        
        self.dwell_time_spin = QDoubleSpinBox()
        self.dwell_time_spin.setRange(10.0, 300.0)
        self.dwell_time_spin.setDecimals(1)
        self.dwell_time_spin.setSingleStep(5.0)
        self.dwell_time_spin.setValue(self.default_dwell_time)
        self.dwell_time_spin.valueChanged.connect(lambda _: self._refresh_route_summary())
        timing_layout.addWidget(self.dwell_time_spin)
        
        timing_layout.addWidget(QLabel("Settling Time (seconds):"))
        self.settling_time_spin = QDoubleSpinBox()
        self.settling_time_spin.setRange(0.0, 30.0)
        self.settling_time_spin.setDecimals(1)
        self.settling_time_spin.setSingleStep(0.5)
        self.settling_time_spin.setValue(self.default_settling_time)
        self.settling_time_spin.valueChanged.connect(lambda _: self._refresh_route_summary())
        timing_layout.addWidget(self.settling_time_spin)
        
        timing_layout.addStretch()
        timing_card_layout.addLayout(timing_layout)
        layout.addWidget(timing_card)
        
        group.setLayout(layout)
        
        # Initialize with vertical line layout
        self._on_scan_type_changed()
        
        return group

    def _create_summary_group(self) -> QFrame:
        """Create a compact live summary strip for the current route inputs."""
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame {"
            " background-color: #eef4ff;"
            " border: 1px solid #c9dbff;"
            " border-radius: 4px;"
            "}"
        )
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        title = QLabel("Route Summary")
        title.setStyleSheet("font-weight: bold; color: #1f4fa2;")
        layout.addWidget(title)

        self.summary_label = QLabel("Waiting for route inputs")
        self.summary_label.setStyleSheet("color: #1f4fa2;")
        layout.addWidget(self.summary_label, 1)

        return panel
    
    def _create_control_group(self) -> QGroupBox:
        """Create automation control UI group."""
        group = QGroupBox("Automation Control")
        layout = QVBoxLayout()
        
        # Calculate button
        calc_layout = QHBoxLayout()
        self.calculate_btn = QPushButton("Calculate Route")
        self.calculate_btn.clicked.connect(self._calculate_route)
        calc_layout.addWidget(self.calculate_btn)
        
        self.route_info_label = QLabel("Click 'Calculate Route' to preview positions")
        self.route_info_label.setStyleSheet("color: #666;")
        calc_layout.addWidget(self.route_info_label)
        calc_layout.addStretch()
        
        layout.addLayout(calc_layout)
        
        # Control buttons
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start_automation)
        self.start_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 8px;")
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._pause_automation)
        self.pause_btn.setStyleSheet("background-color: #ffc107; color: black; font-weight: bold; padding: 8px;")
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_automation)
        self.stop_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; padding: 8px;")
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.stop_btn)
        
        self.skip_btn = QPushButton("Skip Position")
        self.skip_btn.setEnabled(False)
        self.skip_btn.clicked.connect(self._skip_position)
        self.skip_btn.setStyleSheet("background-color: #fd7e14; color: white; font-weight: bold; padding: 8px;")
        btn_layout.addWidget(self.skip_btn)
        
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # ETA label (time remaining)
        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet("font-weight: bold; font-size: 11pt; color: #007bff; padding: 5px;")
        self.eta_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.eta_label)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 10pt;")
        layout.addWidget(self.status_label)
        
        group.setLayout(layout)
        return group
    
    def _create_preview_group(self) -> QGroupBox:
        """Create route preview UI group."""
        group = QGroupBox("Route Preview")
        layout = QVBoxLayout()

        preview_hint = QLabel("Path map (top) and route table (bottom).")
        preview_hint.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(preview_hint)

        self.preview_figure = Figure(figsize=(6, 2.2), dpi=100, constrained_layout=True)
        self.preview_canvas = FigureCanvas(self.preview_figure)
        self.preview_ax = self.preview_figure.add_subplot(111)
        self.preview_canvas.setMinimumHeight(170)
        layout.addWidget(self.preview_canvas)

        self.preview_table = QTableWidget(0, 6)
        self.preview_table.setHorizontalHeaderLabels([
            "#", "X (m)", "Y (m)", "X (steps)", "Y (steps)", "Status"
        ])
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.verticalHeader().setVisible(False)

        header = self.preview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        layout.addWidget(self.preview_table)

        self._update_route_plot()
        
        group.setLayout(layout)
        return group
    
    def _on_scan_type_changed(self):
        """Update UI based on selected scan type."""
        # Clear existing widgets from grid
        while self.position_grid.count():
            item = self.position_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        
        scan_type = self.scan_type_group.checkedId()
        
        if scan_type == 0:  # Vertical line
            self.position_grid.addWidget(self.x_fixed_label, 0, 0)
            self.position_grid.addWidget(self.x_fixed_spin, 0, 1)
            self.position_grid.addWidget(self.y_range_label, 1, 0)
            self.position_grid.addWidget(self.y_range_slider, 1, 1)
            self.position_grid.addWidget(QLabel(""), 2, 0)  # Spacer
            self.position_grid.addWidget(self.y_range_value_label, 2, 1)
            self.position_grid.addWidget(self.y_points_label, 3, 0)
            self.position_grid.addWidget(self.y_points_spin, 3, 1)
            
        elif scan_type == 1:  # Horizontal line
            self.position_grid.addWidget(self.y_fixed_label, 0, 0)
            self.position_grid.addWidget(self.y_fixed_spin, 0, 1)
            self.position_grid.addWidget(self.x_range_label, 1, 0)
            self.position_grid.addWidget(self.x_range_slider, 1, 1)
            self.position_grid.addWidget(QLabel(""), 2, 0)  # Spacer
            self.position_grid.addWidget(self.x_range_value_label, 2, 1)
            self.position_grid.addWidget(self.x_points_label, 3, 0)
            self.position_grid.addWidget(self.x_points_spin, 3, 1)
            
        else:  # XY Grid
            self.position_grid.addWidget(self.x_range_label, 0, 0)
            self.position_grid.addWidget(self.x_range_slider, 0, 1)
            self.position_grid.addWidget(self.x_range_value_label, 1, 1)
            self.position_grid.addWidget(QLabel("X Point Count:"), 2, 0)
            self.position_grid.addWidget(self.grid_x_points_spin, 2, 1)
            self.position_grid.addWidget(self.y_range_label, 0, 2)
            self.position_grid.addWidget(self.y_range_slider, 0, 3)
            self.position_grid.addWidget(self.y_range_value_label, 1, 3)
            self.position_grid.addWidget(QLabel("Y Point Count:"), 2, 2)
            self.position_grid.addWidget(self.grid_y_points_spin, 2, 3)

        self._refresh_route_summary()
    
    def _calculate_route(self):
        """Calculate and display the measurement route."""
        try:
            scan_type = self.scan_type_group.checkedId()
            positions = []
            
            if scan_type == 0:  # Vertical line
                x_m = self.x_fixed_spin.value()
                y_start, y_end = self.y_range_slider.values()
                y_count = self.y_points_spin.value()
                
                if y_count < 2:
                    QMessageBox.warning(self, "Invalid Input", "Point count must be at least 2")
                    return
                
                y_positions = np.linspace(y_start, y_end, y_count)
                
                for y_m in y_positions:
                    x_steps = self._meters_to_steps(x_m)
                    y_steps = self._meters_to_steps(y_m)
                    # Clamp to bounds to handle floating-point precision at max values
                    x_steps = max(0, min(x_steps, self.X_MAX_STEPS))
                    y_steps = max(0, min(y_steps, self.Y_MAX_STEPS))
                    
                    if not self._validate_bounds(x_steps, y_steps):
                        QMessageBox.warning(self, "Out of Bounds", 
                                          f"Position out of workspace bounds: X={x_m:.4f}m, Y={y_m:.4f}m")
                        return
                    
                    positions.append({
                        'x_m': x_m,
                        'y_m': y_m,
                        'x_steps': x_steps,
                        'y_steps': y_steps
                    })
            
            elif scan_type == 1:  # Horizontal line
                y_m = self.y_fixed_spin.value()
                x_start, x_end = self.x_range_slider.values()
                x_count = self.x_points_spin.value()
                
                if x_count < 2:
                    QMessageBox.warning(self, "Invalid Input", "Point count must be at least 2")
                    return
                
                x_positions = np.linspace(x_start, x_end, x_count)
                
                for x_m in x_positions:
                    x_steps = self._meters_to_steps(x_m)
                    y_steps = self._meters_to_steps(y_m)
                    # Clamp to bounds to handle floating-point precision at max values
                    x_steps = max(0, min(x_steps, self.X_MAX_STEPS))
                    y_steps = max(0, min(y_steps, self.Y_MAX_STEPS))
                    
                    if not self._validate_bounds(x_steps, y_steps):
                        QMessageBox.warning(self, "Out of Bounds", 
                                          f"Position out of workspace bounds: X={x_m:.4f}m, Y={y_m:.4f}m")
                        return
                    
                    positions.append({
                        'x_m': x_m,
                        'y_m': y_m,
                        'x_steps': x_steps,
                        'y_steps': y_steps
                    })
            
            else:  # XY Grid
                x_start, x_end = self.x_range_slider.values()
                x_count = self.grid_x_points_spin.value()
                y_start, y_end = self.y_range_slider.values()
                y_count = self.grid_y_points_spin.value()
                
                if x_count < 2 or y_count < 2:
                    QMessageBox.warning(self, "Invalid Input", "Point counts must be at least 2")
                    return
                
                x_positions = np.linspace(x_start, x_end, x_count)
                y_positions = np.linspace(y_start, y_end, y_count)
                
                # Create grid points with snake/boustrophedon pattern:
                # Even rows (0, 2, 4...): left-to-right
                # Odd rows (1, 3, 5...): right-to-left
                for row_idx, y_m in enumerate(y_positions):
                    # Reverse direction on odd rows for efficient snake pattern
                    x_scan = x_positions if row_idx % 2 == 0 else x_positions[::-1]
                    
                    for x_m in x_scan:
                        x_steps = self._meters_to_steps(x_m)
                        y_steps = self._meters_to_steps(y_m)
                        # Clamp to bounds to handle floating-point precision at max values
                        x_steps = max(0, min(x_steps, self.X_MAX_STEPS))
                        y_steps = max(0, min(y_steps, self.Y_MAX_STEPS))
                        
                        if not self._validate_bounds(x_steps, y_steps):
                            QMessageBox.warning(self, "Out of Bounds", 
                                              f"Position out of workspace bounds: X={x_m:.4f}m, Y={y_m:.4f}m")
                            return
                        
                        positions.append({
                            'x_m': x_m,
                            'y_m': y_m,
                            'x_steps': x_steps,
                            'y_steps': y_steps
                        })
            
            self.calculated_positions = positions
            self.completed_positions = []
            
            # Update preview
            self._update_preview()
            
            # Update info label
            dwell_time = self.dwell_time_spin.value()
            settling_time = self.settling_time_spin.value()
            time_per_point = dwell_time + settling_time + 5.0  # +5s for movement estimate
            total_time_min = (len(positions) * time_per_point) / 60.0
            
            self.route_info_label.setText(
                f"{len(positions)} positions calculated. Estimated time: {total_time_min:.1f} minutes"
            )
            self.route_info_label.setStyleSheet("color: #28a745; font-weight: bold;")
            self._refresh_route_summary()
            
            # Enable start button
            self.start_btn.setEnabled(True)
            
        except Exception as e:
            logger.exception("Failed to calculate route")
            QMessageBox.critical(self, "Calculation Error", f"Failed to calculate route:\n{e}")
    
    def _update_preview(self):
        """Update the route preview table."""
        if not self.calculated_positions:
            self.preview_table.setRowCount(0)
            self._update_route_plot()
            return

        self.preview_table.setRowCount(len(self.calculated_positions))
        current_progress = len(self.completed_positions)
        
        for i, pos in enumerate(self.calculated_positions):
            x_m = pos['x_m']
            y_m = pos['y_m']
            x_steps = pos['x_steps']
            y_steps = pos['y_steps']

            if i in self.completed_positions:
                status = "✓ Complete"
            elif self.worker and self.worker_thread and self.worker_thread.isRunning():
                if i == current_progress:
                    status = "→ Current"
                elif i < current_progress:
                    status = "✓ Complete"
                else:
                    status = "Pending"
            else:
                status = "Pending"

            row_items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(f"{x_m:.4f}"),
                QTableWidgetItem(f"{y_m:.4f}"),
                QTableWidgetItem(str(x_steps)),
                QTableWidgetItem(str(y_steps)),
                QTableWidgetItem(status),
            ]

            if status == "→ Current":
                row_color = QColor("#fff3cd")
            elif status == "✓ Complete":
                row_color = QColor("#d1e7dd")
            else:
                row_color = None

            for col, item in enumerate(row_items):
                if row_color is not None:
                    item.setBackground(row_color)
                self.preview_table.setItem(i, col, item)

        if self.worker and self.worker_thread and self.worker_thread.isRunning():
            if 0 <= current_progress < self.preview_table.rowCount():
                self.preview_table.scrollToItem(self.preview_table.item(current_progress, 0))

        self._update_route_plot()

    def _update_route_plot(self):
        """Render a compact map of route order and progress state."""
        if not hasattr(self, 'preview_ax'):
            return

        self.preview_ax.clear()
        self.preview_ax.set_facecolor('#f8f9fa')

        if not self.calculated_positions:
            self.preview_ax.set_xticks([])
            self.preview_ax.set_yticks([])
            for spine in self.preview_ax.spines.values():
                spine.set_visible(False)
            self.preview_ax.text(
                0.5,
                0.5,
                "No route calculated",
                ha='center',
                va='center',
                transform=self.preview_ax.transAxes,
                color='#6c757d',
                fontsize=10,
            )
            self.preview_canvas.draw_idle()
            return

        x_vals = np.array([pos['x_m'] for pos in self.calculated_positions], dtype=float)
        y_vals = np.array([pos['y_m'] for pos in self.calculated_positions], dtype=float)

        self.preview_ax.plot(x_vals, y_vals, color='#0d6efd', linewidth=1.5, alpha=0.7, zorder=1)
        self.preview_ax.scatter(x_vals, y_vals, s=28, color='#adb5bd', edgecolors='white', linewidths=0.5, zorder=2)

        if self.completed_positions:
            done_idx = np.array(sorted(set(i for i in self.completed_positions if 0 <= i < len(x_vals))))
            if done_idx.size > 0:
                self.preview_ax.scatter(
                    x_vals[done_idx],
                    y_vals[done_idx],
                    s=36,
                    color='#198754',
                    edgecolors='white',
                    linewidths=0.6,
                    zorder=3,
                )

        if self.worker and self.worker_thread and self.worker_thread.isRunning():
            current_idx = len(self.completed_positions)
            if 0 <= current_idx < len(x_vals):
                self.preview_ax.scatter(
                    [x_vals[current_idx]],
                    [y_vals[current_idx]],
                    s=90,
                    facecolors='none',
                    edgecolors='#fd7e14',
                    linewidths=2.0,
                    zorder=4,
                )

        self.preview_ax.scatter([x_vals[0]], [y_vals[0]], s=52, color='#20c997', edgecolors='white', linewidths=0.8, zorder=5)
        self.preview_ax.scatter([x_vals[-1]], [y_vals[-1]], s=52, color='#dc3545', edgecolors='white', linewidths=0.8, zorder=5)

        self.preview_ax.set_title("Route Map", fontsize=10, fontweight='bold', color='#212529')
        self.preview_ax.set_xlabel("X (m)", fontsize=9)
        self.preview_ax.set_ylabel("Y (m)", fontsize=9)
        self.preview_ax.grid(True, linestyle='--', alpha=0.25)

        x_span = float(np.max(x_vals) - np.min(x_vals)) if len(x_vals) > 1 else 0.1
        y_span = float(np.max(y_vals) - np.min(y_vals)) if len(y_vals) > 1 else 0.1
        x_pad = max(0.02, x_span * 0.08)
        y_pad = max(0.02, y_span * 0.08)
        self.preview_ax.set_xlim(float(np.min(x_vals)) - x_pad, float(np.max(x_vals)) + x_pad)
        self.preview_ax.set_ylim(float(np.min(y_vals)) - y_pad, float(np.max(y_vals)) + y_pad)

        self.preview_canvas.draw_idle()

    def _refresh_route_summary(self):
        """Refresh the compact route summary strip from current UI inputs."""
        if not hasattr(self, 'summary_label'):
            return

        scan_type = self.scan_type_group.checkedId() if hasattr(self, 'scan_type_group') else 0
        dwell_time = self.dwell_time_spin.value() if hasattr(self, 'dwell_time_spin') else self.default_dwell_time
        settling_time = self.settling_time_spin.value() if hasattr(self, 'settling_time_spin') else self.default_settling_time

        mode_label = "Vertical"
        point_count = 0

        if scan_type == 0:
            mode_label = "Vertical"
            point_count = self.y_points_spin.value()
            y_start, y_end = self.y_range_slider.values()
            detail = f"X={self.x_fixed_spin.value():.4f} m, Y {y_start:.4f}→{y_end:.4f} m"
        elif scan_type == 1:
            mode_label = "Horizontal"
            point_count = self.x_points_spin.value()
            x_start, x_end = self.x_range_slider.values()
            detail = f"Y={self.y_fixed_spin.value():.4f} m, X {x_start:.4f}→{x_end:.4f} m"
        else:
            mode_label = "XY Grid"
            point_count = self.grid_x_points_spin.value() * self.grid_y_points_spin.value()
            x_start, x_end = self.x_range_slider.values()
            y_start, y_end = self.y_range_slider.values()
            detail = (
                f"X {x_start:.4f}→{x_end:.4f} m, Y {y_start:.4f}→{y_end:.4f} m, "
                f"{self.grid_x_points_spin.value()}x{self.grid_y_points_spin.value()}"
            )

        time_per_point = dwell_time + settling_time + 5.0
        total_seconds = point_count * time_per_point
        total_text = self._format_duration(total_seconds)

        self.summary_label.setText(
            f"{mode_label} | {point_count} points | Dwell {dwell_time:.1f}s | "
            f"Settle {settling_time:.1f}s | Est. total {total_text} | {detail}"
        )

    def _format_duration(self, total_seconds: float) -> str:
        """Format seconds as mm:ss or hh:mm:ss."""
        total = max(0, int(round(total_seconds)))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    
    def _start_automation(self):
        """Start the automated measurement sequence."""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Automation Running", "A scan is already running.")
            return

        if not self.calculated_positions:
            QMessageBox.warning(self, "No Route", "Please calculate a route first")
            return
        
        # Check VXC connection
        if not self.vxc:
            QMessageBox.critical(self, "No Controller", "VXC controller not available")
            return
        
        # Confirmation dialog
        dwell_time = self.dwell_time_spin.value()
        settling_time = self.settling_time_spin.value()
        num_positions = len(self.calculated_positions)
        time_per_point = dwell_time + settling_time + 5.0
        total_time_min = (num_positions * time_per_point) / 60.0
        
        reply = QMessageBox.question(
            self, "Start Automation",
            f"This will move the VXC stage to {num_positions} positions.\n"
            f"Estimated time: {total_time_min:.1f} minutes\n\n"
            f"Ensure FlowTracker2 is running and streaming data.\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Export route plan to session if active
        self._export_route_to_session()
        
        # Disable UI controls
        self._set_ui_enabled(False)
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.skip_btn.setEnabled(False)
        self._run_outcome = "running"
        self.status_label.setText("Starting scan...")
        
        # Reset progress
        self.completed_positions = []
        self.progress_bar.setValue(0)
        self.eta_label.setText("Calculating...")
        
        # Start ETA timer
        self.automation_start_time = time.time()
        self.total_pause_time = 0.0
        self.pause_start_time = None
        self.eta_timer.start(1000)  # Update every second
        
        # Create worker and thread
        self.worker_thread = QThread()
        self.worker = CrossSectionWorker(
            self.vxc,
            self.calculated_positions,
            dwell_time,
            settling_time,
            speed=2000  # Default VXC speed in steps/sec
        )
        self.worker.moveToThread(self.worker_thread)
        
        # Connect signals
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.position_reached.connect(self._on_position_reached)
        self.worker.status_update.connect(self._on_status_update)
        self.worker.eta_update.connect(self._on_eta_update)
        self.worker.error.connect(self._on_error)
        self.worker.position_error.connect(self._on_position_error)
        self.worker.completed.connect(self._on_completed)
        self.worker.run_finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._cleanup)
        
        # Start automation
        self.worker_thread.start()
        logger.info(f"Started cross-section automation with {num_positions} positions")
    
    def _pause_automation(self):
        """Pause/resume the automation."""
        if not self.worker:
            return
        
        if self.pause_btn.text() == "Pause":
            self.worker.pause()
            self.pause_btn.setText("Resume")
            self.status_label.setText("Paused - Click Resume to continue")
            self.pause_start_time = time.time()
            self.eta_timer.stop()  # Stop ETA countdown while paused
            logger.info("Automation paused")
        else:
            self.worker.resume()
            self.pause_btn.setText("Pause")
            self.status_label.setText("Resuming...")
            # Track total pause time
            if self.pause_start_time:
                self.total_pause_time += time.time() - self.pause_start_time
                self.pause_start_time = None
            self.eta_timer.start(1000)  # Resume ETA countdown
            logger.info("Automation resumed")
    
    def _stop_automation(self):
        """Stop the automation."""
        if not self.worker:
            return
        
        reply = QMessageBox.question(
            self, "Stop Automation",
            "Are you sure you want to stop the automation?\n"
            "The current position will complete before stopping.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.worker.stop()
            self._run_outcome = "stopped"
            self.status_label.setText("Stopping...")
            self.stop_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            logger.info("Automation stop requested")
    
    def _on_progress(self, current: int, total: int):
        """Handle progress update from worker."""
        percentage = int((current / total) * 100)
        self.progress_bar.setValue(percentage)
        self._update_preview()
    
    def _on_position_reached(self, x_m: float, y_m: float, index: int):
        """Handle position reached signal from worker."""
        self.completed_positions.append(index)
        self._update_preview()
        logger.info(f"Position {index+1} reached: X={x_m:.4f}m, Y={y_m:.4f}m")
    
    def _on_status_update(self, message: str):
        """Handle status update from worker."""
        self.status_label.setText(message)
    
    def _on_eta_update(self, elapsed_sec: float, remaining_sec: float, current_pos: int, total_pos: int):
        """Handle ETA update from worker."""
        self.estimated_remaining_sec = remaining_sec
        self.last_eta_update_time = time.time()
    
    def _update_eta_display(self):
        """Update the ETA display with live countdown."""
        if self.automation_start_time is None:
            return
        
        # Calculate actual elapsed time (excluding pause time)
        elapsed_total = time.time() - self.automation_start_time - self.total_pause_time
        
        # Adjust remaining time based on time since last worker update
        if self.last_eta_update_time:
            time_since_update = time.time() - self.last_eta_update_time
            adjusted_remaining = max(0, self.estimated_remaining_sec - time_since_update)
        else:
            adjusted_remaining = self.estimated_remaining_sec
        
        # Format elapsed time
        elapsed_min = int(elapsed_total // 60)
        elapsed_sec = int(elapsed_total % 60)
        
        # Format remaining time
        remaining_min = int(adjusted_remaining // 60)
        remaining_sec = int(adjusted_remaining % 60)
        
        # Calculate total time
        total_time = elapsed_total + adjusted_remaining
        total_min = int(total_time // 60)
        total_sec = int(total_time % 60)
        
        # Update label with countdown
        eta_text = f"⏱ Elapsed: {elapsed_min:02d}:{elapsed_sec:02d} | Remaining: {remaining_min:02d}:{remaining_sec:02d} | Total: ~{total_min:02d}:{total_sec:02d}"
        self.eta_label.setText(eta_text)
    
    def _on_error(self, error_msg: str):
        """Handle error from worker."""
        self._run_outcome = "error"
        QMessageBox.critical(self, "Automation Error", error_msg)
        self.status_label.setText(f"Error: {error_msg}")

    def _on_position_error(self, error_msg: str):
        """Handle a recoverable position error — enables Skip button to continue scan."""
        logger.warning(f"Position error (awaiting user action): {error_msg}")
        self.status_label.setText(f"\u26a0 {error_msg} — click Skip Position or Stop")
        self.skip_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)  # Disable pause while waiting for decision

    def _skip_position(self):
        """Skip the current erroneous position and continue the scan."""
        if self.worker:
            self.worker.skip_position()
            self.skip_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.status_label.setText("Position skipped — continuing scan...")
            logger.info("User skipped position")
    
    def _on_completed(self):
        """Handle automation completion."""
        self._run_outcome = "completed"
        QMessageBox.information(self, "Complete", 
                               f"Cross-section scan completed successfully!\n"
                               f"{len(self.completed_positions)} positions measured.")
        self.status_label.setText("Completed successfully")
        logger.info("Automation completed successfully")
    
    def _cleanup(self):
        """Clean up after automation completes or stops."""
        # Stop ETA timer
        self.eta_timer.stop()
        
        # Show final run timing and outcome
        if self.automation_start_time:
            final_elapsed = time.time() - self.automation_start_time - self.total_pause_time
            elapsed_min = int(final_elapsed // 60)
            elapsed_sec = int(final_elapsed % 60)
            if self._run_outcome == "completed":
                self.eta_label.setText(f"✓ Completed in {elapsed_min:02d}:{elapsed_sec:02d}")
            elif self._run_outcome == "stopped":
                self.eta_label.setText(f"■ Stopped at {elapsed_min:02d}:{elapsed_sec:02d}")
            elif self._run_outcome == "error":
                self.eta_label.setText(f"! Error after {elapsed_min:02d}:{elapsed_sec:02d}")
            else:
                self.eta_label.setText(f"Elapsed: {elapsed_min:02d}:{elapsed_sec:02d}")
        else:
            self.eta_label.setText("")
        
        self.automation_start_time = None
        self.estimated_remaining_sec = 0.0
        self.last_eta_update_time = None
        self.total_pause_time = 0.0
        self.pause_start_time = None
        
        self.pause_btn.setText("Pause")
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self._set_ui_enabled(True)
        
        if self.calculated_positions:
            self.start_btn.setEnabled(True)
        
        self.worker = None
        self.worker_thread = None
        self._run_outcome = "idle"
        
        self._update_preview()
    
    def _export_route_to_session(self):
        """Export route plan to active session folder."""
        # Get active session from parent's auto_merge_tab
        try:
            parent_window = self.window()
            if hasattr(parent_window, 'auto_merge_tab'):
                auto_merge_tab = parent_window.auto_merge_tab
                if hasattr(auto_merge_tab, 'session_manager') and auto_merge_tab.session_manager:
                    session_mgr = auto_merge_tab.session_manager
                    if session_mgr.is_active():
                        # Export route plan to session directory
                        session_dir = session_mgr.session_dir
                        route_file = session_dir / "route_plan.csv"
                        
                        import csv
                        with open(route_file, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow(['point_number', 'x_m', 'y_m', 'x_steps', 'y_steps', 'estimated_dwell_sec'])
                            
                            dwell_time = self.dwell_time_spin.value()
                            for i, pos in enumerate(self.calculated_positions, start=1):
                                x_m = pos['x_m']
                                y_m = pos['y_m']
                                x_steps = pos['x_steps']
                                y_steps = pos['y_steps']
                                writer.writerow([i, f"{x_m:.4f}", f"{y_m:.4f}", x_steps, y_steps, dwell_time])
                        
                        # Update session config with scan parameters
                        scan_type = "Vertical_Line" if self.vertical_radio.isChecked() else \
                                   "Horizontal_Line" if self.horizontal_radio.isChecked() else "XY_Grid"
                        
                        session_mgr.session_config.scan_type = scan_type
                        session_mgr.session_config.dwell_time_sec = self.dwell_time_spin.value()
                        session_mgr.session_config.settling_time_sec = self.settling_time_spin.value()
                        session_mgr.session_config.point_count_x = len(self.calculated_positions) if scan_type != "XY_Grid" else self.grid_x_points_spin.value()
                        session_mgr.session_config.point_count_y = 1 if scan_type != "XY_Grid" else self.grid_y_points_spin.value()
                        
                        if scan_type == "Vertical_Line":
                            y_start, y_end = self.y_range_slider.values()
                            session_mgr.session_config.start_position = [self.x_fixed_spin.value(), y_start]
                            session_mgr.session_config.end_position = [self.x_fixed_spin.value(), y_end]
                        elif scan_type == "Horizontal_Line":
                            x_start, x_end = self.x_range_slider.values()
                            session_mgr.session_config.start_position = [x_start, self.y_fixed_spin.value()]
                            session_mgr.session_config.end_position = [x_end, self.y_fixed_spin.value()]
                        elif scan_type == "XY_Grid":
                            x_start, x_end = self.x_range_slider.values()
                            y_start, y_end = self.y_range_slider.values()
                            session_mgr.session_config.start_position = [x_start, y_start]
                            session_mgr.session_config.end_position = [x_end, y_end]
                            session_mgr.session_config.scan_pattern = "snake"
                        
                        logger.info(f"Exported route plan to {route_file}")
        except Exception as e:
            logger.warning(f"Failed to export route to session: {e}")
    
    def _set_ui_enabled(self, enabled: bool):
        """Enable/disable UI controls during automation."""
        self.calculate_btn.setEnabled(enabled)
        self.vertical_radio.setEnabled(enabled)
        self.horizontal_radio.setEnabled(enabled)
        self.grid_radio.setEnabled(enabled)
        
        # Disable all input controls (spinboxes and range sliders)
        for widget in [self.x_fixed_spin, self.y_fixed_spin, self.x_range_slider,
                      self.y_range_slider, self.x_points_spin, self.y_points_spin, 
                      self.grid_x_points_spin, self.grid_y_points_spin, 
                      self.dwell_time_spin, self.settling_time_spin]:
            widget.setEnabled(enabled)
    
    def _meters_to_steps(self, meters: float) -> int:
        """Convert meters to steps."""
        feet = meters / self.METERS_PER_FOOT
        inches = feet * 12.0
        steps = int(round(inches * self.STEPS_PER_INCH))
        return steps
    
    def _steps_to_meters(self, steps: float) -> float:
        """Convert steps to meters."""
        inches = steps / self.STEPS_PER_INCH
        feet = inches / 12.0
        meters = feet * self.METERS_PER_FOOT
        return meters
    
    def _validate_bounds(self, x_steps: int, y_steps: int) -> bool:
        """Validate that position is within workspace bounds."""
        if x_steps < self.boundaries['x_min_steps'] or x_steps > self.boundaries['x_max_steps']:
            return False
        if y_steps < self.boundaries['y_min_steps'] or y_steps > self.boundaries['y_max_steps']:
            return False
        return True

    def update_boundaries(self, boundaries: dict):
        """Update workspace boundaries and reconfigure UI.
        
        Args:
            boundaries: Dict with x_min_steps, x_max_steps, y_min_steps, y_max_steps
        """
        self.boundaries = boundaries
        self.X_MAX_STEPS = boundaries['x_max_steps']
        self.Y_MAX_STEPS = boundaries['y_max_steps']
        
        # Update UI elements with new boundaries
        x_max_m = self._steps_to_meters(self.X_MAX_STEPS)
        y_max_m = self._steps_to_meters(self.Y_MAX_STEPS)
        
        # Update workspace info label
        if hasattr(self, 'workspace_label'):
            info_text = f"Workspace: X: 0 to {x_max_m:.4f} m, Y: 0 to {y_max_m:.4f} m"
            self.workspace_label.setText(info_text)
        
        # Update range sliders
        if hasattr(self, 'x_range_slider'):
            self.x_range_slider.setRange(0.0, x_max_m)
            self.x_range_slider.setValues(0.0, x_max_m)
        
        if hasattr(self, 'y_range_slider'):
            self.y_range_slider.setRange(0.0, y_max_m)
            self.y_range_slider.setValues(0.0, y_max_m)
        
        # Update fixed position spinboxes
        if hasattr(self, 'x_fixed_spin'):
            self.x_fixed_spin.setRange(0.0, x_max_m)
            self.x_fixed_spin.setValue(min(self.x_fixed_spin.value(), x_max_m))
        
        if hasattr(self, 'y_fixed_spin'):
            self.y_fixed_spin.setRange(0.0, y_max_m)
            self.y_fixed_spin.setValue(min(self.y_fixed_spin.value(), y_max_m))

        self._refresh_route_summary()
    
    def _update_y_range_label(self, low: float, high: float):
        """Update Y range label when slider changes."""
        self.y_range_value_label.setText(f"{low:.4f} m \u2192 {high:.4f} m")
        self._refresh_route_summary()
    
    def _update_x_range_label(self, low: float, high: float):
        """Update X range label when slider changes."""
        self.x_range_value_label.setText(f"{low:.4f} m \u2192 {high:.4f} m")
        self._refresh_route_summary()

