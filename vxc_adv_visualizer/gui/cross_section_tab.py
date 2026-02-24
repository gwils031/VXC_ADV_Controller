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
from PyQt5.QtCore import QObject, QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton,
    QLabel, QDoubleSpinBox, QSpinBox, QPushButton, QProgressBar,
    QTextEdit, QMessageBox, QButtonGroup, QGridLayout
)

from .range_slider import QRangeSlider

logger = logging.getLogger(__name__)


class CrossSectionWorker(QObject):
    """Worker thread for automated cross-section measurements."""
    
    progress = pyqtSignal(int, int)  # current, total
    position_reached = pyqtSignal(float, float, int)  # x_m, y_m, index
    completed = pyqtSignal()
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)
    eta_update = pyqtSignal(float, float, int, int)  # elapsed_sec, remaining_sec, current_pos, total_pos
    
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
                    self.error.emit(error_msg)
                    break
                
                # Verify position reached with tolerance checking
                actual_x = self.controller.get_position(motor=2)
                actual_y = self.controller.get_position(motor=1)
                
                if actual_x is None or actual_y is None:
                    error_msg = f"Failed to verify position {i+1} - could not read actual position"
                    logger.error(error_msg)
                    self.error.emit(error_msg)
                    break
                
                # Check position accuracy (tolerance: ±10 steps)
                pos_error_x = abs(actual_x - x_steps)
                pos_error_y = abs(actual_y - y_steps)
                logger.info(f"Position verification: Target=({x_steps}, {y_steps}), Actual=({actual_x}, {actual_y}), Error=({pos_error_x}, {pos_error_y})")
                
                if pos_error_x > 10 or pos_error_y > 10:
                    error_msg = f"Position {i+1} accuracy error: X_err={pos_error_x} steps, Y_err={pos_error_y} steps (tolerance: ±10)"
                    logger.error(error_msg)
                    self.error.emit(error_msg)
                    break
                
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
    
    def stop(self):
        """Stop the automation."""
        self._running = False
        self._paused = False
    
    def pause(self):
        """Pause the automation."""
        self._paused = True
    
    def resume(self):
        """Resume the automation."""
        self._paused = False


