# PyQt5 GUI Implementation Guide

## Overview

The MainWindow class provides a complete PyQt5 interface for the VXC/ADV flow measurement system with the following components:

- **Calibration Tab**: Hardware connection, jog controls, grid generation
- **Acquisition Tab**: Measurement controls, real-time status, 2D visualization
- **Configuration Tab**: Parameter settings (grid spacing, Froude threshold, ADV limits)
- **Export Tab**: Data export in multiple formats

## Architecture

### Thread Model

The GUI uses a worker thread pattern for non-blocking acquisition:

```
MainWindow (UI Thread)
  ├─ AcquisitionWorker (QThread)
  │  └─ Sampler.run_measurement_sequence()
  └─ Signals: status_update, state_changed, position_sampled, acquisition_complete
```

### Key Classes

#### MainWindow(QMainWindow)

**Responsibilities**:
- UI layout and widget management
- Hardware connection and initialization
- Signal/slot wiring for worker thread integration
- Configuration loading and saving

**Key Methods**:
- `_connect_hardware()` - Initialize VXC and ADV controllers
- `_start_acquisition()` - Begin measurement with Z-plane specification
- `_pause_acquisition()` / `_resume_acquisition()` - Pause/resume sequence
- `_emergency_stop()` - Immediate halt with motion stop
- `_jog_start(axis, direction)` / `_jog_update()` - Press-and-hold controls
- `_export_data()` - Multi-format data export

#### AcquisitionWorker(QThread)

**Responsibilities**:
- Run Sampler.run_measurement_sequence() in background thread
- Emit signals for status updates and completion

**Signals**:
- `status_update(str)` - General status message
- `state_changed(str)` - Sampler state change
- `position_sampled(dict)` - Position/velocity data
- `acquisition_complete()` - Sequence finished
- `error_occurred(str)` - Error message

## Tab Details

### Calibration Tab

**Hardware Connection**:
```
Port Selection → Refresh → Connect
```
- Auto-detects available COM ports
- Stores port selections in config

**Jog Controls**:
```
Step Size: [Fine|Medium|Coarse]
    ↑ (Y+)
← (X-)  ↓  → (X+)
    ↓ (Y-)
```
- Press and hold arrows for continuous motion
- Dynamically adjusts step size (10, 100, or 1000 steps)
- 50ms polling rate (20Hz responsiveness)

**Direct Positioning**:
```
X (steps): [________]  Go to Position
Y (steps): [________]
```
- Input absolute coordinates
- Blocking motion until complete

**Calibration**:
```
Zero Origin (0,0)  →  Capture Boundary
```
1. Position motor at bottom-left corner of measurement area → Zero Origin
2. Position motor at top-right corner → Capture Boundary
3. System calculates grid bounds

**Grid Generation**:
```
X Spacing: [0.1] feet    Generate Grid
Y Spacing: [0.05] feet
```
- Creates regular grid of measurement positions
- Stores positions for acquisition phase
- Converts feet to motor steps using calibration

### Acquisition Tab

**Control Buttons**:
- **Start Acquisition** (Green) - Begin measurement sequence
  - Prompts for Z-plane coordinate
  - Initializes HDF5 file with Z metadata
  - Launches worker thread
- **Pause** - Freeze acquisition (sampler holds position)
- **Resume** - Continue from paused position
- **Emergency Stop** (Red) - Immediate halt
- **Return Home** - Move to origin after acquisition

**Live Status Display**:
```
State: [IDLE|CALIBRATING|MOVING|SAMPLING|PAUSED|ERROR]
Froude Number: 0.85
Flow Regime: Subcritical | Sampling Decision: Base (10s) [Extended (60s)]
Depth: 0.245 m
Position: X: 0.250 ft | Y: 0.150 ft
Progress: 15/45 ████████░░░░░░░░░░
```

**Status Fields**:
- **State**: Current sampler state machine state
- **Froude Number**: Fr = V/√(gh) from latest sample
- **Flow Regime**: Supercritical (Fr > 1.0) or Subcritical
- **Sampling Decision**: Base or Extended duration based on Froude
- **Depth**: From ADV pressure sensor (meters)
- **Position**: Current X,Y in engineering units
- **Progress**: Completed positions / Total positions

