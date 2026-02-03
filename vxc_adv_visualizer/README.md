# VXC/ADV Flume Flow Measurement and Visualization System

A modular Python application for adaptive flow velocity profiling in flumes using Velmex VXC XY stage and SonTek FlowTracker2 ADV (Acoustic Doppler Velocimeter).

## Features

- **Hardware Control**: Velmex VXC XY stage via ASCII serial protocol, SonTek FlowTracker2 10Hz velocity streaming
- **Adaptive Sampling**: Froude number-based sampling density adjustment for supercritical flow regions
- **Calibration**: Interactive press-and-hold jogging with automatic grid generation from origin/boundary points
- **State Management**: Pause/resume/stop with complete data preservation across sessions
- **Multi-Plane Acquisition**: Sequential Z-upstream measurements with run counter for repeated planes
- **Data Persistence**: HDF5 format for efficient storage, CSV/VTK export for analysis
- **3D Visualization**: Post-processing compilation of multi-plane datasets into flow fields

## Project Structure

```
vxc_adv_visualizer/
├── main.py                          # Entry point and orchestration
├── config/
│   ├── vxc_config.yaml              # Motor controller configuration
│   ├── adv_config.yaml              # ADV sensor configuration
│   └── experiment_config.yaml       # Measurement grid and analysis settings
├── controllers/
│   ├── vxc_controller.py            # Velmex XY stage driver
│   └── adv_controller.py            # SonTek FlowTracker2 driver
├── acquisition/
│   ├── calibration.py               # Grid calibration and generation
│   ├── sampler.py                   # Measurement orchestration (TODO)
│   └── synchronizer.py              # Motion-to-ADV synchronization
├── data/
│   ├── data_model.py                # DataRecord structure and statistics
│   ├── data_logger.py               # HDF5 storage with Z-plane support
│   └── exporters.py                 # CSV, HDF5, VTK export
├── visualization/
│   ├── live_plots.py                # Real-time pyqtgraph display (TODO)
│   └── profiles.py                  # Post-processing and 3D compilation
├── utils/
│   ├── flow_calculations.py         # Froude, turbulence intensity, unit conversion
│   ├── timing.py                    # Precise sleep and rate limiting
│   ├── serial_utils.py              # Serial port utilities
│   └── validation.py                # Data quality checks
└── gui/
    └── main_window.py               # PyQt5 main window (TODO)
```

## Installation

### Requirements

- Python 3.8+
- PySerial (hardware communication)
- h5py (data storage)
- NumPy (numerical processing)
- PyYAML (configuration files)
- PyQt5 (GUI) - optional for CLI mode
- pyqtgraph (live visualization) - optional

### Setup

```bash
# Clone repository
cd vxc_adv_visualizer

# Install dependencies
pip install pyserial h5py numpy pyyaml

# Optional: GUI and visualization
pip install PyQt5 pyqtgraph matplotlib
```

## Usage

### Basic Operation

```python
from main import main
main()
```

### Calibration Workflow (Interactive GUI)

1. **Home Position**: Move XY stage to safe starting location
2. **Bottom-Left Origin**: Jog to water bottom at left bank, press "Zero Origin"
3. **Top-Right Boundary**: Jog to water surface at right bank, press "Capture Boundary"
4. **Generate Grid**: Specify X/Y spacing and ROI zones, system generates measurement positions
5. **Save Calibration**: Calibration auto-saved to config file

### Measurement Workflow

1. **Load Experiment**: Select or create experiment configuration
2. **Start Acquisition**: Press "Start" to begin first Z-plane measurements
3. **Z-Plane Entry**: After each plane completes, enter upstream coordinate (Z value)
   - If unchanged from previous: saves as `plane_Z{value}_run{N}.h5` with incremented run counter
   - If changed: resets counter and saves as `plane_Z{value}_run1.h5`
4. **Pause/Resume**: Can pause mid-plane, motor stays in place, data preserved
5. **Emergency Stop**: Halts immediately, returns motor to (X_mid, Y_max)

### Configuration

Edit `config/experiment_config.yaml`:

```yaml
grid:
  x_spacing_feet: 0.1
  y_spacing_feet: 0.05

roi_zones:
  - name: "Turbulent Area"
    x_min_feet: 0.2
    x_max_feet: 0.5
    y_min_feet: 0.1
    y_max_feet: 0.4
    density_multiplier: 2.0  # 2x sampling in this zone

froude_threshold: 1.0
base_sampling_duration_sec: 10
max_sampling_duration_sec: 120
```

