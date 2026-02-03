# GUI Troubleshooting Guide

## Installation Issues

### ImportError: No module named 'PyQt5'

**Symptom**:
```
ModuleNotFoundError: No module named 'PyQt5'
```

**Solution**:
```bash
pip install PyQt5>=5.15.0
# Or install all requirements
pip install -r requirements.txt
```

### ImportError: No module named 'pyqtgraph'

**Symptom**:
```
ModuleNotFoundError: No module named 'pyqtgraph'
```

**Solution**:
```bash
pip install pyqtgraph>=0.13.0
```

### ImportError: Cannot import name 'VXCController' from 'controllers'

**Symptom**:
```
ImportError: cannot import name 'VXCController' from 'controllers' 
(c:\...\vxc_adv_visualizer\controllers\__init__.py)
```

**Cause**: Module imports not properly configured in `controllers/__init__.py`

**Solution**:
```python
# controllers/__init__.py
from .vxc_controller import VXCController
from .adv_controller import ADVController

__all__ = ["VXCController", "ADVController"]
```

## Connection Issues

### "No serial ports available" error

**Symptom**: Application shows no COM ports in dropdown

**Diagnosis**:
```python
# Check available ports in Python
from utils.serial_utils import list_available_ports
ports = list_available_ports()
print(ports)  # Should show list of (port, description) tuples
```

**Solutions**:

1. **Verify USB connection**:
   - Check physical cables
   - Try different USB port
   - Check Windows Device Manager for "USB Serial Port"

2. **Install CH340 drivers** (if using USB-to-serial converters):
   - Download from: https://github.com/WCHSoftware/ch341ser
   - Install and restart

3. **Reset USB hub**:
   - Disconnect all USB devices
   - Wait 10 seconds
   - Reconnect devices

### "Failed to connect VXC on COM3" error

**Symptom**: Connection dialog shows error after clicking Connect

**Diagnosis**:
```python
# Test direct connection
from controllers.vxc_controller import VXCController
vxc = VXCController('COM3')
if vxc.connect():
    print("Connected successfully")
    pos = vxc.get_position()
    print(f"Position: {pos}")
else:
    print("Connection failed")
```

**Solutions**:

1. **Check port settings**:
   - Default: 9600 baud, 8 data bits, 1 stop bit, no parity
   - Verify in Device Manager → Port Settings

2. **Try different port**:
   ```bash
   # List all COM ports with detailed info
   powershell "Get-WMIObject Win32_SerialPort | Select-Object Name, Description"
   ```

3. **Reset VXC controller**:
   - Disconnect USB
   - Wait 10 seconds
   - Power cycle VXC unit
   - Reconnect USB
   - Try again

4. **Check VXC firmware**:
   - Velmex VXC requires ASCII mode (default)
   - Verify with manufacturer if unsure

### "Failed to connect ADV on COM4" error

**Symptom**: VXC connects but ADV fails

**Diagnosis**:
```python
from controllers.adv_controller import ADVController
adv = ADVController('COM4')
if adv.connect():
    print("Connected successfully")
    sample = adv.read_sample()
    print(f"Sample: {sample}")
else:
    print("Connection failed")
```

**Solutions**:

1. **Verify ADV baud rate** (typically 19200):
   ```python
   # In controllers/adv_controller.py
   ser = serial.Serial(port, baudrate=19200, timeout=1)
   ```

2. **Check probe power**:
   - ADV requires separate power supply
   - LED indicator should be lit
   - Verify battery/power connection

3. **Probe positioning**:
   - Probe must be in water for communication
   - May auto-initialize when water-immersed
   - Check probe window for obstructions

## Hardware Movement Issues

### Motor doesn't move during jog

**Symptom**: Click jog buttons but motor doesn't respond

**Diagnosis**:
```python
# Test direct movement
vxc.move_relative(dx=100)  # Move 100 steps
vxc.wait_for_motion_complete(timeout=10)
pos = vxc.get_position()
print(f"New position: {pos}")
```

**Solutions**:

1. **Check motor power**:
   - VXC unit status light
   - Connection to XY stage
   - Power supply voltage

2. **Check software connection state**:
   - Ensure "Connect" button was clicked
   - Check if jog buttons are enabled
   - Verify position label shows values

3. **Motor limits**:
   - Some positions may be out of range
   - Try moving to 500 steps with direct input
   - Check if motor is stalled

### Motion is very slow

**Symptom**: Jog movement takes >1 second per step