**2D Heatmap Visualization**:
- Displays velocity magnitude (m/s) as color-coded grid
- Updates dynamically as positions are sampled
- Color scale: Blue (low) → Red (high)
- Axes: X (bank-to-bank) vs Y (depth)
- Hover labels show exact values

### Configuration Tab

**Grid Settings**:
```
X Spacing (feet): [0.10]
Y Spacing (feet): [0.05]
```

**Flow Analysis**:
```
Froude Threshold: [1.0]           (1.0 = critical flow)
Base Sampling (s): [10.0]         (subcritical flows)
Max Sampling (s): [120.0]         (supercritical flows)
```

**ADV Settings**:
```
Min SNR (dB): [5.0]              (signal quality threshold)
Min Correlation (%): [70.0]      (velocity estimation quality)
```

**Actions**:
- **Save Configuration** - Persist settings to YAML
- **Load Defaults** - Reset to factory defaults

### Export Tab

**Format Selection**:
```
[CSV (Spreadsheet) ▼]
```
- **CSV**: Spreadsheet-compatible with position and velocity columns
- **HDF5**: Python/MATLAB hierarchical format with metadata
- **VTK**: ParaView-compatible 3D visualization format
- **All Formats**: Export to all three formats simultaneously

**Export Process**:
1. Click "Export Data"
2. Select output directory and filename
3. Writes file(s) with extension added automatically
4. Confirmation dialog on success

**3D Compilation**:
```
[Compile Z-planes to 3D]
```
- Select multiple HDF5 files (one per Z-plane)
- Merges into single 3D dataset
- Outputs as VTK for ParaView visualization

## Signal/Slot Connections

### Sampler Callbacks to GUI

```python
# In _start_acquisition():
self.sampler.on_status_update = self._on_sampler_status
self.sampler.on_state_changed = self._on_sampler_state
self.sampler.on_position_sampled = self._on_position_sampled
```

### Handler Methods

```python
def _on_sampler_status(message: str):
    """Update sampling decision label"""
    self.sampling_decision_label.setText(message)

def _on_sampler_state(state):
    """Update state indicator"""
    self.state_label.setText(state.value.upper())

def _on_position_sampled(record: DataRecord):
    """Update metrics and heatmap"""
    self.froude_label.setText(f"{record.froude_number:.2f}")
    # Update heatmap grid[x,y] = record.velocity_magnitude
```

## Port Auto-Detection

The `list_available_ports()` function returns:
```python
[
    ('COM3', 'USB Serial Port (VXC Controller)'),
    ('COM4', 'USB Serial Port (SonTek FlowTracker2)'),
]
```

Combobox displays:
```
COM3: USB Serial Port (VXC Controller)
COM4: USB Serial Port (SonTek FlowTracker2)
```

## Data Flow

### Calibration Workflow

```
1. Connect Hardware
   ├─ VXC on COM3 (9600 baud)
   └─ ADV on COM4 (19200 baud)

2. Zero Origin
   └─ Captures current motor position as (0,0)

3. Capture Boundary
   └─ Captures top-right position, calculates grid extent

4. Generate Grid
   ├─ Creates SamplingPosition objects with (x_steps, y_steps)
   └─ Converts feet input to motor steps

5. Display Grid
   └─ Shows grid in status bar (count of positions)
```

### Acquisition Workflow

