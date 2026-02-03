"""PyQt5 Main GUI for VXC/ADV flow measurement system."""

import logging
import sys
import os
import yaml
import numpy as np
import time
import serial
from typing import Optional, Dict, List
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QFileDialog, QMessageBox, QProgressBar, QTableWidget,
    QTableWidgetItem, QDialog, QFrame, QGridLayout, QGroupBox,
    QListWidget, QListWidgetItem, QSpinBox as QSpinBoxWidget, QTextEdit,
    QApplication
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtChart import QChart, QChartView, QBarSeries, QBarSet

import pyqtgraph as pg
from pyqtgraph import ImageView

from controllers import VXCController, ADVController
from acquisition.sampler import Sampler, SamplingState, SamplingPosition
from acquisition.calibration import CalibrationManager, STEPS_PER_FOOT
from data.data_logger import DataLogger
from data.exporters import export_csv, export_hdf5, export_vtk
from utils.serial_utils import list_available_ports

logger = logging.getLogger(__name__)


class AcquisitionWorker(QThread):
    """Worker thread for non-blocking acquisition."""
    
    status_update = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    position_sampled = pyqtSignal(dict)
    acquisition_complete = pyqtSignal()
    error_occurred = pyqtSignal(str)
    
    def __init__(self, sampler: Sampler):
        """Initialize worker.
        
        Args:
            sampler: Sampler instance
        """
        super().__init__()
        self.sampler = sampler
        self.running = False
    
    def run(self):
        """Run acquisition sequence."""
        try:
            self.running = True
            self.sampler.run_measurement_sequence()
            self.acquisition_complete.emit()
        except Exception as e:
            logger.error(f"Acquisition error: {e}")
            self.error_occurred.emit(str(e))
        finally:
            self.running = False


class PortScanWorker(QThread):
    """Worker thread for port/protocol scanning."""
    
    log_message = pyqtSignal(str)
    scan_complete = pyqtSignal()
    
    def __init__(self, ports: List[tuple], baud_rates: List[int], line_endings: List[str], commands: List[tuple]):
        """Initialize scanner."""
        super().__init__()
        self.ports = ports
        self.baud_rates = baud_rates
        self.line_endings = line_endings
        self.commands = commands
        self.running = True
    
    def run(self):
        """Run the scan."""
        try:
            flow_options = [
                (False, False, "None"),
                (True, False, "RTS/CTS"),
            ]
            
            self.log_message.emit(f"[SCAN] Starting port scan: {len(self.ports)} ports, {len(self.baud_rates)} bauds, {len(self.line_endings)} endings")
            
            for port, desc in self.ports:
                if not self.running:
                    break
                    
                self.log_message.emit(f"[PORT] {port}: {desc}")
                
                for baud in self.baud_rates:
                    if not self.running:
                        break
                    
                    for line_ending in self.line_endings:
                        if not self.running:
                            break
                        
                        for rtscts, dsrdtr, flow_label in flow_options:
                            if not self.running:
                                break
                            
                            try:
                                with serial.Serial(
                                    port=port,
                                    baudrate=baud,
                                    bytesize=serial.EIGHTBITS,
                                    parity=serial.PARITY_NONE,
                                    stopbits=serial.STOPBITS_ONE,
                                    timeout=1.0,
                                    rtscts=rtscts,
                                    dsrdtr=dsrdtr,
                                ) as ser:
                                    ser.reset_input_buffer()
                                    ser.reset_output_buffer()
                                    time.sleep(0.5)
                                    
                                    for cmd, cmd_label in self.commands:
                                        if not self.running:
                                            break
                                        
                                        try:
                                            payload = (cmd + line_ending).encode("ascii", errors="ignore")
                                            ser.write(payload)
                                            ser.flush()
                                            time.sleep(0.4)
                                            
                                            response = ser.read_all()
                                            if response:
                                                preview = response[:80]
                                                line_label = repr(line_ending).replace("'", "")
                                                self.log_message.emit(
                                                    f"[FOUND] {port}@{baud} [{flow_label}, {line_label}] {cmd} -> {preview!r}"
                                                )
                                                return
                                        except Exception:
                                            pass
                                        
                            except serial.SerialException:
                                pass
                            except Exception as e:
                                self.log_message.emit(f"[ERR] {port}@{baud}: {e}")
            
            self.log_message.emit("[SCAN] Port scan complete. No responses found.")
        
        except Exception as e:
            self.log_message.emit(f"[FATAL] Scan error: {e}")
        finally:
            self.scan_complete.emit()
    
    def stop(self):
        """Stop the scan."""
        self.running = False


