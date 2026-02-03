# VXC/ADV GUI Quick Reference Card

## Keyboard & Control Shortcuts

### Jog Controls
```
↑ (Y+)    Y+ : Increase water depth
← (X-)    X- : Move left (toward Y=0 edge)
→ (X+)    X+ : Move right
↓ (Y-)    Y- : Decrease water depth (toward bottom)
```

### Button Operations

| Tab | Button | Action | Shortcut |
|-----|--------|--------|----------|
| Cal | Refresh Ports | Auto-detect COM ports | F5 |
| Cal | Connect | Initialize VXC + ADV | Ctrl+C |
| Cal | Zero Origin | Set (0,0) at current position | -- |
| Cal | Capture Boundary | Set grid extent | -- |
| Cal | Generate Grid | Create measurement positions | -- |
| Acq | Start Acquisition | Begin measurement sequence | Ctrl+S |
| Acq | Pause | Freeze current position | Space |
| Acq | Resume | Continue from pause | Space |
| Acq | Emergency Stop | Immediate halt (red) | Esc |
| Acq | Return Home | Move to origin | Ctrl+H |
| Cfg | Save Configuration | Persist settings to YAML | Ctrl+S |
| Cfg | Load Defaults | Reset to factory settings | Ctrl+R |
| Exp | Export Data | Save to CSV/HDF5/VTK | Ctrl+E |

## Common Workflows

### Quick Calibration (2 minutes)

```
1. Connect hardware
   └─ Click "Connect" button
   
2. Position at origin (0,0)
   └─ Use jog controls (fine steps)
   └─ Click "Zero Origin"
   
3. Position at top-right corner
   └─ Use direct input: X=10000, Y=5000
   └─ Click "Go to Position"
   └─ Click "Capture Boundary"
   
4. Generate grid
   └─ X Spacing: 0.10 ft
   └─ Y Spacing: 0.05 ft
   └─ Click "Generate Grid"
   └─ Result: "Generated 21 positions"
```

### Standard Measurement (30-60 minutes for 9-position grid)

```
1. [Calibration complete from above]

2. Start acquisition
   └─ Click "Start Acquisition"
   └─ Dialog: "Enter Z-plane coordinate"
   └─ Type: 0.500
   └─ Click OK
   
3. Monitor acquisition
   └─ Watch State: MOVING → SAMPLING → MOVING
   └─ Note Froude Number changes
   └─ Progress bar advances per position
   
4. Pause if needed
   └─ Click "Pause"
   └─ [Motor holds position, data saved]
   └─ Click "Resume" to continue
   
5. After completion
   └─ GUI prompts: "Next Z-plane?"
   └─ For more planes: Enter new Z, repeat
   └─ Or finish: Go to Export tab
   
6. Export data
   └─ Select format: CSV | HDF5 | VTK | All
   └─ Click "Export Data"
   └─ Choose output filename
   └─ Success message displayed
```

### Emergency Recovery (any time)

```
If problems occur:
1. Press "Emergency Stop" (red button)
2. Motor immediately stops
3. Data from completed positions saved
4. GUI returns to IDLE state
5. Click "Return Home" to reset position
6. Resume from previous Z-plane or start new
```

## Status Label Meanings

### State Display
| State | Meaning | Action |
|-------|---------|--------|
| IDLE | Ready for measurement | Click "Start Acquisition" |
| MOVING | Motor traveling to position | Wait... |
| SAMPLING | Collecting ADV data | Takes 10-120s per position |
| PAUSED | Acquisition suspended | Click "Resume" |
| CALIBRATING | Setting origin/boundary | Position motor as needed |
| ERROR | Problem detected | Check error message |

### Froude Number (Fr)
| Range | Regime | Sampling |
|-------|--------|----------|
| Fr < 1.0 | **Subcritical** | Base (10s) |
| Fr ≈ 1.0 | **Critical** | Base (10s) |
| Fr > 1.0 | **Supercritical** | Extended (60-120s) |

### Depth Sensor
```
Shows water depth from ADV pressure sensor
Unit: meters
Typical range: 0.1-3.0 m
```

## Configuration Quick Reference

### Grid Settings
```yaml
X Spacing: 0.10 feet  (typical: 0.05-0.20)
Y Spacing: 0.05 feet  (typical: 0.05-0.15)
```

### Froude Threshold
```yaml
Froude Threshold: 1.0  (cannot change - physics constant)
Base Sampling: 10 sec  (typical: 5-20 sec)
Extended Sampling: 120 sec  (typical: 60-180 sec)
```

### ADV Quality Thresholds
```yaml
Min SNR: 5.0 dB       (lower → accepts noisier data)
Min Correlation: 70%  (lower → accepts less confident estimates)
```

## Data Files

### Generated Files

