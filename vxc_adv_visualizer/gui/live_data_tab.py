"""Live Data tab for displaying averaged velocity vectors on a 2D plane."""

import csv
import logging
import math
from pathlib import Path
from typing import Optional, Tuple, List

import numpy as np
import yaml
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib import cm
from matplotlib.colors import Normalize
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QGroupBox, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

logger = logging.getLogger(__name__)


class LiveDataTab(QWidget):
    """Live Data tab showing normalized velocity vectors for averaged data."""

    STEPS_PER_INCH = 4000.0
    METERS_PER_FOOT = 0.3048
    PLANE_X_STEPS = (0, 165654)  # Positive X axis: 0 to ~1.0519m
    PLANE_Y_STEPS = (0, 57651)   # Positive Y axis: 0 to ~0.3661m

    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_avg_file: Optional[str] = None
        self.last_stats: Optional[dict] = None
        self.colorbar = None
        self._cached_rows: List[dict] = []  # In-memory cache — avoids re-reading CSV on every position update
        self.current_position_m: Optional[Tuple[float, float]] = None
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Top info bar
        info_bar = QFrame()
        info_bar.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(12, 6, 12, 6)

        # File info
        self.file_label = QLabel("Last file: (none)")
        self.file_label.setStyleSheet("color: #495057; font-weight: 500;")
        info_layout.addWidget(self.file_label)

        info_layout.addSpacing(20)

        # Points counter
        self.points_label = QLabel("Valid points: 0/0")
        self.points_label.setStyleSheet("color: #495057; font-weight: 500;")
        info_layout.addWidget(self.points_label)

        info_layout.addStretch()

        # Refresh button
        refresh_btn = QPushButton("↻ Reload")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:pressed {
                background-color: #004085;
            }
        """)
        refresh_btn.clicked.connect(self._reload_last_file)
        info_layout.addWidget(refresh_btn)

        main_layout.addWidget(info_bar)

        # Main content: Split layout (70% plot, 30% stats)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)

        # Left: Plot area (70% width)
        plot_frame = QFrame()
        plot_frame.setFrameShape(QFrame.StyledPanel)
        plot_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 4px;
            }
        """)
        
        plot_layout = QVBoxLayout(plot_frame)
        plot_layout.setContentsMargins(8, 8, 8, 8)

        self.figure = Figure(figsize=(8, 6), dpi=100, constrained_layout=True)
        self.figure.patch.set_facecolor('white')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.figure.add_subplot(111)
        self._draw_placeholder("No data loaded")
        plot_layout.addWidget(self.canvas)

        content_layout.addWidget(plot_frame, 7)  # 70% weight

        # Right: Stats panel (30% width)
        self.stats_panel = QFrame()
        self.stats_panel.setFrameShape(QFrame.StyledPanel)
        self.stats_panel.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
            }
        """)
        self.stats_panel.setMinimumWidth(280)
        self.stats_panel.setMaximumWidth(350)
        
        stats_layout = QVBoxLayout(self.stats_panel)
        stats_layout.setContentsMargins(12, 12, 12, 12)
        stats_layout.setSpacing(8)

        # Stats title
        stats_title = QLabel("Latest Location Data")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        stats_title.setFont(title_font)
        stats_title.setStyleSheet("color: #212529; padding-bottom: 8px;")
        stats_layout.addWidget(stats_title)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #dee2e6;")
        stats_layout.addWidget(separator)

        # Position display
        self.position_label = QLabel("X: -- m\nY: -- m")
        self.position_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 11pt;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 8px;
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 3px;
            }
        """)
        stats_layout.addWidget(self.position_label)

        # Velocity section
        vel_label = QLabel("Averaged Velocities")
        vel_font = QFont()
        vel_font.setPointSize(10)
        vel_font.setBold(True)
        vel_label.setFont(vel_font)
        vel_label.setStyleSheet("color: #212529; padding-top: 8px;")
        stats_layout.addWidget(vel_label)

        self.velocity_label = QLabel("X: -- m/s\nY: -- m/s\nZ: -- m/s")
        self.velocity_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 11pt;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 8px;
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 3px;
            }
        """)
        stats_layout.addWidget(self.velocity_label)

        # Magnitude
        mag_label = QLabel("Magnitude")
        mag_label.setFont(vel_font)
        mag_label.setStyleSheet("color: #212529; padding-top: 8px;")
        stats_layout.addWidget(mag_label)

        self.magnitude_label = QLabel("-- m/s")
        self.magnitude_label.setStyleSheet("""
            QLabel {
                color: #007bff;
                font-size: 14pt;
                font-weight: bold;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 12px;
                background-color: white;
                border: 2px solid #007bff;
                border-radius: 4px;
                qproperty-alignment: AlignCenter;
            }
        """)
        stats_layout.addWidget(self.magnitude_label)

        # Sample count
        self.sample_label = QLabel("Samples: --")
        self.sample_label.setStyleSheet("""
            QLabel {
                color: #6c757d;
                font-size: 9pt;
                padding-top: 8px;
                qproperty-alignment: AlignCenter;
            }
        """)
        stats_layout.addWidget(self.sample_label)

        # Correlation section
        corr_label = QLabel("Correlation Scores")
        corr_label.setFont(vel_font)
        corr_label.setStyleSheet("color: #212529; padding-top: 8px;")
        stats_layout.addWidget(corr_label)

        self.correlation_label = QLabel("Avg: -- %")
        self.correlation_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 10pt;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 8px;
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 3px;
            }
        """)
        stats_layout.addWidget(self.correlation_label)

        # SNR section
        snr_label = QLabel("Signal-to-Noise Ratio")
        snr_label.setFont(vel_font)
        snr_label.setStyleSheet("color: #212529; padding-top: 8px;")
        stats_layout.addWidget(snr_label)

        self.snr_label = QLabel("Avg: -- dB")
        self.snr_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 10pt;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 8px;
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 3px;
            }
        """)
        stats_layout.addWidget(self.snr_label)

        # Pressure section
        pressure_label = QLabel("Pressure")
        pressure_label.setFont(vel_font)
        pressure_label.setStyleSheet("color: #212529; padding-top: 8px;")
        stats_layout.addWidget(pressure_label)

        self.pressure_label = QLabel("Raw:   -- dbar\nGauge: -- dbar")
        self.pressure_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 10pt;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 8px;
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 3px;
            }
        """)
        stats_layout.addWidget(self.pressure_label)

        # Status indicator
        self.status_label = QLabel("● Waiting for data")
        self.status_label.setStyleSheet("color: #6c757d; font-size: 9pt; padding-top: 4px;")
        stats_layout.addWidget(self.status_label)

        stats_layout.addStretch()

        content_layout.addWidget(self.stats_panel, 3)  # 30% weight

        main_layout.addLayout(content_layout)

        self.setLayout(main_layout)

    def update_from_avg_file(self, avg_file: str, stats: Optional[dict] = None):
        """Load and display averaged data from a CSV file."""
        self.last_avg_file = avg_file
        self.last_stats = stats or {}
        self._reload_last_file()

    def _reload_last_file(self):
        if not self.last_avg_file:
            self._draw_placeholder("No data loaded")
            return

        # Always show plane view
        avg_path = Path(self.last_avg_file)
        if not avg_path.exists():
            self._draw_placeholder("Averaged file not found")
            return

        rows = self._load_avg_rows(avg_path)
        if not rows:
            self._draw_placeholder("No valid data to display")
            return

        self._cached_rows = rows  # Update in-memory cache
        self._plot_vectors(rows)
        
        # Update stats panel with the MOST RECENT data point (last row)
        if rows:
            last_point = rows[-1]  # Get the most recent measurement
            self._update_stats_panel(last_point)
            
            # Update position display to show where this data was collected
            x_m = self._parse_float(last_point.get('x_m'))
            y_m = self._parse_float(last_point.get('y_m'))
            if x_m is not None and y_m is not None:
                self.position_label.setText(f"X: {x_m:.6f} m\nY: {y_m:.6f} m")

    def _load_avg_rows(self, filepath: Path) -> List[dict]:
        """Load averaged data and group by location.
        
        If multiple measurements exist for the same location (e.g., from session mode),
        this combines them into a single averaged entry per location.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_rows = list(reader)
        except Exception as e:
            logger.error(f"Failed to read averaged CSV: {e}")
            return []
        
        # Group rows by location (x_m, y_m)
        location_bins = {}
        
        for row in all_rows:
            # Filter out rows with MISSING quality (unmatched VXC data)
            quality = row.get("quality_flag", "")
            if quality == "MISSING":
                continue
            if row.get("sample_count") in ("0", 0, None, ""):
                continue
            
            # Get location coordinates
            x_m = self._parse_float(row.get('x_m'))
            y_m = self._parse_float(row.get('y_m'))
            if x_m is None or y_m is None:
                continue
            
            # Use rounded coordinates as key (6 decimal places = ~1 micrometer precision)
            key = (round(x_m, 6), round(y_m, 6))
            
            if key not in location_bins:
                location_bins[key] = []
            location_bins[key].append(row)
        
        # For each location, aggregate multiple measurements
        aggregated_rows = []
        for (x_loc, y_loc), location_rows in location_bins.items():
            if len(location_rows) == 1:
                # Only one measurement - use it directly
                aggregated_rows.append(location_rows[0])
            else:
                # Multiple measurements at same location - aggregate them
                aggregated_row = self._aggregate_location_rows(location_rows, x_loc, y_loc)
                aggregated_rows.append(aggregated_row)
        
        logger.info(f"Loaded {len(all_rows)} total measurements, grouped into {len(aggregated_rows)} unique locations")
        return aggregated_rows

    def _aggregate_location_rows(self, rows: List[dict], x_loc: float, y_loc: float) -> dict:
        """Aggregate multiple measurements at the same location.
        
        Combines sample counts and computes weighted averages of velocity
        and quality metrics across all measurements at this location.
        """
        # Sum total sample count across all measurements
        total_samples = sum(int(row.get('sample_count', 0)) for row in rows)
        
        # Weighted average of velocities and metrics
        velocity_keys = [
            'Raw Velocity.X (m/s)', 'Raw Velocity.Y (m/s)', 'Raw Velocity.Z (m/s)',
            'Corrected Velocity.X (m/s)', 'Corrected Velocity.Y (m/s)', 'Corrected Velocity.Z (m/s)'
        ]
        
        quality_keys = ['Correlation.Avg (%)', 'SNR.Avg (dB)']
        env_keys = [
            'Temperature (°C)', 'Raw Pressure (dbar)', 'Gauge Pressure (dbar)',
            'Corrected Pressure (dbar)', 'Depth (m)', 'Voltage (V)'
        ]
        
        aggregated = {
            'x_m': f"{x_loc:.6f}",
            'y_m': f"{y_loc:.6f}",
            'sample_count': str(total_samples),
            'quality_flag': 'OK',  # All rows in this group passed quality filter
            'measurement_count': str(len(rows))  # Track how many measurements combined
        }
        
        # Weighted average for each numeric field
        for key in velocity_keys + quality_keys + env_keys:
            values_and_weights = []
            for row in rows:
                val = self._parse_float(row.get(key))
                weight = int(row.get('sample_count', 0))
                if val is not None and weight > 0:
                    values_and_weights.append((val, weight))
            
            if values_and_weights:
                # Weighted average: sum(value * weight) / sum(weight)
                weighted_sum = sum(v * w for v, w in values_and_weights)
                total_weight = sum(w for v, w in values_and_weights)
                aggregated[key] = f"{weighted_sum / total_weight:.6f}"
        
        # Use timestamp from most recent measurement
        if 'timestamp_utc' in rows[-1]:
            aggregated['timestamp_utc'] = rows[-1]['timestamp_utc']
        
        logger.debug(f"Aggregated {len(rows)} measurements at ({x_loc:.3f}, {y_loc:.3f}) "
                    f"with {total_samples} total samples")
        
        return aggregated
    
    def _plot_vectors(self, rows: List[dict]):
        x_vals = []
        y_vals = []
        u_vals = []
        v_vals = []

        u_key = "Corrected Velocity.X (m/s)"
        v_key = "Corrected Velocity.Y (m/s)"

        for row in rows:
            x = self._parse_float(row.get("x_m"))
            y = self._parse_float(row.get("y_m"))
            u = self._parse_float(row.get(u_key))
            v = self._parse_float(row.get(v_key))
            if x is None or y is None or u is None or v is None:
                continue
            x_vals.append(x)
            y_vals.append(y)
            u_vals.append(u)
            v_vals.append(v)

        if not x_vals:
            self._draw_placeholder("Missing velocity columns or data")
            return

        x_arr = np.array(x_vals, dtype=float)
        y_arr = np.array(y_vals, dtype=float)
        u_arr = np.array(u_vals, dtype=float)
        v_arr = np.array(v_vals, dtype=float)

        # Calculate velocity magnitudes (speed) using Euclidean norm: sqrt(u^2 + v^2)
        # This is scientifically accurate for 2D velocity magnitude
        speeds = np.sqrt(u_arr ** 2 + v_arr ** 2)
        valid = speeds > 0
        if not np.any(valid):
            self._draw_placeholder("All velocities are zero")
            return

        # Build color normalizer for speed gradient
        norm = self._build_normalizer(speeds)
        # Use RdYlBu_r: Red (high speed/fast) -> Yellow -> Blue (low speed/slow)
        cmap = cm.get_cmap("RdYlBu_r")

        self.ax.clear()
        self.ax.set_aspect("equal", adjustable="box")
        self.ax.set_xlabel("X (m)", fontsize=10, fontweight='bold')
        self.ax.set_ylabel("Y (m)", fontsize=10, fontweight='bold')
        self.ax.set_title("Velocity Vector Field", fontsize=11, fontweight='bold', pad=10)
        self.ax.grid(True, linestyle='--', alpha=0.3, linewidth=0.5)

        x_min_m, x_max_m, y_min_m, y_max_m = self._plane_limits_m()
        self.ax.set_xlim(x_min_m, x_max_m)
        self.ax.set_ylim(y_min_m, y_max_m)

        # Plot data points as 10px diameter dots colored by velocity magnitude
        # s=78.5 gives approximately 10px diameter (π*r^2 where r=5px)
        scatter = self.ax.scatter(
            x_arr,
            y_arr,
            c=speeds,
            s=78.5,  # ~10px diameter
            cmap=cmap,
            norm=norm,
            edgecolors='black',
            linewidths=0.5,
            alpha=0.9,
            zorder=5
        )

        if self.colorbar:
            try:
                self.colorbar.remove()
            except (AttributeError, ValueError):
                pass
        self.colorbar = self.figure.colorbar(scatter, ax=self.ax, label="Speed (m/s)", pad=0.02)

        # Add current position marker as black dot (10px diameter)
        if self.current_position_m:
            x_pos, y_pos = self.current_position_m
            self.ax.plot(x_pos, y_pos, 'ko', markersize=10, markeredgecolor='white', 
                        markeredgewidth=1.0, label='Current Position', zorder=10)
            self.ax.legend(loc='upper right', fontsize=9, framealpha=0.9)

        if self.last_stats:
            total_points = self.last_stats.get("avg_points_total", 0)
            valid_points = self.last_stats.get("avg_points_valid", 0)
            self.points_label.setText(f"Valid points: {valid_points}/{total_points}")
        else:
            self.points_label.setText(f"Valid points: {len(x_arr)}/{len(x_arr)}")

        self.file_label.setText(f"Last file: {Path(self.last_avg_file).name}")
        self.canvas.draw_idle()

    def _draw_placeholder(self, message: str):
        self.ax.clear()
        self.ax.set_facecolor('#f8f9fa')
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in self.ax.spines.values():
            spine.set_visible(False)
        self.ax.text(0.5, 0.5, message, ha="center", va="center", 
                    transform=self.ax.transAxes, fontsize=12, color='#6c757d',
                    bbox=dict(boxstyle="round,pad=0.5", facecolor="white", 
                             edgecolor="#dee2e6", alpha=0.9))
        self.canvas.draw_idle()

    def _parse_float(self, value: object) -> Optional[float]:
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

    def _load_grid_spacing_m(self) -> Tuple[float, float]:
        default_spacing = (0.001, 0.001)
        config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"
        if not config_path.exists():
            return default_spacing

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            grid = config.get("grid", {})
            x_spacing_feet = float(grid.get("x_spacing_feet", 0))
            y_spacing_feet = float(grid.get("y_spacing_feet", 0))
            if x_spacing_feet <= 0 or y_spacing_feet <= 0:
                return default_spacing
            return (x_spacing_feet * 0.3048, y_spacing_feet * 0.3048)
        except Exception as e:
            logger.warning(f"Failed to load grid spacing: {e}")
            return default_spacing

    def _build_normalizer(self, speeds: np.ndarray) -> Normalize:
        min_speed = float(np.min(speeds))
        max_speed = float(np.max(speeds))
        if math.isclose(min_speed, max_speed):
            max_speed = min_speed + 1e-6
        return Normalize(vmin=min_speed, vmax=max_speed)

    def _plane_limits_m(self) -> Tuple[float, float, float, float]:
        """Return plane limits in meters based on step bounds."""
        x_min_steps, x_max_steps = self.PLANE_X_STEPS
        y_min_steps, y_max_steps = self.PLANE_Y_STEPS

        x_min_m = self._steps_to_meters(x_min_steps)
        x_max_m = self._steps_to_meters(x_max_steps)
        y_min_m = self._steps_to_meters(y_min_steps)
        y_max_m = self._steps_to_meters(y_max_steps)
        
        return (x_min_m, x_max_m, y_min_m, y_max_m)

    def update_current_position(self, x_m: float, y_m: float):
        """Update current VXC position marker on the plot.
        
        Uses the in-memory row cache — does NOT re-read the CSV file from disk.
        The cache is refreshed whenever new merged data arrives.
        """
        self.current_position_m = (x_m, y_m)
        
        # Redraw with cached data (no disk I/O)
        if self._cached_rows:
            self._plot_vectors(self._cached_rows)

    def _update_stats_panel(self, point_data: Optional[dict]):
        """Update the statistics panel with current position data."""
        if point_data is None:
            # No data at current position
            self.velocity_label.setText("U: -- m/s\nV: -- m/s\nW: -- m/s")
            self.magnitude_label.setText("-- m/s")
            self.sample_label.setText("Samples: --")
            self.correlation_label.setText("Beam1: N/A\nBeam2: N/A\nBeam3: N/A\nAvg: -- %")
            self.snr_label.setText("Beam1: N/A\nBeam2: N/A\nBeam3: N/A\nAvg: -- dB")
            self.pressure_label.setText("Raw:   -- dbar\nGauge: -- dbar")
            self.status_label.setText("● No data at position")
            self.status_label.setStyleSheet("color: #dc3545; font-size: 9pt; padding-top: 4px;")
            return

        # Extract velocity components
        u_key = "Corrected Velocity.X (m/s)"
        v_key = "Corrected Velocity.Y (m/s)"
        w_key = "Corrected Velocity.Z (m/s)"
        
        u_val = self._parse_float(point_data.get(u_key))
        v_val = self._parse_float(point_data.get(v_key))
        w_val = self._parse_float(point_data.get(w_key))
        sample_count = point_data.get("sample_count", "0")
        measurement_count = point_data.get("measurement_count", "1")
        
        # Format velocity display
        u_str = f"{u_val:.6f}" if u_val is not None else "--"
        v_str = f"{v_val:.6f}" if v_val is not None else "--"
        w_str = f"{w_val:.6f}" if w_val is not None else "--"
        
        self.velocity_label.setText(f"U: {u_str} m/s\nV: {v_str} m/s\nW: {w_str} m/s")
        
        # Calculate and display magnitude
        if u_val is not None and v_val is not None and w_val is not None:
            mag = math.sqrt(u_val**2 + v_val**2 + w_val**2)
            self.magnitude_label.setText(f"{mag:.6f} m/s")
            self.magnitude_label.setStyleSheet("""
                QLabel {
                    color: #28a745;
                    font-size: 14pt;
                    font-weight: bold;
                    font-family: 'Consolas', 'Courier New', monospace;
                    padding: 12px;
                    background-color: white;
                    border: 2px solid #28a745;
                    border-radius: 4px;
                    qproperty-alignment: AlignCenter;
                }
            """)
        else:
            self.magnitude_label.setText("-- m/s")
            self.magnitude_label.setStyleSheet("""
                QLabel {
                    color: #6c757d;
                    font-size: 14pt;
                    font-weight: bold;
                    font-family: 'Consolas', 'Courier New', monospace;
                    padding: 12px;
                    background-color: white;
                    border: 2px solid #dee2e6;
                    border-radius: 4px;
                    qproperty-alignment: AlignCenter;
                }
            """)
        
        self.sample_label.setText(f"Samples: {sample_count}")
        
        # Show measurement count if multiple measurements were combined
        if measurement_count != "1":
            self.sample_label.setText(f"Samples: {sample_count} ({measurement_count} visits)")
        
        # Extract averaged correlation and SNR (individual beam data not available in averaged CSV)
        corr_avg = self._parse_float(point_data.get("Correlation.Avg (%)"))
        snr_avg = self._parse_float(point_data.get("SNR.Avg (dB)"))
        
        # Format correlation display (averaged data only)
        corr_avg_str = f"{corr_avg:.1f}" if corr_avg is not None else "--"
        
        self.correlation_label.setText(
            f"Beam1: N/A\nBeam2: N/A\nBeam3: N/A\nAvg: {corr_avg_str} %"
        )
        
        # Format SNR display (averaged data only)
        snr_avg_str = f"{snr_avg:.2f}" if snr_avg is not None else "--"
        
        self.snr_label.setText(
            f"Beam1: N/A\nBeam2: N/A\nBeam3: N/A\nAvg: {snr_avg_str} dB"
        )
        
        # Extract pressure data
        raw_pressure = self._parse_float(point_data.get("Raw Pressure (dbar)"))
        gauge_pressure = self._parse_float(point_data.get("Gauge Pressure (dbar)"))

        raw_pres_str = f"{raw_pressure:.4f}" if raw_pressure is not None else "--"
        gauge_pres_str = f"{gauge_pressure:.4f}" if gauge_pressure is not None else "--"
        self.pressure_label.setText(f"Raw:   {raw_pres_str} dbar\nGauge: {gauge_pres_str} dbar")

        self.status_label.setText("● Data available")
        self.status_label.setStyleSheet("color: #28a745; font-size: 9pt; padding-top: 4px;")

    def _find_point_data(self, filepath: Path, position: Tuple[float, float]) -> Optional[dict]:
        """Find data for a specific position from the averaged CSV."""
        x_target, y_target = position
        spacing_x, spacing_y = self._load_grid_spacing_m()
        
        # Calculate expected bin center
        if spacing_x > 0 and spacing_y > 0:
            x_bin = round(x_target / spacing_x) * spacing_x
            y_bin = round(y_target / spacing_y) * spacing_y
        else:
            x_bin = x_target
            y_bin = y_target
        
        # Search for matching row in CSV
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_x = self._parse_float(row.get("x_m"))
                    row_y = self._parse_float(row.get("y_m"))
                    if row_x is None or row_y is None:
                        continue
                    
                    # Check if this row matches the target bin
                    if abs(row_x - x_bin) < spacing_x/2 and abs(row_y - y_bin) < spacing_y/2:
                        if row.get("status") == "OK":
                            return row
        except Exception as e:
            logger.error(f"Failed to search averaged CSV: {e}")
        
        return None

    def _steps_to_meters(self, steps: float) -> float:
        inches = steps / self.STEPS_PER_INCH
        feet = inches / 12.0
        return feet * self.METERS_PER_FOOT
