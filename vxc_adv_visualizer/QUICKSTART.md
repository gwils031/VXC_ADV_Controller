# Quick Start Guide - VXC/ADV Flow Measurement System

## Installation

```bash
# Clone/navigate to project
cd vxc_adv_visualizer

# Install dependencies
pip install -r requirements.txt
```

## Hardware Setup

1. **Velmex VXC Stage**
   - Connect USB to computer
   - Note COM port (e.g., COM3)
   - Update `config/vxc_config.yaml` with port

2. **SonTek FlowTracker2 ADV**
   - Connect USB to computer
   - Immerse probe in water
   - Note COM port (e.g., COM4)
   - Update `config/adv_config.yaml` with port

## Minimal Working Example

```python
#!/usr/bin/env python
"""Minimal example: Connect, calibrate, sample one position."""

import logging
logging.basicConfig(level=logging.INFO)

from controllers import VXCController, ADVController
from acquisition.calibration import CalibrationManager
from acquisition.sampler import Sampler, SamplingPosition
from data.data_logger import DataLogger

# Initialize hardware
vxc = VXCController('COM3')
adv = ADVController('COM4')

if not vxc.connect():
    print("VXC connection failed")
    exit(1)

if not adv.connect():
    print("ADV connection failed")
    vxc.disconnect()
    exit(1)

# Calibration
calibration = CalibrationManager()

# Manual jog example (would use GUI in real application)
print("Moving to origin (bottom-left)")
vxc.set_speed(1000)
vxc.move_absolute(x=0, y=0)
vxc.wait_for_motion_complete()

calibration.set_origin(0, 0)

print("Moving to boundary (top-right)")
vxc.move_absolute(x=46000, y=46000)  # ~1 foot in each direction
vxc.wait_for_motion_complete()

calibration.set_boundary(46000, 46000)

# Generate grid (10 positions in 2x5 array)
grid = calibration.generate_grid(x_spacing_feet=0.1, y_spacing_feet=0.1)
positions = calibration.get_grid_positions()

print(f"Grid has {len(positions)} positions")

# Sample
data_logger = DataLogger()
sampler = Sampler(vxc, adv, data_logger, calibration)

# Start sampling
if not sampler.start_acquisition(z_plane=0.0, run_number=1):
    print("Failed to start acquisition")
    exit(1)

# Create position objects
sampling_positions = []
for x_steps, y_steps in positions[:3]:  # Sample first 3 positions
    x_feet = calibration.steps_to_feet(x_steps)
    y_feet = calibration.steps_to_feet(y_steps)
    sampling_positions.append(
        SamplingPosition(
            x_steps=x_steps,
            y_steps=y_steps,
            x_feet=x_feet,
            y_feet=y_feet,
            in_roi=False
        )
    )

sampler.initialize_measurement_sequence(sampling_positions)
sampler.run_measurement_sequence()

# Return home
sampler.return_home()

# Export
from data.exporters import export_csv, export_hdf5
records = data_logger.get_all()
export_csv(records, "./measurements.csv")
print(f"Exported {len(records)} records to measurements.csv")

# Cleanup
data_logger.close()
adv.disconnect()
vxc.disconnect()

print("Done!")
```

## Testing Without Hardware

```python
"""Test data model and processing without hardware."""

import numpy as np
from data.data_model import ADVSample, DataRecord
from data.data_logger import DataLogger
from utils.flow_calculations import calculate_froude

# Create mock samples
samples = []
for i in range(100):
    samples.append(ADVSample(
        u=0.3 + np.random.normal(0, 0.05),
        v=0.05 + np.random.normal(0, 0.02),
        w=0.0 + np.random.normal(0, 0.02),
        snr=45.0 + np.random.normal(0, 5),
        correlation=92.0 + np.random.normal(0, 2),
        depth=0.50,
        amplitude=1000,
        temperature=18.5,
        valid=True
    ))

# Create record
record = DataRecord.from_samples(
    x_steps=5000,
    y_steps=2500,
    x_feet=0.11,
    y_feet=0.05,
    z_plane=0.0,
    samples=samples,
    froude_number=0.45,  # Subcritical
)

print(f"Velocity magnitude: {record.velocity_magnitude:.3f} m/s")
print(f"Froude number: {record.froude_number:.2f}")
print(f"Turbulence intensity: {record.turbulence_intensity:.3f}")
print(f"Samples: {record.num_samples} ({record.valid_samples} valid)")

# Store to HDF5
logger = DataLogger()
logger.create_experiment(z_plane=0.0, run_number=1, experiment_name="test")
logger.append(record)
logger.close()

print("Test record saved to HDF5")
```

