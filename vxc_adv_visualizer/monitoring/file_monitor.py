"""File monitoring system for automatic ADV-VXC merge."""

import logging
import time
import re
import math
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

    POSITION_SEGMENT_TOLERANCE_M = 0.005

    completed = pyqtSignal(str, dict)
    failed = pyqtSignal(str)

    def __init__(self, adv_file: Path, vxc_file: Path, output_dir: Path, tolerance_sec: float, session_manager=None):
        super().__init__()
        self.adv_file = adv_file
        self.vxc_file = vxc_file
        self.output_dir = output_dir
        self.tolerance_sec = tolerance_sec
        self.session_manager = session_manager

    @staticmethod
    def _get_sample_timestamp(sample: Dict) -> Optional[str]:
        return sample.get('UTC time') or sample.get('timestamp_utc')

    def _segment_matched_samples(self, merger: ADVVXCMerger, matched_samples: List[Dict]) -> List[List[Dict]]:
        """Split matched samples into contiguous position segments using 5 mm threshold."""
        if not matched_samples:
            return []

        segments: List[List[Dict]] = [[matched_samples[0]]]
        prev_x = merger._parse_float(matched_samples[0].get('x_m'))
        prev_y = merger._parse_float(matched_samples[0].get('y_m'))

        for sample in matched_samples[1:]:
            x = merger._parse_float(sample.get('x_m'))
            y = merger._parse_float(sample.get('y_m'))

            should_split = False
            if None in (prev_x, prev_y, x, y):
                should_split = True
            else:
                should_split = (
                    abs(x - prev_x) > self.POSITION_SEGMENT_TOLERANCE_M
                    or abs(y - prev_y) > self.POSITION_SEGMENT_TOLERANCE_M
                )

            if should_split:
                segments.append([sample])
            else:
                segments[-1].append(sample)

            prev_x, prev_y = x, y

        return segments

    def _build_segment_average(
        self,
        merger: ADVVXCMerger,
        segment_samples: List[Dict],
        source_adv_file: str,
        segment_index: int,
        segment_count: int,
    ) -> Dict:
        """Compute averaged and turbulence outputs for one position segment."""
        avg_data_dict: Dict = {}
        if not segment_samples:
            return avg_data_dict

        first = segment_samples[0]
        last = segment_samples[-1]

        avg_data_dict['source_adv_file'] = source_adv_file
        avg_data_dict['segment_index'] = segment_index
        avg_data_dict['segment_count'] = segment_count
        avg_data_dict['segment_start_utc'] = self._get_sample_timestamp(first)
        avg_data_dict['segment_end_utc'] = self._get_sample_timestamp(last)
        avg_data_dict['segment_sample_count'] = len(segment_samples)
        avg_data_dict['x_m'] = first.get('x_m')
        avg_data_dict['y_m'] = first.get('y_m')
        avg_data_dict['segment_anchor_x_m'] = first.get('x_m')
        avg_data_dict['segment_anchor_y_m'] = first.get('y_m')
        avg_data_dict['timestamp_utc'] = self._get_sample_timestamp(first)
        avg_data_dict['sample_count'] = len(segment_samples)

        def _safe_floats(samples, key):
            result = []
            for s in samples:
                v = merger._parse_float(s.get(key))
                if v is not None:
                    result.append(v)
            return result

        for key in [
            'Raw Velocity.X (m/s)', 'Raw Velocity.Y (m/s)', 'Raw Velocity.Z (m/s)',
            'Corrected Velocity.X (m/s)', 'Corrected Velocity.Y (m/s)', 'Corrected Velocity.Z (m/s)'
        ]:
            values = _safe_floats(segment_samples, key)
            if values:
                avg_data_dict[key] = sum(values) / len(values)

        corr_values, snr_values = [], []
        for s in segment_samples:
            for i in range(1, 4):
                c = merger._parse_float(s.get(f'Correlation Score.Beam{i} (%)'))
                n = merger._parse_float(s.get(f'SNR.Beam{i} (dB)'))
                if c is not None:
                    corr_values.append(c)
                if n is not None:
                    snr_values.append(n)
        if corr_values:
            avg_data_dict['Correlation.Avg (%)'] = sum(corr_values) / len(corr_values)
        if snr_values:
            avg_data_dict['SNR.Avg (dB)'] = sum(snr_values) / len(snr_values)

        env_field_map = {
            'Temperature (°C)': 'Temperature (C)',
            'Raw Pressure (dbar)': 'Raw Pressure (dbar)',
            'Voltage (V)': 'Voltage (V)',
        }
        for adv_key, session_key in env_field_map.items():
            values = _safe_floats(segment_samples, adv_key)
            if values:
                avg_data_dict[session_key] = sum(values) / len(values)

        if 'Raw Pressure (dbar)' in avg_data_dict:
            atm = merger._load_atmospheric_pressure()
            avg_data_dict['Gauge Pressure (dbar)'] = float(avg_data_dict['Raw Pressure (dbar)']) - atm

        ux_vals = _safe_floats(segment_samples, 'Corrected Velocity.X (m/s)')
        uy_vals = _safe_floats(segment_samples, 'Corrected Velocity.Y (m/s)')
        uz_vals = _safe_floats(segment_samples, 'Corrected Velocity.Z (m/s)')

        ux_mean = (sum(ux_vals) / len(ux_vals)) if ux_vals else None
        uy_mean = (sum(uy_vals) / len(uy_vals)) if uy_vals else None
        uz_mean = (sum(uz_vals) / len(uz_vals)) if uz_vals else None

        ux2_terms: List[float] = []
        uy2_terms: List[float] = []
        uz2_terms: List[float] = []
        uxuz_terms: List[float] = []

        for s in segment_samples:
            ux = merger._parse_float(s.get('Corrected Velocity.X (m/s)'))
            uy = merger._parse_float(s.get('Corrected Velocity.Y (m/s)'))
            uz = merger._parse_float(s.get('Corrected Velocity.Z (m/s)'))

            if ux is not None and ux_mean is not None:
                upx = ux - ux_mean
                s['u_prime_x (m/s)'] = upx
                s['u_prime_x2 (m2/s2)'] = upx * upx
                ux2_terms.append(upx * upx)

            if uy is not None and uy_mean is not None:
                upy = uy - uy_mean
                s['u_prime_y (m/s)'] = upy
                s['u_prime_y2 (m2/s2)'] = upy * upy
                uy2_terms.append(upy * upy)

            if uz is not None and uz_mean is not None:
                upz = uz - uz_mean
                s['u_prime_z (m/s)'] = upz
                s['u_prime_z2 (m2/s2)'] = upz * upz
                uz2_terms.append(upz * upz)

            if ux is not None and ux_mean is not None and uz is not None and uz_mean is not None:
                upx_upz = (ux - ux_mean) * (uz - uz_mean)
                s['u_prime_x_u_prime_z (m2/s2)'] = upx_upz
                uxuz_terms.append(upx_upz)

        var_x = (sum(ux2_terms) / len(ux2_terms)) if ux2_terms else None
        var_y = (sum(uy2_terms) / len(uy2_terms)) if uy2_terms else None
        var_z = (sum(uz2_terms) / len(uz2_terms)) if uz2_terms else None

        if var_x is not None:
            avg_data_dict['TI_x (m/s)'] = math.sqrt(var_x)
        if var_y is not None:
            avg_data_dict['TI_y (m/s)'] = math.sqrt(var_y)
        if var_z is not None:
            avg_data_dict['TI_z (m/s)'] = math.sqrt(var_z)

        if var_x is not None and var_y is not None and var_z is not None:
            avg_data_dict['TKE (m2/s2)'] = 0.5 * (var_x + var_y + var_z)

        cov_ux_uz = (sum(uxuz_terms) / len(uxuz_terms)) if uxuz_terms else None
        if cov_ux_uz is not None:
            avg_data_dict['u_prime_x_u_prime_z_cov (m2/s2)'] = cov_ux_uz

        temp_c = merger._parse_float(avg_data_dict.get('Temperature (C)'))
        if cov_ux_uz is not None and temp_c is not None:
            rho = (
                999.842594
                + 6.793952e-2 * temp_c
                - 9.09529e-3 * (temp_c ** 2)
                + 1.001685e-4 * (temp_c ** 3)
                - 1.120083e-6 * (temp_c ** 4)
                + 6.536332e-9 * (temp_c ** 5)
            )
            avg_data_dict['rho_freshwater (kg/m3)'] = rho
            avg_data_dict['Reynolds tau_xz (Pa)'] = -rho * cov_ux_uz

        return avg_data_dict

    @staticmethod
    def _is_position_usable_for_segmentation(sample: Dict) -> bool:
        """Return True only when VXC quality explicitly marks stationary/usable position."""
        return str(sample.get('vxc_quality', '')).strip().upper() == 'GOOD'

    @staticmethod
    def _sample_beam_average(merger: ADVVXCMerger, sample: Dict, prefix: str) -> Optional[float]:
        values: List[float] = []
        for i in range(1, 4):
            val = merger._parse_float(sample.get(prefix.format(i)))
            if val is not None:
                values.append(val)
        if not values:
            return None
        return sum(values) / len(values)

    def _sample_passes_filter_gates(
        self,
        merger: ADVVXCMerger,
        sample: Dict,
        min_corr_avg_pct: float,
        min_snr_avg_db: float,
    ) -> bool:
        """Apply per-sample correlation/SNR thresholds before filtered averaging."""
        corr_avg = self._sample_beam_average(merger, sample, 'Correlation Score.Beam{} (%)')
        snr_avg = self._sample_beam_average(merger, sample, 'SNR.Beam{} (dB)')
        if corr_avg is None or snr_avg is None:
            return False
        return corr_avg >= min_corr_avg_pct and snr_avg >= min_snr_avg_db

    def run(self):
        """Execute merge operation in background thread.
        
        All output is written exclusively through the active session manager.
        If no session is active the file is skipped to prevent stray output files.
        """
        filename = self.adv_file.name
        try:
            # Guard: require an active session — no standalone file writes
            if not (self.session_manager and self.session_manager.is_active()):
                logger.warning(f"[WORKER] No active session — skipping {filename}")
                self.failed.emit(f"{filename}: No active session (start a session first)")
                return

            logger.info(f"[WORKER] Starting merge for {filename}")
            merger = ADVVXCMerger(tolerance_sec=self.tolerance_sec)

            logger.debug(f"[WORKER] Parsing ADV file: {self.adv_file}")
            merger.parse_adv_csv(str(self.adv_file))

            logger.debug(f"[WORKER] Parsing VXC file: {self.vxc_file}")
            merger.parse_vxc_csv(str(self.vxc_file))

            logger.debug(f"[WORKER] Merging data for {filename}")
            matched, _unmatched, stats = merger.merge()

            logger.debug(f"[WORKER] Building session data for {filename}")
            all_merged = merger.merged_data

            # Segmentation uses stationary/valid VXC position only.
            matched_samples = [
                s for s in all_merged if self._is_position_usable_for_segmentation(s)
            ]

            min_corr_gate = float(self.session_manager.session_config.min_correlation_avg_pct or 0.0)
            min_snr_gate = float(self.session_manager.session_config.min_snr_avg_db or 0.0)

            # Remap merger key names → session schema key names so the raw
            # DictWriter (which expects x_m / y_m / time_delta_ms / timestamp_utc)
            # gets the correct values.  The averaged path does its own remap a
            # few lines below; this closes the same gap for per-sample rows.
            for s in matched_samples:
                s['x_m'] = s.get('vxc_x_m')
                s['y_m'] = s.get('vxc_y_m')
                s['time_delta_ms'] = s.get('vxc_time_delta_ms')
                s['timestamp_utc'] = s.get('UTC time') or s.get('timestamp_utc')

            segments = self._segment_matched_samples(merger, matched_samples)

            # Append per-segment raw + averaged summaries to session files.
            try:
                session_seqs: List[int] = []
                filtered_segments_written = 0
                filtered_samples_total = 0
                if segments:
                    for segment_index, segment_samples in enumerate(segments, start=1):
                        for sample in segment_samples:
                            sample['source_adv_file'] = filename
                            sample['segment_index'] = segment_index

                        avg_data_dict = self._build_segment_average(
                            merger,
                            segment_samples,
                            filename,
                            segment_index,
                            len(segments),
                        )
                        avg_data_dict['status'] = 'OK'

                        filtered_segment_samples = [
                            s for s in segment_samples
                            if self._sample_passes_filter_gates(
                                merger,
                                s,
                                min_corr_gate,
                                min_snr_gate,
                            )
                        ]

                        avg_data_dict['filter_pass_sample_count'] = len(filtered_segment_samples)
                        avg_data_dict['filter_source_sample_count'] = len(segment_samples)

                        filtered_avg_data_dict: Optional[Dict] = None
                        if filtered_segment_samples:
                            filtered_avg_data_dict = self._build_segment_average(
                                merger,
                                [dict(s) for s in filtered_segment_samples],
                                filename,
                                segment_index,
                                len(segments),
                            )
                            filtered_avg_data_dict['status'] = 'OK'
                            filtered_avg_data_dict['filter_pass_sample_count'] = len(filtered_segment_samples)
                            filtered_avg_data_dict['filter_source_sample_count'] = len(segment_samples)
                            filtered_segments_written += 1
                            filtered_samples_total += len(filtered_segment_samples)

                        seq = self.session_manager.append_measurement(
                            segment_samples,
                            avg_data_dict,
                            filtered_avg_data_dict,
                        )
                        session_seqs.append(seq)
                else:
                    empty_avg = {
                        'source_adv_file': filename,
                        'segment_index': 0,
                        'segment_count': 0,
                        'segment_sample_count': 0,
                        'status': 'INVALID',
                    }
                    seq = self.session_manager.append_measurement([], empty_avg, None)
                    session_seqs.append(seq)

                stats['session_measurement_seq_start'] = session_seqs[0]
                stats['session_measurement_seq_end'] = session_seqs[-1]
                stats['session_measurement_count'] = len(session_seqs)
                stats['segment_count'] = len(segments)
                stats['filtered_segments_written'] = filtered_segments_written
                stats['filtered_samples_total'] = filtered_samples_total
                logger.info(
                    f"[WORKER] Appended {len(session_seqs)} segment measurements "
                    f"for {filename} ({len(matched_samples)} usable samples, "
                    f"{filtered_segments_written} filtered segments)"
                )
            except Exception as e:
                logger.error(f"[WORKER] Failed to append to session: {e}")
                self.failed.emit(f"{filename}: session write error — {e}")
                return

            # Archive raw ADV files into session/raw_exports/
            try:
                import shutil
                raw_exports_dir = self.session_manager.session_dir / "raw_exports"
                raw_exports_dir.mkdir(exist_ok=True)
                shutil.copy2(self.adv_file, raw_exports_dir / self.adv_file.name)
                config_file = self.adv_file.with_suffix('.labadv_config')
                if config_file.exists():
                    shutil.copy2(config_file, raw_exports_dir / config_file.name)
                logger.info(f"[WORKER] Archived raw files to {raw_exports_dir}")
            except Exception as archive_err:
                logger.warning(f"[WORKER] Failed to archive raw files: {archive_err}")

            stats["matched"] = matched
            logger.info(f"[WORKER] Merge completed for {filename}, emitting signal")
            self.completed.emit(filename, stats)

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
        
        # Timer 1: Combined file-completion + queue processor (500ms)
        # Handles both pending-file stability checks and merge-queue dispatch
        # in one timer to halve GUI-thread wakeups vs two separate timers.
        self.completion_timer = QTimer()
        self.completion_timer.timeout.connect(self._check_pending_files)
        self.completion_timer.timeout.connect(self._process_merge_queue)
        
        # Timer 2: (alias kept for stop_monitoring compatibility)
        self.queue_timer = self.completion_timer
        
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
        
        # Pre-populate processed_files with all existing CSVs so they are NOT treated as new.
        # Only files that appear AFTER monitoring starts will be processed.
        self.processed_files.clear()
        existing_count = 0
        for existing_file in self.watch_dir.glob("*.csv"):
            if self.is_valid_adv_filename(existing_file.name):
                self.processed_files.add(existing_file)
                existing_count += 1
        logger.info(f"Pre-marked {existing_count} existing ADV CSV files as already processed — only new files will be merged")
        
        # Add watch path
        if str(self.watch_dir) not in self.file_watcher.directories():
            self.file_watcher.addPath(str(self.watch_dir))
        
        # Start all timers
        self.completion_timer.start(500)  # Check pending + process queue every 500ms
        # queue_timer is an alias for completion_timer — no separate start needed
        self.poll_timer.start(int(self.poll_interval * 1000))  # Polling fallback
        self.retry_timer.start(10000)  # Retry every 10s
        self.cleanup_timer.start(300000)  # Cleanup every 5 minutes
        
        self.monitoring_active = True
        logger.info(f"File monitoring started: {self.watch_dir}")
        self.status_update.emit(f"Monitoring active: {self.watch_dir}")
        
        return True
    
    def stop_monitoring(self):
        """Stop file monitoring."""
        # Stop all timers (queue_timer is same object as completion_timer)
        self.completion_timer.stop()
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
        
        The compiled regex already enforces the digit counts for date and time
        components, so a simple match is sufficient — no need to re-parse each
        component manually.
        """
        if not filename or not isinstance(filename, str):
            return False
        return ADV_FILENAME_PATTERN.match(filename) is not None
    
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
        """Remove entries for deleted files from tracking sets to prevent memory growth.

        In session mode no _merged.csv sidecar files are written, so the only
        reliable cleanup signal is the source file being deleted from the ADV
        watch directory.
        """
        to_remove = [fp for fp in self.processed_files if not fp.exists()]

        for filepath in to_remove:
            self.processed_files.discard(filepath)
            self.file_sizes.pop(filepath, None)

        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} deleted file entries from tracking")
    
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
