# VXC/ADV Flow Measurement System - Codebase Summary

**Last Updated**: February 11, 2026  
**Purpose**: Quick reference for AI assistants working on this codebase

---

## High-Level Purpose

This is a **laboratory instrument control system** that combines:
- **Velmex VXC 2-axis motorized positioning stage** (precision XY control)
- **SonTek FlowTracker2 Acoustic Doppler Velocimeter** (3D water velocity measurements)

Used for mapping 3D velocity fields in hydraulic flume experiments (open channel hydraulics, supercritical flows, hydraulic jumps).

---

## Core Functionality (5 Processes)

### 1. VXC Controller
- **File**: `vxc_adv_visualizer/controllers/vxc_controller.py`
- **Purpose**: Serial communication with Velmex VXC stage
- **Protocol**: ASCII commands @ 57600 baud
- **Precision**: 48,000 steps/foot (4,000 steps/inch)
- **Key Commands**:
  - `F` - Set online mode, disable echo
  - `I` - Step motor (e.g., `IA1M2000` = motor A, dir 1, 2000 steps)
  - `X` - Get current position
  - `V` - Query motor status
- **Features**: Jog controls, boundary detection, thread-safe operation

### 2. ADV Integration (File-Based)
- **Approach**: Monitors FlowTracker2 CSV exports (~1 minute intervals)
- **Data**: 3D velocity vectors (X, Y, Z in m/s), correlation scores, SNR, temperature
- **Format**: CSV with UTC timestamps
- **Note**: NOT direct serial integration - leverages official SonTek software

### 3. File Monitoring & Auto-Merge
- **File Monitor**: `vxc_adv_visualizer/monitoring/file_monitor.py`
  - QFileSystemWatcher + 10s polling fallback
  - Validates filenames with regex patterns
  - 2s file stability check before processing
  - Filters non-data files (README, config, output files)
  
- **VXC Matcher**: `vxc_adv_visualizer/monitoring/vxc_matcher.py`
  - **CRITICAL**: Converts ADV local timestamps → UTC before matching
  - 5-minute matching window
  - Binary search for nearest timestamp
  - Handles date boundary crossings

- **Filename Patterns**:
  - ADV: `YYYYMMDD-HHMMSS.csv` (e.g., `20260209-144849.csv`)
  - VXC: `vxc_pos_YYYYMMDD_HHMMSS.csv`

### 4. Data Processing
- **Position Logger**: `vxc_adv_visualizer/data/vxc_position_logger.py`
  - Logs XY positions with millisecond UTC timestamps
  - Format: `timestamp_utc,x_m,y_m,quality`
  - Automatic 1-minute file rotation
  - Thread-safe concurrent logging
  - Converts motor steps → meters (48,000 steps/foot × 0.3048)

- **Merger**: `vxc_adv_visualizer/data/adv_vxc_merger.py`
  - Nearest-neighbor timestamp alignment (0.5s tolerance)
  - Binary search optimization for large datasets
  - **Two Outputs**:
    1. **Merged CSV**: Sample-by-sample alignment with all columns
    2. **Averaged Plane CSV**: Grid-based spatial averaging for visualization

- **Grid Averaging**:
  - Bins measurements by XY position into grid cells
  - Computes mean velocities, std dev, sample counts per cell
  - Quality filtering: marks cells with insufficient samples as "INVALID"
  - Configurable grid spacing via `experiment_config.yaml`

### 5. PyQt5 GUI (3 Tabs)
- **Main Window**: `vxc_adv_visualizer/gui/main_window.py`
  - **Tab 1: VXC Controller** - Manual positioning, jog controls (0.25", 0.5", 0.75", 1.0"), boundary finder, real-time position polling @ 1Hz
  - **Tab 2: Auto-Merge** (`auto_merge_tab.py`) - Directory monitoring, activity log, statistics, merge worker threads
  - **Tab 3: Live Data** (`live_data_tab.py`) - Matplotlib vector field plots, color-coded velocity magnitude (viridis colormap)

- **Background Workers**: All hardware I/O runs in QThread to prevent GUI freezing
- **Signals/Slots**: Thread-safe communication between workers and GUI

---

## Project Structure