```
measurements_Z0.5_run1.h5  ← HDF5 (during acquisition)
├─ Attributes:
│  ├─ z_plane: 0.5
│  ├─ run_number: 1
│  └─ timestamp: 2024-01-15T10:30:45
├─ /measurements/ group
│  ├─ position_x (steps)
│  ├─ position_y (steps)
│  ├─ velocity_mag (m/s)
│  ├─ froude_number
│  └─ ...

measurements.csv  ← Spreadsheet export
X_steps,Y_steps,X_feet,Y_feet,V_mean,V_std,Fr,...
0,0,0.000,0.000,0.25,0.03,0.85,...
...

measurements.vtk  ← ParaView 3D visualization
measurements_3d.h5  ← Multi-plane stack (Phase 3)
```

## Port Selection Guide

### Typical Configuration

```
VXC Port:  COM3 (USB)
ADV Port:  COM4 (USB)
```

### If Different
```
1. Click "Refresh Ports"
2. Note description next to port:
   - "Velmex" → VXC
   - "SonTek" or "FlowTracker" → ADV
3. Select correct port for each
4. Click "Connect"
```

### Port Detection Fails?
```
Troubleshooting:
1. Ensure USB cables connected
2. Check Device Manager (Windows):
   - Dev Mgr → Ports (COM & LPT)
   - Look for COM ports with USB description
3. Try different USB hub port
4. Restart application
5. See GUI_TROUBLESHOOTING_GUIDE.md
```

## Performance Notes

### Jog Response
- Fine stepping: ~1-2 steps/click
- Medium stepping: ~10-20 steps/click
- Coarse stepping: ~100-200 steps/click
- All "instantaneous" from user perspective

### Acquisition Timing
```
Time per position = Movement + Sampling

For typical 2×2 ft grid (21 positions, 0.1 ft spacing):
├─ Subcritical flow: ~21 × 15s = 315s ≈ 5-6 min
└─ Mixed flow: ~21 × 35s (avg) = 735s ≈ 12 min

Extended sampling adds 50-110s per supercritical position
```

### Memory Usage
```
GUI: ~100-150 MB
Per measurement: ~1-2 KB
HDF5 file growth: ~1 KB per sample
1000-position grid: ~2-5 MB on disk
```

## Troubleshooting Checklist

### GUI Won't Start
```
☐ Python installed? (python --version)
☐ PyQt5 installed? (pip install PyQt5)
☐ Run from correct directory? (cd vxc_adv_visualizer)
☐ Check console for error messages
```

### Hardware Won't Connect
```
☐ USB cables connected?
☐ Devices powered on?
☐ Correct COM ports selected?
☐ Click "Refresh Ports" first
☐ Check Device Manager for port list
```

### Motor Won't Move
```
☐ "Connect" button clicked?
☐ Motor power supply on?
☐ Jog buttons enabled? (not grayed out)
☐ No mechanical obstruction?
☐ Try fine steps first
```

### No ADV Data
```
☐ Probe in water?
☐ Probe powered on?
☐ Correct ADV port selected?
☐ SNR/Correlation above thresholds?
☐ Probe window clean?
```

## Advanced Tips

### Custom Grid Spacing
```
For dense sampling in ROI:
1. Run standard grid (0.1 ft spacing)
2. Note positions of interest
3. Edit experiment_config.yaml
4. Change spacing: 0.05 ft
5. Re-calibrate, re-sample ROI
6. Merge data manually (advanced users)
```

### Multi-Plane Z-Stack
```
1. Measure at Z = 0.0 ft
   └─ Export as measurement_Z0.0_run1.csv
2. Measure at Z = 0.5 ft
   └─ Export as measurement_Z0.5_run1.csv
3. Measure at Z = 1.0 ft
   └─ Export as measurement_Z1.0_run1.csv
4. In Phase 3:
   └─ Use "Compile Z-planes to 3D"
   └─ Open in ParaView for 3D visualization
```

### Repeated Measurements
```
For same position, different time:
1. First measurement:
   └─ Z = 0.5, Run 1 (auto-created)
2. Return to same position
3. Measure again:
   └─ Z = 0.5, Run 2 (auto-incremented)
   
Files created:
measurements_Z0.5_run1.h5
measurements_Z0.5_run2.h5

[Can compare time-series variations]
```

## Support

### First Time?
👉 Read: [QUICKSTART.md](QUICKSTART.md)

### Need Help?
👉 Read: [GUI_TROUBLESHOOTING_GUIDE.md](../docs/GUI_TROUBLESHOOTING_GUIDE.md)

### Want Details?
👉 Read: [GUI_IMPLEMENTATION_GUIDE.md](../docs/GUI_IMPLEMENTATION_GUIDE.md)

### Test Before Deploy?
👉 Run: [GUI_TESTING_GUIDE.md](../docs/GUI_TESTING_GUIDE.md)

---

**Version**: 1.0  
**Print-Friendly**: Yes (fits on 2 pages @ 10pt font)  
**Last Updated**: Phase 2 Release
