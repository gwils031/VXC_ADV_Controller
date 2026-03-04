# VXC/ADV Controller

PyQt5 desktop application for controlling a Velmex VXC XY stage and automatically
merging SonTek FlowTracker2 ADV exports with logged motor positions.

---

## Quick Start

```powershell
# 1 — Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 2 — Install / update dependencies (first time only)
pip install -r vxc_adv_visualizer/requirements.txt

# 3 — Launch
python -m vxc_adv_visualizer.main

cd "C:\App Development\ADV&VXC Controller"; python -m vxc_adv_visualizer.main
```

The GUI opens immediately. Hardware connections are optional — all tabs are
accessible without a connected VXC or ADV instrument.

---

## Application Layout

The window contains four tabs:

| Tab | Purpose |
|-----|---------|
| **VXC Controller** | Connect the stage, jog manually, position via sliders |
| **Auto-Merge** | Session management and automatic ADV+VXC file merging |
| **Live Data** | 2-D velocity-vector plot updated live from merged output |
| **Cross-Section** | Automated multi-point scan routes (vertical / horizontal / grid) |

---

## Tab Reference

### VXC Controller

**Connection group**
- Select the COM port from the dropdown (populated on startup).
- Click **Auto Detect VXC** to scan all ports and connect to the first
  responding Velmex controller.
- Click **Disconnect** to release the port cleanly.
- Status label shows *Not Connected* (red) or *Connected — COM X* (green).

**Current Position group**
- Displays live X and Y coordinates in metres, updated at ~2 Hz while connected.

**Jog Controls group**
- Select a jog distance from the dropdown: 6.35 mm, 12.7 mm, 19.05 mm, or 25.4 mm.
- Press and hold **X−**, **X+**, **Y−**, **Y+** arrow buttons to jog continuously.
  Releasing the button stops motion.

**Jog to Position (X→Y) group**
- Two sliders set absolute target positions within the stage travel envelope:
  - X: 0 → 1051.9 mm (left = origin)
  - Y: 0 → 366.1 mm (bottom = origin)
- Drag a slider to the desired coordinate, then click **GO**.
- The GO button is disabled until the VXC is connected.
- While a move is in progress the GO button is greyed out and a status
  message shows which axis is moving. Double-pressing GO during a move is
  ignored.
- Live position updates are paused for the duration of the move to avoid
  feedback against the sliders.

**Zero / utility buttons**
- **Zero Position** — marks the current motor position as (0, 0) in firmware.
- **Find Origin** — runs both axes to the hardware limit switches and re-zeroes.

---

### Auto-Merge

Watches an ADV export folder for new FlowTracker2 CSV files and merges them
with the nearest-in-time VXC position log entry to produce per-file merged
CSVs and rolling session-wide summary files.

**Session Management group**

| Control | Description |
|---------|-------------|
| Session Name | Free-text label used as the output sub-folder name |
| Operator | Optional operator name written to the session metadata |
| Notes | Brief experiment description |
| **Start Session** (green) | Creates the output folder and begins accumulating files |
| **End Session** (red) | Flushes remaining data and closes the session |
| **Browse…** | Opens the output folder in Explorer |

A session must be active before monitoring can start. When the application
launches it automatically creates a session named `Session_<YYYYMMDD>`.

**Directory Configuration group**

| Field | Default |
|-------|---------|
| ADV Watch Folder | `ADV_Data/` |
| VXC Positions Folder | `VXC_Positions/` |
| Output Folder | `Data_Output/` |

Click **Browse** next to any field to change it. Paths are persisted in the
Windows registry between runs.

**Monitoring Control group**
- **Start Monitoring** — begins watching the ADV folder; any `.csv` files
  added after this point are automatically processed. Existing files are
  skipped (pre-marked on startup).
- **Stop Monitoring** — halts the watcher.
- Status bar shows the monitoring state and number of files processed.

**Output files (per session)**

| File | Contents |
|------|----------|
| `<timestamp>_merged.csv` | One row per ADV sample with matched VXC X/Y |
| `<timestamp>_averaged.csv` | Row per ADV file, spatially averaged velocities |
| `master_merged.csv` | All merged rows accumulated across the session |
| `master_averaged.csv` | All averaged rows accumulated across the session |

Every new averaged file triggers a **Live Data** tab update automatically.

**Activity Log** — scrollable text log of merge results capped at 500 lines.

---

### Live Data

Displays normalized velocity vectors (quiver arrows) overlaid on a flume
cross-section diagram. The plot updates whenever Auto-Merge produces a new
averaged output file.

- **↻ Reload** — re-reads the last averaged CSV and redraws immediately.
- The colourbar shows normalised velocity magnitude.
- A magenta marker indicates the current VXC position if the stage is
  connected and moving.
- Valid-point counter (top bar) shows how many positions have usable
  velocity data.

---

### Cross-Section

Plans and executes automated multi-point measurement routes. The VXC must be
connected first.

**Route Configuration group**