```
vxc_adv_visualizer/
├── main.py                     # Application entry point
├── requirements.txt            # Python dependencies
├── README.md                   # Package documentation
├── config/
│   ├── vxc_config.yaml        # VXC hardware config (baudrate, steps_per_foot)
│   └── experiment_config.yaml  # Grid spacing, sampling parameters
├── controllers/
│   ├── __init__.py
│   └── vxc_controller.py      # VXC serial driver
├── data/
│   ├── __init__.py
│   ├── adv_vxc_merger.py      # Timestamp-based data fusion
│   └── vxc_position_logger.py # XY position logging
├── gui/
│   ├── __init__.py
│   ├── main_window.py         # Main GUI with 3 tabs
│   ├── auto_merge_tab.py      # Auto-merge monitoring tab
│   └── live_data_tab.py       # Velocity visualization tab
├── monitoring/
│   ├── __init__.py
│   ├── file_monitor.py        # Directory watcher + merge orchestration
│   └── vxc_matcher.py         # Timezone-aware file matching
└── utils/
    ├── __init__.py
    └── serial_utils.py        # Serial port enumeration
```

**Total**: 15 Python files + 2 config YAML files

---

## Key Technical Details

### Import Structure
- **Relative imports**: All internal imports use relative paths (e.g., `from ..controllers.vxc_controller import VXCController`)
- **Package structure**: Designed as proper Python package with `__init__.py` files

### VXC Coordinate System
- **Origin**: Bottom-left (0,0)
- **X-axis**: Cross-channel (bank-to-bank), 0 = left bank, positive rightward (0 to 163,963 steps)
- **Y-axis**: Vertical (water depth), 0 = bottom, positive upward (0 to 39,000 steps)
- **Z-axis**: Upstream position (user-specified per measurement plane)
- **Units**: Motor steps (primary), converted to feet/meters for display
- **Conversion**: 46,000 steps/foot = 4,600 steps/0.1 foot
- **Motor mapping**: Motor 2 = X-axis, Motor 1 = Y-axis

### Timezone Handling
- **VXC logs**: Always UTC timestamps
- **ADV exports**: Local time in filename, UTC in CSV content
- **Critical**: `vxc_matcher.py` converts ADV filename timestamps from local → UTC before matching
- **Tolerance**: 0.5s for sample matching, 5min window for file matching

### Thread Safety
- **Qt Main Thread**: GUI rendering, user interaction only
- **Worker Threads** (QThread): Hardware I/O, file parsing, data processing
- **Communication**: PyQt signals/slots for thread-safe updates
- **Locking**: Command lock in VXC controller for serial I/O

### Data Flow
```
1. User moves VXC stage (manual jog or automated)
   ↓
2. VXCPositionLogger records XY positions @ 1Hz with UTC timestamps
   → Writes to VXC_Positions/vxc_pos_YYYYMMDD_HHMMSS.csv
   
3. FlowTracker2 (running independently) measures velocities
   → Exports to ADV_Data/YYYYMMDD-HHMMSS.csv every ~1 minute
   
4. FileMonitor detects new ADV file
   ↓
5. VXCMatcher finds corresponding VXC log (5min window)
   ↓
6. MergeWorkerThread (background):
   - Parse ADV CSV → velocity vectors
   - Parse VXC CSV → XY positions
   - Binary search nearest timestamp (0.5s tolerance)
   - Output merged.csv (sample-level) + avg_xy.csv (grid-averaged)
   ↓
7. LiveDataTab auto-refreshes with new averaged data
   → Displays velocity vector field on 2D plane
```

---

## Configuration Files

### `vxc_config.yaml`
```yaml
default_port: null
baudrate: 57600
timeout: 1
steps_per_foot: 48000
default_speed: 2000
default_acceleration: 1000
```

### `experiment_config.yaml`
```yaml
grid:
  x_spacing_ft: 0.1      # Grid cell width (feet)
  y_spacing_ft: 0.05     # Grid cell height (feet)
  
merge:
  tolerance_sec: 0.5     # Timestamp matching tolerance
```

---

## How to Run

### Launch GUI
```bash
cd "c:\App Development\ADV&VXC Controller"
python -m vxc_adv_visualizer.main
```

### Typical Workflow
1. **Connect VXC**: Select COM port, click "Connect"
2. **Position Stage**: Use jog buttons (±0.25", ±0.5", ±0.75", ±1.0")
3. **Start Position Logging**: Enable monitoring in Auto-Merge tab
4. **Configure Directories**:
   - ADV Data Dir: Where FlowTracker2 exports CSVs
   - VXC Positions Dir: Where position logs are saved
   - Output Dir: Where merged files go