class MainWindow(QMainWindow):
    """Main PyQt5 application window with full functionality."""
    
    def __init__(self, config_dir: str = "./config"):
        """Initialize main window.
        
        Args:
            config_dir: Configuration directory path
        """
        super().__init__()
        self.config_dir = config_dir
        self.config = self._load_config()
        
        # Hardware
        self.vxc: Optional[VXCController] = None
        self.adv: Optional[ADVController] = None
        self.sampler: Optional[Sampler] = None
        self.data_logger: Optional[DataLogger] = None
        self.calibration: Optional[CalibrationManager] = None
        
        # Worker thread
        self.acquisition_worker: Optional[AcquisitionWorker] = None
        
        # UI state
        self.current_z_plane = 0.0
        self.current_run_number = 1
        self.measurement_positions: List[SamplingPosition] = []
        
        # Setup UI
        self.setWindowTitle("VXC/ADV Flow Measurement System")
        self.setGeometry(100, 100, 1400, 900)
        
        self._setup_ui()
        self._setup_timers()
        
        logger.info("MainWindow initialized")
    
    def _load_config(self) -> Dict:
        """Load configuration files.
        
        Returns:
            Configuration dictionary
        """
        config = {}
        config_files = {
            'vxc': 'vxc_config.yaml',
            'adv': 'adv_config.yaml',
            'experiment': 'experiment_config.yaml',
        }
        
        for key, filename in config_files.items():
            filepath = os.path.join(self.config_dir, filename)
            try:
                if os.path.exists(filepath):
                    with open(filepath, 'r') as f:
                        config[key] = yaml.safe_load(f) or {}
                else:
                    config[key] = {}
            except Exception as e:
                logger.error(f"Error loading {filename}: {e}")
                config[key] = {}
        
        return config
    
    def _setup_ui(self):
        """Setup user interface."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        
        # Tab widget
        tabs = QTabWidget()
        
        # Calibration tab
        tabs.addTab(self._create_calibration_tab(), "Calibration")
        
        # Acquisition tab
        tabs.addTab(self._create_acquisition_tab(), "Acquisition")
        
        # Configuration tab
        tabs.addTab(self._create_config_tab(), "Configuration")
        
        # Export tab
        tabs.addTab(self._create_export_tab(), "Export")
        
        main_layout.addWidget(tabs)
        central_widget.setLayout(main_layout)
        
        # Menu bar
        self._setup_menu_bar()
    
    def _create_calibration_tab(self) -> QWidget:
        """Create calibration tab."""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Port selection
        port_layout = QGridLayout()
        port_layout.setHorizontalSpacing(12)
        port_layout.setVerticalSpacing(8)
        port_layout.addWidget(QLabel("VXC Port:"), 0, 0)
        self.vxc_port_combo = QComboBox()
        port_layout.addWidget(self.vxc_port_combo, 0, 1)
        
        self.vxc_connect_btn = QPushButton("Connect VXC")
        self.vxc_connect_btn.clicked.connect(self._connect_vxc)
        port_layout.addWidget(self.vxc_connect_btn, 0, 2)
        
        self.vxc_status_label = QLabel("Not Connected")
        self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
        port_layout.addWidget(self.vxc_status_label, 0, 3)
        
        port_layout.addWidget(QLabel("ADV Port:"), 1, 0)
        self.adv_port_combo = QComboBox()
        port_layout.addWidget(self.adv_port_combo, 1, 1)
        
        self.adv_connect_btn = QPushButton("Connect ADV")
        self.adv_connect_btn.clicked.connect(self._connect_adv)
        port_layout.addWidget(self.adv_connect_btn, 1, 2)
        
        self.adv_status_label = QLabel("Not Connected")
        self.adv_status_label.setStyleSheet("color: red; font-weight: bold;")
        port_layout.addWidget(self.adv_status_label, 1, 3)
        
        refresh_btn = QPushButton("Refresh Ports")
        refresh_btn.clicked.connect(self._refresh_ports)
        port_layout.addWidget(refresh_btn, 0, 4)
        
        port_layout.setColumnStretch(1, 1)
        port_layout.setColumnStretch(4, 1)
        layout.addLayout(port_layout)
        self._refresh_ports()

        # Port/Protocol Probe
        probe_group = QGroupBox("Port/Protocol Probe")
        probe_layout = QGridLayout()
        probe_layout.setHorizontalSpacing(12)
        probe_layout.setVerticalSpacing(8)

        probe_layout.addWidget(QLabel("Port:"), 0, 0)
        self.probe_port_combo = QComboBox()
        probe_layout.addWidget(self.probe_port_combo, 0, 1)

        probe_layout.addWidget(QLabel("Baud:"), 0, 2)
        self.probe_baud_combo = QComboBox()
        for baud in [9600, 19200, 38400, 57600, 115200]:
            self.probe_baud_combo.addItem(str(baud), baud)
        # Set default to 38400 (VXC default)
        self.probe_baud_combo.setCurrentIndex(2)
        probe_layout.addWidget(self.probe_baud_combo, 0, 3)

        probe_layout.addWidget(QLabel("Line Ending:"), 0, 4)
        self.probe_line_combo = QComboBox()
        self.probe_line_combo.addItem("CR", "\r")
        self.probe_line_combo.addItem("LF", "\n")
        self.probe_line_combo.addItem("CRLF", "\r\n")
        probe_layout.addWidget(self.probe_line_combo, 0, 5)

        probe_layout.addWidget(QLabel("Flow Control:"), 0, 6)
        self.probe_flow_combo = QComboBox()
        self.probe_flow_combo.addItem("None", (False, False))
        self.probe_flow_combo.addItem("RTS/CTS", (True, False))
        self.probe_flow_combo.addItem("DTR/DSR", (False, True))
        self.probe_flow_combo.addItem("RTS/CTS + DTR/DSR", (True, True))
        probe_layout.addWidget(self.probe_flow_combo, 0, 7)

        probe_btn = QPushButton("Probe Selected")
        probe_btn.clicked.connect(self._probe_selected_port)
        probe_layout.addWidget(probe_btn, 0, 8)

        scan_btn = QPushButton("Scan Ports")
        scan_btn.clicked.connect(self._scan_ports)
        probe_layout.addWidget(scan_btn, 0, 9)
        self.scan_button = scan_btn

        stop_btn = QPushButton("Stop Scan")
        stop_btn.clicked.connect(self._stop_scan)
        stop_btn.setEnabled(False)
        probe_layout.addWidget(stop_btn, 0, 10)
        self.stop_button = stop_btn

        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self._clear_probe_log)
        probe_layout.addWidget(clear_btn, 0, 11)
        
        # Scan status indicator
        self.scan_status = QLabel("Ready")
        self.scan_status.setStyleSheet("color: green; font-weight: bold;")
        probe_layout.addWidget(self.scan_status, 0, 12)

        self.probe_log = QTextEdit()
        self.probe_log.setReadOnly(True)
        self.probe_log.setMinimumHeight(120)
        probe_layout.addWidget(self.probe_log, 1, 0, 1, 13)

        for col in range(1, 13):
            probe_layout.setColumnStretch(col, 1)

        probe_group.setLayout(probe_layout)
        layout.addWidget(probe_group)
        
        # Default probe baud from config when available
        vxc_baud = self.config.get('vxc', {}).get('baudrate')
        if vxc_baud:
            for i in range(self.probe_baud_combo.count()):
                if self.probe_baud_combo.itemData(i) == vxc_baud:
                    self.probe_baud_combo.setCurrentIndex(i)
                    break

        # Default probe baud from config when available
        vxc_baud = self.config.get('vxc', {}).get('baudrate')
        if vxc_baud:
            for i in range(self.probe_baud_combo.count()):
                if self.probe_baud_combo.itemData(i) == vxc_baud:
                    self.probe_baud_combo.setCurrentIndex(i)
                    break
        
        # Current position display
        pos_layout = QHBoxLayout()
        pos_layout.setSpacing(12)
        pos_layout.addWidget(QLabel("Current Position:"))
        self.pos_label = QLabel("X: 0 steps (0.000 ft) | Y: 0 steps (0.000 ft)")
        self.pos_label.setFont(QFont("Courier", 10))
        pos_layout.addWidget(self.pos_label)
        pos_layout.addStretch()
        layout.addLayout(pos_layout)
        
        # Jog controls
        jog_layout = self._create_jog_controls()
        layout.addLayout(jog_layout)
        
        # Direct coordinate input
        coord_layout = QGridLayout()
        coord_layout.setHorizontalSpacing(12)
        coord_layout.setVerticalSpacing(8)
        
        coord_layout.addWidget(QLabel("X (steps):"), 0, 0)
        self.jog_x_input = QSpinBox()
        self.jog_x_input.setRange(-1000000, 1000000)
        coord_layout.addWidget(self.jog_x_input, 0, 1)
        
        coord_layout.addWidget(QLabel("Y (steps):"), 0, 2)
        self.jog_y_input = QSpinBox()
        self.jog_y_input.setRange(-1000000, 1000000)
        coord_layout.addWidget(self.jog_y_input, 0, 3)
        
        go_btn = QPushButton("Go to Position")
        go_btn.clicked.connect(self._go_to_position)
        coord_layout.addWidget(go_btn, 0, 4)
        coord_layout.setColumnStretch(1, 1)
        coord_layout.setColumnStretch(3, 1)
        
        layout.addLayout(coord_layout)
        
        # Calibration buttons
        cal_layout = QGridLayout()
        cal_layout.setHorizontalSpacing(12)
        cal_layout.setVerticalSpacing(8)
        cal_layout.addWidget(QLabel("Calibration:"), 0, 0)
        
        zero_btn = QPushButton("Zero Origin (0,0)")
        zero_btn.clicked.connect(self._zero_origin)
        cal_layout.addWidget(zero_btn, 0, 1)
        
        capture_btn = QPushButton("Capture Boundary")
        capture_btn.clicked.connect(self._capture_boundary)
        cal_layout.addWidget(capture_btn, 0, 2)
        
        cal_layout.setColumnStretch(1, 1)
        cal_layout.setColumnStretch(2, 1)
        layout.addLayout(cal_layout)
        
        # Grid generation
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(12)
        grid_layout.setVerticalSpacing(8)
        grid_layout.setHorizontalSpacing(12)
        grid_layout.setVerticalSpacing(8)
        
        grid_layout.addWidget(QLabel("X Spacing (feet):"), 0, 0)
        self.grid_x_spacing = QDoubleSpinBox()
        self.grid_x_spacing.setValue(0.1)
        self.grid_x_spacing.setSingleStep(0.01)
        grid_layout.addWidget(self.grid_x_spacing, 0, 1)
        
        grid_layout.addWidget(QLabel("Y Spacing (feet):"), 0, 2)
        self.grid_y_spacing = QDoubleSpinBox()
        self.grid_y_spacing.setValue(0.05)
        self.grid_y_spacing.setSingleStep(0.01)
        grid_layout.addWidget(self.grid_y_spacing, 0, 3)
        
        gen_grid_btn = QPushButton("Generate Grid")
        gen_grid_btn.clicked.connect(self._generate_grid)
        grid_layout.addWidget(gen_grid_btn, 0, 4)
        grid_layout.setColumnStretch(1, 1)
        grid_layout.setColumnStretch(3, 1)
        
        layout.addLayout(grid_layout)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def _create_jog_controls(self) -> QVBoxLayout:
        """Create arrow key jog controls."""
        layout = QVBoxLayout()
        
        # Step size selector
        step_layout = QHBoxLayout()
        step_layout.setSpacing(12)
        step_layout.addWidget(QLabel("Step Size:"))
        self.step_size_combo = QComboBox()
        self.step_size_combo.addItems(["Fine (10 steps)", "Medium (100 steps)", "Coarse (1000 steps)"])
        step_layout.addWidget(self.step_size_combo)
        step_layout.addStretch()
        layout.addLayout(step_layout)
        
        # Arrow button grid
        button_layout = QGridLayout()
        button_layout.setHorizontalSpacing(12)
        button_layout.setVerticalSpacing(12)
        
        # Up arrow (Y+)
        up_btn = QPushButton("↑ Y+")
        up_btn.pressed.connect(lambda: self._jog_start('Y', 1))
        up_btn.released.connect(self._jog_stop)
        button_layout.addWidget(up_btn, 0, 1)
        
        # Left arrow (X-)
        left_btn = QPushButton("← X-")
        left_btn.pressed.connect(lambda: self._jog_start('X', -1))
        left_btn.released.connect(self._jog_stop)
        button_layout.addWidget(left_btn, 1, 0)
        
        # Right arrow (X+)
        right_btn = QPushButton("X+ →")
        right_btn.pressed.connect(lambda: self._jog_start('X', 1))
        right_btn.released.connect(self._jog_stop)
        button_layout.addWidget(right_btn, 1, 2)
        
        # Down arrow (Y-)
        down_btn = QPushButton("↓ Y-")
        down_btn.pressed.connect(lambda: self._jog_start('Y', -1))
        down_btn.released.connect(self._jog_stop)
        button_layout.addWidget(down_btn, 2, 1)
        
        # Center label
        center_label = QLabel("Jog\n(Press & Hold)")
        center_label.setAlignment(Qt.AlignCenter)
        button_layout.addWidget(center_label, 1, 1)
        
        layout.addLayout(button_layout)
        
        # Timer for continuous jog
        self.jog_timer = QTimer()
        self.jog_timer.timeout.connect(self._jog_update)
        self.jog_axis = None
        self.jog_direction = 0
        
        return layout
    
    def _create_acquisition_tab(self) -> QWidget:
        """Create acquisition tab."""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Control buttons
        control_layout = QGridLayout()
        control_layout.setHorizontalSpacing(12)
        control_layout.setVerticalSpacing(8)
        
        self.start_btn = QPushButton("Start Acquisition")
        self.start_btn.clicked.connect(self._start_acquisition)
        self.start_btn.setStyleSheet("background-color: #90EE90; font-weight: bold;")
        control_layout.addWidget(self.start_btn, 0, 0)
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self._pause_acquisition)
        self.pause_btn.setEnabled(False)
        control_layout.addWidget(self.pause_btn, 0, 1)
        
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.clicked.connect(self._resume_acquisition)
        self.resume_btn.setEnabled(False)
        control_layout.addWidget(self.resume_btn, 0, 2)
        
        self.stop_btn = QPushButton("Emergency Stop")
        self.stop_btn.clicked.connect(self._emergency_stop)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("background-color: #FF6B6B; color: white;")
        control_layout.addWidget(self.stop_btn, 0, 3)
        
        self.home_btn = QPushButton("Return Home")
        self.home_btn.clicked.connect(self._return_home)
        self.home_btn.setEnabled(False)
        control_layout.addWidget(self.home_btn, 0, 4)
        control_layout.setColumnStretch(0, 1)
        control_layout.setColumnStretch(1, 1)
        control_layout.setColumnStretch(2, 1)
        control_layout.setColumnStretch(3, 1)
        control_layout.setColumnStretch(4, 1)
        
        layout.addLayout(control_layout)
        
        # Status panel
        status_layout = QGridLayout()
        status_layout.setHorizontalSpacing(12)
        status_layout.setVerticalSpacing(8)
        status_frame = QGroupBox("Live Status")
        
        status_layout.addWidget(QLabel("State:"), 0, 0)
        self.state_label = QLabel("IDLE")
        self.state_label.setFont(QFont("Arial", 11, QFont.Bold))
        status_layout.addWidget(self.state_label, 0, 1)
        
        status_layout.addWidget(QLabel("Froude Number:"), 0, 2)
        self.froude_label = QLabel("--")
        self.froude_label.setFont(QFont("Courier", 10))
        status_layout.addWidget(self.froude_label, 0, 3)
        
        status_layout.addWidget(QLabel("Flow Regime:"), 1, 0)
        self.regime_label = QLabel("--")
        status_layout.addWidget(self.regime_label, 1, 1)
        
        status_layout.addWidget(QLabel("Depth:"), 1, 2)
        self.depth_label = QLabel("--")
        status_layout.addWidget(self.depth_label, 1, 3)
        
        status_layout.addWidget(QLabel("Sampling Decision:"), 2, 0, 1, 2)
        self.sampling_decision_label = QLabel("Waiting to start")
        status_layout.addWidget(self.sampling_decision_label, 2, 2, 1, 2)
        
        status_layout.addWidget(QLabel("Position:"), 3, 0)
        self.acq_pos_label = QLabel("X: -- | Y: --")
        status_layout.addWidget(self.acq_pos_label, 3, 1, 1, 3)
        
        status_layout.addWidget(QLabel("Progress:"), 4, 0)
        self.progress_label = QLabel("0/0")
        status_layout.addWidget(self.progress_label, 4, 1)
        
        self.progress_bar = QProgressBar()
        status_layout.addWidget(self.progress_bar, 4, 2, 1, 2)
        
        status_frame.setLayout(status_layout)
        layout.addWidget(status_frame)
        
        # 2D Heatmap
        heatmap_frame = QGroupBox("2D Velocity Heatmap")
        heatmap_layout = QVBoxLayout()
        
        self.heatmap_view = pg.ImageView()
        self.heatmap_view.ui.roiBtn.hide()
        self.heatmap_view.ui.menuBtn.hide()
        heatmap_layout.addWidget(self.heatmap_view)
        
        heatmap_frame.setLayout(heatmap_layout)
        heatmap_frame.setMinimumHeight(300)
        layout.addWidget(heatmap_frame)
        
        widget.setLayout(layout)
        return widget
    
    def _create_config_tab(self) -> QWidget:
        """Create configuration tab."""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Grid settings
        grid_frame = QGroupBox("Grid Settings")
        grid_layout = QGridLayout()
        
        grid_layout.addWidget(QLabel("X Spacing (feet):"), 0, 0)
        self.cfg_x_spacing = QDoubleSpinBox()
        self.cfg_x_spacing.setValue(self.config.get('experiment', {}).get('grid', {}).get('x_spacing_feet', 0.1))
        grid_layout.addWidget(self.cfg_x_spacing, 0, 1)
        
        grid_layout.addWidget(QLabel("Y Spacing (feet):"), 1, 0)
        self.cfg_y_spacing = QDoubleSpinBox()
        self.cfg_y_spacing.setValue(self.config.get('experiment', {}).get('grid', {}).get('y_spacing_feet', 0.05))
        grid_layout.addWidget(self.cfg_y_spacing, 1, 1)
        
        grid_frame.setLayout(grid_layout)
        layout.addWidget(grid_frame)
        
        # Flow analysis
        flow_frame = QGroupBox("Flow Analysis")
        flow_layout = QGridLayout()
        flow_layout.setHorizontalSpacing(12)
        flow_layout.setVerticalSpacing(8)
        
        flow_layout.addWidget(QLabel("Froude Threshold:"), 0, 0)
        self.froude_threshold = QDoubleSpinBox()
        self.froude_threshold.setValue(self.config.get('experiment', {}).get('froude_threshold', 1.0))
        flow_layout.addWidget(self.froude_threshold, 0, 1)
        
        flow_layout.addWidget(QLabel("Base Sampling (s):"), 1, 0)
        self.base_sampling = QDoubleSpinBox()
        self.base_sampling.setValue(self.config.get('experiment', {}).get('base_sampling_duration_sec', 10))
        flow_layout.addWidget(self.base_sampling, 1, 1)
        
        flow_layout.addWidget(QLabel("Max Sampling (s):"), 2, 0)
        self.max_sampling = QDoubleSpinBox()
        self.max_sampling.setValue(self.config.get('experiment', {}).get('max_sampling_duration_sec', 120))
        flow_layout.addWidget(self.max_sampling, 2, 1)
        
        flow_frame.setLayout(flow_layout)
        layout.addWidget(flow_frame)
        
        # ADV settings
        adv_frame = QGroupBox("ADV Settings")
        adv_layout = QGridLayout()
        adv_layout.setHorizontalSpacing(12)
        adv_layout.setVerticalSpacing(8)
        
        adv_layout.addWidget(QLabel("Min SNR (dB):"), 0, 0)
        self.min_snr = QDoubleSpinBox()
        self.min_snr.setValue(self.config.get('adv', {}).get('min_snr_db', 5.0))
        adv_layout.addWidget(self.min_snr, 0, 1)
        
        adv_layout.addWidget(QLabel("Min Correlation (%):"), 1, 0)
        self.min_correlation = QDoubleSpinBox()
        self.min_correlation.setValue(self.config.get('adv', {}).get('min_correlation_percent', 70.0))
        adv_layout.addWidget(self.min_correlation, 1, 1)
        
        adv_frame.setLayout(adv_layout)
        layout.addWidget(adv_frame)
        
        # Buttons
        button_layout = QGridLayout()
        button_layout.setHorizontalSpacing(12)
        button_layout.setVerticalSpacing(8)
        
        save_btn = QPushButton("Save Configuration")
        save_btn.clicked.connect(self._save_config)
        button_layout.addWidget(save_btn, 0, 0)
        
        reset_btn = QPushButton("Load Defaults")
        reset_btn.clicked.connect(self._load_defaults)
        button_layout.addWidget(reset_btn, 0, 1)
        button_layout.setColumnStretch(0, 1)
        button_layout.setColumnStretch(1, 1)
        
        layout.addLayout(button_layout)
        layout.addStretch()
        
        widget.setLayout(layout)
        return widget
    
    def _create_export_tab(self) -> QWidget:
        """Create export tab."""
        widget = QWidget()
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("Export Data:"))
        
        # Export format selection
        format_layout = QGridLayout()
        format_layout.setHorizontalSpacing(12)
        format_layout.setVerticalSpacing(8)
        format_layout.addWidget(QLabel("Format:"), 0, 0)
        
        self.export_format = QComboBox()
        self.export_format.addItems(["CSV (Spreadsheet)", "HDF5 (Python/MATLAB)", "VTK (ParaView)", "All Formats"])
        format_layout.addWidget(self.export_format, 0, 1)
        format_layout.setColumnStretch(1, 1)
        
        layout.addLayout(format_layout)
        
        # Export button
        export_btn = QPushButton("Export Data")
        export_btn.clicked.connect(self._export_data)
        layout.addWidget(export_btn)
        
        # 3D Compilation
        layout.addWidget(QLabel("3D Compilation (Multi-plane):"))
        
        compile_layout = QGridLayout()
        compile_layout.setHorizontalSpacing(12)
        compile_layout.setVerticalSpacing(8)
        compile_btn = QPushButton("Compile Z-planes to 3D")
        compile_btn.clicked.connect(self._compile_3d)
        compile_layout.addWidget(compile_btn, 0, 0)
        compile_layout.setColumnStretch(0, 1)
        
        layout.addLayout(compile_layout)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def _setup_menu_bar(self):
        """Setup menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        file_menu.addAction("New Experiment", self._new_experiment)
        file_menu.addAction("Open Experiment", self._open_experiment)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About", self._show_about)
    
    def _setup_timers(self):
        """Setup timers."""
        # Position update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_position)
        self.update_timer.start(500)  # Update every 500ms
    
    def _refresh_ports(self):
        """Refresh COM port list."""
        ports = list_available_ports()
        
        self.vxc_port_combo.clear()
        self.adv_port_combo.clear()
        if hasattr(self, "probe_port_combo"):
            self.probe_port_combo.clear()
        
        for port, desc in ports:
            self.vxc_port_combo.addItem(f"{port}: {desc}", port)
            self.adv_port_combo.addItem(f"{port}: {desc}", port)
            if hasattr(self, "probe_port_combo"):
                self.probe_port_combo.addItem(f"{port}: {desc}", port)
        
        # Set defaults from config
        vxc_port = self.config.get('vxc', {}).get('port', 'COM3')
        adv_port = self.config.get('adv', {}).get('port', 'COM4')
        
        for i in range(self.vxc_port_combo.count()):
            if vxc_port in self.vxc_port_combo.itemData(i):
                self.vxc_port_combo.setCurrentIndex(i)
                break
        
        for i in range(self.adv_port_combo.count()):
            if adv_port in self.adv_port_combo.itemData(i):
                self.adv_port_combo.setCurrentIndex(i)
                break

        if hasattr(self, "probe_port_combo") and self.probe_port_combo.count() > 0:
            self.probe_port_combo.setCurrentIndex(0)

    def _append_probe_log(self, message: str) -> None:
        """Append a message to the probe log."""
        if not hasattr(self, "probe_log"):
            return
        timestamp = time.strftime("%H:%M:%S")
        self.probe_log.append(f"[{timestamp}] {message}")

    def _clear_probe_log(self) -> None:
        """Clear probe log output."""
        if hasattr(self, "probe_log"):
            self.probe_log.clear()
    
    def _stop_scan(self) -> None:
        """Stop the running port scan."""
        if hasattr(self, "scan_worker") and self.scan_worker:
            self.scan_worker.stop()
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.scan_status.setText("Stopped")
            self.scan_status.setStyleSheet("color: red; font-weight: bold;")
    
    def _update_scan_status(self, message: str) -> None:
        """Update scan status based on log messages."""
        if "[FOUND]" in message:
            self.scan_status.setText("FOUND!")
            self.scan_status.setStyleSheet("color: green; font-weight: bold; background-color: lightgreen;")
        elif "[SCAN]" in message:
            self.scan_status.setText("Scanning...")
            self.scan_status.setStyleSheet("color: orange; font-weight: bold;")

    def _probe_selected_port(self) -> None:
        """Probe the selected port with current settings."""
        if not hasattr(self, "probe_port_combo"):
            return
        port = self.probe_port_combo.currentData()
        baud = self.probe_baud_combo.currentData()
        line_ending = self.probe_line_combo.currentData()
        rtscts, dsrdtr = self.probe_flow_combo.currentData()

        if not port:
            self._append_probe_log("No port selected.")
            return

        self._append_probe_log(f"Probing {port} @ {baud} baud, ending={repr(line_ending)}, flow={self.probe_flow_combo.currentText()}")
        self._run_probe_attempt(port, baud, line_ending, rtscts, dsrdtr)

    def _scan_ports(self) -> None:
        """Scan all available ports with common settings in background thread."""
        all_ports = list_available_ports()
        if not all_ports:
            self._append_probe_log("No COM ports detected.")
            return
        
        # Filter out Bluetooth ports - only scan USB serial ports
        ports = [
            (port, desc) for port, desc in all_ports
            if "bluetooth" not in desc.lower() and "rfcomm" not in desc.lower()
        ]
        
        if not ports:
            self._append_probe_log("No USB serial ports found. (Skipped Bluetooth ports)")
            return
        
        # Update UI for scanning state
        self.scan_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.scan_status.setText("Scanning...")
        self.scan_status.setStyleSheet("color: orange; font-weight: bold;")
        self._append_probe_log(f"Scanning {len(ports)} USB serial ports (skipped {len(all_ports) - len(ports)} Bluetooth ports)...")
        
        baud_rates = [9600, 19200, 38400, 57600, 115200]
        line_endings = ["\r", "\n", "\r\n"]
        commands = [
            ("P", "VXC position"),
            ("?V", "VXC version"),
            ("F", "VXC features"),
            ("getMT1M", "VXC axis type"),
            ("SN", "VXC serial"),
            ("REV", "VXC revision"),
            ("*", "ADV status"),
            ("START", "ADV start"),
        ]
        
        # Create and start scanner thread
        self.scan_worker = PortScanWorker(ports, baud_rates, line_endings, commands)
        self.scan_worker.log_message.connect(self._append_probe_log)
        self.scan_worker.log_message.connect(self._update_scan_status)
        
        def on_scan_complete():
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.scan_status.setText("Scan Complete")
            self.scan_status.setStyleSheet("color: blue; font-weight: bold;")
        
        self.scan_worker.scan_complete.connect(on_scan_complete)
        self.scan_worker.start()

    def _run_probe_attempt(
        self,
        port: str,
        baud: int,
        line_ending: str,
        rtscts: bool,
        dsrdtr: bool,
        label: Optional[str] = None,
    ) -> None:
        """Attempt to probe a port and log responses."""
        commands = [
            ("P", "VXC position"),
            ("?V", "VXC version"),
            ("F", "VXC features"),
            ("getMT1M", "VXC axis1 type"),
            ("getL1M", "VXC axis1 limits"),
            ("getHS1M", "VXC axis1 home"),
            ("SN", "VXC serial"),
            ("REV", "VXC revision"),
            ("*", "ADV status"),
            ("START", "ADV start"),
        ]

        flow_label = label or self.probe_flow_combo.currentText()
        try:
            with serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.4,
                rtscts=rtscts,
                dsrdtr=dsrdtr,
            ) as ser:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                time.sleep(0.2)

                for cmd, cmd_label in commands:
                    payload = (cmd + line_ending).encode("ascii", errors="ignore")
                    ser.write(payload)
                    ser.flush()
                    time.sleep(0.2)
                    response = ser.read_all()
                    if response:
                        preview = response[:120]
                        self._append_probe_log(
                            f"{port} @ {baud} [{flow_label}] {cmd} -> {preview!r}"
                        )
                        return
                self._append_probe_log(
                    f"{port} @ {baud} [{flow_label}] no response"
                )
        except serial.SerialException as e:
            self._append_probe_log(f"{port} @ {baud} [{flow_label}] error: {e}")
        except Exception as e:
            self._append_probe_log(f"{port} @ {baud} [{flow_label}] unexpected error: {e}")
    
    def _connect_vxc(self):
        """Connect to VXC hardware only."""
        try:
            vxc_port = self.vxc_port_combo.currentData()
            
            if not vxc_port:
                QMessageBox.warning(self, "No Port", "Please select a COM port for VXC")
                return
            
            # Disconnect if already connected
            if self.vxc:
                self.vxc.disconnect()
                self.vxc = None
            
            # Initialize VXC hardware
            vxc_baud = self.config.get('vxc', {}).get('baudrate', 9600)
            vxc_line_ending = self.config.get('vxc', {}).get('line_ending', "\r")
            vxc_init_commands = self.config.get('vxc', {}).get('init_commands', [])
            
            logger.info(f"Attempting VXC connection on {vxc_port} @ {vxc_baud} baud")
            self.vxc = VXCController(
                vxc_port,
                baudrate=vxc_baud,
                line_ending=vxc_line_ending,
                init_commands=vxc_init_commands,
            )
            
            if not self.vxc.connect():
                QMessageBox.critical(self, "Connection Failed", f"Failed to connect VXC on {vxc_port}")
                self.vxc_status_label.setText("Connection Failed")
                self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
                self.vxc = None
                return
            
            # Initialize calibration manager
            if not self.calibration:
                self.calibration = CalibrationManager()
            
            self.vxc_status_label.setText(f"Connected @ {vxc_baud}")
            self.vxc_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.vxc_connect_btn.setText("Disconnect VXC")
            QMessageBox.information(self, "Connected", f"VXC connected successfully on {vxc_port} @ {vxc_baud} baud!")
            logger.info(f"VXC connected on {vxc_port} @ {vxc_baud} baud")
            
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            logger.error(f"VXC connection error: {e}")
            self.vxc_status_label.setText("Connection Error")
            self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
    
    def _connect_adv(self):
        """Connect to ADV hardware only."""
        try:
            adv_port = self.adv_port_combo.currentData()
            
            if not adv_port:
                QMessageBox.warning(self, "No Port", "Please select a COM port for ADV")
                return
            
            # Disconnect if already connected
            if self.adv:
                self.adv.disconnect()
                self.adv = None
            
            # Initialize ADV hardware
            adv_baud = self.config.get('adv', {}).get('baudrate', 9600)
            
            logger.info(f"Attempting ADV connection on {adv_port} @ {adv_baud} baud")
            self.adv = ADVController(adv_port, baudrate=adv_baud)
            
            if not self.adv.connect():
                QMessageBox.critical(self, "Connection Failed", f"Failed to connect ADV on {adv_port}")
                self.adv_status_label.setText("Connection Failed")
                self.adv_status_label.setStyleSheet("color: red; font-weight: bold;")
                self.adv = None
                return
            
            # Initialize data logger if not exists
            if not self.data_logger:
                self.data_logger = DataLogger()
            
            self.adv_status_label.setText(f"Connected @ {adv_baud}")
            self.adv_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.adv_connect_btn.setText("Disconnect ADV")
            QMessageBox.information(self, "Connected", f"ADV connected successfully on {adv_port} @ {adv_baud} baud!")
            logger.info(f"ADV connected on {adv_port} @ {adv_baud} baud")
            
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            logger.error(f"ADV connection error: {e}")
            self.adv_status_label.setText("Connection Error")
            self.adv_status_label.setStyleSheet("color: red; font-weight: bold;")
    
    def _jog_start(self, axis: str, direction: int):
        """Start continuous jogging."""
        self.jog_axis = axis
        self.jog_direction = direction
        self.jog_timer.start(50)  # 50ms poll rate (20Hz)
    
    def _jog_stop(self):
        """Stop jogging."""
        self.jog_timer.stop()
        self.jog_axis = None
        if self.vxc:
            self.vxc.stop_motion()
    
    def _jog_update(self):
        """Update position during jog."""
        if not self.vxc or not self.jog_axis:
            return
        
        # Get step size
        step_size_text = self.step_size_combo.currentText()
        if "Fine" in step_size_text:
            step_size = 10
        elif "Medium" in step_size_text:
            step_size = 100
        else:
            step_size = 1000
        
        # Move
        delta = step_size * self.jog_direction
        if self.jog_axis == 'X':
            self.vxc.move_relative(dx=delta)
        else:
            self.vxc.move_relative(dy=delta)
    
    def _go_to_position(self):
        """Move to direct coordinate input."""
        if not self.vxc:
            QMessageBox.warning(self, "Not Connected", "Connect to VXC first")
            return
        
        x = self.jog_x_input.value()
        y = self.jog_y_input.value()
        
        self.vxc.move_absolute(x=x, y=y)
    
    def _update_position(self):
        """Update position display."""
        if self.vxc:
            pos = self.vxc.get_position()
            if pos:
                x_feet = pos['X'] / STEPS_PER_FOOT
                y_feet = pos['Y'] / STEPS_PER_FOOT
                self.pos_label.setText(
                    f"X: {pos['X']} steps ({x_feet:.4f} ft) | Y: {pos['Y']} steps ({y_feet:.4f} ft)"
                )
    
    def _zero_origin(self):
        """Set bottom-left origin."""
        if not self.vxc or not self.calibration:
            QMessageBox.warning(self, "Not Ready", "Connect and initialize calibration first")
            return
        
        pos = self.vxc.get_position()
        if pos:
            self.calibration.set_origin(pos['X'], pos['Y'])
            QMessageBox.information(self, "Origin Set", f"Origin set to X={pos['X']}, Y={pos['Y']}")
    
    def _capture_boundary(self):
        """Set top-right boundary."""
        if not self.vxc or not self.calibration:
            QMessageBox.warning(self, "Not Ready", "Connect and initialize calibration first")
            return
        
        pos = self.vxc.get_position()
        if pos:
            self.calibration.set_boundary(pos['X'], pos['Y'])
            QMessageBox.information(self, "Boundary Set", f"Boundary set to X={pos['X']}, Y={pos['Y']}")
    
    def _generate_grid(self):
        """Generate measurement grid."""
        if not self.calibration:
            QMessageBox.warning(self, "Not Ready", "Calibrate first")
            return
        
        x_spacing = self.grid_x_spacing.value()
        y_spacing = self.grid_y_spacing.value()
        
        grid = self.calibration.generate_grid(x_spacing, y_spacing)
        if grid:
            positions = self.calibration.get_grid_positions()
            self.measurement_positions = [
                SamplingPosition(
                    x_steps=x, y_steps=y,
                    x_feet=self.calibration.steps_to_feet(x),
                    y_feet=self.calibration.steps_to_feet(y),
                    in_roi=False
                ) for x, y in positions
            ]
            
            self.calibration.set_home_position()
            
            QMessageBox.information(
                self, "Grid Generated",
                f"Generated {len(self.measurement_positions)} measurement positions"
            )
    
    def _start_acquisition(self):
        """Start acquisition."""
        if not self.vxc or not self.adv or not self.data_logger:
            QMessageBox.warning(self, "Not Ready", "Connect to hardware first")
            return
        
        if not self.measurement_positions:
            QMessageBox.warning(self, "No Grid", "Generate measurement grid first")
            return
        
        # Get Z value
        z_value, ok = self._get_z_plane_input()
        if not ok:
            return
        
        self.current_z_plane = z_value
        
        # Initialize sampler
        self.sampler = Sampler(self.vxc, self.adv, self.data_logger, self.calibration)
        self.sampler.on_status_update = self._on_sampler_status
        self.sampler.on_state_changed = self._on_sampler_state
        self.sampler.on_position_sampled = self._on_position_sampled
        
        # Start acquisition
        if self.sampler.start_acquisition(self.current_z_plane, self.current_run_number):
            self.sampler.initialize_measurement_sequence(self.measurement_positions)
            
            # Run in worker thread
            self.acquisition_worker = AcquisitionWorker(self.sampler)
            self.acquisition_worker.status_update.connect(self._on_worker_status)
            self.acquisition_worker.acquisition_complete.connect(self._on_acquisition_complete)
            self.acquisition_worker.error_occurred.connect(self._on_worker_error)
            self.acquisition_worker.start()
            
            # Update UI
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
    
    def _pause_acquisition(self):
        """Pause acquisition."""
        if self.sampler:
            self.sampler.pause_acquisition()
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
    
    def _resume_acquisition(self):
        """Resume acquisition."""
        if self.sampler:
            self.sampler.resume_acquisition()
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
    
    def _emergency_stop(self):
        """Emergency stop."""
        if self.sampler:
            self.sampler.emergency_stop()
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
    
    def _return_home(self):
        """Return to home position."""
        if self.sampler:
            self.sampler.return_home()
    
    def _on_sampler_status(self, message: str):
        """Handle sampler status update."""
        self.sampling_decision_label.setText(message)
    
    def _on_sampler_state(self, state):
        """Handle sampler state change."""
        self.state_label.setText(state.value.upper())
    
    def _on_position_sampled(self, record):
        """Handle position sampled event."""
        self.froude_label.setText(f"{record.froude_number:.2f}")
        self.regime_label.setText(
            "Supercritical" if record.froude_number > 1.0 else "Subcritical"
        )
        self.depth_label.setText(f"{record.depth_mean:.3f} m")
        
        x_feet = record.x_feet
        y_feet = record.y_feet
        self.acq_pos_label.setText(f"X: {x_feet:.3f} ft | Y: {y_feet:.3f} ft")
    
    def _on_worker_status(self, message: str):
        """Handle worker status."""
        logger.info(f"Worker: {message}")
    
    def _on_acquisition_complete(self):
        """Handle acquisition completion."""
        QMessageBox.information(self, "Acquisition Complete", "Measurement sequence finished")
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        
        # Prompt for next Z-plane
        z_value, ok = self._get_z_plane_input(
            f"Enter Z for next plane (previous: {self.current_z_plane}):"
        )
        if ok:
            self.current_z_plane = z_value
    
    def _on_worker_error(self, error: str):
        """Handle worker error."""
        QMessageBox.critical(self, "Acquisition Error", error)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
    
    def _export_data(self):
        """Export data to file."""
        if not self.data_logger or not self.data_logger.get_all():
            QMessageBox.warning(self, "No Data", "No data to export")
            return
        
        filepath, _ = QFileDialog.getSaveFileName(self, "Export Data", ".", "All Files (*)")
        if not filepath:
            return
        
        records = self.data_logger.get_all()
        format_choice = self.export_format.currentText()
        
        try:
            if "CSV" in format_choice:
                export_csv(records, filepath + ".csv")
            elif "HDF5" in format_choice:
                export_hdf5(records, filepath + ".h5")
            elif "VTK" in format_choice:
                export_vtk(records, filepath + ".vtk")
            else:  # All formats
                export_csv(records, filepath + ".csv")
                export_hdf5(records, filepath + ".h5")
                export_vtk(records, filepath + ".vtk")
            
            QMessageBox.information(self, "Export Complete", "Data exported successfully")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))
    
    def _compile_3d(self):
        """Compile multiple Z-planes to 3D."""
        QMessageBox.information(self, "3D Compilation", "Select HDF5 files from each Z-plane")
        # TODO: Implement file selection and 3D compilation
    
    def _save_config(self):
        """Save configuration."""
        config = {
            'grid': {
                'x_spacing_feet': self.cfg_x_spacing.value(),
                'y_spacing_feet': self.cfg_y_spacing.value(),
            },
            'froude_threshold': self.froude_threshold.value(),
            'base_sampling_duration_sec': self.base_sampling.value(),
            'max_sampling_duration_sec': self.max_sampling.value(),
        }
        
        filepath = os.path.join(self.config_dir, 'experiment_config.yaml')
        try:
            with open(filepath, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            QMessageBox.information(self, "Saved", "Configuration saved successfully")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))
    
    def _load_defaults(self):
        """Load default configuration."""
        self.cfg_x_spacing.setValue(0.1)
        self.cfg_y_spacing.setValue(0.05)
        self.froude_threshold.setValue(1.0)
        self.base_sampling.setValue(10.0)
        self.max_sampling.setValue(120.0)
    
    def _new_experiment(self):
        """Create new experiment."""
        QMessageBox.information(self, "New Experiment", "Start a new measurement campaign")
    
    def _open_experiment(self):
        """Open existing experiment."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Open Experiment", ".", "HDF5 Files (*.h5)")
        if filepath:
            if self.data_logger.load_experiment(filepath):
                QMessageBox.information(self, "Loaded", "Experiment loaded successfully")
    
    def _get_z_plane_input(self, prompt: str = "Enter Z-plane coordinate:"):
        """Get Z-plane input from user.
        
        Returns:
            (z_value, ok) tuple
        """
        from PyQt5.QtWidgets import QInputDialog
        z_value, ok = QInputDialog.getDouble(self, "Z-Plane", prompt, self.current_z_plane)
        return z_value, ok
    
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, "About",
            "VXC/ADV Flow Measurement System\n"
            "Version 1.0\n\n"
            "Adaptive flume flow profiling with Velmex XY stage\n"
            "and SonTek FlowTracker2 ADV"
        )
    
    def closeEvent(self, event):
        """Handle window close event."""
        if self.vxc:
            self.vxc.disconnect()
        if self.adv:
            self.adv.disconnect()
        if self.data_logger:
            self.data_logger.close()
        
        event.accept()
