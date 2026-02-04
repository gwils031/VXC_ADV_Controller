"""Simplified PyQt5 GUI with separate VXC and ADV testing tabs."""

import logging
import time
import yaml
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QSpinBox, QComboBox, QMessageBox,
    QGroupBox, QGridLayout, QTextEdit, QDoubleSpinBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from controllers import VXCController, ADVController
from utils.serial_utils import list_available_ports

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Simplified testing window with VXC and ADV tabs."""
    
    def __init__(self, config_dir: str = "./config"):
        """Initialize main window.
        
        Args:
            config_dir: Configuration directory path
        """
        super().__init__()
        self.config_dir = config_dir
        
        # Load configs
        self.vxc_config = self._load_config("vxc_config.yaml")
        self.adv_config = self._load_config("adv_config.yaml")
        
        # Hardware
        self.vxc: Optional[VXCController] = None
        self.adv: Optional[ADVController] = None
        
        # UI state
        self._closing = False
        self.jog_axis = None
        self.jog_direction = 0
        self.adv_sample_count = 0
        
        # Setup UI
        self.setWindowTitle("VXC/ADV Hardware Testing")
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
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
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
        tabs = QTabWidget()
        
        # VXC Controller tab
        tabs.addTab(self._create_vxc_tab(), "VXC Controller")
        
        # ADV Streaming tab
        tabs.addTab(self._create_adv_tab(), "ADV Streaming")
        
        main_layout.addWidget(tabs)
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
        
        self.vxc_connect_btn = QPushButton("Connect")
        self.vxc_connect_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        self.vxc_connect_btn.clicked.connect(self._connect_vxc)
        conn_layout.addWidget(self.vxc_connect_btn)
        
        self.vxc_status_label = QLabel("Not Connected")
        self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
        conn_layout.addWidget(self.vxc_status_label)
        
        refresh_btn = QPushButton("Refresh Ports")
        refresh_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        refresh_btn.clicked.connect(self._refresh_ports)
        conn_layout.addWidget(refresh_btn)
        
        conn_layout.addStretch()
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)
        
        # Position display
        pos_group = QGroupBox("Current Position")
        pos_layout = QHBoxLayout()
        
        self.vxc_x_label = QLabel("X: ---")
        self.vxc_x_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        pos_layout.addWidget(self.vxc_x_label)
        
        pos_layout.addSpacing(20)
        
        self.vxc_y_label = QLabel("Y: ---")
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
        step_layout.addWidget(QLabel("Step Size:"))
        self.vxc_step_combo = QComboBox()
        self.vxc_step_combo.addItems(["1000 steps", "2000 steps", "3000 steps", "4000 steps"])
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
        
        # Action buttons
        btn_layout = QVBoxLayout()
        
        stop_btn = QPushButton("🛑 EMERGENCY STOP 🛑")
        stop_btn.setStyleSheet(
            "QPushButton { background-color: #cc0000; color: white; font-weight: bold; "
            "font-size: 16px; padding: 15px; border: 3px solid #990000; } "
            "QPushButton:hover { background-color: #ff0000; border: 3px solid #cc0000; }"
        )
        stop_btn.setMinimumHeight(60)
        stop_btn.clicked.connect(self._vxc_stop)
        
        zero_btn = QPushButton("Zero Position")
        zero_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        zero_btn.setMinimumHeight(40)
        zero_btn.clicked.connect(self._vxc_zero)
        
        # Center buttons horizontally
        btn_container = QHBoxLayout()
        btn_container.addStretch()
        
        btn_vertical = QVBoxLayout()
        btn_vertical.addWidget(stop_btn)
        btn_vertical.addSpacing(10)
        btn_vertical.addWidget(zero_btn)
        
        btn_container.addLayout(btn_vertical)
        btn_container.addStretch()
        
        layout.addLayout(btn_container)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def _create_adv_tab(self) -> QWidget:
        """Create ADV streaming tab."""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Connection section
        conn_group = QGroupBox("ADV Connection")
        conn_layout = QHBoxLayout()
        
        conn_layout.addWidget(QLabel("Port:"))
        self.adv_port_combo = QComboBox()
        conn_layout.addWidget(self.adv_port_combo)
        
        self.adv_connect_btn = QPushButton("Connect")
        self.adv_connect_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        self.adv_connect_btn.clicked.connect(self._connect_adv)
        conn_layout.addWidget(self.adv_connect_btn)
        
        self.adv_status_label = QLabel("Not Connected")
        self.adv_status_label.setStyleSheet("color: red; font-weight: bold;")
        conn_layout.addWidget(self.adv_status_label)
        
        conn_layout.addStretch()
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)
        
        # Streaming controls
        stream_group = QGroupBox("Streaming Controls")
        stream_layout = QHBoxLayout()
        
        self.adv_start_btn = QPushButton("Start Streaming")
        self.adv_start_btn.setStyleSheet("QPushButton:hover:enabled { background-color: #b3ffb3; }")
        self.adv_start_btn.clicked.connect(self._adv_start)
        self.adv_start_btn.setEnabled(False)
        stream_layout.addWidget(self.adv_start_btn)
        
        self.adv_stop_btn = QPushButton("Stop Streaming")
        self.adv_stop_btn.setStyleSheet("QPushButton:hover:enabled { background-color: #ffb3b3; }")
        self.adv_stop_btn.clicked.connect(self._adv_stop)
        self.adv_stop_btn.setEnabled(False)
        stream_layout.addWidget(self.adv_stop_btn)
        
        clear_btn = QPushButton("Clear Log")
        clear_btn.setStyleSheet("QPushButton:hover { background-color: #e0e0e0; }")
        clear_btn.clicked.connect(self._adv_clear)
        stream_layout.addWidget(clear_btn)
        
        stream_layout.addStretch()
        
        stream_layout.addWidget(QLabel("Samples:"))
        self.adv_count_label = QLabel("0")
        self.adv_count_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        stream_layout.addWidget(self.adv_count_label)
        
        stream_group.setLayout(stream_layout)
        layout.addWidget(stream_group)
        
        # Current sample display
        sample_group = QGroupBox("Current Sample")
        sample_layout = QGridLayout()
        sample_layout.setHorizontalSpacing(15)
        sample_layout.setVerticalSpacing(10)
        
        # U velocity
        sample_layout.addWidget(QLabel("U (m/s):"), 0, 0)
        self.adv_u_label = QLabel("---")
        self.adv_u_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        sample_layout.addWidget(self.adv_u_label, 0, 1)
        
        # V velocity
        sample_layout.addWidget(QLabel("V (m/s):"), 0, 2)
        self.adv_v_label = QLabel("---")
        self.adv_v_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        sample_layout.addWidget(self.adv_v_label, 0, 3)
        
        # W velocity
        sample_layout.addWidget(QLabel("W (m/s):"), 0, 4)
        self.adv_w_label = QLabel("---")
        self.adv_w_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        sample_layout.addWidget(self.adv_w_label, 0, 5)
        
        # SNR
        sample_layout.addWidget(QLabel("SNR (dB):"), 1, 0)
        self.adv_snr_label = QLabel("---")
        self.adv_snr_label.setStyleSheet("font-size: 12pt;")
        sample_layout.addWidget(self.adv_snr_label, 1, 1)
        
        # Correlation
        sample_layout.addWidget(QLabel("Corr (%):"), 1, 2)
        self.adv_corr_label = QLabel("---")
        self.adv_corr_label.setStyleSheet("font-size: 12pt;")
        sample_layout.addWidget(self.adv_corr_label, 1, 3)
        
        sample_layout.setColumnStretch(6, 1)
        sample_group.setLayout(sample_layout)
        layout.addWidget(sample_group)
        
        # Data log
        log_group = QGroupBox("Data Log")
        log_layout = QVBoxLayout()
        
        self.adv_log_text = QTextEdit()
        self.adv_log_text.setReadOnly(True)
        self.adv_log_text.setMaximumHeight(300)
        self.adv_log_text.setFont(QFont("Courier", 9))
        log_layout.addWidget(self.adv_log_text)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
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
        
        # ADV streaming timer
        self.adv_timer = QTimer()
        self.adv_timer.timeout.connect(self._update_adv_stream)
    
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
        
        # Update ADV combo
        current_adv = self.adv_port_combo.currentText()
        self.adv_port_combo.clear()
        self.adv_port_combo.addItems(port_names)
        if current_adv in port_names:
            self.adv_port_combo.setCurrentText(current_adv)
        elif self.adv_config.get('port') in port_names:
            self.adv_port_combo.setCurrentText(self.adv_config['port'])
        
        logger.info(f"Found {len(ports)} serial ports")
    
    # ========== VXC Methods ==========
    
    def _connect_vxc(self):
        """Connect or disconnect VXC."""
        if self.vxc is not None:
            # Disconnect
            self.vxc_timer.stop()
            self.jog_timer.stop()
            try:
                self.vxc.close()
            except Exception as e:
                logger.error(f"Error closing VXC: {e}")
            self.vxc = None
            self.vxc_status_label.setText("Not Connected")
            self.vxc_status_label.setStyleSheet("color: red; font-weight: bold;")
            self.vxc_connect_btn.setText("Connect")
            self.vxc_x_label.setText("X: ---")
            self.vxc_y_label.setText("Y: ---")
            logger.info("VXC disconnected")
        else:
            # Connect
            port = self.vxc_port_combo.currentText()
            if not port:
                QMessageBox.warning(self, "No Port", "Please select a port.")
                return
            
            try:
                baudrate = self.vxc_config.get('baudrate', 57600)
                self.vxc = VXCController(port, baudrate)
                
                # Actually connect to the device
                if not self.vxc.connect():
                    raise Exception("Failed to establish connection")
                
                self.vxc_status_label.setText(f"Connected: {port}")
                self.vxc_status_label.setStyleSheet("color: green; font-weight: bold;")
                self.vxc_connect_btn.setText("Disconnect")
                self.vxc_timer.start(500)  # Update position every 500ms
                logger.info(f"VXC connected to {port}")
                
                # Update position immediately
                self._update_vxc_position()
            except Exception as e:
                QMessageBox.critical(self, "Connection Error", f"Failed to connect to VXC:\n{e}")
                logger.error(f"VXC connection failed: {e}")
                self.vxc = None
    
    def _update_vxc_position(self):
        """Update VXC position display."""
        if self.vxc is None or self._closing:
            return
        
        try:
            x = self.vxc.get_position(motor=2)  # Motor 2 = X axis
            y = self.vxc.get_position(motor=1)  # Motor 1 = Y axis
            if x is not None and y is not None:
                self.vxc_x_label.setText(f"X: {x} steps")
                self.vxc_y_label.setText(f"Y: {y} steps")
        except Exception as e:
            logger.error(f"Failed to get VXC position: {e}")
    
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
        self.jog_timer.start(100)  # Jog every 100ms
        self._jog_update()  # First step immediately
    
    def _jog_stop(self):
        """Stop jogging VXC."""
        self.jog_timer.stop()
        self.jog_axis = None
        self.jog_direction = 0
    
    def _jog_update(self):
        """Execute one jog step."""
        if self.vxc is None or self.jog_axis is None:
            return
        
        # Get step size
        step_index = self.vxc_step_combo.currentIndex()
        if step_index == 0:
            step = 1000
        elif step_index == 1:
            step = 2000
        elif step_index == 2:
            step = 3000
        else:
            step = 4000
        
        # Apply direction
        step = step * self.jog_direction
        
        try:
            # Convert axis letter to motor number
            motor = 2 if self.jog_axis == 'X' else 1
            self.vxc.step_motor(motor=motor, steps=step)
        except Exception as e:
            logger.error(f"Jog failed: {e}")
            self._jog_stop()
    
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
    
    # ========== ADV Methods ==========
    
    def _connect_adv(self):
        """Connect or disconnect ADV."""
        if self.adv is not None:
            # Disconnect
            self.adv_timer.stop()
            try:
                if self.adv.streaming:
                    self.adv.stop_stream()
                self.adv.close()
            except Exception as e:
                logger.error(f"Error closing ADV: {e}")
            self.adv = None
            self.adv_status_label.setText("Not Connected")
            self.adv_status_label.setStyleSheet("color: red; font-weight: bold;")
            self.adv_connect_btn.setText("Connect")
            self.adv_start_btn.setEnabled(False)
            self.adv_stop_btn.setEnabled(False)
            logger.info("ADV disconnected")
        else:
            # Connect
            port = self.adv_port_combo.currentText()
            if not port:
                QMessageBox.warning(self, "No Port", "Please select a port.")
                return
            
            try:
                # Get config parameters
                baudrate = self.adv_config.get('baudrate', 9600)
                timeout = self.adv_config.get('timeout', 2.0)
                line_ending = self.adv_config.get('line_ending', '\r\n')
                start_cmd = self.adv_config.get('start_command', 'start')
                stop_cmd = self.adv_config.get('stop_command', 'stop')
                expected_fields = self.adv_config.get('expected_fields', 20)
                
                self.adv = ADVController(
                    port, baudrate,
                    timeout=timeout,
                    line_ending=line_ending,
                    start_command=start_cmd,
                    stop_command=stop_cmd,
                    expected_fields=expected_fields
                )
                
                # Actually connect to the device
                if not self.adv.connect():
                    raise Exception("Failed to establish connection")
                
                self.adv_status_label.setText(f"Connected: {port}")
                self.adv_status_label.setStyleSheet("color: green; font-weight: bold;")
                self.adv_connect_btn.setText("Disconnect")
                self.adv_start_btn.setEnabled(True)
                logger.info(f"ADV connected to {port}")
            except Exception as e:
                QMessageBox.critical(self, "Connection Error", f"Failed to connect to ADV:\n{e}")
                logger.error(f"ADV connection failed: {e}")
                self.adv = None
    
    def _adv_start(self):
        """Start ADV streaming."""
        if self.adv is None:
            return
        
        try:
            self.adv.start_stream()
            self.adv_start_btn.setEnabled(False)
            self.adv_stop_btn.setEnabled(True)
            self.adv_timer.start(100)  # Read every 100ms
            self.adv_sample_count = 0
            self.adv_count_label.setText("0")
            logger.info("ADV streaming started")
        except Exception as e:
            QMessageBox.critical(self, "Start Error", f"Failed to start ADV:\n{e}")
            logger.error(f"ADV start failed: {e}")
    
    def _adv_stop(self):
        """Stop ADV streaming."""
        if self.adv is None:
            return
        
        try:
            self.adv_timer.stop()
            self.adv.stop_stream()
            self.adv_start_btn.setEnabled(True)
            self.adv_stop_btn.setEnabled(False)
            logger.info("ADV streaming stopped")
        except Exception as e:
            logger.error(f"ADV stop failed: {e}")
    
    def _update_adv_stream(self):
        """Update ADV streaming display."""
        if self.adv is None or not self.adv.streaming or self._closing:
            return
        
        try:
            # Try to read raw line
            line = self.adv.read_raw_line()
            if line:
                # Log raw line
                self._adv_log(line)
                
                # Try to parse
                data = self.adv.parse_line(line)
                if data:
                    # Update sample display
                    self.adv_u_label.setText(f"{data.get('u', 0):.4f}")
                    self.adv_v_label.setText(f"{data.get('v', 0):.4f}")
                    self.adv_w_label.setText(f"{data.get('w', 0):.4f}")
                    self.adv_snr_label.setText(f"{data.get('snr', 0):.1f}")
                    self.adv_corr_label.setText(f"{data.get('corr', 0):.1f}")
                    
                    # Update count
                    self.adv_sample_count += 1
                    self.adv_count_label.setText(str(self.adv_sample_count))
        except Exception as e:
            logger.error(f"ADV stream update failed: {e}")
    
    def _adv_clear(self):
        """Clear ADV log."""
        self.adv_log_text.clear()
    
    def _adv_log(self, message: str):
        """Add message to ADV log.
        
        Args:
            message: Message to log
        """
        self.adv_log_text.append(message.strip())
        
        # Auto-scroll to bottom
        cursor = self.adv_log_text.textCursor()
        cursor.movePosition(cursor.End)
        self.adv_log_text.setTextCursor(cursor)
    
    def closeEvent(self, event):
        """Handle window close."""
        self._closing = True
        
        # Stop timers
        self.vxc_timer.stop()
        self.jog_timer.stop()
        self.adv_timer.stop()
        
        # Disconnect hardware
        if self.vxc is not None:
            try:
                self.vxc.close()
            except Exception as e:
                logger.error(f"Error closing VXC: {e}")
        
        if self.adv is not None:
            try:
                if self.adv.streaming:
                    self.adv.stop_stream()
                self.adv.close()
            except Exception as e:
                logger.error(f"Error closing ADV: {e}")
        
        logger.info("MainWindow closed")
        event.accept()
