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
from matplotlib.colors import Normalize, LinearSegmentedColormap, TwoSlopeNorm
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QFileDialog, QComboBox, QGroupBox,
)
from PyQt5.QtCore import Qt, QSettings

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
        self.plot_mode = "velocity"
        self._setup_ui()

    # ─── UI Setup ────────────────────────────────────────────────────────────

    def _setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # ── Unified top bar (context + metric columns) ───────────────────────
        top_bar = QFrame()
        top_bar.setStyleSheet("""
            QFrame {
                background-color: #f1f3f5;
                border: 1px solid #dee2e6;
                border-radius: 4px;
            }
            QGroupBox {
                font-weight: 600;
                color: #212529;
                border: 1px solid #d6d9de;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 10px;
                background-color: #fafbfc;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px;
            }
        """)
        top_layout = QVBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(6)

        top_header = QHBoxLayout()
        top_header.setSpacing(16)

        self.file_label = QLabel("File: (none)")
        self.file_label.setStyleSheet("color: #495057; font-weight: 500;")
        top_header.addWidget(self.file_label)

        self.points_label = QLabel("Points: 0")
        self.points_label.setStyleSheet("color: #495057; font-weight: 500;")
        top_header.addWidget(self.points_label)

        mode_label = QLabel("Color Mode:")
        mode_label.setStyleSheet("color: #495057; font-weight: 500;")
        top_header.addWidget(mode_label)

        self.plot_mode_combo = QComboBox()
        self.plot_mode_combo.addItem("Velocity |V|", "velocity")
        self.plot_mode_combo.addItem("TKE", "tke")
        self.plot_mode_combo.addItem("Reynolds tau_xz", "tau_xz")
        self.plot_mode_combo.setCurrentIndex(0)
        self.plot_mode_combo.setStyleSheet("""
            QComboBox {
                background-color: white;
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 150px;
            }
        """)
        self.plot_mode_combo.currentIndexChanged.connect(self._on_plot_mode_changed)
        top_header.addWidget(self.plot_mode_combo)

        top_header.addStretch()

        self.status_label = QLabel("READY")
        self.status_label.setStyleSheet(
            "background-color: #e9ecef; color: #6c757d; "
            "font-size: 8pt; font-weight: 700; padding: 3px 8px; border-radius: 10px;"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        top_header.addWidget(self.status_label)

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
        top_header.addWidget(import_btn)

        reload_btn = QPushButton("↻ Reload")
        reload_btn.setToolTip("Re-read the current file from disk")
        reload_btn.setStyleSheet("""
            QPushButton {
                background-color: #2f6fda;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #255dbe; }
            QPushButton:pressed { background-color: #1f4fa2; }
        """)
        reload_btn.clicked.connect(self._reload_last_file)
        top_header.addWidget(reload_btn)

        top_layout.addLayout(top_header)

        hint_label = QLabel("Cross-section map below; columns show selected measurement details.")
        hint_label.setStyleSheet("color: #6c757d; font-size: 9pt;")
        top_layout.addWidget(hint_label)

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

        metric_row = QHBoxLayout()
        metric_row.setSpacing(8)

        position_box = QGroupBox("Position")
        position_layout = QVBoxLayout(position_box)
        position_layout.setContentsMargins(8, 8, 8, 8)
        self.position_label = QLabel("Cross-Stream: -- m\nDepth:        -- m")
        self.position_label.setStyleSheet(mono_style)
        position_layout.addWidget(self.position_label)
        metric_row.addWidget(position_box, 1)

        flow_box = QGroupBox("Flow")
        flow_layout = QVBoxLayout(flow_box)
        flow_layout.setContentsMargins(8, 8, 8, 8)
        self.vx_label = QLabel("Vx: -- m/s")
        self.vx_label.setStyleSheet(mono_style)
        flow_layout.addWidget(self.vx_label)
        self.vy_vz_label = QLabel("Vy: -- m/s\nVz: -- m/s")
        self.vy_vz_label.setStyleSheet(mono_style)
        flow_layout.addWidget(self.vy_vz_label)
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
        flow_layout.addWidget(self.magnitude_label)
        metric_row.addWidget(flow_box, 1)

        quality_box = QGroupBox("Quality")
        quality_layout = QVBoxLayout(quality_box)
        quality_layout.setContentsMargins(8, 8, 8, 8)
        self.quality_label = QLabel("Corr: -- %\nSNR:  -- dB\nN:    --")
        self.quality_label.setStyleSheet(mono_style)
        quality_layout.addWidget(self.quality_label)
        metric_row.addWidget(quality_box, 1)

        turbulence_box = QGroupBox("Turbulence")
        turbulence_layout = QVBoxLayout(turbulence_box)
        turbulence_layout.setContentsMargins(8, 8, 8, 8)
        self.turbulence_label = QLabel("TIx: -- m/s\nTIy: -- m/s\nTIz: -- m/s\nTKE: -- m2/s2\nTau_xz: -- Pa")
        self.turbulence_label.setStyleSheet(mono_style)
        turbulence_layout.addWidget(self.turbulence_label)
        metric_row.addWidget(turbulence_box, 1)

        legend_box = QGroupBox("Plot Legend")
        legend_layout = QVBoxLayout(legend_box)
        legend_layout.setContentsMargins(8, 8, 8, 8)
        self.legend_label = QLabel(
            "Arrows = (Vy, Vz) direction\n"
            "  length ∝ in-plane speed\n"
            "  (Vx-only → collapses to dot)\n\n"
            "Color  = Total speed |V|\n"
            "  Red    = high magnitude\n"
            "  Blue   = low magnitude\n"
            "  (turbo colormap)"
        )
        self.legend_label.setStyleSheet("""
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
        legend_layout.addWidget(self.legend_label)
        metric_row.addWidget(legend_box, 1)

        top_layout.addLayout(metric_row)
        main_layout.addWidget(top_bar)

        # ── Plot area ─────────────────────────────────────────────────────────
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

        main_layout.addWidget(plot_frame, 1)
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
        settings = QSettings("ADV-VXC", "VXC-ADV-Controller")
        output_dir = settings.value("auto_merge/output_dir", "")

        if output_dir:
            default_dir = Path(str(output_dir)) / "sessions"
        else:
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

    def _on_plot_mode_changed(self):
        """Switch colormap source between velocity magnitude and turbulence fields."""
        selected = self.plot_mode_combo.currentData()
        self.plot_mode = selected if selected else "velocity"
        self._update_plot_legend()
        if self._cached_rows:
            self._plot_cross_section(self._cached_rows)

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
        tke_vals, tau_vals = [], []
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
            tke_vals.append(self._parse_float(row.get('TKE (m2/s2)')))
            tau_vals.append(self._parse_float(row.get('Reynolds tau_xz (Pa)')))

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

        tke_arr = np.array([np.nan if v is None else float(v) for v in tke_vals], dtype=float)
        tau_arr = np.array([np.nan if v is None else float(v) for v in tau_vals], dtype=float)

        # Use raw (Vy, Vz) — arrow length reflects in-plane speed.
        # Points where in-plane flow ≈ 0 (Vx-only) render as zero-length arrows (dots).

        color_values = total_mag
        colorbar_label = "Total Speed |V| (m/s)"
        norm = self._build_normalizer(total_mag)

        mode = self.plot_mode
        if mode == "tke":
            valid_tke = ~np.isnan(tke_arr)
            if np.any(valid_tke):
                color_values = np.where(valid_tke, tke_arr, np.nanmin(tke_arr))
                norm = self._build_normalizer(tke_arr[valid_tke])
                colorbar_label = "TKE (m2/s2)"
            else:
                logger.info("Cross-section view: no valid TKE values, falling back to velocity colors")
                self.plot_mode = "velocity"
                self.plot_mode_combo.blockSignals(True)
                self.plot_mode_combo.setCurrentIndex(0)
                self.plot_mode_combo.blockSignals(False)
                mode = "velocity"
        elif mode == "tau_xz":
            valid_tau = ~np.isnan(tau_arr)
            if np.any(valid_tau):
                tau_valid = tau_arr[valid_tau]
                tau_max_abs = float(np.max(np.abs(tau_valid)))
                tau_max_abs = tau_max_abs if tau_max_abs > 1e-12 else 1e-12
                color_values = np.where(valid_tau, tau_arr, 0.0)
                norm = TwoSlopeNorm(vmin=-tau_max_abs, vcenter=0.0, vmax=tau_max_abs)
                colorbar_label = "Reynolds tau_xz (Pa)"
            else:
                logger.info("Cross-section view: no valid tau_xz values, falling back to velocity colors")
                self.plot_mode = "velocity"
                self.plot_mode_combo.blockSignals(True)
                self.plot_mode_combo.setCurrentIndex(0)
                self.plot_mode_combo.blockSignals(False)
                mode = "velocity"

            self.plot_mode = mode
            self._update_plot_legend()

        # Clip turbo to start at ~30% (light cyan) so the dark navy/purple
        # low-end colors are removed — all arrows remain legible on dark bg
        _turbo_colors = cm.get_cmap('turbo')(np.linspace(0.30, 0.92, 256))
        if mode == "tau_xz":
            cmap = cm.get_cmap('RdBu_r')
        else:
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
            color_values,
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
                c=color_values[near_zero], cmap=cmap, norm=norm,
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
        mode_title = {
            "velocity": "Velocity Magnitude Colors",
            "tke": "TKE Colors",
            "tau_xz": "Reynolds tau_xz Colors",
        }.get(mode, "Velocity Magnitude Colors")
        self.ax.set_title(f"Flow Cross-Section (Downstream View) - {mode_title}", fontsize=11, fontweight='bold',
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
        self.colorbar = self.figure.colorbar(
            quiv,
            ax=self.ax,
            label=colorbar_label,
            orientation='horizontal',
            pad=0.08,
            fraction=0.06,
        )
        self.colorbar.ax.xaxis.label.set_color(_FG)
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

    def _update_plot_legend(self):
        """Refresh legend text to reflect active color mode."""
        mode_text = {
            "velocity": "Color  = Total speed |V|\n  Red    = high magnitude\n  Blue   = low magnitude\n  (turbo colormap)",
            "tke": "Color  = TKE\n  Red    = high turbulence energy\n  Blue   = low turbulence energy\n  (turbo colormap)",
            "tau_xz": "Color  = Reynolds tau_xz\n  Red    = positive stress\n  Blue   = negative stress\n  (RdBu diverging colormap)",
        }.get(self.plot_mode, "Color  = Total speed |V|")
        self.legend_label.setText(
            "Arrows = (Vy, Vz) direction\n"
            "  length ∝ in-plane speed\n"
            "  (Vx-only → collapses to dot)\n\n"
            f"{mode_text}"
        )

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

        self.status_label.setText("POINT SELECTED")
        self.status_label.setStyleSheet(
            "background-color: #d1e7dd; color: #0f5132; "
            "font-size: 8pt; font-weight: 700; padding: 3px 8px; border-radius: 10px;"
        )

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
