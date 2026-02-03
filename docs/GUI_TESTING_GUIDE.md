# GUI Testing Guide - Phase 2

## Pre-Requisites

### Environment Setup

```bash
# Create Python virtual environment
python -m venv venv
source venv/Scripts/activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### Required Hardware (for full testing)

- Velmex VXC USB motor controller (COM3)
- SonTek FlowTracker2 ADV (COM4)
- XY positioning stage connected to VXC
- Water channel/flume with ADV probe mounting

### Simulation Mode (for testing without hardware)

```python
# Set environment variable to enable mock hardware
export MOCK_HARDWARE=1
python main.py
```

## Test Cases

### TC-001: Application Launch

**Steps**:
1. From command line: `python main.py`
2. Observe: MainWindow displays with 4 tabs

**Expected Results**:
- Application window appears (1400×900)
- Title bar: "VXC/ADV Flow Measurement System"
- All tabs accessible: Calibration, Acquisition, Configuration, Export
- No console errors

**Pass/Fail**: ___

### TC-002: Port Auto-Detection

**Steps**:
1. In Calibration tab, observe Combobox contents
2. Click "Refresh Ports"
3. Connect/disconnect USB device
4. Click "Refresh Ports" again

**Expected Results**:
- Combobox shows available COM ports
- Format: "COM3: USB Serial Port Description"
- Port list updates after refresh
- Connected ports appear in both Combobox controls

**Pass/Fail**: ___

### TC-003: Hardware Connection - Success Path

**Prerequisites**: VXC and ADV connected on known COM ports

**Steps**:
1. Select correct COM ports from Combobox
2. Click "Connect"
3. Observe status message

**Expected Results**:
- Success dialog: "VXC and ADV connected successfully!"
- Position label updates (no longer "0 steps")
- Jog controls become responsive
- Position display shows current motor coordinates

**Pass/Fail**: ___

### TC-004: Hardware Connection - Failure Path

**Prerequisites**: Known incorrect COM ports (or devices disconnected)

**Steps**:
1. Select incorrect COM port for VXC
2. Click "Connect"
3. Observe error message

**Expected Results**:
- Error dialog: "Failed to connect VXC on COM[X]"
- OR "Connection Failed" with descriptive message
- Jog controls remain disabled
- Position label unchanged

**Pass/Fail**: ___

### TC-005: Position Display Update

**Prerequisites**: VXC connected

**Steps**:
1. Note initial position (X, Y in steps and feet)
2. Move motor manually OR use jog controls
3. Observe position label update

**Expected Results**:
- Position updates every 500ms
- Both step count AND feet values shown
- Format: "X: 1000 steps (0.2174 ft) | Y: 500 steps (0.1087 ft)"
- Values change smoothly with motor movement

**Pass/Fail**: ___

### TC-006: Jog Control - Fine Steps

**Prerequisites**: VXC connected, Step Size = "Fine (10 steps)"

**Steps**:
1. Press and hold "→ X+" button
2. Hold for 1 second, release
3. Check position change
4. Repeat for ↑↓← directions

**Expected Results**:
- Smooth continuous motion in specified direction
- Total displacement: ~10-15 steps per second (50ms poll rate)
- Motion stops immediately on button release
- All four directions work

**Pass/Fail**: ___

### TC-007: Jog Control - Medium/Coarse Steps

**Prerequisites**: VXC connected

**Steps**:
1. Change Step Size to "Medium (100 steps)"
2. Press and hold "→ X+" for 1 second
3. Observe displacement
4. Change to "Coarse (1000 steps)" and repeat

**Expected Results**:
- Medium: ~100-150 steps per second
- Coarse: ~1000-1500 steps per second
- Displacement scales proportionally

**Pass/Fail**: ___

### TC-008: Direct Positioning

**Prerequisites**: VXC connected

**Steps**:
1. Enter X: 5000, Y: 2500 in input fields
2. Click "Go to Position"
3. Observe motor movement
4. Check final position label

**Expected Results**:
- Motor moves to specified coordinates
- Position label shows "X: 5000 steps | Y: 2500 steps"
- Button is non-blocking (can click during motion)
- Motion completes with ±1 step accuracy

**Pass/Fail**: ___

### TC-009: Zero Origin

**Prerequisites**: VXC connected, motor at desired origin (0,0 position)

**Steps**:
1. Position motor at bottom-left of measurement area
2. Click "Zero Origin (0,0)"
3. Observe confirmation dialog
4. Check position label shows current coordinates

**Expected Results**:
- Dialog: "Origin set to X=[current], Y=[current]"
- Calibration object stores origin coordinates
- Subsequent grid generation uses this as reference

**Pass/Fail**: ___

### TC-010: Capture Boundary

**Prerequisites**: VXC connected, origin already set, motor at desired boundary (top-right)

**Steps**:
1. Move motor to top-right corner of measurement area
2. Click "Capture Boundary"
3. Check confirmation

**Expected Results**:
- Dialog: "Boundary set to X=[current], Y=[current]"
- Grid will use this as maximum extent
- Preparation for grid generation

**Pass/Fail**: ___

### TC-011: Grid Generation

**Prerequisites**: VXC connected, origin and boundary set

**Steps**:
1. Set X Spacing to 0.10 feet
2. Set Y Spacing to 0.05 feet
3. Click "Generate Grid"
4. Check result dialog

**Expected Results**:
- Dialog: "Generated [N] measurement positions"
- N = number of positions in calculated grid
- Example: 4.0 ft width ÷ 0.10 spacing = 41 X positions
- Position list created for acquisition phase

**Pass/Fail**: ___

### TC-012: Configuration Tab - Save Settings

**Prerequisites**: None

**Steps**:
1. Go to Configuration tab
2. Change values:
   - X Spacing: 0.15
   - Y Spacing: 0.08
   - Froude Threshold: 1.2
   - Base Sampling: 15
   - Max Sampling: 100
   - Min SNR: 3.0
   - Min Correlation: 60.0
3. Click "Save Configuration"
4. Check result

**Expected Results**:
- Dialog: "Configuration saved successfully"
- File created: `config/experiment_config.yaml`
- Values persisted for next session

**Pass/Fail**: ___

### TC-013: Configuration Tab - Load Defaults

**Prerequisites**: Configuration tab with modified values

**Steps**:
1. Observe modified values in fields
2. Click "Load Defaults"
3. Check all fields reset

**Expected Results**:
- X Spacing: 0.10
- Y Spacing: 0.05
- Froude Threshold: 1.0
- Base Sampling: 10.0
- Max Sampling: 120.0
- Min SNR: 5.0
- Min Correlation: 70.0

**Pass/Fail**: ___

### TC-014: Acquisition Start - Pre-Conditions Met

**Prerequisites**: VXC/ADV connected, grid generated

**Steps**:
1. Go to Acquisition tab
2. Click "Start Acquisition"
3. Input dialog appears: "Enter Z-plane coordinate"
4. Enter: 0.500
5. Click OK

**Expected Results**:
- Start button becomes disabled (grayed out)
- Pause, Stop buttons become enabled
- State label shows: "MOVING"
- Progress bar shows: "0/[total]"
- Motor begins moving to first position

**Pass/Fail**: ___

### TC-015: Acquisition - First Position Sampling

**Prerequisites**: Acquisition running, motor at first position

**Steps**:
1. Observe state transitions
2. Wait for sampling to complete (~10s for base case)
3. Check status labels

**Expected Results**:
- State: "MOVING" → "SAMPLING" → "MOVING"
- Froude number displays actual value (e.g., 0.85)
- Flow regime: "Subcritical" or "Supercritical"
- Depth shows sensor reading (e.g., 0.245 m)
- Position updates: X: 0.250 ft | Y: 0.150 ft
- Progress updates: 1/[total]

**Pass/Fail**: ___

### TC-016: Acquisition - Froude-Based Adaptive Sampling

**Prerequisites**: Acquisition running, multiple positions sampled

**Steps**:
1. Observe Froude numbers across positions
2. Note when Fr > 1.0 (supercritical)
3. Check sampling duration indicator

**Expected Results**:
- Subcritical (Fr < 1.0): "Base (10s)" in decision label
- Supercritical (Fr > 1.0): "Extended (60s+)" in decision label
- Extended sampling takes longer (~60-120s)
- Froude threshold from config (default 1.0) used

**Pass/Fail**: ___

### TC-017: Acquisition - Pause/Resume

**Prerequisites**: Acquisition running, at least 3 positions sampled

**Steps**:
1. During position sampling, click "Pause"
2. Observe state change
3. Wait 5 seconds
4. Click "Resume"
5. Observe sequence continue

**Expected Results**:
- Pause: Motor stops, sampling pauses, state = "PAUSED"
- Pause button disabled, Resume enabled
- Motor remains at pause position during wait
- Resume: Acquisition continues from same position
- Final data includes all positions before/after pause

**Pass/Fail**: ___

### TC-018: Acquisition - Emergency Stop

**Prerequisites**: Acquisition running

**Steps**:
1. During acquisition, click "Emergency Stop" (red button)
2. Observe immediate reaction

**Expected Results**:
- Motor stops immediately
- ADV stops streaming
- HDF5 file closes (data saved)
- State → "ERROR" (or IDLE)
- All buttons reset to initial state
- No data loss (all previous positions saved)

**Pass/Fail**: ___

### TC-019: Acquisition - Return Home

**Prerequisites**: Acquisition complete or paused

**Steps**:
1. Click "Return Home"
2. Observe motor movement

**Expected Results**:
- Motor moves to origin position (0,0)
- Movement is coordinated XY motion
- Position label shows: X: 0 | Y: 0 (after completion)

**Pass/Fail**: ___

### TC-020: Export - CSV Format

**Prerequisites**: Acquisition data collected

**Steps**:
1. Go to Export tab
2. Select format: "CSV (Spreadsheet)"
3. Click "Export Data"
4. Select output file: "measurement.csv"
5. Open in spreadsheet application (Excel/LibreOffice)

**Expected Results**:
- File created: measurement.csv
- Columns present: X_steps, Y_steps, X_feet, Y_feet, V_mean, V_std, Fr, TI, etc.
- One row per sampled position
- All numeric values readable
- Can be plotted/analyzed in spreadsheet

**Pass/Fail**: ___

### TC-021: Export - HDF5 Format

**Prerequisites**: Acquisition data collected

**Steps**:
1. Go to Export tab
2. Select format: "HDF5 (Python/MATLAB)"
3. Click "Export Data"
4. File: "measurement.h5"
5. Verify with Python: `h5py.File('measurement.h5')`

**Expected Results**:
- File created: measurement.h5
- Structure preserved: position, velocity, statistics groups
- Metadata includes: Z-plane, run number, timestamp
- Can be loaded in MATLAB or Python

**Pass/Fail**: ___

### TC-022: Export - VTK Format

**Prerequisites**: Acquisition data collected

**Steps**:
1. Go to Export tab
2. Select format: "VTK (ParaView)"
3. Click "Export Data"
4. File: "measurement.vtk"
5. Open in ParaView

**Expected Results**:
- File created: measurement.vtk
- Format: VTK legacy ASCII
- Contains velocity vectors at each measurement point
- Viewable in ParaView with 3D visualization

**Pass/Fail**: ___

### TC-023: Export - All Formats

**Prerequisites**: Acquisition data collected

**Steps**:
1. Go to Export tab
2. Select format: "All Formats"
3. Click "Export Data"
4. File: "measurement"
5. Check directory after export

**Expected Results**:
- Three files created:
  - measurement.csv
  - measurement.h5
  - measurement.vtk
- All formats correct per TC-020/021/022

**Pass/Fail**: ___

### TC-024: Error Handling - ADV Signal Quality

**Prerequisites**: Acquisition running, poor ADV signal

**Steps**:
1. Block ADV optical probe during sampling
2. Observe ADV readout

**Expected Results**:
- SNR drops below minimum (5.0 dB)
- Sample marked as invalid
- Status displays: "ADV: Low signal quality"
- Measurement continues (skips invalid sample)

**Pass/Fail**: ___

### TC-025: Error Handling - Motor Timeout

**Prerequisites**: VXC connected but motor power lost mid-motion

**Steps**:
1. Start acquisition
2. During motion phase, disconnect motor power
3. Observe timeout behavior

**Expected Results**:
- Motor motion requested but incomplete
- 60-second timeout expires
- Status: "Timeout waiting for motion complete"
- Emergency stop triggered
- Data file saved

**Pass/Fail**: ___

### TC-026: Menu - File Operations

**Prerequisites**: Application running

**Steps**:
1. Click Menu → File
2. Observe options

**Expected Results**:
- New Experiment
- Open Experiment
- ---
- Exit

**Pass/Fail**: ___

### TC-027: Menu - Help

**Prerequisites**: Application running

**Steps**:
1. Click Menu → Help
2. Click "About"

**Expected Results**:
- Dialog displays:
  - "VXC/ADV Flow Measurement System"
  - "Version 1.0"
  - Description of hardware

**Pass/Fail**: ___

### TC-028: Full Workflow - Complete Acquisition Cycle

**Prerequisites**: All hardware connected

**Steps**:

**Phase 1: Calibration**
1. Connect hardware (TC-003)
2. Position motor at origin
3. Zero Origin
4. Move to opposite corner
5. Capture Boundary
6. Set spacing: X=0.20, Y=0.10
7. Generate Grid

**Phase 2: Acquisition**
8. Start Acquisition
9. Enter Z-plane: 0.500
10. Let complete (or pause/resume)
11. Observe progress to completion

**Phase 3: Export**
12. Export as CSV
13. Verify file with 9+ measurement positions

**Expected Results**:
- All sub-steps execute without error
- Grid generated: expected count
- Acquisition completes: all positions sampled
- Data file valid: CSV readable with velocity data
- Timeline: 5-10 minutes for typical 3×3 grid with base sampling

**Pass/Fail**: ___

## Regression Testing

After any code changes, verify:

1. **Connection**: TC-003 ✓
2. **Jog**: TC-006 ✓
3. **Calibration**: TC-009, TC-010, TC-011 ✓
4. **Acquisition**: TC-014, TC-015, TC-017, TC-018 ✓
5. **Export**: TC-020, TC-021, TC-022 ✓
6. **Error Handling**: TC-024, TC-025 ✓

## Performance Benchmarks

| Operation | Target | Actual | Status |
|-----------|--------|--------|--------|
| Jog response time | <100ms | ___ | ___ |
| Position update rate | 2 Hz | ___ | ___ |
| Grid generation | <1s | ___ | ___ |
| First position move | <30s | ___ | ___ |
| Single position (base) | ~10s | ___ | ___ |
| Single position (extended) | ~60-120s | ___ | ___ |
| Export to CSV | <5s | ___ | ___ |
| Application launch | <5s | ___ | ___ |

## Bug Report Template

```
**Title**: [Component] Issue description
**Severity**: Critical | High | Medium | Low
**Reproducibility**: Always | Often | Sometimes | Rarely

**Steps to Reproduce**:
1. ...
2. ...
3. ...

**Expected Result**:
...

**Actual Result**:
...

**Screenshots/Logs**:
[Attach if applicable]

**Environment**:
- Python: 3.x
- PyQt5: x.xx
- Hardware: [VXC/ADV/Both]
```

---

**Test Suite Version**: 1.0  
**Total Test Cases**: 28  
**Last Updated**: Phase 2 Release  