## Coordinate System

```
X-axis:   Bank-to-bank (0 = left bank, increasing rightward)
Y-axis:   Water depth (0 = bottom, positive upward to surface)
Z-axis:   Upstream position (user-specified per measurement plane)

Unit conversion: 4600 steps = 0.1 feet (46000 steps/foot)

Motor steps: Primary storage and display
Physical feet: Displayed with conversion factor shown
```

## Flow Analysis

### Froude Number

Calculated as: Fr = V / √(gh)

Where:
- V = velocity magnitude (m/s) from ADV
- g = 9.81 m/s²
- h = water depth (m) from depth sensor

**Adaptive Sampling**:
- Fr < 1.0 (Subcritical): Base 10s sampling
- Fr > 1.0 (Supercritical): Extended sampling (up to 120s) for improved statistics

### Data Quality

Each measurement includes:
- SNR (Signal-to-Noise Ratio): Minimum 5 dB required
- Correlation: Minimum 70% required
- Automatic retry up to 3 attempts with exponential backoff (0.5s → 1s → 2s)

## Data Storage

### HDF5 Format (During Acquisition)

File: `plane_Z{value}_run{N}.h5`

```
/ (root)
  ├── @z_plane: 0.5         # Z coordinate
  ├── @run_number: 2        # Run iteration
  ├── @created_timestamp    # Creation time
  └── measurements/
      ├── x_steps           # Motor X position (steps)
      ├── y_steps           # Motor Y position (steps)
      ├── u_mean, v_mean, w_mean     # Velocity (m/s)
      ├── u_std, v_std, w_std        # Velocity std dev
      ├── snr_mean, correlation_mean
      ├── velocity_magnitude
      ├── froude_number
      ├── turbulence_intensity
      └── [...]
```

### Export Formats

- **CSV**: Flat table for spreadsheet/plotting tools
- **VTK**: ParaView-compatible for 3D visualization
- **MATLAB**: .mat format for MATLAB analysis

## 3D Compilation

After acquiring multiple Z-planes:

```python
from visualization.profiles import compile_3d_flow

files = ['data/plane_Z0.5_run1.h5', 'data/plane_Z1.0_run1.h5']
output = compile_3d_flow(files, output_format='vtk')
# Opens in ParaView for interactive exploration
```

## Architecture Notes

### Design Principles

1. **Separation of Concerns**: Controllers talk to hardware only, samplers orchestrate acquisition, data layer handles storage
2. **Modular Hardware**: Swappable controller implementations without touching sampler or GUI
3. **Stateless Processing**: Each measurement self-contained; pause/resume works by position checkpoints
4. **Non-blocking UI**: Long operations run on separate threads, GUI remains responsive

### Error Handling

- **Exponential Backoff**: Serial communication failures retry with increasing delays (0.5s → 1s → 2s)
- **Data Quality Validation**: SNR/correlation checked; failed samples trigger retries
- **Graceful Degradation**: If ADV is temporarily unavailable, motor position is still recorded
- **Logging**: All operations logged with DEBUG/INFO/WARNING/ERROR levels

## Future Enhancements

- [ ] Live pyqtgraph heatmap with velocity magnitude coloring
- [ ] 3D visualization engine with ParaView export
- [ ] Batch mode for unattended operation
- [ ] Real-time Reynolds number and turbulence display
- [ ] Motion profile optimization (non-uniform grid density)
- [ ] Multi-depth scanning (Z as motor axis, not manual input)

## Troubleshooting

### COM Port Not Found
```python
from utils.serial_utils import list_available_ports
ports = list_available_ports()
print(ports)  # Check available ports
```

### Motion Timeout
- Verify VXC power supply and USB connection
- Check motor speeds in `vxc_config.yaml`
- Inspect mechanical for obstructions

### ADV No Data
- Verify probe is in water and powered
- Check SNR on handheld unit (should be > 40 dB)
- Inspect USB connection

## References

- [Velmex VXC Documentation](https://velmex.com/product/vxc)
- [SonTek FlowTracker2](https://www.sontek.com/flowtracker2)
- [VXC ASCII Command Protocol](https://velmex.com/support)

## License

[Specify your license here]

## Contact

Research team contact information