## Configuration Files

### vxc_config.yaml
```yaml
port: COM3
baudrate: 9600
max_speed_steps_per_sec: 5000
```

### adv_config.yaml
```yaml
port: COM4
baudrate: 9600
min_snr_db: 5.0
min_correlation_percent: 70.0
```

### experiment_config.yaml
```yaml
grid:
  x_spacing_feet: 0.1
  y_spacing_feet: 0.05

roi_zones:
  - name: "Turbulent Zone"
    x_min_feet: 0.2
    x_max_feet: 0.5
    y_min_feet: 0.1
    y_max_feet: 0.4
    density_multiplier: 2.0

froude_threshold: 1.0
base_sampling_duration_sec: 10
max_sampling_duration_sec: 120
```

## Common Operations

### Query Available COM Ports
```python
from utils.serial_utils import list_available_ports
ports = list_available_ports()
for port, description in ports:
    print(f"{port}: {description}")
```

### Get Motor Position
```python
pos = vxc.get_position()
print(f"Position: X={pos['X']} steps, Y={pos['Y']} steps")
```

### Read Single ADV Sample
```python
adv.start_stream()
sample = adv.read_sample()
print(f"u={sample.u:.3f}, v={sample.v:.3f}, w={sample.w:.3f} m/s")
print(f"SNR={sample.snr:.1f} dB, Correlation={sample.correlation:.1f}%")
print(f"Depth={sample.depth:.2f} m")
adv.stop_stream()
```

### Calculate Froude Number
```python
from utils.flow_calculations import calculate_froude

velocity = 0.35  # m/s
depth = 0.50     # m
fr = calculate_froude(velocity, depth)
print(f"Fr = {fr:.2f} ({'Supercritical' if fr > 1.0 else 'Subcritical'})")
```

### Convert Units
```python
from acquisition.calibration import STEPS_PER_FOOT

# Steps to feet
feet = 5000 / STEPS_PER_FOOT
print(f"5000 steps = {feet:.3f} feet")

# Feet to steps
steps = 0.1 * STEPS_PER_FOOT
print(f"0.1 feet = {int(steps)} steps")
```

### Export Data
```python
from data.exporters import export_csv, export_hdf5, export_vtk

records = data_logger.get_all()

# CSV (for Excel/plotting)
export_csv(records, "./flow_data.csv")

# HDF5 (for Python/MATLAB analysis)
export_hdf5(records, "./flow_data.h5")

# VTK (for ParaView 3D visualization)
export_vtk(records, "./flow_data.vtk")
```

## Troubleshooting

### ADV showing "No response"
```python
# Check if ADV stream is actually available
adv.flush_buffer()  # Clear any stale data
sample = adv.read_sample()
if sample:
    print(f"ADV responding: {sample.u:.3f} m/s")
else:
    print("ADV not responding - check power and USB connection")
```

### Motor not moving
```python
# Verify motion is not already in progress
is_moving = vxc.is_motion_complete()
print(f"Motion complete: {is_moving}")

# Check current position
pos = vxc.get_position()
print(f"Current position: {pos}")

# Try emergency stop
vxc.stop_motion()
```

### Data file not created
```python
import os
# Check directory exists
os.makedirs("./data", exist_ok=True)

# Check write permissions
try:
    with open("./data/test.txt", "w") as f:
        f.write("test")
    print("Write permissions OK")
except Exception as e:
    print(f"Permission error: {e}")
```

---

**For full documentation, see README.md**
