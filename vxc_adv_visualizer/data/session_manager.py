"""Session Manager - Manages data collection sessions with metadata tracking.

Provides session-based data organization, cumulative file writing, and
automatic metadata generation for research data management.
"""

import csv
import logging
import yaml
import math
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
import threading
from dataclasses import dataclass, field, asdict


logger = logging.getLogger(__name__)


@dataclass
class SessionConfig:
    """Configuration for a data collection session."""
    session_name: str = "Unnamed_Session"
    operator: str = "Unknown"
    notes: str = ""
    scan_type: str = "Manual"  # Manual, Vertical_Line, Horizontal_Line, XY_Grid
    
    # Measurement parameters
    grid_spacing_x_m: Optional[float] = None
    grid_spacing_y_m: Optional[float] = None
    dwell_time_sec: Optional[float] = None
    settling_time_sec: Optional[float] = None
    
    # Scanner parameters
    start_position: Optional[List[float]] = None
    end_position: Optional[List[float]] = None
    point_count_x: Optional[int] = None
    point_count_y: Optional[int] = None
    scan_pattern: str = "raster"  # raster or snake
    
    # Environmental
    water_temperature_c: Optional[float] = None
    flow_conditions: str = ""

    # Per-session filtering thresholds for Filtered_Averages output
    min_correlation_avg_pct: float = 0.0
    min_snr_avg_db: float = 0.0


@dataclass
class SessionStatistics:
    """Statistics tracked during a session."""
    total_measurements: int = 0
    valid_measurements: int = 0
    total_samples: int = 0
    matched_samples: int = 0

    filtered_measurements: int = 0
    filtered_samples: int = 0
    
    mean_correlation: float = 0.0
    mean_snr: float = 0.0
    mean_velocity_x: float = 0.0
    mean_velocity_y: float = 0.0
    mean_velocity_z: float = 0.0