**Diagnosis**:
```python
# Check motor speed setting
pos1 = vxc.get_position()
vxc.move_relative(dx=100)
vxc.wait_for_motion_complete(timeout=10)
pos2 = vxc.get_position()
# If pos2 == pos1, motion never occurred
```

**Solutions**:

1. **Verify speed setting** in VXC config:
   ```yaml
   # vxc_config.yaml
   speed:
     x_speed: 10  # steps per second
     y_speed: 10
   ```

2. **Increase step speed**:
   ```python
   vxc.set_speed(x_speed=50, y_speed=50)  # Faster
   ```

3. **Check mechanical friction**:
   - Stage rails clean?
   - Proper lubrication?
   - Any obstructions?

### Motion timeout ("Timeout waiting for motion complete")

**Symptom**: Motor moves but GUI shows timeout after 60s

**Diagnosis**:
```python
# Check if motion actually completes
vxc.move_relative(dx=1000)
start = time.time()
while not vxc.is_motion_complete():
    time.sleep(0.1)
elapsed = time.time() - start
print(f"Motion took {elapsed:.1f} seconds")
```

**Solutions**:

1. **Increase timeout** in sampler:
   ```python
   # acquisition/sampler.py
   MOTION_TIMEOUT = 120  # seconds (default 60)
   ```

2. **Check motor stall**:
   - Mechanical obstruction?
   - Motor coil temperature high?
   - Try manually pushing stage

3. **Verify communication**:
   - Check serial port is not blocked by other software
   - Restart hardware connection

## ADV Data Quality Issues

### "Low SNR" warnings during acquisition

**Symptom**: Status shows "ADV: Signal Quality (SNR=2.1 dB < 5.0 dB)"

**Solutions**:

1. **Reposition probe**:
   - Move probe closer to seeded particles
   - Reduce angle from flow direction
   - Ensure probe is not touching walls

2. **Check probe window**:
   - Optical window dirty?
   - Clean gently with distilled water
   - Verify no air bubbles around tip

3. **Adjust sampling parameters**:
   ```yaml
   # experiment_config.yaml
   adv:
     min_snr_db: 3.0  # Lower threshold (was 5.0)
     min_correlation_percent: 60.0  # Lower threshold (was 70.0)
   ```

4. **Check seeding**:
   - Water lacks particles/bubbles?
   - Add tracer particles (glass beads ~100μm)
   - Check particle concentration

### "Low Correlation" warnings

**Symptom**: Status shows "ADV: Correlation (64% < 70.0%)"

**Solutions**:

1. **Increase burst length**:
   ```python
   # In sampler.py
   num_samples = 200  # More samples for averaging
   ```

2. **Reduce sampling rate**:
   - Lower ADV frequency
   - More time between measurements

3. **Check water conditions**:
   - Turbulence reducing correlation?
   - Temperature variations?
   - Sediment content?

### No ADV data appearing

**Symptom**: Sampling shows "SAMPLING" state but no data updates

**Diagnosis**:
```python
# Check ADV directly
adv = ADVController('COM4')
adv.connect()
adv.start_stream()
for i in range(10):
    sample = adv.read_sample()
    print(sample)
adv.stop_stream()
```

**Solutions**:

1. **Probe not initialized**:
   - Ensure probe is water-immersed
   - Wait 30 seconds for initialization
   - Check LED indicators

2. **Serial port conflict**:
   - Close other serial applications
   - Restart ADV connection
   - Check Device Manager for COM port conflicts

3. **Incorrect ADV port**:
   - Verify selected COM port
   - Try alternate port selection
   - Swap VXC/ADV port assignments

## GUI Responsiveness Issues

### GUI freezes during acquisition

**Symptom**: Window becomes unresponsive, "Not Responding" in title bar

**Cause**: Blocking operation on main thread

**Solution**:
- GUI uses worker thread for acquisition
- If still freezing, check:
  ```python
  # In AcquisitionWorker.run()
  # Should NOT call blocking Qt methods
  # Use self.emit(signal) instead
  ```

### Status labels don't update

**Symptom**: Position and Froude labels show old values

**Diagnosis**:
- Check if `_on_position_sampled()` is being called

**Solutions**:

1. **Verify signal connection**:
   ```python
   # In _start_acquisition()
   self.sampler.on_position_sampled = self._on_position_sampled
   # Should be set before calling run_measurement_sequence()
   ```

2. **Check Sampler callbacks**:
   ```python
   # In sampler.py, verify these are being called:
   self.on_position_sampled(record)  # After each position
   self.on_state_changed(state)      # On state transition
   self.on_status_update(message)    # On status change
   ```

### Heatmap visualization empty

