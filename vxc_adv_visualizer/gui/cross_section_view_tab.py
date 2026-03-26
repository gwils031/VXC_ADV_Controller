"""Cross-Section View tab for displaying hydraulic velocity cross-sections.

Plots in-plane velocity arrows (Vy, Vz) and out-of-plane Vx symbols at each
measured (x_m, y_m) location using averaged ADV data.

ADV convention used here:
  Vx = downstream (out-of-plane when viewing cross-section)
  Vy = cross-stream (horizontal arrow component)
  Vz = vertical     (vertical arrow component)
VXC convention:
  x_m = cross-stream position (plot horizontal axis)
  y_m = vertical / depth position (plot vertical axis)
"""

import csv
import logging
import math
from pathlib import Path
from typing import Optional, List, Tuple

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib import cm
from matplotlib.colors import Normalize, LinearSegmentedColormap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QFileDialog,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

logger = logging.getLogger(__name__)


class CrossSectionViewTab(QWidget):
    """Tab showing hydraulic flow cross-section with quiver arrows and Vx symbols."""

    # Threshold (m/s) above/below which Vx is considered significant out-of-plane flow
    VX_SYMBOL_THRESHOLD = 0.01

    def __init__(self, parent=None, boundaries: dict = None):
        super().__init__(parent)
        if boundaries is None:
            boundaries = {
                'x_min_steps': 0,
                'x_max_steps': 165654,
                'y_min_steps': 0,
                'y_max_steps': 57651,
            }
        self.boundaries = boundaries
        self.last_avg_file: Optional[str] = None
        self.colorbar = None
        self._cached_rows: List[dict] = []
        self._setup_ui()

    # ─── UI Setup ────────────────────────────────────────────────────────────

    def _setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # ── Top info bar ──────────────────────────────────────────────────────
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

        self.file_label = QLabel("File: (none)")
        self.file_label.setStyleSheet("color: #495057; font-weight: 500;")
        info_layout.addWidget(self.file_label)

        info_layout.addSpacing(20)

        self.points_label = QLabel("Points: 0")
        self.points_label.setStyleSheet("color: #495057; font-weight: 500;")
        info_layout.addWidget(self.points_label)

        info_layout.addStretch()

        # Import button — green
        import_btn = QPushButton("📂 Import Session Data")
        import_btn.setToolTip("Open an averaged_grid_data.csv from a past session")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #218838; }
            QPushButton:pressed { background-color: #1e7e34; }
        """)
        import_btn.clicked.connect(self._import_session_data)
        info_layout.addWidget(import_btn)

        info_layout.addSpacing(8)

        # Reload button — blue
        reload_btn = QPushButton("↻ Reload")
        reload_btn.setToolTip("Re-read the current file from disk")
        reload_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #0056b3; }
            QPushButton:pressed { background-color: #004085; }
        """)
        reload_btn.clicked.connect(self._reload_last_file)
        info_layout.addWidget(reload_btn)

        main_layout.addWidget(info_bar)

        # ── Main content: 70 % plot / 30 % stats ─────────────────────────────
        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)

        # Left — plot frame
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
        self._draw_placeholder(
            "No data loaded\n\n"
            "Use '📂 Import Session Data' to load a past session,\n"
            "or wait for live merged data to appear."
        )
        plot_layout.addWidget(self.canvas)

        self.canvas.mpl_connect('button_press_event', self._on_plot_click)

        content_layout.addWidget(plot_frame, 7)

        # Right — stats panel
        self.stats_panel = QFrame()
        self.stats_panel.setFrameShape(QFrame.StyledPanel)
        self.stats_panel.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
            }
        """)
        self.stats_panel.setMinimumWidth(260)
        self.stats_panel.setMaximumWidth(340)

        stats_layout = QVBoxLayout(self.stats_panel)
        stats_layout.setContentsMargins(12, 12, 12, 12)
        stats_layout.setSpacing(6)

        title_label = QLabel("Measurement Point")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #212529; padding-bottom: 6px;")
        stats_layout.addWidget(title_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #dee2e6;")
        stats_layout.addWidget(sep)

        mono_style = """
            QLabel {
                color: #495057;
                font-size: 10pt;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 6px;
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 3px;
            }
        """
        section_font = QFont()
        section_font.setPointSize(10)
        section_font.setBold(True)

        def _section(text):
            lbl = QLabel(text)
            lbl.setFont(section_font)
            lbl.setStyleSheet("color: #212529; padding-top: 6px;")
            return lbl

        # Position
        stats_layout.addWidget(_section("Position"))
        self.position_label = QLabel("Cross-Stream: -- m\nDepth:        -- m")
        self.position_label.setStyleSheet(mono_style)
        stats_layout.addWidget(self.position_label)

        # Vx (downstream / out-of-plane)
        stats_layout.addWidget(_section("Downstream Vx (out-of-plane)"))
        self.vx_label = QLabel("Vx: -- m/s")
        self.vx_label.setStyleSheet(mono_style)
        stats_layout.addWidget(self.vx_label)

        # Vy / Vz (cross-section arrows)
        stats_layout.addWidget(_section("Cross-Section Vy, Vz (arrows)"))
        self.vy_vz_label = QLabel("Vy: -- m/s\nVz: -- m/s")
        self.vy_vz_label.setStyleSheet(mono_style)
        stats_layout.addWidget(self.vy_vz_label)

        # Total magnitude
        stats_layout.addWidget(_section("Total Magnitude |V|"))
        self.magnitude_label = QLabel("-- m/s")
        self.magnitude_label.setStyleSheet("""
            QLabel {
                color: #007bff;
                font-size: 14pt;
                font-weight: bold;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 10px;
                background-color: white;
                border: 2px solid #007bff;
                border-radius: 4px;
                qproperty-alignment: AlignCenter;
            }
        """)
        stats_layout.addWidget(self.magnitude_label)

        # Quality metrics
        stats_layout.addWidget(_section("Quality Metrics"))
        self.quality_label = QLabel("Corr: -- %\nSNR:  -- dB\nN:    --")
        self.quality_label.setStyleSheet(mono_style)
        stats_layout.addWidget(self.quality_label)

        # Turbulence metrics
        stats_layout.addWidget(_section("Turbulence Metrics"))
        self.turbulence_label = QLabel("TIx: -- m/s\nTIy: -- m/s\nTIz: -- m/s\nTKE: -- m2/s2\nTau_xz: -- Pa")
        self.turbulence_label.setStyleSheet(mono_style)
        stats_layout.addWidget(self.turbulence_label)

        # Plot legend (static reference box)
        stats_layout.addWidget(_section("Plot Legend"))
        legend_label = QLabel(
            "Arrows = (Vy, Vz) direction\n"
            "  length ∝ in-plane speed\n"
            "  (Vx-only → collapses to dot)\n\n"
            "Color  = Total speed |V|\n"
            "  Red    = high magnitude\n"
            "  Blue   = low magnitude\n"
            "  (turbo colormap)"
        )
        legend_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 9pt;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 8px;
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 3px;
            }
        """)
        stats_layout.addWidget(legend_label)

        self.status_label = QLabel("● Click a point to inspect")
        self.status_label.setStyleSheet("color: #6c757d; font-size: 9pt; padding-top: 4px;")
        stats_layout.addWidget(self.status_label)

        stats_layout.addStretch()

        content_layout.addWidget(self.stats_panel, 3)
        main_layout.addLayout(content_layout)
        self.setLayout(main_layout)

    # ─── Public API ──────────────────────────────────────────────────────────

    def update_from_avg_file(self, avg_file: str, stats: Optional[dict] = None):
        """Called by auto-merge signal or manual import to refresh the plot."""
        self.last_avg_file = avg_file
        self._reload_last_file()

    def update_boundaries(self, boundaries: dict):
        """Store updated workspace boundaries (plot axes are data-driven; no redraw needed)."""
        self.boundaries = boundaries

    def update_current_position(self, x_m: float, y_m: float):
        """No-op stub — VXC live position marker is not shown in this view."""
        pass

    # ─── Import ──────────────────────────────────────────────────────────────

    def _import_session_data(self):
        """Open a file dialog to select an averaged CSV from a past session."""
        default_dir = Path(__file__).resolve().parents[2] / "Data_Output" / "sessions"
        if not default_dir.exists():
            default_dir = Path.home()

        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open Averaged Session Data",
            str(default_dir),
            "CSV Files (*.csv);;All Files (*.*)",
        )
        if filepath:
            self.update_from_avg_file(filepath)

    # ─── Data loading ────────────────────────────────────────────────────────

    def _reload_last_file(self):
        if not self.last_avg_file:
            self._draw_placeholder(
                "No data loaded\n\n"
                "Use '📂 Import Session Data' to load a past session,\n"
                "or wait for live merged data to appear."
            )
            return

        avg_path = Path(self.last_avg_file)
        if not avg_path.exists():
            self._draw_placeholder(f"File not found:\n{avg_path.name}")
            return

        rows = self._load_avg_rows(avg_path)
        if not rows:
            self._draw_placeholder("No valid data to display")
            return

        self._cached_rows = rows
        self.file_label.setText(f"File: {avg_path.name}")
        self.points_label.setText(f"Points: {len(rows)}")
        self._plot_cross_section(rows)

    def _load_avg_rows(self, filepath: Path) -> List[dict]:
        """Read averaged CSV, group by (x_m, y_m), aggregate multiple measurements."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_rows = list(reader)
        except Exception as e:
            logger.error(f"Failed to read averaged CSV: {e}")
            return []

        location_bins: dict = {}
        for row in all_rows:
            if row.get("quality_flag", "") == "MISSING":
                continue
            if row.get("sample_count") in ("0", 0, None, ""):
                continue
            x_m = self._parse_float(row.get('x_m'))
            y_m = self._parse_float(row.get('y_m'))
            if x_m is None or y_m is None:
                continue
            key = (round(x_m, 6), round(y_m, 6))
            location_bins.setdefault(key, []).append(row)

        aggregated: List[dict] = []
        for (x_loc, y_loc), loc_rows in location_bins.items():
            if len(loc_rows) == 1:
                aggregated.append(loc_rows[0])
            else:
                aggregated.append(self._aggregate_location_rows(loc_rows, x_loc, y_loc))

        logger.info(
            f"Cross-section view: {len(all_rows)} rows → {len(aggregated)} unique locations"
        )
        return aggregated

    def _aggregate_location_rows(self, rows: List[dict], x_loc: float, y_loc: float) -> dict:
        """Weighted-average velocity + quality metrics for duplicate locations."""
        total_samples = sum(int(row.get('sample_count', 0)) for row in rows)
        avg_keys = [
            'Raw Velocity.X (m/s)', 'Raw Velocity.Y (m/s)', 'Raw Velocity.Z (m/s)',
            'Corrected Velocity.X (m/s)', 'Corrected Velocity.Y (m/s)', 'Corrected Velocity.Z (m/s)',
            'Correlation.Avg (%)', 'SNR.Avg (dB)',
            'TI_x (m/s)', 'TI_y (m/s)', 'TI_z (m/s)',
            'TKE (m2/s2)', 'u_prime_x_u_prime_z_cov (m2/s2)',
            'rho_freshwater (kg/m3)', 'Reynolds tau_xz (Pa)',
        ]
        result: dict = {
            'x_m': f"{x_loc:.6f}",
            'y_m': f"{y_loc:.6f}",
            'sample_count': str(total_samples),
            'quality_flag': 'GOOD',
            'measurement_count': str(len(rows)),
        }
        for key in avg_keys:
            vw_pairs = []
            for row in rows:
                val = self._parse_float(row.get(key))
                w = int(row.get('sample_count', 0))
                if val is not None and w > 0:
                    vw_pairs.append((val, w))
            if vw_pairs:
                wsum = sum(v * w for v, w in vw_pairs)
                total_w = sum(w for _, w in vw_pairs)
                result[key] = f"{wsum / total_w:.6f}"
        return result

    # ─── Plotting ────────────────────────────────────────────────────────────

    def _plot_cross_section(self, rows: List[dict]):
        """Render equal-length quiver arrows (Vy, Vz direction) coloured by total |V|."""
        x_vals, y_vals, vx_vals, vy_vals, vz_vals = [], [], [], [], []
        vx_key = "Corrected Velocity.X (m/s)"
        vy_key = "Corrected Velocity.Y (m/s)"
        vz_key = "Corrected Velocity.Z (m/s)"

        for row in rows:
            x = self._parse_float(row.get('x_m'))
            y = self._parse_float(row.get('y_m'))
            vx = self._parse_float(row.get(vx_key))
            vy = self._parse_float(row.get(vy_key))
            vz = self._parse_float(row.get(vz_key))
            if any(v is None for v in (x, y, vx, vy, vz)):
                continue
            x_vals.append(x)
            y_vals.append(y)
            vx_vals.append(vx)
            vy_vals.append(vy)
            vz_vals.append(vz)

        if not x_vals:
            self._draw_placeholder("Missing velocity columns or no valid data")
            return

        x_arr = np.array(x_vals, dtype=float)
        y_arr = np.array(y_vals, dtype=float)
        vx_arr = np.array(vx_vals, dtype=float)
        vy_arr = np.array(vy_vals, dtype=float)
        vz_arr = np.array(vz_vals, dtype=float)

        total_mag = np.sqrt(vx_arr**2 + vy_arr**2 + vz_arr**2)
        in_plane_mag = np.sqrt(vy_arr**2 + vz_arr**2)

        # Use raw (Vy, Vz) — arrow length reflects in-plane speed.
        # Points where in-plane flow ≈ 0 (Vx-only) render as zero-length arrows (dots).

        norm = self._build_normalizer(total_mag)
        # Clip turbo to start at ~30% (light cyan) so the dark navy/purple
        # low-end colors are removed — all arrows remain legible on dark bg
        _turbo_colors = cm.get_cmap('turbo')(np.linspace(0.30, 0.92, 256))
        cmap = LinearSegmentedColormap.from_list('turbo_clipped', _turbo_colors)

        self.ax.clear()

        # Axis limits — data-driven with 10 % padding
        x_range = float(np.max(x_arr) - np.min(x_arr))
        y_range = float(np.max(y_arr) - np.min(y_arr))
        x_pad = max(x_range * 0.1, 0.05)
        y_pad = max(y_range * 0.1, 0.05)
        xlim = (float(np.min(x_arr)) - x_pad, float(np.max(x_arr)) + x_pad)
        ylim = (float(np.min(y_arr)) - y_pad, float(np.max(y_arr)) + y_pad)

        spatial_scale = max(x_range, y_range, 0.1)
        max_in_plane = float(np.max(in_plane_mag)) if float(np.max(in_plane_mag)) > 1e-9 else 1.0

        # ── Remap arrow lengths into a visible bounded range ──────────────────
        # sqrt-compression: small arrows get boosted, large ones pulled down.
        # Non-zero in-plane → mapped to [min_len, max_len] in data units.
        # Near-zero in-plane (Vx-only) → drawn as scatter dots instead.
        MIN_LEN = 0.025 * spatial_scale   # shortest visible arrow
        MAX_LEN = 0.07  * spatial_scale   # longest arrow
        has_inplane = in_plane_mag > 1e-9

        t = np.where(has_inplane, np.sqrt(in_plane_mag / max_in_plane), 0.0)  # [0, 1], sqrt-compressed
        target_len = np.where(has_inplane,
                              MIN_LEN + t * (MAX_LEN - MIN_LEN),
                              0.0)
        sf = np.where(has_inplane, target_len / in_plane_mag, 0.0)
        vy_plot = vy_arr * sf
        vz_plot = vz_arr * sf

        # ── Quiver: arrows with remapped lengths, coloured by total |V| ──────
        quiv = self.ax.quiver(
            x_arr, y_arr, vy_plot, vz_plot,
            total_mag,
            cmap=cmap,
            norm=norm,
            angles='xy',
            scale_units='xy',
            scale=1.0,
            width=0.004,
            headwidth=4,
            headlength=5,
            alpha=0.95,
            zorder=3,
        )

        # ── Scatter dots for near-zero in-plane points (quiver zero ≈ invisible)
        near_zero = ~has_inplane
        if np.any(near_zero):
            self.ax.scatter(
                x_arr[near_zero], y_arr[near_zero],
                c=total_mag[near_zero], cmap=cmap, norm=norm,
                s=55, edgecolors='white', linewidths=0.5,
                zorder=4,
            )

        # Axes styling — dark background so every arrow is visible regardless of colour
        _BG = '#111827'   # dark navy
        _FG = '#e5e7eb'   # light gray text / grid
        self.ax.set_facecolor(_BG)
        self.figure.patch.set_facecolor(_BG)
        self.ax.set_aspect('equal', adjustable='box')
        self.ax.set_xlim(xlim)
        self.ax.set_ylim(ylim)
        self.ax.set_xlabel("Cross-Stream Position (m)", fontsize=10, fontweight='bold', color=_FG)
        self.ax.set_ylabel("Vertical Position / Depth (m)", fontsize=10, fontweight='bold', color=_FG)
        self.ax.set_title("Flow Cross-Section (Downstream View)", fontsize=11, fontweight='bold',
                          pad=10, color=_FG)
        self.ax.tick_params(colors=_FG)
        for spine in self.ax.spines.values():
            spine.set_edgecolor(_FG)
        self.ax.grid(True, linestyle='--', alpha=0.25, linewidth=0.5, color=_FG)

        # Colorbar
        if self.colorbar:
            try:
                self.colorbar.remove()
            except (AttributeError, ValueError):
                pass
        self.colorbar = self.figure.colorbar(quiv, ax=self.ax, label="Total Speed |V| (m/s)", pad=0.02)
        self.colorbar.ax.yaxis.label.set_color(_FG)
        self.colorbar.ax.tick_params(colors=_FG, labelsize=9)
        self.colorbar.outline.set_edgecolor(_FG)

        self.canvas.draw_idle()

    def _draw_placeholder(self, message: str):
        self.ax.clear()
        self.figure.patch.set_facecolor('white')
        self.ax.set_facecolor('#f8f9fa')
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in self.ax.spines.values():
            spine.set_visible(False)
        self.ax.text(
            0.5, 0.5, message,
            ha='center', va='center',
            transform=self.ax.transAxes,
            fontsize=12, color='#6c757d',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='#dee2e6', alpha=0.9),
        )
        self.canvas.draw_idle()

    # ─── Interaction ─────────────────────────────────────────────────────────

    def _on_plot_click(self, event):
        """Find and display stats for the nearest measurement point to a mouse click."""
        if event.inaxes != self.ax or not self._cached_rows:
            return
        cx, cy = event.xdata, event.ydata
        if cx is None or cy is None:
            return

        best_row = None
        best_dist = float('inf')
        for row in self._cached_rows:
            x = self._parse_float(row.get('x_m'))
            y = self._parse_float(row.get('y_m'))
            if x is None or y is None:
                continue
            d = math.hypot(cx - x, cy - y)
            if d < best_dist:
                best_dist = d
                best_row = row

        if best_row is not None:
            self._update_stats(best_row)

    def _update_stats(self, row: dict):
        """Populate the stats panel from a measurement row dict."""
        x = self._parse_float(row.get('x_m'))
        y = self._parse_float(row.get('y_m'))
        vx = self._parse_float(row.get('Corrected Velocity.X (m/s)'))
        vy = self._parse_float(row.get('Corrected Velocity.Y (m/s)'))
        vz = self._parse_float(row.get('Corrected Velocity.Z (m/s)'))
        corr = self._parse_float(row.get('Correlation.Avg (%)'))
        snr = self._parse_float(row.get('SNR.Avg (dB)'))
        n = row.get('sample_count', '--')
        tix = self._parse_float(row.get('TI_x (m/s)'))
        tiy = self._parse_float(row.get('TI_y (m/s)'))
        tiz = self._parse_float(row.get('TI_z (m/s)'))
        tke = self._parse_float(row.get('TKE (m2/s2)'))
        tau_xz = self._parse_float(row.get('Reynolds tau_xz (Pa)'))

        x_str = f"{x:.4f}" if x is not None else "--"
        y_str = f"{y:.4f}" if y is not None else "--"
        self.position_label.setText(f"Cross-Stream: {x_str} m\nDepth:        {y_str} m")

        if vx is not None:
            if vx > self.VX_SYMBOL_THRESHOLD:
                direction = "↓ downstream (⊙)"
            elif vx < -self.VX_SYMBOL_THRESHOLD:
                direction = "↑ upstream (⊗)"
            else:
                direction = "≈ zero (•)"
            self.vx_label.setText(f"Vx: {vx:.4f} m/s\n{direction}")
        else:
            self.vx_label.setText("Vx: -- m/s")

        vy_str = f"{vy:.4f}" if vy is not None else "--"
        vz_str = f"{vz:.4f}" if vz is not None else "--"
        self.vy_vz_label.setText(f"Vy: {vy_str} m/s\nVz: {vz_str} m/s")

        if vx is not None and vy is not None and vz is not None:
            mag = math.sqrt(vx**2 + vy**2 + vz**2)
            self.magnitude_label.setText(f"{mag:.4f} m/s")
            self.magnitude_label.setStyleSheet("""
                QLabel {
                    color: #28a745;
                    font-size: 14pt;
                    font-weight: bold;
                    font-family: 'Consolas', 'Courier New', monospace;
                    padding: 10px;
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
                    padding: 10px;
                    background-color: white;
                    border: 2px solid #dee2e6;
                    border-radius: 4px;
                    qproperty-alignment: AlignCenter;
                }
            """)

        corr_str = f"{corr:.1f}" if corr is not None else "--"
        snr_str = f"{snr:.2f}" if snr is not None else "--"
        self.quality_label.setText(f"Corr: {corr_str} %\nSNR:  {snr_str} dB\nN:    {n}")

        tix_str = f"{tix:.6f}" if tix is not None else "--"
        tiy_str = f"{tiy:.6f}" if tiy is not None else "--"
        tiz_str = f"{tiz:.6f}" if tiz is not None else "--"
        tke_str = f"{tke:.6f}" if tke is not None else "--"
        tau_xz_str = f"{tau_xz:.6f}" if tau_xz is not None else "--"
        self.turbulence_label.setText(
            f"TIx: {tix_str} m/s\n"
            f"TIy: {tiy_str} m/s\n"
            f"TIz: {tiz_str} m/s\n"
            f"TKE: {tke_str} m2/s2\n"
            f"Tau_xz: {tau_xz_str} Pa"
        )

        self.status_label.setText("● Point selected")
        self.status_label.setStyleSheet("color: #28a745; font-size: 9pt; padding-top: 4px;")

    # ─── Helpers ─────────────────────────────────────────────────────────────

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

    def _build_normalizer(self, speeds: np.ndarray) -> Normalize:
        min_s = float(np.min(speeds))
        max_s = float(np.max(speeds))
        if math.isclose(min_s, max_s):
            max_s = min_s + 1e-6
        return Normalize(vmin=min_s, vmax=max_s)