class SessionManager:
    """Manages data collection sessions with metadata and cumulative output.
    
    Features:
    - Session-based folder organization
    - Cumulative CSV files (appending during session)
    - Automatic metadata generation
    - Quality statistics tracking
    - Session event logging
    """
    
    def __init__(self, base_output_dir: str):
        """Initialize session manager.
        
        Args:
            base_output_dir: Base directory for all session data
        """
        self.base_output_dir = Path(base_output_dir)
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        
        self.active_session: Optional[str] = None
        self.session_dir: Optional[Path] = None
        self.session_config = SessionConfig()
        self.session_stats = SessionStatistics()
        
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        
        # File handles for cumulative writing
        self.averaged_file: Optional[Path] = None
        self.filtered_averaged_file: Optional[Path] = None
        self.raw_file: Optional[Path] = None
        self.averaged_writer: Optional[csv.DictWriter] = None
        self.filtered_averaged_writer: Optional[csv.DictWriter] = None
        self.raw_writer: Optional[csv.DictWriter] = None
        self.averaged_handle = None
        self.filtered_averaged_handle = None
        self.raw_handle = None
        
        # Session log
        self.log_file: Optional[Path] = None
        self.log_handle = None
        
        self.lock = threading.Lock()
        self.measurement_seq = 0
        
    def start_session(self, session_config: SessionConfig) -> str:
        """Start a new data collection session.
        
        Args:
            session_config: Configuration for this session
            
        Returns:
            Session ID
            
        Raises:
            RuntimeError: If a session is already active
        """
        with self.lock:
            if self.active_session:
                raise RuntimeError(f"Session already active: {self.active_session}")
            
            # Generate session ID
            now = datetime.now(timezone.utc)
            self.start_time = now
            timestamp = now.strftime('%Y%m%d_%H%M%S')
            
            # Clean session name for filesystem
            clean_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' 
                                for c in session_config.session_name)
            
            self.active_session = f"session_{timestamp}_{clean_name}"
            self.session_config = session_config
            self.session_stats = SessionStatistics()
            self.measurement_seq = 0
            
            # Create session directory structure
            self.session_dir = self.base_output_dir / "sessions" / self.active_session
            self.session_dir.mkdir(parents=True, exist_ok=True)
            (self.session_dir / "raw_exports").mkdir(exist_ok=True)
            (self.session_dir / "plots").mkdir(exist_ok=True)
            
            # Initialize cumulative files
            self._init_cumulative_files()
            
            # Start session log
            self._init_session_log()
            self._log_event("SESSION_START", f"Started session: {session_config.session_name}")
            
            logger.info(f"Started session: {self.active_session}")
            return self.active_session
    
    def _init_cumulative_files(self):
        """Initialize cumulative CSV files for the session.
        
        Files are opened in append mode so that data is never lost on crash.
        Headers are written only when the file is empty (new session or first open).
        """
        # Master averaged file — one row per measurement position
        self.averaged_file = self.session_dir / "master_averaged.csv"
        self.averaged_handle = open(self.averaged_file, 'a', newline='', encoding='utf-8')
        
        avg_fieldnames = [
            'session_id', 'measurement_seq', 'timestamp_utc', 'x_m', 'y_m',
            'source_adv_file', 'segment_index', 'segment_count',
            'segment_start_utc', 'segment_end_utc',
            'segment_sample_count', 'segment_anchor_x_m', 'segment_anchor_y_m',
            'sample_count', 'quality_flag', 'elapsed_time_sec',
            'Raw Velocity.X (m/s)', 'Raw Velocity.Y (m/s)', 'Raw Velocity.Z (m/s)',
            'Corrected Velocity.X (m/s)', 'Corrected Velocity.Y (m/s)', 'Corrected Velocity.Z (m/s)',
            'Correlation.Avg (%)', 'SNR.Avg (dB)',
            'Temperature (C)', 'Raw Pressure (dbar)', 'Gauge Pressure (dbar)', 'Voltage (V)',
            'TI_x (m/s)', 'TI_y (m/s)', 'TI_z (m/s)',
            'TKE (m2/s2)', 'u_prime_x_u_prime_z_cov (m2/s2)',
            'rho_freshwater (kg/m3)', 'Reynolds tau_xz (Pa)'
        ]
        
        self.averaged_writer = csv.DictWriter(self.averaged_handle, fieldnames=avg_fieldnames,
                                              extrasaction='ignore')
        if self.averaged_handle.tell() == 0:  # Write header only for new / empty file
            self.averaged_writer.writeheader()
        self.averaged_handle.flush()

        # Filtered averaged file — one row per segment after threshold gates
        self.filtered_averaged_file = self.session_dir / "Filtered_Averages.csv"
        self.filtered_averaged_handle = open(self.filtered_averaged_file, 'a', newline='', encoding='utf-8')

        filtered_avg_fieldnames = avg_fieldnames + [
            'filter_min_correlation_avg_pct',
            'filter_min_snr_avg_db',
            'filter_pass_sample_count',
            'filter_source_sample_count',
        ]

        self.filtered_averaged_writer = csv.DictWriter(
            self.filtered_averaged_handle,
            fieldnames=filtered_avg_fieldnames,
            extrasaction='ignore',
        )
        if self.filtered_averaged_handle.tell() == 0:
            self.filtered_averaged_writer.writeheader()
        self.filtered_averaged_handle.flush()
        
        # Master merged file — one row per matched ADV sample (~10 Hz)
        self.raw_file = self.session_dir / "master_merged.csv"
        self.raw_handle = open(self.raw_file, 'a', newline='', encoding='utf-8')
        
        raw_fieldnames = [
            'session_id', 'measurement_seq', 'sample_seq', 'timestamp_utc',
            'source_adv_file', 'segment_index',
            'x_m', 'y_m', 'vxc_quality', 'time_delta_ms',
            'Corrected Velocity.X (m/s)', 'Corrected Velocity.Y (m/s)', 'Corrected Velocity.Z (m/s)',
            'u_prime_x (m/s)', 'u_prime_y (m/s)', 'u_prime_z (m/s)',
            'u_prime_x2 (m2/s2)', 'u_prime_y2 (m2/s2)', 'u_prime_z2 (m2/s2)',
            'u_prime_x_u_prime_z (m2/s2)',
            'Correlation Score.Beam1 (%)', 'Correlation Score.Beam2 (%)', 'Correlation Score.Beam3 (%)',
            'SNR.Beam1 (dB)', 'SNR.Beam2 (dB)', 'SNR.Beam3 (dB)',
            'Temperature (°C)', 'Raw Pressure (dbar)', 'Corrected Pressure (dbar)', 'Depth (m)', 'Voltage (V)'
        ]
        
        self.raw_writer = csv.DictWriter(self.raw_handle, fieldnames=raw_fieldnames, extrasaction='ignore')
        if self.raw_handle.tell() == 0:  # Write header only for new / empty file
            self.raw_writer.writeheader()
        self.raw_handle.flush()
        
        logger.info(
            "Initialized cumulative files: "
            f"{self.averaged_file.name}, {self.filtered_averaged_file.name}, {self.raw_file.name}"
        )
    
    def _init_session_log(self):
        """Initialize session event log."""
        self.log_file = self.session_dir / "session_log.txt"
        self.log_handle = open(self.log_file, 'w', encoding='utf-8')
        
        header = f"""
{'='*80}
VXC/ADV DATA COLLECTION SESSION LOG
{'='*80}
Session: {self.active_session}
Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}
Operator: {self.session_config.operator}
Scan Type: {self.session_config.scan_type}
{'='*80}

"""
        self.log_handle.write(header)
        self.log_handle.flush()
    
    def _log_event(self, event_type: str, message: str):
        """Log an event to session log.
        
        Args:
            event_type: Type of event (e.g., MEASUREMENT, ERROR, INFO)
            message: Event message
        """
        if self.log_handle:
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            log_line = f"[{timestamp}] {event_type:15s} | {message}\n"
            self.log_handle.write(log_line)
            self.log_handle.flush()
    
    def append_measurement(
        self,
        merged_data: List[Dict],
        averaged_data: Dict,
        filtered_averaged_data: Optional[Dict] = None,
    ) -> int:
        """Append measurement data to cumulative files.
        
        Args:
            merged_data: List of sample-level merged records
            averaged_data: Averaged grid point data
            filtered_averaged_data: Threshold-gated averaged row for Filtered_Averages.csv
            
        Returns:
            Measurement sequence number
            
        Raises:
            RuntimeError: If no active session
        """
        with self.lock:
            if not self.active_session:
                raise RuntimeError("No active session")
            
            self.measurement_seq += 1
            current_seq = self.measurement_seq
            
            # Calculate elapsed time
            elapsed_sec = (datetime.now(timezone.utc) - self.start_time).total_seconds()

            full_quality_flag = 'OK' if averaged_data.get('status') == 'OK' else averaged_data.get('status', 'INVALID')
            
            # Write averaged data
            if averaged_data and self.averaged_writer:
                avg_row = {
                    'session_id': self.active_session,
                    'measurement_seq': current_seq,
                    'timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    'elapsed_time_sec': f"{elapsed_sec:.1f}",
                    'quality_flag': full_quality_flag,
                    **averaged_data
                }
                self.averaged_writer.writerow(avg_row)
                self.averaged_handle.flush()

            # Write threshold-filtered averaged data (parallel output)
            if filtered_averaged_data and self.filtered_averaged_writer:
                filtered_row = {
                    'session_id': self.active_session,
                    'measurement_seq': current_seq,
                    'timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    'elapsed_time_sec': f"{elapsed_sec:.1f}",
                    'quality_flag': 'FILTER_PASS',
                    'filter_min_correlation_avg_pct': self.session_config.min_correlation_avg_pct,
                    'filter_min_snr_avg_db': self.session_config.min_snr_avg_db,
                    **filtered_averaged_data,
                }
                self.filtered_averaged_writer.writerow(filtered_row)
                self.filtered_averaged_handle.flush()
            
            # Write raw data
            if merged_data and self.raw_writer:
                for sample_seq, sample in enumerate(merged_data, start=1):
                    raw_row = {
                        'session_id': self.active_session,
                        'measurement_seq': current_seq,
                        'sample_seq': sample_seq,
                        **sample
                    }
                    self.raw_writer.writerow(raw_row)
                
                self.raw_handle.flush()  # Single flush after all rows for this measurement
            
            # Update statistics
            self._update_statistics(merged_data, averaged_data, filtered_averaged_data)
            
            # Log event
            x_m = averaged_data.get('x_m', ' N/A')
            y_m = averaged_data.get('y_m', 'N/A')
            sample_count = averaged_data.get('sample_count', 0)
            filtered_samples = 0
            if filtered_averaged_data:
                try:
                    filtered_samples = int(filtered_averaged_data.get('sample_count', 0))
                except (TypeError, ValueError):
                    filtered_samples = 0
            self._log_event(
                "MEASUREMENT",
                f"Seq {current_seq}: Position ({x_m}, {y_m}), "
                f"Samples: {sample_count}, Filtered Samples: {filtered_samples}",
            )
            
            logger.info(f"Appended measurement {current_seq} to session {self.active_session}")
            return current_seq
    
    def _update_statistics(
        self,
        merged_data: List[Dict],
        averaged_data: Dict,
        filtered_averaged_data: Optional[Dict],
    ):
        """Update session statistics.
        
        Args:
            merged_data: Raw merged data
            averaged_data: Averaged data point
            filtered_averaged_data: Threshold-gated averaged data point
        """
        self.session_stats.total_measurements += 1
        
        if averaged_data.get('status') == 'OK':
            self.session_stats.valid_measurements += 1

        if filtered_averaged_data and filtered_averaged_data.get('status') == 'OK':
            self.session_stats.filtered_measurements += 1
            try:
                self.session_stats.filtered_samples += int(filtered_averaged_data.get('sample_count', 0))
            except (TypeError, ValueError):
                pass
        
        # Count samples
        if merged_data:
            self.session_stats.total_samples += len(merged_data)
            matched = sum(1 for s in merged_data if str(s.get('vxc_quality', '')).upper() == 'GOOD')
            self.session_stats.matched_samples += matched
    
    def stop_session(self) -> Dict[str, Any]:
        """Stop the current session and generate final metadata.
        
        Returns:
            Session summary dictionary
            
        Raises:
            RuntimeError: If no active session
        """
        with self.lock:
            if not self.active_session:
                raise RuntimeError("No active session to stop")
            
            self.end_time = datetime.now(timezone.utc)
            duration_sec = (self.end_time - self.start_time).total_seconds()
            
            # Close cumulative files
            if self.averaged_handle:
                self.averaged_handle.close()
                self.averaged_handle = None
                self.averaged_writer = None

            if self.filtered_averaged_handle:
                self.filtered_averaged_handle.close()
                self.filtered_averaged_handle = None
                self.filtered_averaged_writer = None
            
            if self.raw_handle:
                self.raw_handle.close()
                self.raw_handle = None
                self.raw_writer = None
            
            # Log session end
            self._log_event("SESSION_END", f"Duration: {duration_sec/60:.1f} minutes")
            
            if self.log_handle:
                self.log_handle.close()
                self.log_handle = None
            
            # Generate metadata
            metadata = self._generate_metadata(duration_sec)
            self._write_metadata(metadata)
            
            # Generate README
            self._generate_readme(metadata)
            
            # Generate experiment index entry
            self._update_experiment_index(metadata)
            
            logger.info(f"Stopped session: {self.active_session} (duration: {duration_sec/60:.1f} min)")
            
            session_id = self.active_session
            self.active_session = None
            
            return {'session_id': session_id, 'metadata': metadata}
    
    def _generate_metadata(self, duration_sec: float) -> Dict[str, Any]:
        """Generate metadata dictionary for the session.
        
        Args:
            duration_sec: Session duration in seconds
            
        Returns:
            Metadata dictionary
        """
        # Calculate match rate
        match_rate = 0.0
        if self.session_stats.total_samples > 0:
            match_rate = (self.session_stats.matched_samples / self.session_stats.total_samples) * 100

        filtered_measurement_rate = 0.0
        if self.session_stats.valid_measurements > 0:
            filtered_measurement_rate = (
                self.session_stats.filtered_measurements / self.session_stats.valid_measurements
            ) * 100

        filtered_sample_rate = 0.0
        if self.session_stats.total_samples > 0:
            filtered_sample_rate = (
                self.session_stats.filtered_samples / self.session_stats.total_samples
            ) * 100
        
        metadata = {
            'session_info': {
                'session_id': self.active_session,
                'session_name': self.session_config.session_name,
                'start_time_utc': self.start_time.strftime('%Y-%m-%d %H:%M:%S'),
                'end_time_utc': self.end_time.strftime('%Y-%m-%d %H:%M:%S'),
                'duration_minutes': round(duration_sec / 60, 2),
                'operator': self.session_config.operator,
                'notes': self.session_config.notes,
            },
            'experiment_parameters': {
                'scan_type': self.session_config.scan_type,
                'grid_spacing_x_m': self.session_config.grid_spacing_x_m,
                'grid_spacing_y_m': self.session_config.grid_spacing_y_m,
                'dwell_time_sec': self.session_config.dwell_time_sec,
                'settling_time_sec': self.session_config.settling_time_sec,
                'min_correlation_avg_pct': self.session_config.min_correlation_avg_pct,
                'min_snr_avg_db': self.session_config.min_snr_avg_db,
            },
            'measurement_plan': {
                'start_position': self.session_config.start_position,
                'end_position': self.session_config.end_position,
                'point_count_x': self.session_config.point_count_x,
                'point_count_y': self.session_config.point_count_y,
                'scan_pattern': self.session_config.scan_pattern,
            },
            'environmental_conditions': {
                'water_temperature_c': self.session_config.water_temperature_c,
                'flow_conditions': self.session_config.flow_conditions,
            },
            'statistics': {
                'total_measurements': self.session_stats.total_measurements,
                'valid_measurements': self.session_stats.valid_measurements,
                'total_samples': self.session_stats.total_samples,
                'matched_samples': self.session_stats.matched_samples,
                'match_rate_percent': round(match_rate, 2),
            },
            'filter_summary': {
                'min_correlation_avg_pct': self.session_config.min_correlation_avg_pct,
                'min_snr_avg_db': self.session_config.min_snr_avg_db,
                'filtered_measurements': self.session_stats.filtered_measurements,
                'filtered_samples': self.session_stats.filtered_samples,
                'filtered_measurement_rate_percent': round(filtered_measurement_rate, 2),
                'filtered_sample_rate_percent': round(filtered_sample_rate, 2),
            },
            'turbulence_summary': self._compute_turbulence_summary(),
            'segment_integrity': self._compute_segment_integrity_summary(),
            'data_files': {
                'master_averaged': str(self.averaged_file.name) if self.averaged_file else None,
                'filtered_averages': str(self.filtered_averaged_file.name) if self.filtered_averaged_file else None,
                'master_merged': str(self.raw_file.name) if self.raw_file else None,
                'session_log': str(self.log_file.name) if self.log_file else None,
                'session_dir': str(self.session_dir),
            },
            'software': {
                'application': 'VXC/ADV Visualizer',
                'version': '1.0.0',
                'python_version': '3.11+',
            }
        }
        
        return metadata

    def _safe_float(self, value: Any) -> Optional[float]:
        """Parse a scalar value into finite float, returning None on invalid input."""
        try:
            if value is None:
                return None
            if isinstance(value, str) and not value.strip():
                return None
            parsed = float(value)
            if math.isnan(parsed) or math.isinf(parsed):
                return None
            return parsed
        except (TypeError, ValueError):
            return None

    def _safe_int(self, value: Any) -> Optional[int]:
        """Parse integer-like values while tolerating empty strings and floats."""
        try:
            if value is None:
                return None
            if isinstance(value, str) and not value.strip():
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _metric_summary(self, values: List[float]) -> Dict[str, Optional[float]]:
        """Return count/mean/min/max for a numeric list."""
        if not values:
            return {
                'count': 0,
                'mean': None,
                'min': None,
                'max': None,
            }

        return {
            'count': len(values),
            'mean': round(sum(values) / len(values), 9),
            'min': round(min(values), 9),
            'max': round(max(values), 9),
        }

    def _compute_turbulence_summary(self) -> Dict[str, Any]:
        """Compute per-session turbulence summary stats from master_averaged rows."""
        summary: Dict[str, Any] = {
            'rows_with_turbulence': 0,
            'TI_x (m/s)': self._metric_summary([]),
            'TI_y (m/s)': self._metric_summary([]),
            'TI_z (m/s)': self._metric_summary([]),
            'TKE (m2/s2)': self._metric_summary([]),
            'u_prime_x_u_prime_z_cov (m2/s2)': self._metric_summary([]),
            'Reynolds tau_xz (Pa)': self._metric_summary([]),
        }

        if not self.averaged_file or not self.averaged_file.exists():
            return summary

        ti_x_vals: List[float] = []
        ti_y_vals: List[float] = []
        ti_z_vals: List[float] = []
        tke_vals: List[float] = []
        cov_vals: List[float] = []
        tau_vals: List[float] = []

        try:
            with open(self.averaged_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tix = self._safe_float(row.get('TI_x (m/s)'))
                    tiy = self._safe_float(row.get('TI_y (m/s)'))
                    tiz = self._safe_float(row.get('TI_z (m/s)'))
                    tke = self._safe_float(row.get('TKE (m2/s2)'))
                    cov = self._safe_float(row.get('u_prime_x_u_prime_z_cov (m2/s2)'))
                    tau = self._safe_float(row.get('Reynolds tau_xz (Pa)'))

                    if tix is not None:
                        ti_x_vals.append(tix)
                    if tiy is not None:
                        ti_y_vals.append(tiy)
                    if tiz is not None:
                        ti_z_vals.append(tiz)
                    if tke is not None:
                        tke_vals.append(tke)
                    if cov is not None:
                        cov_vals.append(cov)
                    if tau is not None:
                        tau_vals.append(tau)

                    if any(v is not None for v in (tix, tiy, tiz, tke, cov, tau)):
                        summary['rows_with_turbulence'] += 1
        except Exception as e:
            logger.warning(f"Failed to compute turbulence summary: {e}")
            return summary

        summary['TI_x (m/s)'] = self._metric_summary(ti_x_vals)
        summary['TI_y (m/s)'] = self._metric_summary(ti_y_vals)
        summary['TI_z (m/s)'] = self._metric_summary(ti_z_vals)
        summary['TKE (m2/s2)'] = self._metric_summary(tke_vals)
        summary['u_prime_x_u_prime_z_cov (m2/s2)'] = self._metric_summary(cov_vals)
        summary['Reynolds tau_xz (Pa)'] = self._metric_summary(tau_vals)
        return summary

    def _compute_segment_integrity_summary(self) -> Dict[str, Any]:
        """Compute audit counters linking raw matched rows to segment-level averaged rows."""
        summary: Dict[str, Any] = {
            'segment_rows': 0,
            'segment_samples_total': 0,
            'matched_samples_total': self.session_stats.matched_samples,
            'sample_accounting_match': False,
            'files_with_segments': 0,
        }

        if not self.averaged_file or not self.averaged_file.exists():
            return summary

        source_files: set = set()
        try:
            with open(self.averaged_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    segment_index = self._safe_int(row.get('segment_index'))
                    if segment_index is None or segment_index <= 0:
                        continue

                    summary['segment_rows'] += 1

                    segment_samples = self._safe_int(row.get('segment_sample_count'))
                    if segment_samples is None:
                        segment_samples = self._safe_int(row.get('sample_count'))
                    if segment_samples is not None:
                        summary['segment_samples_total'] += segment_samples

                    src = row.get('source_adv_file')
                    if src:
                        source_files.add(src)

            summary['files_with_segments'] = len(source_files)
            summary['sample_accounting_match'] = (
                summary['segment_samples_total'] == summary['matched_samples_total']
            )
        except Exception as e:
            logger.warning(f"Failed to compute segment integrity summary: {e}")

        return summary
    
    def _write_metadata(self, metadata: Dict[str, Any]):
        """Write metadata to YAML file.
        
        Args:
            metadata: Metadata dictionary
        """
        metadata_file = self.session_dir / "metadata.yaml"
        
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)
            
            logger.info(f"Wrote metadata: {metadata_file}")
        except Exception as e:
            logger.error(f"Failed to write metadata: {e}")
    
    def _generate_readme(self, metadata: Dict[str, Any]):
        """Generate human-readable README for the session.
        
        Args:
            metadata: Session metadata
        """
        readme_file = self.session_dir / "README.txt"
        
        session_info = metadata['session_info']
        stats = metadata['statistics']
        filter_summary = metadata.get('filter_summary', {})
        params = metadata['experiment_parameters']
        turbulence = metadata.get('turbulence_summary', {})
        segment_integrity = metadata.get('segment_integrity', {})
        
        readme_content = f"""
{'='*80}
SESSION: {session_info['session_name']}
{'='*80}

DATE: {session_info['start_time_utc']} UTC
OPERATOR: {session_info['operator']}
DURATION: {session_info['duration_minutes']} minutes

DESCRIPTION:
{session_info['notes']}

MEASUREMENT PARAMETERS:
- Scan Type: {params['scan_type']}
- Grid Spacing: {params['grid_spacing_x_m']}m x {params['grid_spacing_y_m']}m
- Dwell Time: {params['dwell_time_sec']} seconds per point
- Settling Time: {params['settling_time_sec']} seconds

DATA FILES:
- master_averaged.csv: {stats['valid_measurements']} positions with per-position averaged velocities
- Filtered_Averages.csv: {filter_summary.get('filtered_measurements', 0)} threshold-passing positions
- master_merged.csv: {stats['matched_samples']} matched ADV samples (~10 Hz, VXC position attached)
- metadata.yaml: Complete experiment parameters in YAML format
- session_log.txt: Detailed event log

FILTER SUMMARY:
- Total Measurements: {stats['total_measurements']}
- Valid Measurements: {stats['valid_measurements']} ({stats['valid_measurements'] / max(stats['total_measurements'], 1) * 100:.1f}%)
- Sample Match Rate: {stats['match_rate_percent']}%
- Correlation Gate: >= {filter_summary.get('min_correlation_avg_pct', params.get('min_correlation_avg_pct', 0.0))}
- SNR Gate: >= {filter_summary.get('min_snr_avg_db', params.get('min_snr_avg_db', 0.0))}
- Filtered Measurements: {filter_summary.get('filtered_measurements', 0)} ({filter_summary.get('filtered_measurement_rate_percent', 0.0)}%)
- Filtered Samples: {filter_summary.get('filtered_samples', 0)} ({filter_summary.get('filtered_sample_rate_percent', 0.0)}%)

TURBULENCE SUMMARY:
- Rows with turbulence values: {turbulence.get('rows_with_turbulence', 0)}
- TI_x mean: {turbulence.get('TI_x (m/s)', {}).get('mean', 'N/A')} m/s
- TI_y mean: {turbulence.get('TI_y (m/s)', {}).get('mean', 'N/A')} m/s
- TI_z mean: {turbulence.get('TI_z (m/s)', {}).get('mean', 'N/A')} m/s
- TKE mean: {turbulence.get('TKE (m2/s2)', {}).get('mean', 'N/A')} m2/s2
- Tau_xz mean: {turbulence.get('Reynolds tau_xz (Pa)', {}).get('mean', 'N/A')} Pa

SEGMENT INTEGRITY:
- Segment rows: {segment_integrity.get('segment_rows', 0)}
- Files with segments: {segment_integrity.get('files_with_segments', 0)}
- Segment samples total: {segment_integrity.get('segment_samples_total', 0)}
- Matched samples total: {segment_integrity.get('matched_samples_total', 0)}
- Sample accounting match: {segment_integrity.get('sample_accounting_match', False)}

SOFTWARE:
{metadata['software']['application']} v{metadata['software']['version']}

{'='*80}
"""
        
        try:
            with open(readme_file, 'w', encoding='utf-8') as f:
                f.write(readme_content.strip())
            
            logger.info(f"Generated README: {readme_file}")
        except Exception as e:
            logger.error(f"Failed to write README: {e}")
    
    def _update_experiment_index(self, metadata: Dict[str, Any]):
        """Update the master experiment index file.
        
        Args:
            metadata: Session metadata
        """
        index_file = self.base_output_dir / "sessions" / "experiment_index.csv"

        fieldnames = [
            'session_id', 'session_name', 'date', 'start_time', 'end_time', 'operator',
            'scan_type', 'point_count', 'valid_measurements', 'duration_min',
            'min_correlation_avg_pct', 'min_snr_avg_db',
            'filtered_measurements', 'filtered_samples', 'filtered_measurement_rate',
            'total_samples', 'matched_samples', 'match_rate', 'output_path', 'notes',
        ]

        try:
            # Schema migration: if the file exists with a different schema, rewrite it
            # with the new headers, preserving old rows (new columns get empty string).
            if index_file.exists():
                with open(index_file, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    if list(reader.fieldnames or []) != fieldnames:
                        old_rows = list(reader)
                        with open(index_file, 'w', newline='', encoding='utf-8') as fw:
                            writer = csv.DictWriter(fw, fieldnames=fieldnames, extrasaction='ignore')
                            writer.writeheader()
                            for row in old_rows:
                                writer.writerow({k: row.get(k, '') for k in fieldnames})

            file_exists = index_file.exists()

            session_info = metadata['session_info']
            stats = metadata['statistics']
            params = metadata['experiment_parameters']
            filter_summary = metadata.get('filter_summary', {})
            data_files = metadata.get('data_files', {})

            with open(index_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                if not file_exists:
                    writer.writeheader()

                writer.writerow({
                    'session_id': session_info['session_id'],
                    'session_name': session_info['session_name'],
                    'date': session_info['start_time_utc'][:10],
                    'start_time': session_info['start_time_utc'],
                    'end_time': session_info.get('end_time_utc', ''),
                    'operator': session_info['operator'],
                    'scan_type': params['scan_type'],
                    'point_count': stats['total_measurements'],
                    'valid_measurements': stats['valid_measurements'],
                    'duration_min': session_info['duration_minutes'],
                    'min_correlation_avg_pct': params.get('min_correlation_avg_pct', 0.0),
                    'min_snr_avg_db': params.get('min_snr_avg_db', 0.0),
                    'filtered_measurements': filter_summary.get('filtered_measurements', 0),
                    'filtered_samples': filter_summary.get('filtered_samples', 0),
                    'filtered_measurement_rate': filter_summary.get('filtered_measurement_rate_percent', 0.0),
                    'total_samples': stats['total_samples'],
                    'matched_samples': stats['matched_samples'],
                    'match_rate': stats['match_rate_percent'],
                    'output_path': data_files.get('session_dir', ''),
                    'notes': session_info['notes'],
                })

            logger.info(f"Updated experiment index: {index_file}")
        except Exception as e:
            logger.error(f"Failed to update experiment index: {e}")
    
    def update_session_config(self, **kwargs):
        """Update session configuration fields during active session.
        
        Allows updating fields like notes, operator, etc. during data collection.
        Updates are immediately written to metadata.yaml file.
        
        Args:
            **kwargs: Fields to update (e.g., notes="New notes", operator="John")
            
        Raises:
            RuntimeError: If no session is active
        """
        with self.lock:
            if not self.active_session:
                raise RuntimeError("No active session to update")
            
            # Update session_config fields
            for key, value in kwargs.items():
                if hasattr(self.session_config, key):
                    setattr(self.session_config, key, value)
                    logger.info(f"Updated session config: {key} = {value}")
            
            # Write updated metadata immediately
            self._write_live_metadata()
            
    def _write_live_metadata(self):
        """Write current session metadata during active session (partial metadata).
        
        This writes a snapshot of current metadata while session is still running.
        """
        if not self.active_session or not self.session_dir:
            return
        
        metadata_file = self.session_dir / "metadata.yaml"
        
        # Calculate current duration
        if self.start_time:
            duration_sec = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        else:
            duration_sec = 0
        
        # Build partial metadata
        metadata = {
            'session_info': {
                'session_id': self.active_session,
                'session_name': self.session_config.session_name,
                'start_time_utc': self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else None,
                'status': 'ACTIVE',
                'duration_minutes': round(duration_sec / 60, 2),
                'operator': self.session_config.operator,
                'notes': self.session_config.notes,
            },
            'experiment_parameters': {
                'scan_type': self.session_config.scan_type,
                'grid_spacing_x_m': self.session_config.grid_spacing_x_m,
                'grid_spacing_y_m': self.session_config.grid_spacing_y_m,
                'dwell_time_sec': self.session_config.dwell_time_sec,
                'settling_time_sec': self.session_config.settling_time_sec,
                'min_correlation_avg_pct': self.session_config.min_correlation_avg_pct,
                'min_snr_avg_db': self.session_config.min_snr_avg_db,
            },
            'statistics': {
                'total_measurements': self.session_stats.total_measurements,
                'total_samples': self.session_stats.total_samples,
                'filtered_measurements': self.session_stats.filtered_measurements,
                'filtered_samples': self.session_stats.filtered_samples,
            }
        }
        
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)
            logger.debug(f"Updated live metadata: {metadata_file}")
        except Exception as e:
            logger.error(f"Failed to write live metadata: {e}")
    
    def is_active(self) -> bool:
        """Check if a session is currently active."""
        return self.active_session is not None
    
    def get_session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self.active_session
    
    def get_measurement_count(self) -> int:
        """Get number of measurements in current session."""
        return self.measurement_seq
