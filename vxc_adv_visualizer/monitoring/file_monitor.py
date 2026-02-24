"""File monitoring system for automatic ADV-VXC merge."""

import logging
import time
import re
from pathlib import Path
from typing import Optional, Dict, Set, List, Tuple
from datetime import datetime, timedelta, timezone

from PyQt5.QtCore import QObject, QTimer, QFileSystemWatcher, pyqtSignal, QThread, pyqtSlot

from ..data.adv_vxc_merger import ADVVXCMerger
from ..data.session_manager import SessionConfig
from .vxc_matcher import VXCLogMatcher

logger = logging.getLogger(__name__)

# ADV filename pattern: YYYYMMDD-HHMMSS.csv (e.g., 20260209-144849.csv)
ADV_FILENAME_PATTERN = re.compile(r'^(\d{8})-(\d{6})\.csv$')


class MergeWorkerThread(QThread):
    """Background thread to parse, merge, and write ADV/VXC outputs."""

    completed = pyqtSignal(str, dict)
    failed = pyqtSignal(str)

    def __init__(self, adv_file: Path, vxc_file: Path, output_dir: Path, tolerance_sec: float, session_manager=None):
        super().__init__()
        self.adv_file = adv_file
        self.vxc_file = vxc_file
        self.output_dir = output_dir
        self.tolerance_sec = tolerance_sec
        self.session_manager = session_manager

    def run(self):
        """Execute merge operation in background thread."""
        filename = self.adv_file.name
        try:
            logger.info(f"[WORKER] Starting merge for {filename}")
            merger = ADVVXCMerger(tolerance_sec=self.tolerance_sec)
            
            logger.debug(f"[WORKER] Parsing ADV file: {self.adv_file}")
            merger.parse_adv_csv(str(self.adv_file))
            
            logger.debug(f"[WORKER] Parsing VXC file: {self.vxc_file}")
            merger.parse_vxc_csv(str(self.vxc_file))
            
            logger.debug(f"[WORKER] Merging data for {filename}")
            matched, _unmatched, stats = merger.merge()

            # Use session manager if active, otherwise write to output_dir
            if self.session_manager and self.session_manager.is_active():
                logger.debug(f"[WORKER] Using session manager for {filename}")
                
                # Get merged and averaged data from merger
                merged_data = merger.merged_data
                
                # Calculate averaged data for session
                avg_data_dict = {}
                if merged_data:
                    # Get grid position from first valid sample with VXC data
                    for sample in merged_data:
                        if sample.get('vxc_quality') != 'MISSING':
                            avg_data_dict['x_m'] = sample.get('vxc_x_m')
                            avg_data_dict['y_m'] = sample.get('vxc_y_m')
                            avg_data_dict['timestamp_utc'] = sample.get('timestamp_utc')
                            avg_data_dict['quality_flag'] = sample.get('vxc_quality')  # Use quality_flag for averaged schema
                            # Note: time_delta_ms not in averaged schema, only in raw
                            break
                    
                    # Calculate averages for velocity and quality metrics
                    valid_samples = [s for s in merged_data if s.get('vxc_quality') != 'MISSING']
                    if valid_samples:
                        avg_data_dict['sample_count'] = len(valid_samples)
                        # Note: 'status' field removed - not in session fieldnames
                        
                        # Average velocity components
                        for key in ['Raw Velocity.X (m/s)', 'Raw Velocity.Y (m/s)', 'Raw Velocity.Z (m/s)',
                                   'Corrected Velocity.X (m/s)', 'Corrected Velocity.Y (m/s)', 'Corrected Velocity.Z (m/s)']:
                            values = [float(s.get(key, 0)) for s in valid_samples if s.get(key) is not None]
                            if values:
                                avg_data_dict[key] = sum(values) / len(values)
                        
                        # Average correlation and SNR
                        corr_values = []
                        snr_values = []
                        for s in valid_samples:
                            for i in range(1, 4):
                                corr_val = s.get(f'Correlation Score.Beam{i} (%)')
                                snr_val = s.get(f'SNR.Beam{i} (dB)')
                                if corr_val is not None:
                                    corr_values.append(float(corr_val))
                                if snr_val is not None:
                                    snr_values.append(float(snr_val))
                        
                        if corr_values:
                            avg_data_dict['Correlation.Avg (%)'] = sum(corr_values) / len(corr_values)
                        if snr_values:
                            avg_data_dict['SNR.Avg (dB)'] = sum(snr_values) / len(snr_values)
                        
                        # Average environmental data - map field names to match session schema
                        env_field_map = {
                            'Temperature (°C)': 'Temperature (C)',  # Remove degree symbol
                            'Pressure (dbar)': 'Pressure (dbar)',
                            'Voltage (V)': 'Voltage (V)'
                        }
                        for adv_key, session_key in env_field_map.items():
                            values = [float(s.get(adv_key, 0)) for s in valid_samples if s.get(adv_key) is not None]
                            if values:
                                avg_data_dict[session_key] = sum(values) / len(values)
                
                # Append to session
                try:
                    seq = self.session_manager.append_measurement(merged_data, avg_data_dict)
                    stats['session_measurement_seq'] = seq
                    logger.info(f"[WORKER] Appended to session: measurement {seq}")
                except Exception as e:
                    logger.error(f"[WORKER] Failed to append to session: {e}")
                    # Fall through to write individual files
            else:
                # No active session - write individual files (legacy behavior)
                logger.debug(f"[WORKER] Writing merged output for {filename}")
                output_file = self.output_dir / f"{self.adv_file.stem}_merged.csv"
                merger.write_merged_csv(str(output_file))

                logger.debug(f"[WORKER] Writing averaged output for {filename}")
                avg_output_file = self.output_dir / f"{self.adv_file.stem}_avg_xy.csv"
                try:
                    avg_path, avg_stats = merger.write_averaged_plane_csv(str(avg_output_file))
                    stats.update(avg_stats)
                    stats["avg_output_file"] = avg_path
                except Exception as e:
                    logger.warning(f"[WORKER] Averaged output failed for {filename}: {e}")

            stats["matched"] = matched
            
            # Validate merged data - delete output files if no valid matches
            # (Only applies when writing individual files, not for sessions)
            if not (self.session_manager and self.session_manager.is_active()):
                avg_valid_points = stats.get("avg_points_valid", 0)
                
                if matched == 0 or avg_valid_points == 0:
                    reason = "no merged data" if matched == 0 else "no valid grid points with position data"
                    logger.warning(f"[WORKER] Invalid output for {filename}: {reason} - deleting files")
                    try:
                        if output_file.exists():
                            output_file.unlink()
                            logger.info(f"[WORKER] Deleted {output_file.name} ({reason})")
                        if avg_output_file.exists():
                            avg_output_file.unlink()
                            logger.info(f"[WORKER] Deleted {avg_output_file.name} ({reason})")
                    except Exception as del_err:
                        logger.error(f"[WORKER] Failed to delete invalid output files: {del_err}")
                    
                    # Emit failure signal instead of success
                    error_msg = f"{filename}: No valid VXC+ADV data (matched={matched}, valid_points={avg_valid_points})"
                    self.failed.emit(error_msg)
                    return
            
            # Archive raw ADV files to session if active
            if self.session_manager and self.session_manager.is_active():
                try:
                    import shutil
                    session_dir = self.session_manager.session_dir
                    raw_exports_dir = session_dir / "raw_exports"
                    raw_exports_dir.mkdir(exist_ok=True)
                    
                    # Copy ADV CSV file
                    shutil.copy2(self.adv_file, raw_exports_dir / self.adv_file.name)
                    
                    # Copy config file if exists
                    config_file = self.adv_file.with_suffix('.labadv_config')
                    if config_file.exists():
                        shutil.copy2(config_file, raw_exports_dir / config_file.name)
                    
                    logger.info(f"[WORKER] Archived raw files to {raw_exports_dir}")
                except Exception as archive_err:
                    logger.warning(f"[WORKER] Failed to archive raw files: {archive_err}")
            
            logger.info(f"[WORKER] Merge completed for {filename}, emitting signal")
            self.completed.emit(filename, stats)
            logger.debug(f"[WORKER] Signal emitted for {filename}")
        except Exception as e:
            logger.error(f"[WORKER] Merge failed for {filename}: {e}", exc_info=True)
            self.failed.emit(f"{filename}: {str(e)}")