5. **Enable Monitoring**: System auto-merges as ADV files appear
6. **View Results**: Live Data tab shows velocity vectors

---

## Important Notes

### What This System Does NOT Include
- ❌ Flow calculations (Froude number, Reynolds, adaptive sampling) - REMOVED
- ❌ Direct ADV serial integration - Uses file-based approach instead
- ❌ Test suites - All tests removed in February 2026 streamlining
- ❌ Demo scripts - Removed to focus on core functionality
- ❌ FlowTracker2 plugin (C# AQTS project) - Separate codebase

### Output Files Generated
- `YYYYMMDD-HHMMSS_merged.csv` - Sample-by-sample aligned data
- `YYYYMMDD-HHMMSS_avg_xy.csv` - Grid-averaged for visualization
- `vxc_pos_YYYYMMDD_HHMMSS.csv` - Position logs (every 1 minute)

### File Filtering Logic
**FileMonitor ignores**:
- Files not matching ADV/VXC patterns
- README.md, .gitignore, .xlsx, .txt, .log
- Output files (`_merged.csv`, `_avg_xy.csv`) to prevent reprocessing

---

## Dependencies (requirements.txt)

Key packages:
- **PyQt5** - GUI framework
- **pyserial** - Serial communication
- **matplotlib** - Visualization
- **numpy** - Numerical operations
- **PyYAML** - Config parsing

---

## Common Tasks for AI Assistants

### Adding New VXC Commands
1. Edit `vxc_controller.py`
2. Add method following pattern: `_send_command()` → `_parse_response()`
3. Add error handling and timeout logic
4. Update GUI in `main_window.py` if user-facing

### Modifying Grid Averaging
1. Edit `adv_vxc_merger.py` → `write_averaged_plane_csv()` function
2. Update binning logic, statistical calculations
3. Test with real ADV/VXC data files
4. Update `experiment_config.yaml` if new parameters needed

### Changing File Matching Logic
1. Edit `vxc_matcher.py` → `find_matching_vxc_log()` function
2. Adjust time window, tolerance, or matching algorithm
3. Test with edge cases (date boundaries, timezone changes)

### GUI Modifications
1. **Tab changes**: Edit respective file (`main_window.py`, `auto_merge_tab.py`, `live_data_tab.py`)
2. **Worker threads**: Use QThread pattern, emit signals for updates
3. **Always** run long operations in background threads to prevent GUI freezing

---

## Debugging Tips

### Import Errors
- All imports should be relative (e.g., `from ..controllers import VXCController`)
- Run from package root: `python -m vxc_adv_visualizer.main`

### VXC Connection Issues
- Check COM port with `serial_utils.list_available_ports()`
- Verify baudrate: 57600 (hardcoded in VXC firmware)
- Test with bare serial commands: `F\r`, `IXA\r`, `V\r`

### File Matching Failures
- Check timezone conversion in `vxc_matcher.py`
- Verify ADV filename pattern matches FlowTracker2 exports
- Confirm VXC logs exist in specified directory
- Check 5-minute matching window isn't too restrictive

### Merge Errors
- Verify timestamp formats match: ISO 8601 UTC
- Check tolerance (0.5s) isn't too strict for your data
- Ensure ADV CSV columns match expected format
- Test with smaller datasets first

---

## File Locations Referenced in Code

### Hardcoded Paths (Relative)
- Config: `./config/vxc_config.yaml`, `./config/experiment_config.yaml`
- Log: `./vxc_adv_system.log` (created at runtime)

### User-Selectable Paths (Saved to QSettings)
- ADV Data Directory
- VXC Positions Directory
- Output Directory

---

## Version History

- **Feb 2026**: Streamlined to 5 core processes (current state)
  - Removed flow calculations, tests, demos, docs, plugin
  - Fixed relative imports for proper package structure
  - 15 Python files + 2 config files remain
  
- **Historical**: Had 4-tab GUI with acquisition workflows, calibration, Froude analysis

---

## Contact Points for Hardware

- **VXC Stage**: Velmex VXC controller (RS-232/USB serial)
- **FlowTracker2**: SonTek ADV (file-based integration via CSV exports)
- **No other hardware** directly controlled by this system

---

**End of Summary**