class CrossSectionTab(QWidget):
    """Tab for automated cross-section measurement control."""
    
    # Hardware constants
    STEPS_PER_INCH = 4000.0
    METERS_PER_FOOT = 0.3048
    X_MAX_STEPS = 163963  # Motor 2
    Y_MAX_STEPS = 39000   # Motor 1
    
    def __init__(self, vxc_controller, vxc_logger=None):
        super().__init__()
        self.vxc = vxc_controller
        self.vxc_logger = vxc_logger
        
        self.worker = None
        self.worker_thread = None
        self.calculated_positions = []
        self.completed_positions = []
        
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
        
        # Route Configuration Section
        route_group = self._create_route_config_group()
        layout.addWidget(route_group)
        
        # Automation Control Section
        control_group = self._create_control_group()
        layout.addWidget(control_group)
        
        # Route Preview Section
        preview_group = self._create_preview_group()
        layout.addWidget(preview_group, stretch=1)
        
        self.setLayout(layout)
    
    def _create_route_config_group(self) -> QGroupBox:
        """Create route configuration UI group."""
        group = QGroupBox("Route Configuration")
        layout = QVBoxLayout()
        
        # Scan type selection
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
        
        scan_layout.addWidget(self.vertical_radio)
        scan_layout.addWidget(self.horizontal_radio)
        scan_layout.addWidget(self.grid_radio)
        scan_layout.addStretch()
        
        layout.addLayout(scan_layout)
        
        # Position input fields (dynamic based on scan type)
        self.position_grid = QGridLayout()
        
        # Workspace limits for reference
        x_max_m = self._steps_to_meters(self.X_MAX_STEPS)
        y_max_m = self._steps_to_meters(self.Y_MAX_STEPS)
        
        info_text = f"Workspace: X: 0 to {x_max_m:.4f} m, Y: 0 to {y_max_m:.4f} m"
        self.workspace_label = QLabel(info_text)
        self.workspace_label.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(self.workspace_label)
        
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
        
        # Add to position grid (will be shown/hidden based on scan type)
        layout.addLayout(self.position_grid)
        
        # Timing configuration
        timing_layout = QHBoxLayout()
        timing_layout.addWidget(QLabel("Dwell Time (seconds/point):"))
        
        self.dwell_time_spin = QDoubleSpinBox()
        self.dwell_time_spin.setRange(10.0, 300.0)
        self.dwell_time_spin.setDecimals(1)
        self.dwell_time_spin.setSingleStep(5.0)
        self.dwell_time_spin.setValue(self.default_dwell_time)
        timing_layout.addWidget(self.dwell_time_spin)
        
        timing_layout.addWidget(QLabel("Settling Time (seconds):"))
        self.settling_time_spin = QDoubleSpinBox()
        self.settling_time_spin.setRange(0.0, 30.0)
        self.settling_time_spin.setDecimals(1)
        self.settling_time_spin.setSingleStep(0.5)
        self.settling_time_spin.setValue(self.default_settling_time)
        timing_layout.addWidget(self.settling_time_spin)
        
        timing_layout.addStretch()
        layout.addLayout(timing_layout)
        
        group.setLayout(layout)
        
        # Initialize with vertical line layout
        self._on_scan_type_changed()
        
        return group
    
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
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setStyleSheet("font-family: 'Courier New'; font-size: 9pt;")
        layout.addWidget(self.preview_text)
        
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
            
            # Enable start button
            self.start_btn.setEnabled(True)
            
        except Exception as e:
            logger.exception("Failed to calculate route")
            QMessageBox.critical(self, "Calculation Error", f"Failed to calculate route:\n{e}")
    
    def _update_preview(self):
        """Update the route preview text."""
        if not self.calculated_positions:
            self.preview_text.setPlainText("No route calculated")
            return
        
        lines = ["Position | X (m)      | Y (m)      | X (steps) | Y (steps) | Status"]
        lines.append("-" * 75)
        
        for i, pos in enumerate(self.calculated_positions):
            x_m = pos['x_m']
            y_m = pos['y_m']
            x_steps = pos['x_steps']
            y_steps = pos['y_steps']
            
            if i in self.completed_positions:
                status = "✓ Complete"
            elif self.worker and self.worker_thread and self.worker_thread.isRunning():
                current_progress = len(self.completed_positions)
                if i == current_progress:
                    status = "→ Current"
                elif i < current_progress:
                    status = "✓ Complete"
                else:
                    status = "Pending"
            else:
                status = "Pending"
            
            line = f"{i+1:8d} | {x_m:10.4f} | {y_m:10.4f} | {x_steps:9d} | {y_steps:9d} | {status}"
            lines.append(line)
        
        self.preview_text.setPlainText("\n".join(lines))
    
    def _start_automation(self):
        """Start the automated measurement sequence."""
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
        self.worker.completed.connect(self._on_completed)
        self.worker.completed.connect(self.worker_thread.quit)
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
            self.status_label.setText("Stopping...")
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
        QMessageBox.critical(self, "Automation Error", error_msg)
        self.status_label.setText(f"Error: {error_msg}")
        self._cleanup()
    
    def _on_completed(self):
        """Handle automation completion."""
        QMessageBox.information(self, "Complete", 
                               f"Cross-section scan completed successfully!\n"
                               f"{len(self.completed_positions)} positions measured.")
        self.status_label.setText("Completed successfully")
        logger.info("Automation completed successfully")
    
    def _cleanup(self):
        """Clean up after automation completes or stops."""
        # Stop ETA timer
        self.eta_timer.stop()
        
        # Show final time if automation completed
        if self.automation_start_time:
            final_elapsed = time.time() - self.automation_start_time - self.total_pause_time
            elapsed_min = int(final_elapsed // 60)
            elapsed_sec = int(final_elapsed % 60)
            self.eta_label.setText(f"✓ Completed in {elapsed_min:02d}:{elapsed_sec:02d}")
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
        self._set_ui_enabled(True)
        
        if self.calculated_positions:
            self.start_btn.setEnabled(True)
        
        self.worker = None
        self.worker_thread = None
        
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
                            for i, (x_steps, y_steps) in enumerate(self.calculated_positions, start=1):
                                x_m = self._steps_to_meters(x_steps)
                                y_m = self._steps_to_meters(y_steps)
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
        if x_steps < 0 or x_steps > self.X_MAX_STEPS:
            return False
        if y_steps < 0 or y_steps > self.Y_MAX_STEPS:
            return False
        return True
    
    def _update_y_range_label(self, low: float, high: float):
        """Update Y range label when slider changes."""
        self.y_range_value_label.setText(f"{low:.4f} m \u2192 {high:.4f} m")
    
    def _update_x_range_label(self, low: float, high: float):
        """Update X range label when slider changes."""
        self.x_range_value_label.setText(f"{low:.4f} m \u2192 {high:.4f} m")