class FileMonitor(QObject):
    """Monitors directory for new ADV CSV files and triggers auto-merge.
    
    Uses hybrid approach: QFileSystemWatcher for immediate detection + 
    QTimer polling for reliability.
    """
    
    # Signals for GUI updates (thread-safe)
    file_detected = pyqtSignal(str)  # filepath
    merge_started = pyqtSignal(str)  # filename
    merge_completed = pyqtSignal(str, dict)  # filename, stats
    merge_failed = pyqtSignal(str, str)  # filename, error_message
    status_update = pyqtSignal(str)  # status_message
    
    def __init__(self, 
                 watch_directory: str,
                 vxc_log_directory: str,
                 output_directory: Optional[str] = None,
                 tolerance_sec: float = 0.5,
                 file_stable_duration_sec: float = 2.0,
                 poll_interval_sec: float = 10.0,
                 time_window_minutes: float = 90.0,
                 session_manager=None):
        """Initialize file monitor.
        
        Args:
            watch_directory: Directory to watch for ADV CSV exports
            vxc_log_directory: Directory containing VXC position logs
            output_directory: Directory for merged output (default: same as watch_directory)
            tolerance_sec: Timestamp matching tolerance for merge
            file_stable_duration_sec: File size must be stable this long before processing
            poll_interval_sec: Polling interval for fallback detection
            time_window_minutes: Maximum time difference (minutes) between ADV and VXC filenames for matching (default 90 for 1-hour VXC log rotation)
            session_manager: Optional SessionManager for session-based output
        """
        super().__init__()
        
        # Configuration
        self.watch_dir = Path(watch_directory)
        self.vxc_log_dir = Path(vxc_log_directory)
        self.output_dir = Path(output_directory) if output_directory else self.watch_dir
        self.tolerance_sec = tolerance_sec
        self.file_stable_duration = file_stable_duration_sec
        self.poll_interval = poll_interval_sec
        self.time_window_minutes = time_window_minutes
        self.session_manager = session_manager
        
        # VXC matcher
        self.vxc_matcher = VXCLogMatcher(str(self.vxc_log_dir))
        
        # Tracking data structures
        self.processed_files: Set[Path] = set()
        self.pending_files: Dict[Path, float] = {}  # filepath -> detection_time
        self.retry_queue: List[Tuple[Path, int]] = []  # (filepath, attempt_count)
        self.file_sizes: Dict[Path, int] = {}  # For stability checking
        
        # Statistics
        self.total_processed = 0
        self.total_failed = 0
        self.last_merge_time = 0
        
        # QFileSystemWatcher for event-driven detection
        self.file_watcher = QFileSystemWatcher()
        self.file_watcher.directoryChanged.connect(self._on_directory_changed)
        
        # Timer 1: File completion checker (500ms)
        self.completion_timer = QTimer()
        self.completion_timer.timeout.connect(self._check_pending_files)
        
        # Timer 2: Queue processor (1000ms)
        self.queue_timer = QTimer()
        self.queue_timer.timeout.connect(self._process_merge_queue)
        
        # Timer 3: Polling fallback (user-configurable, default 5000ms)
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_directory)
        
        # Timer 4: Retry handler (10000ms)
        self.retry_timer = QTimer()
        self.retry_timer.timeout.connect(self._process_retry_queue)
        
        # Timer 5: Cleanup (300000ms = 5 minutes)
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self._cleanup_old_entries)
        
        # Monitoring state
        self.monitoring_active = False
        self.active_merge_threads: Dict[str, QThread] = {}
        self.max_concurrent_merges = 2
        self.merge_queue: List[Tuple[Path, Path]] = []  # (adv_file, vxc_file) pairs waiting to merge
    
    def start_monitoring(self) -> bool:
        """Start file monitoring.
        
        Returns:
            True if started successfully, False otherwise
        """
        if not self.watch_dir.exists():
            logger.error(f"Watch directory not found: {self.watch_dir}")
            self.status_update.emit(f"Error: Watch directory not found")
            return False
        
        if not self.vxc_log_dir.exists():
            logger.warning(f"VXC log directory not found: {self.vxc_log_dir}")
            # Don't fail - VXC logs might be created later
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Clear cached processed files on startup to allow reprocessing of failed merges
        self.processed_files.clear()
        logger.info("Cleared processed files cache for fresh scan")
        
        # Add watch path
        if str(self.watch_dir) not in self.file_watcher.directories():
            self.file_watcher.addPath(str(self.watch_dir))
        
        # Start all timers
        self.completion_timer.start(500)  # Check pending files every 500ms
        self.queue_timer.start(1000)  # Process queue every 1s
        self.poll_timer.start(int(self.poll_interval * 1000))  # Polling fallback
        self.retry_timer.start(10000)  # Retry every 10s
        self.cleanup_timer.start(300000)  # Cleanup every 5 minutes
        
        self.monitoring_active = True
        logger.info(f"File monitoring started: {self.watch_dir}")
        self.status_update.emit(f"Monitoring active: {self.watch_dir}")
        
        # Process any existing backlog
        self._process_backlog()
        
        return True
    
    def stop_monitoring(self):
        """Stop file monitoring."""
        # Stop all timers
        self.completion_timer.stop()
        self.queue_timer.stop()
        self.poll_timer.stop()
        self.retry_timer.stop()
        self.cleanup_timer.stop()
        
        # Remove watch paths
        for path in self.file_watcher.directories():
            self.file_watcher.removePath(path)
        
        self.monitoring_active = False
        logger.info("File monitoring stopped")
        self.status_update.emit("Monitoring stopped")
    
    def is_monitoring(self) -> bool:
        """Check if monitoring is active."""
        return self.monitoring_active
    
    def _on_directory_changed(self, path: str):
        """Handle directory change event from QFileSystemWatcher.
        
        Args:
            path: Directory path that changed
        """
        logger.debug(f"Directory changed: {path}")
        self._scan_for_new_files()
    
    def _poll_directory(self):
        """Polling fallback to catch missed events."""
        if not self.monitoring_active:
            return
        
        logger.debug("Polling directory for new files")
        self._scan_for_new_files()
    
    @staticmethod
    def is_valid_adv_filename(filename: str) -> bool:
        """Validate ADV filename format: YYYYMMDD-HHMMSS.csv
        
        Args:
            filename: Filename to validate
            
        Returns:
            True if filename matches ADV export format
        """
        if not filename or not isinstance(filename, str):
            return False
        
        match = ADV_FILENAME_PATTERN.match(filename)
        if not match:
            return False
        
        # Validate date/time components
        date_str, time_str = match.groups()
        try:
            # Check if valid date
            year = int(date_str[0:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            
            # Check if valid time
            hour = int(time_str[0:2])
            minute = int(time_str[2:4])
            second = int(time_str[4:6])
            
            # Basic range validation
            if not (1900 <= year <= 2100):
                return False
            if not (1 <= month <= 12):
                return False
            if not (1 <= day <= 31):
                return False
            if not (0 <= hour <= 23):
                return False
            if not (0 <= minute <= 59):
                return False
            if not (0 <= second <= 59):
                return False
            
            return True
        except ValueError:
            return False
    
    def _scan_for_new_files(self):
        """Scan watch directory for new ADV CSV files.
        
        Only processes files matching the ADV export format (YYYYMMDD-HHMMSS.csv).
        Safely ignores other files in the directory.
        """
        if not self.watch_dir.exists():
            return
        
        # Look for all .csv files first
        for csv_file in self.watch_dir.glob("*.csv"):
            # Validate filename format
            if not self.is_valid_adv_filename(csv_file.name):
                logger.debug(f"Skipping non-ADV file: {csv_file.name}")
                continue
            
            # Skip if already processed or pending
            if csv_file in self.processed_files or csv_file in self.pending_files:
                continue
            
            # Skip merged/averaged output files
            if '_merged' in csv_file.stem or '_avg_xy' in csv_file.stem:
                logger.debug(f"Skipping output file: {csv_file.name}")
                continue
            
            # New valid ADV file detected!
            logger.info(f"New file detected: {csv_file.name}")
            self.file_detected.emit(str(csv_file))
            self.pending_files[csv_file] = time.time()
    
    def _check_pending_files(self):
        """Check pending files for completion."""
        if not self.pending_files:
            return
        
        current_time = time.time()
        completed = []
        
        for filepath, detect_time in list(self.pending_files.items()):
            # Skip if too recent (file might still be writing)
            if current_time - detect_time < self.file_stable_duration:
                continue
            
            # Check if file is complete
            if self._is_file_complete(filepath):
                logger.info(f"File complete: {filepath.name}")
                completed.append(filepath)
                # Add to processed set to prevent reprocessing
                self.processed_files.add(filepath)
                # Trigger merge
                self._trigger_merge(filepath)
        
        # Remove completed from pending
        for filepath in completed:
            del self.pending_files[filepath]
    
    def _is_file_complete(self, filepath: Path) -> bool:
        """Check if file write is complete by monitoring size stability.
        
        Args:
            filepath: Path to file
            
        Returns:
            True if file appears complete
        """
        if not filepath.exists():
            return False
        
        try:
            current_size = filepath.stat().st_size
            
            # Check if size is zero
            if current_size == 0:
                return False
            
            # Check size stability
            previous_size = self.file_sizes.get(filepath, None)
            
            if previous_size is None:
                # First check - record size
                self.file_sizes[filepath] = current_size
                return False
            
            # Size must be stable
            if current_size == previous_size:
                # Size is stable - file is complete
                return True
            else:
                # Size changed - still writing
                self.file_sizes[filepath] = current_size
                return False
                
        except OSError as e:
            logger.error(f"Error checking file completion: {e}")
            return False
    
    def _process_merge_queue(self):
        """Process queued merge operations (rate limiting)."""
        # Check if we have capacity for more merges
        while len(self.active_merge_threads) < self.max_concurrent_merges and self.merge_queue:
            adv_file, vxc_file = self.merge_queue.pop(0)
            if adv_file.exists() and vxc_file.exists():
                logger.info(f"Processing queued merge: {adv_file.name} with {vxc_file.name}")
                self._start_merge_worker(adv_file, vxc_file)
            else:
                logger.warning(f"Queued file disappeared: {adv_file.name}")
    
    def _trigger_merge(self, adv_file: Path):
        """Trigger merge operation for ADV file.
        
        Args:
            adv_file: ADV CSV file to merge
        """
        if not adv_file.exists():
            logger.warning(f"File disappeared before processing: {adv_file}")
            return
        
        try:
            self.merge_started.emit(adv_file.name)
            
            # Find corresponding VXC log
            vxc_file = self.vxc_matcher.find_matching_vxc_log(adv_file, time_window_minutes=self.time_window_minutes)
            
            if not vxc_file:
                # No VXC log - add to retry queue but KEEP in processed_files
                # This prevents infinite re-detection loops
                logger.warning(f"No VXC log for {adv_file.name}, queuing for retry")
                self.retry_queue.append((adv_file, 1))
                self.merge_failed.emit(adv_file.name, "No matching VXC log found (queued for retry)")
                return
            
            logger.info(f"Merging {adv_file.name} with {vxc_file.name}")
            if len(self.active_merge_threads) >= self.max_concurrent_merges:
                logger.warning(f"Merge backlog: too many concurrent merges, queuing {adv_file.name}")
                self.merge_queue.append((adv_file, vxc_file))
                return
            self._start_merge_worker(adv_file, vxc_file)
            
        except Exception as e:
            logger.error(f"Merge failed for {adv_file.name}: {e}")
            self.total_failed += 1
            self.merge_failed.emit(adv_file.name, str(e))

    def _start_merge_worker(self, adv_file: Path, vxc_file: Path):
        logger.info(f"[MONITOR] Starting merge worker for {adv_file.name}")
        
        # Use current session manager (which may or may not have an active session)
        # DO NOT auto-create sessions - let user control session lifecycle
        session_to_use = self.session_manager
        
        # Create worker thread (QThread subclass with run() override)
        thread = MergeWorkerThread(adv_file, vxc_file, self.output_dir, self.tolerance_sec, session_to_use)
        
        # Connect signals
        thread.completed.connect(lambda name, stats: self._on_merge_success(adv_file, name, stats))
        thread.failed.connect(lambda error: self._on_merge_error(adv_file, error))
        thread.finished.connect(lambda: self._cleanup_merge_thread(adv_file))

        # Safety timeout - if worker doesn't complete in 30 seconds, something is wrong
        timeout_timer = QTimer()
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(lambda: self._on_worker_timeout(adv_file, thread))
        timeout_timer.start(30000)  # 30 seconds
        
        # Store timer reference so it doesn't get garbage collected
        thread._timeout_timer = timeout_timer

        self.active_merge_threads[str(adv_file)] = thread
        logger.debug(f"[MONITOR] Thread created, starting for {adv_file.name}")
        thread.start()
        logger.debug(f"[MONITOR] Thread started for {adv_file.name}")

    def _on_merge_success(self, adv_file: Path, filename: str, stats: dict):
        logger.info(f"[MONITOR] _on_merge_success called for {filename}")
        self.total_processed += 1
        self.last_merge_time = time.time()
        logger.info(
            f"Merge complete: {stats.get('matched', 0)}/{stats.get('total_adv_records', 0)} "
            f"records ({stats.get('match_rate_percent', 0):.1f}%)"
        )
        self.merge_completed.emit(filename, stats)
        self.file_sizes.pop(adv_file, None)

    def _on_merge_error(self, adv_file: Path, error: str):
        logger.error(f"[MONITOR] _on_merge_error called for {adv_file.name}")
        logger.error(f"Merge failed for {adv_file.name}: {error}")
        self.total_failed += 1
        self.merge_failed.emit(adv_file.name, error)

    def _cleanup_merge_thread(self, adv_file: Path):
        logger.info(f"[MONITOR] Cleaning up thread for {adv_file.name}")
        thread = self.active_merge_threads.pop(str(adv_file), None)
        if thread and hasattr(thread, '_timeout_timer'):
            thread._timeout_timer.stop()
        logger.info(f"[MONITOR] Active threads: {len(self.active_merge_threads)}, Queued: {len(self.merge_queue)}")
        # When a merge completes, check if we can start queued merges
        self._process_merge_queue()
    
    def _on_worker_timeout(self, adv_file: Path, thread: QThread):
        """Handle worker timeout - worker took too long."""
        logger.error(f"[MONITOR] TIMEOUT: Worker for {adv_file.name} exceeded 30s limit!")
        logger.error(f"[MONITOR] Force-terminating thread and marking as failed")
        thread.quit()
        thread.wait(1000)  # Wait up to 1 second for clean shutdown
        if thread.isRunning():
            thread.terminate()  # Force terminate if still running
        self.total_failed += 1
        self.merge_failed.emit(adv_file.name, "Worker timeout - exceeded 30 seconds")
    
    def _process_retry_queue(self):
        """Process files in retry queue."""
        if not self.retry_queue:
            return
        
        # Process one retry per timer tick
        if self.retry_queue:
            adv_file, attempt_count = self.retry_queue.pop(0)
            
            # Check if VXC log exists now
            vxc_file = self.vxc_matcher.find_matching_vxc_log(adv_file, time_window_minutes=self.time_window_minutes)
            
            if vxc_file:
                # VXC log now available - trigger merge
                logger.info(f"Retry {attempt_count}: VXC log now available for {adv_file.name}")
                self._trigger_merge(adv_file)
            else:
                # Still no VXC log
                if attempt_count < 5:  # Max 5 attempts
                    logger.debug(f"Retry {attempt_count+1}/5: Still no VXC log for {adv_file.name}")
                    self.retry_queue.append((adv_file, attempt_count + 1))
                else:
                    logger.warning(f"Giving up on {adv_file.name} after 5 retry attempts")
                    self.merge_failed.emit(adv_file.name, "No VXC log after 5 retry attempts")
    
    def _process_backlog(self):
        """Process existing files on startup (backlog processing)."""
        if not self.watch_dir.exists():
            return
        
        # Find ADV files without corresponding merged files
        unprocessed = []
        
        for adv_file in self.watch_dir.glob("????????-??????.csv"):
            if adv_file.stem.endswith('_merged'):
                continue
            
            # Check if merged version exists
            merged_file = self.output_dir / f"{adv_file.stem}_merged.csv"
            if not merged_file.exists():
                unprocessed.append(adv_file)
        
        if unprocessed:
            logger.info(f"Found {len(unprocessed)} unprocessed files in backlog")
            self.status_update.emit(f"Processing {len(unprocessed)} backlog files...")
            
            # Add ALL unprocessed files to pending (not limited to 50)
            # Mark as stable so they process immediately
            for adv_file in unprocessed:
                self.pending_files[adv_file] = time.time() - self.file_stable_duration
                logger.debug(f"Added to pending: {adv_file.name}")
        else:
            logger.info("No backlog files to process")
    
    def _cleanup_old_entries(self):
        """Remove old entries from tracking sets to prevent memory growth."""
        # Clean up processed files that no longer exist or have been successfully merged
        to_remove = []
        for filepath in self.processed_files:
            if not filepath.exists():
                # File was deleted
                to_remove.append(filepath)
            else:
                # Check if successfully merged
                merged_file = self.output_dir / f"{filepath.stem}_merged.csv"
                if merged_file.exists():
                    # Successfully merged - can remove from tracking
                    to_remove.append(filepath)
        
        for filepath in to_remove:
            self.processed_files.discard(filepath)
            self.file_sizes.pop(filepath, None)
        
        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} processed file entries")
    
    def _parse_timestamp_from_filename(self, filename: str) -> Optional[datetime]:
        """Extract timestamp from ADV filename (YYYYMMDD-HHMMSS.csv).
        
        Args:
            filename: ADV filename to parse
            
        Returns:
            datetime object if valid, None otherwise
        """
        match = ADV_FILENAME_PATTERN.match(filename)
        if not match:
            return None
        
        try:
            date_str = match.group(1)  # YYYYMMDD
            time_str = match.group(2)  # HHMMSS
            
            year = int(date_str[0:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            
            hour = int(time_str[0:2])
            minute = int(time_str[2:4])
            second = int(time_str[4:6])
            
            return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            return None
    
    # Historical session auto-creation removed - sessions are now user-controlled
    # Users must explicitly start sessions via the UI
    
    def get_statistics(self) -> Dict:
        """Get monitoring statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'monitoring_active': self.monitoring_active,
            'watch_directory': str(self.watch_dir),
            'total_processed': self.total_processed,
            'total_failed': self.total_failed,
            'pending_count': len(self.pending_files),
            'queued_merges': len(self.merge_queue),
            'retry_queue_count': len(self.retry_queue),
            'last_merge_time': self.last_merge_time
        }