```
1. Start Acquisition
   ├─ Prompt: "Enter Z-plane coordinate"
   ├─ Initialize: DataLogger with Z metadata
   ├─ Create: AcquisitionWorker (QThread)
   └─ Call: Sampler.run_measurement_sequence()

2. For Each Position (in worker thread):
   ├─ Move motor to (x_steps, y_steps)
   ├─ Wait for motion complete (±1 step verification)
   ├─ Read ADV burst (100 samples at 10Hz = 10s)
   ├─ Calculate: Froude, turbulence intensity
   ├─ Adaptive sampling: If Fr > 1.0, extend to 60-120s
   ├─ Store: DataRecord to HDF5
   └─ Emit: position_sampled signal → Update GUI

3. Pause/Resume (state machine in Sampler)
   ├─ Pause: Motor stops, ADV paused
   ├─ Resume: Continue from saved position
   └─ Both: Maintain state consistency

4. Emergency Stop
   ├─ Motor: Immediate stop_motion()
   ├─ ADV: Stop stream
   ├─ File: Close HDF5 (data saved)
   └─ Thread: Exit gracefully

5. Acquisition Complete
   ├─ Close HDF5 file
   ├─ Emit: acquisition_complete signal
   ├─ Prompt: Next Z-plane or Done?
   └─ Reset: UI to IDLE state
```

## Configuration Files

### experiment_config.yaml

```yaml
grid:
  x_spacing_feet: 0.10
  y_spacing_feet: 0.05

froude_threshold: 1.0
base_sampling_duration_sec: 10
max_sampling_duration_sec: 120

adv:
  min_snr_db: 5.0
  min_correlation_percent: 70.0
```

## Error Handling

### Connection Failures

```
VXC Connection Failed on COM3
├─ Check port selection
├─ Verify USB cable
├─ Confirm device is powered on
└─ Retry "Connect" button
```

### ADV Streaming Errors

```
ADV: Low Signal Quality (SNR=2.1 dB < 5.0 dB)
├─ Reposition probe
├─ Check water quality (sediment)
└─ Verify optical window is clean
```

### Motor Timeout

```
Timeout waiting for motion complete (60s)
├─ Check motor power
├─ Verify no mechanical obstruction
├─ Try "Return Home" to reset
└─ Restart hardware connection
```

## Testing Checklist

### Unit Testing (Without Hardware)

```python
# Test config loading
assert app.config['vxc']['port'] == 'COM3'

# Test grid generation (with mock calibration)
positions = cal.generate_grid(0.1, 0.05)
assert len(positions) == expected_count

# Test data model
record = DataRecord.from_samples(adv_samples)
assert record.froude_number > 0
assert record.turbulence_intensity >= 0
```

### Integration Testing (With Hardware)

```python
# Calibration cycle
1. Connect to VXC/ADV
2. Zero origin (measure actual position)
3. Move 0.1 ft (verify step count = 4600)
4. Capture boundary
5. Generate 3×2 grid
6. Verify grid has 6 positions

# Acquisition cycle (mock data)
1. Start acquisition at Z=0.5 ft
2. Verify first position move
3. Pause → Resume (check state recovery)
4. Stop → Verify HDF5 file created
5. Export to CSV → Verify columns match DataRecord
```

### User Acceptance Testing

```python
# End-to-end workflow
1. Launch application
2. Auto-detect COM ports
3. Connect VXC/ADV
4. Calibrate grid (2 ft × 1 ft area, 0.1 ft spacing)
   └─ 21 positions expected
5. Start acquisition
   ├─ Supercritical flow detected (Fr=1.3)
   ├─ Extended sampling initiated
   └─ Progress updates every 5s
6. Pause at 50%, Resume
7. Emergency stop test
8. Export to CSV/HDF5/VTK
9. Verify data in ParaView
```

## Performance Notes

- **Jog Responsiveness**: 50ms poll rate = 20 Hz responsiveness (imperceptible lag)
- **Status Updates**: 500ms position update rate during idle
- **Progress Bar**: Updates every position completion (adaptive rate)
- **Memory Usage**: ~50 MB for 1000-position grid (100 velocity samples per position)

## Future Enhancements (Phase 3)

- [ ] Multi-plane 3D visualization (stacking Z-planes)
- [ ] ROI (Region of Interest) editing in heatmap
- [ ] Real-time turbulence intensity display
- [ ] Velocity vector field overlay on heatmap
- [ ] Custom export templates
- [ ] Experimental comparison (overlay multiple datasets)

---

**Last Updated**: Phase 2 Completion  
**Lines of Code**: ~1,200 (MainWindow + AcquisitionWorker)
