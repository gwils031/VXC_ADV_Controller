# VXC/ADV Hardware Testing Application

**Simplified testing interface for Velmex XY stage and SonTek FlowTracker2 ADV.**

## Quick Start

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Hardware** (edit YAML files):
   - `config/vxc_config.yaml` - VXC port and baudrate
   - `config/adv_config.yaml` - ADV port and communication settings

3. **Run Application**:
   ```bash
   python main.py
   ```

## Features

### VXC Controller Tab
- Connect/disconnect to VXC motor controller
- Real-time position display (X, Y in mm)
- Jog controls with 3 speeds: Slow (10), Medium (100), Fast (1000)
- Direct positioning: Enter target X/Y and go
- Zero current position
- Emergency stop

### ADV Streaming Tab
- Connect/disconnect to ADV sensor
- Start/stop data streaming
- Real-time velocity display (U, V, W in m/s)
- Quality metrics (SNR, Correlation)
- Sample counter
- Scrolling log of raw data

## Configuration

### VXC Configuration (`config/vxc_config.yaml`)
```yaml
port: COM8
baudrate: 57600
timeout: 2.0
```

### ADV Configuration (`config/adv_config.yaml`)
```yaml
port: COM9
baudrate: 9600
timeout: 2.0
line_ending: "\r\n"
start_command: "start"
stop_command: "stop"
expected_fields: 20
```

## Testing Workflow

### Test VXC Motor Control
1. Select VXC tab
2. Click "Refresh Ports" and select VXC port (e.g., COM8)
3. Click "Connect"
4. Verify position display updates (X: --- mm, Y: --- mm)
5. Use jog arrows to move stage:
   - Press and hold for continuous motion
   - Release to stop
   - Change step size as needed
6. Test direct positioning:
   - Enter X and Y coordinates
   - Click "Go To Position"
7. Test "Zero Position" to reset current position to (0, 0)
8. Test "Emergency Stop" to halt motion

### Test ADV Streaming
1. Select ADV tab
2. Select ADV port from dropdown
3. Click "Connect"
4. Click "Start Streaming"
5. Verify sample display updates:
   - U, V, W velocities (m/s)
   - SNR (dB)
   - Correlation (%)
   - Sample count increments
6. Monitor raw data in log window
7. Click "Stop Streaming" when done
8. Use "Clear Log" to reset log window

## Command-Line MVP

For standalone ADV testing without GUI:
```bash
python mvp/adv_stream_mvp.py
```

This minimal script:
- Connects to ADV using config settings
- Starts streaming
- Prints raw data or parsed samples
- Useful for debugging ADV communication

## Troubleshooting

### VXC Not Connecting
- Verify correct COM port in config
- Check baudrate (typically 57600 for Velmex)
- Ensure USB cable is connected
- Try different USB port
- Check Windows Device Manager for port number

### ADV Not Streaming
- Verify correct COM port and baudrate
- Check line_ending setting ("\r", "\n", or "\r\n")
- Verify start_command and stop_command
- Use MVP script to test ADV communication independently
- Check ADV power and USB connection

### Position Not Updating
- Verify VXC connection is active (green status)
- Check VXC is powered on
- Try disconnecting and reconnecting
- Check Windows Task Manager for resource usage

### Jog Not Working
- Ensure VXC is connected
- Verify position updates are working
- Try different step sizes
- Check for error messages in log

## Project Structure

```
vxc_adv_visualizer/
├── config/               # YAML configuration files
├── controllers/          # Hardware drivers (VXC, ADV)
├── gui/                  # PyQt5 main window
├── mvp/                  # Command-line test scripts
├── utils/                # Serial utilities
├── main.py              # Application entry point
└── requirements.txt     # Python dependencies
```

## Dependencies

- Python 3.7+
- PyQt5 5.15+
- pyserial 3.5+
- PyYAML

## Hardware

- **VXC**: Velmex XY BiSlide stage with VXM motor controller
- **ADV**: SonTek FlowTracker2 Acoustic Doppler Velocimeter

## Development

### Running Tests
```bash
# Test VXC controller
python -c "from controllers import VXCController; vxc = VXCController('COM8', 57600); print(vxc.get_position())"

# Test ADV controller  
python mvp/adv_stream_mvp.py
```

### Logging
Application logs to `vxc_adv_system.log` with timestamps and log levels.

### Extending
- Add new hardware: Create controller in `controllers/`
- Add new GUI features: Edit `gui/main_window.py`
- Add new utilities: Create modules in `utils/`

## References

- [VXC Controller Documentation](controllers/)
- [ADV Controller Documentation](controllers/)
- [Configuration Guide](config/)
- [Refactoring Summary](REFACTORING_SUMMARY.md)