**Symptom**: Acquisition running but heatmap shows no data

**Solutions**:

1. **Verify data collection**:
   - Check if `on_position_sampled()` is called
   - Verify records contain velocity data

2. **Update heatmap code**:
   ```python
   # Skeleton in current implementation
   def _on_position_sampled(self, record):
       # TODO: Update heatmap grid
       # self.heatmap_view.setImage(grid_data)
   ```

## File I/O Issues

### HDF5 file not created

**Symptom**: Acquisition completes but no .h5 file

**Diagnosis**:
```python
# Check data_logger state
print(f"HDF5 file: {self.data_logger.current_file}")
print(f"Records: {len(self.data_logger.get_all())}")
```

**Solutions**:

1. **Check file permissions**:
   - Output directory writable?
   - Try creating test file in directory

2. **Verify DataLogger initialization**:
   ```python
   # In _start_acquisition()
   self.data_logger = DataLogger()
   self.sampler = Sampler(..., self.data_logger)
   # data_logger must be passed to sampler
   ```

3. **Check filename**:
   ```python
   # File should be named based on Z-plane
   # Example: measurements_Z0.5_run1.h5
   ```

### CSV export shows incorrect columns

**Symptom**: CSV missing velocity columns or wrong values

**Solutions**:

1. **Verify export function**:
   ```python
   # In data/exporters.py
   # Column order should match DataRecord fields
   ```

2. **Check data types**:
   - Velocity in m/s?
   - Position in feet?
   - Froude dimensionless?

## Configuration Issues

### Configuration not persisting between sessions

**Symptom**: Settings reset when app restarts

**Solutions**:

1. **Check save operation**:
   ```python
   # In _save_config()
   filepath = os.path.join(self.config_dir, 'experiment_config.yaml')
   # File should exist after save
   ```

2. **Verify YAML format**:
   ```bash
   cat config/experiment_config.yaml
   # Should contain valid YAML structure
   ```

3. **File permissions**:
   - config/ directory writable?
   - Try saving to Desktop
   - Check for file locks

### "Configuration not found" warnings

**Symptom**: Log shows multiple "Configuration file not found" warnings

**Solutions**:

1. **Create default configs**:
   ```bash
   cd vxc_adv_visualizer
   mkdir -p config
   # Copy template files from docs/
   cp ../docs/templates/*.yaml config/
   ```

2. **Check config directory path**:
   ```python
   import os
   config_dir = os.path.join(os.getcwd(), 'config')
   print(f"Looking in: {config_dir}")
   print(f"Exists: {os.path.exists(config_dir)}")
   print(f"Files: {os.listdir(config_dir)}")
   ```

## Performance Issues

### Application startup takes >10 seconds

**Solutions**:

1. **Check import times**:
   ```bash
   python -X importtime main.py 2>&1 | grep -E "\.py|cumulative"
   ```

2. **Lazy load heavy modules**:
   - Move imports inside functions
   - Don't import visualization unless needed

### Memory grows during long acquisitions

**Symptom**: After sampling 100+ positions, memory usage increases

**Solutions**:

1. **Check for data leaks**:
   ```python
   # In Sampler._collect_samples()
   # Ensure ADV sample lists are cleared after averaging
   ```

2. **Monitor HDF5 file**:
   - File size growing correctly?
   - Each record should be ~100 bytes
   - 1000 records = ~100 KB

3. **Clear UI cache**:
   ```python
   # If heatmap accumulates old data
   self.heatmap_view.clear()
   ```

## Debug Mode

### Enable verbose logging

```python
# In main.py
logging.basicConfig(level=logging.DEBUG)  # Changed from INFO
```

### Log file inspection

```bash
# After running application
tail -100 vxc_adv_system.log
# Look for ERROR, WARNING levels
grep -E "ERROR|WARNING" vxc_adv_system.log
```

### Hardware debug output

```python
# Patch VXCController to show all commands
# In controllers/vxc_controller.py
def _send_command(self, command, retry_count=0):
    print(f"SEND: {command}")  # Add this
    response = ...
    print(f"RECV: {response}")  # Add this
    return response
```

## Getting Help

1. **Check logs**: `vxc_adv_system.log`
2. **Review test cases**: `docs/GUI_TESTING_GUIDE.md`
3. **Consult implementation**: `docs/GUI_IMPLEMENTATION_GUIDE.md`
4. **Hardware documentation**:
   - Velmex VXC manual
   - SonTek FlowTracker2 manual

---

**Last Updated**: Phase 2 Release  
**Version**: 1.0
