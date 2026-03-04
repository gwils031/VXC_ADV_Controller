"""Auto-Merge tab widget for file monitoring and automatic ADV-VXC merging."""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, 
    QPushButton, QTextEdit, QCheckBox, QFileDialog, QLineEdit,
    QGridLayout
)
from PyQt5.QtCore import Qt, pyqtSlot, pyqtSignal, QTimer, QSettings
from PyQt5.QtGui import QFont, QTextCursor

from ..monitoring.file_monitor import FileMonitor
from ..data.vxc_position_logger import VXCPositionLogger
from ..data.session_manager import SessionManager, SessionConfig

logger = logging.getLogger(__name__)


class AutoMergeTab(QWidget):
    """Tab for automatic ADV-VXC file monitoring and merging."""

    averaged_file_ready = pyqtSignal(str, dict)
    
    def __init__(self, vxc_logger: Optional[VXCPositionLogger] = None, parent=None):
        """Initialize auto-merge tab.
        
        Args:
            vxc_logger: VXC position logger instance (for auto-start integration)
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.vxc_logger = vxc_logger
        self.file_monitor: Optional[FileMonitor] = None
        self.session_manager: Optional[SessionManager] = None
        self.current_session_dir: Optional[Path] = None
        
        # Settings
        self.settings = QSettings("ADV-VXC", "VXC-ADV-Controller")

        # Default directories (user requested)
        default_watch = "C:/App Development/ADV&VXC Controller/ADV_Data"
        default_vxc = "C:/App Development/ADV&VXC Controller/VXC_Positions"
        default_output = "C:/App Development/ADV&VXC Controller/Data_Output"

        # Load persisted directories if available
        self.watch_dir = self.settings.value("auto_merge/watch_dir", default_watch)
        self.vxc_dir = self.settings.value("auto_merge/vxc_dir", default_vxc)
        self.output_dir = self.settings.value("auto_merge/output_dir", default_output)
        
        # Statistics
        self.total_processed = 0
        self.total_failed = 0
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup user interface."""
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # === Quick Start ===
        quick_group = QGroupBox("Quick Start")
        quick_layout = QVBoxLayout()
        quick_text = QLabel(
            "1) Select the FlowTracker2 export folder\n"
            "2) Enable monitoring to auto-merge new exports\n"
            "3) Merged and averaged files appear in the Output folder"
        )
        quick_text.setWordWrap(True)
        quick_text.setStyleSheet("color: #444;")
        quick_layout.addWidget(quick_text)
        quick_group.setLayout(quick_layout)
        layout.addWidget(quick_group)

        # === Session Management Section ===
        session_group = QGroupBox("Session Management")
        session_layout = QGridLayout()
        session_layout.setSpacing(8)
        
        # Session name input
        session_layout.addWidget(QLabel("Session Name:"), 0, 0)
        self.session_name_edit = QLineEdit()
        self.session_name_edit.setText(self._generate_default_session_name())
        self.session_name_edit.setPlaceholderText("e.g., Run01, BaselineTest, CrossSection_Y_05m")
        session_layout.addWidget(self.session_name_edit, 0, 1, 1, 2)
        
        # Start Session button (replaces New Session)
        self.new_session_btn = QPushButton("Start Session")
        self.new_session_btn.clicked.connect(self._create_new_session)
        self.new_session_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        session_layout.addWidget(self.new_session_btn, 0, 3)
        
        # End Session button (new)
        self.end_session_btn = QPushButton("End Session")
        self.end_session_btn.clicked.connect(self._end_current_session)
        self.end_session_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold;")
        self.end_session_btn.setEnabled(False)  # Disabled until session starts
        session_layout.addWidget(self.end_session_btn, 0, 4)
        
        # Browse sessions button (moved to row 1)
        self.browse_sessions_btn = QPushButton("Browse...")
        self.browse_sessions_btn.clicked.connect(self._browse_sessions)
        self.browse_sessions_btn.setMaximumWidth(100)
        session_layout.addWidget(self.browse_sessions_btn, 0, 5)
        
        # Operator and notes
        session_layout.addWidget(QLabel("Operator:"), 1, 0)
        self.operator_edit = QLineEdit()
        self.operator_edit.setPlaceholderText("Your name")
        session_layout.addWidget(self.operator_edit, 1, 1)
        
        session_layout.addWidget(QLabel("Notes:"), 1, 2)
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Brief description of experiment")
        session_layout.addWidget(self.notes_edit, 1, 3)
        
        self.save_notes_btn = QPushButton("Save Notes")
        self.save_notes_btn.clicked.connect(self._save_notes)
        self.save_notes_btn.setMaximumWidth(100)
        self.save_notes_btn.setEnabled(False)  # Disabled until session is active
        session_layout.addWidget(self.save_notes_btn, 1, 4, 1, 2)  # Span 2 columns
        
        # Session status with indicator
        session_layout.addWidget(QLabel("Session Status:"), 2, 0)
        self.session_status_label = QLabel("⚪ NO SESSION")
        self.session_status_label.setStyleSheet("color: #888; font-weight: bold;")
        session_layout.addWidget(self.session_status_label, 2, 1, 1, 5)  # Span all columns
        
        session_group.setLayout(session_layout)
        layout.addWidget(session_group)

        # === Monitoring Status Section ===
        status_group = QGroupBox("Status")
        status_layout = QGridLayout()
        status_layout.setSpacing(8)
        
        # Status indicator
        status_layout.addWidget(QLabel("Status:"), 0, 0)
        self.status_indicator = QLabel("● Inactive")
        self.status_indicator.setStyleSheet("color: gray; font-weight: bold; font-size: 11pt;")
        status_layout.addWidget(self.status_indicator, 0, 1)
        
        # Watch directory
        status_layout.addWidget(QLabel("ADV Export Folder:"), 1, 0)
        self.watch_dir_label = QLabel(self.watch_dir)
        self.watch_dir_label.setStyleSheet("color: #555;")
        status_layout.addWidget(self.watch_dir_label, 1, 1, 1, 2)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.setMaximumWidth(100)
        browse_btn.clicked.connect(self._browse_watch_directory)
        status_layout.addWidget(browse_btn, 1, 3)
        status_layout.addWidget(
            self._make_hint_label("Folder where FlowTracker2 exports ADV CSV files"),
            1,
            4,
        )
        
        # Statistics
        status_layout.addWidget(QLabel("Files Processed:"), 2, 0)
        self.processed_label = QLabel("0")
        self.processed_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.processed_label, 2, 1)
        
        status_layout.addWidget(QLabel("Failed:"), 2, 2)
        self.failed_label = QLabel("0")
        self.failed_label.setStyleSheet("font-weight: bold; color: red;")
        status_layout.addWidget(self.failed_label, 2, 3)
        
        # Last merge info
        status_layout.addWidget(QLabel("Last Merge:"), 3, 0)
        self.last_merge_label = QLabel("(none)")
        self.last_merge_label.setStyleSheet("color: #555; font-style: italic;")
        status_layout.addWidget(self.last_merge_label, 3, 1, 1, 3)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # === Controls Section ===
        controls_group = QGroupBox("Auto-Merge Control")
        controls_layout = QHBoxLayout()
        
        self.enable_checkbox = QCheckBox("Monitor and Auto-Merge")
        self.enable_checkbox.setStyleSheet("font-weight: bold;")
        self.enable_checkbox.stateChanged.connect(self._on_enable_changed)
        controls_layout.addWidget(self.enable_checkbox)
        controls_layout.addWidget(
            self._make_hint_label("Watches the export folder and merges new files automatically")
        )
        
        controls_layout.addSpacing(20)
        
        # VXC logging is always auto-started when monitoring is enabled.
        
        controls_layout.addStretch()
        
        self.clear_log_btn = QPushButton("Clear Activity Log")
        self.clear_log_btn.clicked.connect(self._clear_activity_log)
        controls_layout.addWidget(self.clear_log_btn)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # === Activity Log Section ===
        log_group = QGroupBox("Activity")
        log_layout = QVBoxLayout()
        
        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumHeight(300)
        self.activity_log.setStyleSheet("""
            QTextEdit {
                background-color: #f8f8f8;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 9pt;
            }
        """)
        log_layout.addWidget(self.activity_log)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # === Configuration Section ===
        config_group = QGroupBox("Advanced Settings")
        config_layout = QGridLayout()
        
        config_layout.addWidget(QLabel("VXC Logs Folder:"), 0, 0)
        self.vxc_dir_edit = QLineEdit(self.vxc_dir)
        config_layout.addWidget(self.vxc_dir_edit, 0, 1)
        vxc_browse_btn = QPushButton("Browse...")
        vxc_browse_btn.setMaximumWidth(100)
        vxc_browse_btn.clicked.connect(self._browse_vxc_directory)
        config_layout.addWidget(vxc_browse_btn, 0, 2)
        config_layout.addWidget(
            self._make_hint_label("Folder where this app writes VXC position logs"),
            0,
            3,
        )
        
        config_layout.addWidget(QLabel("Output Folder:"), 1, 0)
        self.output_dir_edit = QLineEdit(self.output_dir)
        config_layout.addWidget(self.output_dir_edit, 1, 1)
        output_browse_btn = QPushButton("Browse...")
        output_browse_btn.setMaximumWidth(100)
        output_browse_btn.clicked.connect(self._browse_output_directory)
        config_layout.addWidget(output_browse_btn, 1, 2)
        config_layout.addWidget(
            self._make_hint_label("Merged and averaged CSV files are saved here"),
            1,
            3,
        )
        
        config_layout.addWidget(QLabel("Match Tolerance (sec):"), 2, 0)
        from PyQt5.QtWidgets import QDoubleSpinBox
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.1, 5.0)
        self.tolerance_spin.setValue(0.5)
        self.tolerance_spin.setSingleStep(0.1)
        self.tolerance_spin.setSuffix(" s")
        config_layout.addWidget(self.tolerance_spin, 2, 1)
        config_layout.addWidget(
            self._make_hint_label("Maximum time difference between ADV and VXC samples"),
            2,
            3,
        )
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Initial log message
        self._log_activity("Auto-merge system initialized", "info")
        self._log_activity(f"Watch directory: {self.watch_dir}", "info")

        # Auto-start monitoring with defaults
        QTimer.singleShot(0, lambda: self.enable_checkbox.setChecked(True))

        # Ensure configured folders exist
        self._ensure_paths()

    def _make_hint_label(self, tooltip: str) -> QLabel:
        """Create a small hint label with a tooltip."""
        label = QLabel("?")
        label.setToolTip(tooltip)
        label.setAlignment(Qt.AlignCenter)
        label.setFixedWidth(16)
        label.setStyleSheet(
            "QLabel { color: #666; border: 1px solid #bbb; border-radius: 8px; "
            "background: #f5f5f5; font-weight: bold; }"
        )
        return label
    
    def set_vxc_logger(self, vxc_logger: VXCPositionLogger):
        """Set VXC position logger reference."""
        self.vxc_logger = vxc_logger

    def _ensure_paths(self):
        """Create VXC logs and output folders if missing."""
        vxc_dir = Path(self.vxc_dir_edit.text())
        output_dir = Path(self.output_dir_edit.text())
        vxc_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

    def handle_vxc_connected(self):
        """Start VXC logging if monitoring is enabled and auto-start is checked."""
        if not self.enable_checkbox.isChecked():
            return
        if self.vxc_logger is None:
            self._log_activity("Error: VXC logger not available", "error")
            return
        if not hasattr(self.vxc_logger, 'current_file') or self.vxc_logger.current_file is None:
            try:
                self.vxc_logger.start_logging()
                self._log_activity("✓ VXC position logging auto-started", "success")
            except Exception as e:
                self._log_activity(f"Warning: Could not auto-start VXC logging: {e}", "warning")
    
    def _browse_watch_directory(self):
        """Open directory browser for watch directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select ADV Export Directory",
            self.watch_dir,
            QFileDialog.ShowDirsOnly
        )
        
        if directory:
            self.watch_dir = directory
            self.watch_dir_label.setText(directory)
            self.settings.setValue("auto_merge/watch_dir", directory)
            self._log_activity(f"Watch directory changed: {directory}", "info")
            
            # Restart monitoring if active
            if self.file_monitor and self.file_monitor.is_monitoring():
                self._stop_monitoring()
                self._start_monitoring()
    
    def _browse_vxc_directory(self):
        """Open directory browser for VXC logs directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select VXC Logs Directory",
            self.vxc_dir_edit.text(),
            QFileDialog.ShowDirsOnly
        )
        
        if directory:
            self.vxc_dir_edit.setText(directory)
            self.settings.setValue("auto_merge/vxc_dir", directory)
            self._log_activity(f"VXC logs directory changed: {directory}", "info")
    
    def _browse_output_directory(self):
        """Open directory browser for output directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.output_dir_edit.text(),
            QFileDialog.ShowDirsOnly
        )
        
        if directory:
            self.output_dir_edit.setText(directory)
            self.settings.setValue("auto_merge/output_dir", directory)
            self._log_activity(f"Output directory changed: {directory}", "info")
    
    def _on_enable_changed(self, state):
        """Handle enable checkbox state change."""
        if state == Qt.Checked:
            self._start_monitoring()
        else:
            self._stop_monitoring()
    
    def _start_monitoring(self):
        """Start file monitoring."""
        # Validate directories
        watch_path = Path(self.watch_dir)
        if not watch_path.exists():
            self._log_activity(f"Error: Watch directory not found: {self.watch_dir}", "error")
            self.enable_checkbox.setChecked(False)
            return
        
        # Get configuration values
        vxc_dir = self.vxc_dir_edit.text()
        output_dir = self.output_dir_edit.text()

        # Persist current directories
        self.settings.setValue("auto_merge/watch_dir", self.watch_dir)
        self.settings.setValue("auto_merge/vxc_dir", vxc_dir)
        self.settings.setValue("auto_merge/output_dir", output_dir)
        tolerance = self.tolerance_spin.value()
        
        # Initialize session manager if needed
        if self.session_manager is None:
            self.session_manager = SessionManager(output_dir)
        
        # Auto-start a session if none is active
        if not self.session_manager.is_active():
            self._auto_start_session()
        else:
            # Session already active — update UI to reflect this
            session_id = self.session_manager.active_session
            self.session_status_label.setText(f"🟢 COLLECTING DATA - {session_id}")
            self.session_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.new_session_btn.setEnabled(False)
            self.end_session_btn.setEnabled(True)
            self.session_name_edit.setEnabled(False)
            self.operator_edit.setEnabled(False)
            self.save_notes_btn.setEnabled(True)
            self._log_activity(f"ℹ️ Continuing active session: {session_id}", "info")
        
        # One-time cleanup of legacy standalone output files in the output root
        self._cleanup_legacy_files(output_dir)
        
        # Ensure VXC log directory exists
        Path(vxc_dir).mkdir(parents=True, exist_ok=True)
        
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Auto-start VXC logging if enabled and not already logging
        if self.vxc_logger is None:
            self._log_activity("Waiting for VXC connection to start logging...", "warning")
        else:
            if not hasattr(self.vxc_logger, 'current_file') or self.vxc_logger.current_file is None:
                try:
                    self.vxc_logger.start_logging()
                    self._log_activity("✓ VXC position logging auto-started", "success")
                except Exception as e:
                    self._log_activity(f"Warning: Could not auto-start VXC logging: {e}", "warning")
        
        # Create file monitor with session manager
        self.file_monitor = FileMonitor(
            watch_directory=self.watch_dir,
            vxc_log_directory=vxc_dir,
            output_directory=output_dir,
            tolerance_sec=tolerance,
            file_stable_duration_sec=2.0,
            poll_interval_sec=2.0,
            # time_window_minutes uses default (90 min) to handle VXC log rotation
            session_manager=self.session_manager  # Pass session manager
        )
        
        # Connect signals
        self.file_monitor.file_detected.connect(self._on_file_detected)
        self.file_monitor.merge_started.connect(self._on_merge_started)
        self.file_monitor.merge_completed.connect(self._on_merge_completed)
        self.file_monitor.merge_failed.connect(self._on_merge_failed)
        self.file_monitor.status_update.connect(self._on_status_update)
        
        # Start monitoring
        if self.file_monitor.start_monitoring():
            self.status_indicator.setText("● Monitoring Active")
            self.status_indicator.setStyleSheet("color: green; font-weight: bold; font-size: 11pt;")
            self._log_activity("✓ File monitoring started", "success")
        else:
            self._log_activity("✗ Failed to start file monitoring", "error")
            self.enable_checkbox.setChecked(False)
    
    def _stop_monitoring(self):
        """Stop file monitoring."""
        if self.file_monitor:
            self.file_monitor.stop_monitoring()
            self.file_monitor = None
        
        # DON'T automatically end session - let user control session lifecycle
        # Sessions now independent of monitoring state
        
        self.status_indicator.setText("● Inactive")
        self.status_indicator.setStyleSheet("color: gray; font-weight: bold; font-size: 11pt;")
        self._log_activity("File monitoring stopped", "info")
        
        if self.session_manager and self.session_manager.is_active():
            self._log_activity(
                "ℹ️ Session still active. End session manually when data collection complete.",
                "info"
            )
    
    @pyqtSlot(str)
    def _on_file_detected(self, filepath: str):
        """Handle file detected signal."""
        filename = Path(filepath).name
        self._log_activity(f"🔍 Detected: {filename}", "info")
    
    @pyqtSlot(str)
    def _on_merge_started(self, filename: str):
        """Handle merge started signal."""
        self._log_activity(f"🔄 Processing: {filename}", "info")
    
    @pyqtSlot(str, dict)
    def _on_merge_completed(self, filename: str, stats: dict):
        """Handle merge completed signal."""
        match_rate = stats.get('match_rate_percent', 0)
        matched = stats.get('matched', 0)
        total = stats.get('total_adv_records', 0)
        avg_delta = stats.get('time_delta_avg_ms', 0)
        avg_output = stats.get('avg_output_file')
        avg_points_total = stats.get('avg_points_total', 0)
        avg_points_valid = stats.get('avg_points_valid', 0)
        
        self.total_processed += 1
        self.processed_label.setText(str(self.total_processed))
        
        # Update last merge info
        self.last_merge_label.setText(
            f"{filename} ({match_rate:.1f}% match, {matched}/{total} records)"
        )
        
        # Log with color coding based on match rate
        if match_rate >= 90:
            self._log_activity(f"✅ Merged: {filename} ({match_rate:.1f}%, Δt={avg_delta:.1f}ms)", "success")
        elif match_rate >= 50:
            self._log_activity(f"⚠️  Merged: {filename} ({match_rate:.1f}%, Δt={avg_delta:.1f}ms)", "warning")
        else:
            self._log_activity(f"❌ Merged: {filename} ({match_rate:.1f}%, Δt={avg_delta:.1f}ms) - Low match rate!", "error")

        # Emit signal for Live Data tab update
        # For session-based collection, use the session's averaged file
        # For non-session collection, use the individual averaged output file
        avg_file_to_display = None
        
        if self.session_manager and self.session_manager.is_active():
            # Always use the session master averaged file
            avg_file_to_display = str(self.session_manager.averaged_file)
            seq = self.session_manager.measurement_seq
            self._log_activity(
                f"📊 Measurement {seq} appended to session master files",
                "info",
            )
        
        # Update Live Data tab if we have data to show
        if avg_file_to_display:
            self.averaged_file_ready.emit(avg_file_to_display, stats)
        
        # Show toast notification (optional - could add a temporary overlay)
        self._show_toast(f"✓ Merged: {filename} ({match_rate:.1f}%)")
    
    @pyqtSlot(str, str)
    def _on_merge_failed(self, filename: str, error: str):
        """Handle merge failed signal."""
        self.total_failed += 1
        self.failed_label.setText(str(self.total_failed))
        
        self._log_activity(f"✗ Failed: {filename} - {error}", "error")
    
    @pyqtSlot(str)
    def _on_status_update(self, message: str):
        """Handle status update signal."""
        self._log_activity(message, "info")
    
    def _log_activity(self, message: str, level: str = "info"):
        """Add message to activity log with timestamp.
        
        Args:
            message: Log message
            level: Log level (info, success, warning, error)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Color coding
        if level == "success":
            color = "#2e7d32"  # Green
        elif level == "warning":
            color = "#f57c00"  # Orange
        elif level == "error":
            color = "#c62828"  # Red
        else:
            color = "#424242"  # Dark gray
        
        # Add to log
        html = f'<span style="color: {color};"><b>[{timestamp}]</b> {message}</span>'
        self.activity_log.append(html)

        # Cap log at 500 lines to prevent memory growth during long sessions
        _MAX_LOG_LINES = 500
        doc = self.activity_log.document()
        if doc.blockCount() > _MAX_LOG_LINES:
            trim_cursor = QTextCursor(doc)
            trim_cursor.movePosition(QTextCursor.Start)
            trim_cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor)
            trim_cursor.removeSelectedText()

        # Auto-scroll to bottom
        cursor = self.activity_log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.activity_log.setTextCursor(cursor)
    
    def _clear_activity_log(self):
        """Clear activity log."""
        self.activity_log.clear()
        self._log_activity("Activity log cleared", "info")
    
    def _show_toast(self, message: str):
        """Show temporary toast notification (placeholder for now)."""
        # Could implement a temporary overlay widget here
        # For MVP, just log to activity
        pass
    
    def cleanup(self):
        """Cleanup when tab is destroyed."""
        if self.file_monitor and self.file_monitor.is_monitoring():
            self._stop_monitoring()

    def _generate_default_session_name(self) -> str:
        """Generate default session name with timestamp."""
        return datetime.now().strftime("Session_%Y%m%d_%H%M%S")
    
    def _auto_start_session(self):
        """Prompt the user for a session name and start the session automatically.
        
        Called at monitoring start when no session is active. The user can accept
        the default date-based name with one click, or type a custom name.
        If the dialog is cancelled, the date-based default is used silently.
        """
        from PyQt5.QtWidgets import QInputDialog
        default_name = datetime.now().strftime("Session_%Y%m%d")
        name, ok = QInputDialog.getText(
            self,
            "Start Data Collection Session",
            "Name this session\n"
            "(e.g. Run01, CrossSection_Y05, BaselineTest):",
            text=default_name,
        )
        if not ok or not name.strip():
            name = default_name  # Silent fallback to date-based name
        name = name.strip()

        session_config = SessionConfig(
            session_name=name,
            operator=self.operator_edit.text().strip() or "Unknown",
            notes=self.notes_edit.text().strip(),
            scan_type="Manual",
        )
        try:
            session_id = self.session_manager.start_session(session_config)
            self.current_session_dir = self.session_manager.session_dir
            self.session_name_edit.setText(name)

            self.session_status_label.setText(f"🟢 COLLECTING DATA - {session_id}")
            self.session_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.new_session_btn.setEnabled(False)
            self.end_session_btn.setEnabled(True)
            self.session_name_edit.setEnabled(False)
            self.operator_edit.setEnabled(False)
            self.save_notes_btn.setEnabled(True)

            self._log_activity(f"✓ Session auto-started: {session_id}", "success")
        except Exception as e:
            self._log_activity(f"✗ Failed to auto-start session: {e}", "error")

    def _cleanup_legacy_files(self, output_dir: str):
        """Delete standalone _merged.csv and _avg_xy.csv files from the output root.
        
        These are leftover from before session-based collection was enforced.
        Called once at monitoring start.
        """
        output_path = Path(output_dir)
        deleted = 0
        for pattern in ("*_merged.csv", "*_avg_xy.csv"):
            for f in output_path.glob(pattern):
                try:
                    f.unlink()
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete legacy file {f.name}: {e}")
        if deleted:
            self._log_activity(f"🧹 Cleaned up {deleted} legacy standalone output files", "info")

    
    def _save_notes(self):
        """Save notes and operator to active session metadata."""
        if not self.session_manager or not self.session_manager.is_active():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Active Session", 
                               "No session is currently active. Start a session first.")
            return
        
        try:
            # Get current values from UI
            notes = self.notes_edit.text().strip()
            operator = self.operator_edit.text().strip()
            
            # Update session configuration
            self.session_manager.update_session_config(
                notes=notes,
                operator=operator
            )
            
            self._log_activity(f"✓ Saved notes to session metadata", "success")
            
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Save Failed", f"Failed to save notes: {e}")
            self._log_activity(f"✗ Failed to save notes: {e}", "error")
    
    def _create_new_session(self):
        """Create a new session directory."""
        session_name = self.session_name_edit.text().strip()
        if not session_name:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid Session Name", 
                               "Please enter a session name.")
            return
        
        # Create SessionManager if not exists
        if self.session_manager is None:
            base_output = self.output_dir_edit.text()
            self.session_manager = SessionManager(base_output)
        
        # Create session configuration
        session_config = SessionConfig(
            session_name=session_name,
            operator=self.operator_edit.text().strip() or "Unknown",
            notes=self.notes_edit.text().strip(),
            scan_type="Manual"  # Will be updated by cross-section tab if applicable
        )
        
        try:
            # Start the session
            session_id = self.session_manager.start_session(session_config)
            self.current_session_dir = self.session_manager.session_dir
            
            # Update UI with session active state
            self.session_status_label.setText(f"🟢 COLLECTING DATA - {session_id}")
            self.session_status_label.setStyleSheet("color: green; font-weight: bold;")
            
            # Disable Start Session, enable End Session
            self.new_session_btn.setEnabled(False)
            self.end_session_btn.setEnabled(True)
            
            # Lock session parameters
            self.session_name_edit.setEnabled(False)
            self.operator_edit.setEnabled(False)
            self.save_notes_btn.setEnabled(True)
            
            self._log_activity(f"✓ Session started: {session_id}", "success")
            
        except RuntimeError as e:
            from PyQt5.QtWidgets import QMessageBox
            error_msg = str(e)
            
            # Check if it's the "session already active" error
            if "already active" in error_msg.lower():
                QMessageBox.warning(
                    self, 
                    "Session Already Active", 
                    f"{error_msg}\n\n"
                    "You must end the current session before starting a new one.\n"
                    "Click the 'End Session' button (red) to close the current session."
                )
            else:
                QMessageBox.warning(self, "Session Error", error_msg)
            
            self._log_activity(f"✗ Failed to start session: {e}", "error")
    
    def _end_current_session(self):
        """End the current session and generate metadata."""
        if self.session_manager and self.session_manager.is_active():
            try:
                result = self.session_manager.stop_session()
                session_id = result['session_id']
                metadata = result['metadata']
                
                # Update UI to show no session
                self.session_status_label.setText("⚪ NO SESSION")
                self.session_status_label.setStyleSheet("color: #888; font-weight: bold;")
                
                # Enable Start Session, disable End Session
                self.new_session_btn.setEnabled(True)
                self.end_session_btn.setEnabled(False)
                
                # Unlock session parameters
                self.session_name_edit.setEnabled(True)
                self.operator_edit.setEnabled(True)
                self.save_notes_btn.setEnabled(False)
                
                # Generate new default name for next session
                self.session_name_edit.setText(self._generate_default_session_name())
                
                # Log session summary
                stats = metadata['statistics']
                quality = metadata['quality_summary']
                self._log_activity(
                    f"✓ Session ended: {session_id} - "
                    f"{stats['total_measurements']} measurements, "
                    f"{quality['excellent_points']} excellent, {quality['good_points']} good",
                    "success"
                )
                
            except Exception as e:
                self._log_activity(f"✗ Failed to end session: {e}", "error")
    
    def _browse_sessions(self):
        """Browse and view past sessions."""
        base_output = self.output_dir_edit.text()
        sessions_dir = Path(base_output) / "sessions"
        
        if not sessions_dir.exists():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Sessions", 
                                   "No session directory found. Create a session first.")
            return
        
        # Check for experiment index
        index_file = sessions_dir / "experiment_index.csv"
        if not index_file.exists():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Sessions", 
                                   "No sessions have been completed yet.")
            return
        
        # Read and display sessions
        try:
            import csv
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QHBoxLayout
            
            dialog = QDialog(self)
            dialog.setWindowTitle("Session Browser")
            dialog.setMinimumSize(900, 500)
            
            layout = QVBoxLayout()
            
            # Create table
            table = QTableWidget()
            table.setColumnCount(9)
            table.setHorizontalHeaderLabels([
                "Session ID", "Name", "Date", "Operator", "Type", 
                "Points", "Duration (min)", "Match Rate %", "Notes"
            ])
            table.horizontalHeader().setStretchLastSection(True)
            
            # Load sessions from index
            with open(index_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                sessions = list(reader)
                
                table.setRowCount(len(sessions))
                for i, session in enumerate(sessions):
                    table.setItem(i, 0, QTableWidgetItem(session.get('session_id', '')))
                    table.setItem(i, 1, QTableWidgetItem(session.get('session_name', '')))
                    table.setItem(i, 2, QTableWidgetItem(session.get('date', '')))
                    table.setItem(i, 3, QTableWidgetItem(session.get('operator', '')))
                    table.setItem(i, 4, QTableWidgetItem(session.get('scan_type', '')))
                    table.setItem(i, 5, QTableWidgetItem(session.get('point_count', '')))
                    table.setItem(i, 6, QTableWidgetItem(session.get('duration_min', '')))
                    table.setItem(i, 7, QTableWidgetItem(session.get('match_rate', '')))
                    table.setItem(i, 8, QTableWidgetItem(session.get('notes', '')))
            
            table.resizeColumnsToContents()
            layout.addWidget(table)
            
            # Buttons
            btn_layout = QHBoxLayout()
            
            open_folder_btn = QPushButton("Open Session Folder")
            open_folder_btn.clicked.connect(lambda: self._open_session_folder(table, sessions_dir))
            btn_layout.addWidget(open_folder_btn)
            
            btn_layout.addStretch()
            
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            btn_layout.addWidget(close_btn)
            
            layout.addLayout(btn_layout)
            dialog.setLayout(layout)
            dialog.exec_()
            
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Failed to load sessions: {e}")
            self._log_activity(f"✗ Failed to browse sessions: {e}", "error")
    
    def _open_session_folder(self, table, sessions_dir):
        """Open the selected session folder in file explorer."""
        current_row = table.currentRow()
        if current_row < 0:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Selection", "Please select a session first.")
            return
        
        session_id = table.item(current_row, 0).text()
        session_path = sessions_dir / session_id
        
        if session_path.exists():
            import subprocess
            subprocess.Popen(f'explorer "{session_path}"')
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Not Found", f"Session folder not found:\n{session_path}")