| Scan Type | Description |
|-----------|-------------|
| Vertical Line | Evenly spaced points along a fixed X, varying Y |
| Horizontal Line | Evenly spaced points along a fixed Y, varying X |
| XY Grid | Full rectangular grid of N×M points |

Configure start/end coordinates and number of points (or spacing) using the
input fields. Click **Preview Route** to visualise the points in the preview
pane before committing.

**Route parameters**
- **Dwell time** — seconds the instrument dwells at each point (default 60 s,
  read from `experiment_config.yaml`).
- **Settling time** — pause after each move before starting data acquisition
  (default 2 s).
- **Y tolerance warning / hard stop** — configurable step thresholds that
  warn or abort if the Y axis deviates during a move.

**Automation Control group**

| Button | Action |
|--------|--------|
| **Start** | Begin executing the planned route |
| **Pause** | Hold at current position (resumes from same point) |
| **Resume** | Continue after a pause |
| **Stop** | Abort the run and return to origin |
| **Skip Position** | Skip the current dwell and advance to the next point |

A progress bar, ETA countdown, and per-position status are displayed while
a run is active.

---

## Configuration Files

### `vxc_adv_visualizer/config/vxc_config.yaml`

Controls the serial connection to the Velmex VXC.

```yaml
port: COM8          # Change to your actual COM port
baudrate: 57600
timeout: 2.0
steps_per_foot: 46000
motion_timeout_sec: 60
```

### `vxc_adv_visualizer/config/experiment_config.yaml`

Controls automation defaults and session behaviour.

```yaml
automation:
  default_dwell_time_sec: 60.0
  movement_settling_time_sec: 2.0
  default_vertical_points: 10
  default_horizontal_points: 15

sessions:
  base_output_dir: "Data_Output"
  auto_create_on_start: true

environment:
  atmospheric_pressure_dbar: 8.5   # adjust for your site elevation
```

---

## Directory Structure

```
ADV&VXC Controller/
├── .venv/                          Python virtual environment
├── ADV_Data/                       Drop FlowTracker2 exports here
├── VXC_Positions/                  VXC position log CSVs (auto-written)
├── Data_Output/                    Merged and averaged output
│   └── <session_name>/
│       ├── master_averaged.csv
│       ├── master_merged.csv
│       └── <timestamp>_merged.csv  (one per ADV file)
├── vxc_adv_system.log              Rotating log (5 MB × 3 backups)
├── vxc_adv_visualizer/
│   ├── main.py                     Entry point
│   ├── config/
│   │   ├── experiment_config.yaml
│   │   └── vxc_config.yaml
│   ├── gui/
│   │   ├── main_window.py          Main window + VXC Controller tab
│   │   ├── auto_merge_tab.py       Auto-Merge tab
│   │   ├── live_data_tab.py        Live Data tab
│   │   ├── cross_section_tab.py    Cross-Section tab
│   │   └── range_slider.py         Shared widget
│   ├── controllers/                VXC and ADV hardware drivers
│   ├── data/                       Session manager, merger, logger
│   └── monitoring/                 File-system watcher
└── vxc_adv_visualizer/
    └── requirements.txt
```

---

## Typical Workflow

### Manual positioning + single measurement
1. Connect VXC via **Auto Detect VXC** on the VXC Controller tab.
2. Jog to the desired position using arrow buttons or the position sliders.
3. Open Auto-Merge tab → confirm session is active → click **Start Monitoring**.
4. Trigger a FlowTracker2 measurement. The resulting CSV lands in `ADV_Data/`.
5. The merge runs automatically; the Live Data tab updates.

### Automated cross-section
1. Connect VXC.
2. Start a session on the Auto-Merge tab and enable monitoring.
3. Switch to the Cross-Section tab.
4. Select scan type, set coordinates and dwell time.
5. Click **Preview Route** to verify.
6. Click **Start** — the stage moves point-to-point, triggering the ADV
   at each position. Progress and ETA are shown in real time.

---

## System Requirements

- Windows 10 / 11
- Python 3.10 or later (tested on 3.13)
- Two USB ports (VXC on one, FlowTracker2 on another)
- Velmex VXC controller (57600 baud)
- SonTek FlowTracker2 (exports CSV to a watched folder)

---

## Troubleshooting

**App does not start — `ModuleNotFoundError`**
```powershell
pip install -r vxc_adv_visualizer/requirements.txt
```

**VXC not detected by Auto Detect**
- Check the USB cable and power.
- Open Device Manager and note the COM port; set it manually in
  `vxc_config.yaml` or the port dropdown.
- Ensure no other application (e.g. VXC software) has the port open.

**ADV files not being merged**
- Confirm monitoring is *Started* (green indicator).
- Confirm the watch folder matches where FlowTracker2 saves exports.
- Check `vxc_adv_system.log` for error messages.

**GO button does not re-enable after a jog**
- If the serial port was lost mid-move, use **Disconnect** then reconnect.
  The cleanup path restores the button state on disconnect.

**Log location**: `vxc_adv_system.log` in the workspace root, rotated at
5 MB with 3 backups (`...log.1`, `...log.2`, `...log.3`).

---

## Last Updated

March 4, 2026
