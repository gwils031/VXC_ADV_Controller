# Development Roadmap

## Phase 1: Core Engine ✅ COMPLETE
All foundational modules implemented and documented.

**Completed:**
- [x] VXCController (375 lines) - Full ASCII protocol
- [x] ADVController (250 lines) - 10Hz streaming + depth sensor
- [x] DataRecord & DataLogger (500 lines) - HDF5 with Z-plane support
- [x] Sampler (530 lines) - Adaptive Froude-based orchestration
- [x] Calibration (250 lines) - Grid generation with ROI support
- [x] Synchronizer (150 lines) - Position verification
- [x] Utilities (500 lines) - Flow calculations, timing, serial, validation
- [x] Exporters (250 lines) - CSV, HDF5, VTK, MATLAB
- [x] Configuration (3 files) - YAML templates
- [x] Documentation (700 lines) - README, QUICKSTART, IMPLEMENTATION_STATUS

**Total: 3,395 lines of implemented code**

---

## Phase 2: GUI Implementation 🚀 NEXT PHASE
PyQt5-based user interface with real-time visualization.

### 2.1 Calibration Mode
**Estimated: 150 lines**

Features:
- [ ] Press-and-hold arrow buttons (50ms polling via QTimer)
- [ ] Direct coordinate input fields (X, Y steps or feet)
- [ ] Status label showing current position (dual units)
- [ ] "Zero Origin" button - capture bottom-left
- [ ] "Capture Boundary" button - capture top-right
- [ ] "Generate Grid" dialog:
  - X/Y spacing input (feet)
  - ROI zone editor (rectangular boxes)
  - Density multiplier slider (1.0-5.0x)
- [ ] "Save Calibration" button

### 2.2 Acquisition Mode
**Estimated: 200 lines**

Features:
- [ ] Start/Pause/Resume/Emergency Stop buttons
- [ ] Return Home button
- [ ] Live status panel:
  - Froude number (real-time)
  - Flow regime indicator (Subcritical/Supercritical)
  - Sampling logic display ("Fr=1.3 - Extended 45s sampling")
  - Current position (X, Y in steps and feet)
  - Water depth reading
  - Progress: "Position 5 of 23"
- [ ] Z-plane input dialog (after each plane):
  - Text field for Z coordinate
  - "Same as previous" option
  - Run counter display
- [ ] Data quality indicators:
  - SNR meter (live)
  - Correlation meter (live)
  - Valid samples counter

### 2.3 Visualization
**Estimated: 250 lines**

Features:
- [ ] 2D velocity heatmap using pyqtgraph
  - Update trigger: per-position measurement completion
  - Colormap: velocity magnitude (m/s)
  - Overlay: Froude number contours
  - Axis labels: X (feet/steps), Y (feet/steps)
  - Colorbar with statistics
- [ ] Live statistics panel:
  - Min/max/mean velocity
  - Velocity std deviation
  - Turbulence intensity
  - Mean SNR/Correlation

### 2.4 Configuration Editor
**Estimated: 100 lines**

Features:
- [ ] Tabbed interface:
  - Experiment settings (grid spacing, ROI zones)
  - Flow analysis (Fr threshold, sampling durations)
  - ADV parameters (SNR/Correlation thresholds)
  - VXC parameters (speed, acceleration)
  - Export options
- [ ] Load/Save configuration files
- [ ] Apply defaults button
- [ ] Experiment name input
- [ ] Data directory selector

### 2.5 Port Configuration
**Estimated: 75 lines**

Features:
- [ ] Auto-detect dropdown for VXC port
- [ ] Auto-detect dropdown for ADV port
- [ ] Refresh button to rescan ports
- [ ] Port test button (ping devices)
- [ ] Test results display (✓ Connected / ✗ Failed)
- [ ] Manual port input fallback

### 2.6 Export Controls
**Estimated: 75 lines**

Features:
- [ ] Export button opens file selector
- [ ] Format selection:
  - [ ] CSV (default)
  - [ ] HDF5
  - [ ] VTK (for ParaView)
  - [ ] MATLAB
- [ ] Export progress indicator
- [ ] Success notification with file path

### 2.7 Menu Bar
**Estimated: 50 lines**

Features:
- [ ] File menu:
  - New Experiment
  - Open Experiment
  - Recent Files (last 5)
  - Export
  - Exit
- [ ] Edit menu:
  - Preferences
  - Clear Data
- [ ] View menu:
  - Fullscreen heatmap
  - Show/hide panels
- [ ] Help menu:
  - About
  - Documentation
  - Troubleshooting

### 2.8 Application Architecture
**Estimated: 100 lines**

Features:
- [ ] QApplication setup
- [ ] Threading model:
  - Main thread: GUI events
  - Worker thread: Acquisition (via QThread)
- [ ] Signal/slot connections:
  - Hardware events → GUI updates
  - Button clicks → Sampler commands
  - Sampler callbacks → Status display
- [ ] Error dialog system
- [ ] Logging display panel (optional)

### 2.9 Unit Testing for GUI
**Estimated: 75 lines**

Tests:
- [ ] Port auto-detection
- [ ] Configuration loading/saving
- [ ] Button state transitions
- [ ] Mock hardware communication
- [ ] Data persistence after pause/resume

**Phase 2 Total: ~1,050 lines**

---

## Phase 3: Hardware Testing & Refinement
Validate on actual VXC and ADV devices.

### 3.1 VXC Integration Testing
- [ ] Test ASCII command protocol with actual motor
- [ ] Verify position tolerance (±1 step)
- [ ] Calibrate steps-per-foot conversion (4600/0.1 ft assumption)
- [ ] Test motion at various speeds
- [ ] Test emergency stop robustness
- [ ] Characterize motion timing

### 3.2 ADV Integration Testing
- [ ] Verify 10Hz sampling consistency
- [ ] Test depth sensor readings
- [ ] Measure SNR in various water conditions
- [ ] Test correlation values
- [ ] Characterize retry behavior

### 3.3 End-to-End Workflow Testing
- [ ] Full calibration on test flume
- [ ] Single-plane acquisition (10+ positions)
- [ ] Multi-plane acquisition (3 Z-planes)
- [ ] Pause/resume cycle
- [ ] Emergency stop recovery
- [ ] Data export and verification

---

## Phase 4: Advanced Features (Optional)
Post-MVP enhancements.

### 4.1 3D Visualization Engine
- [ ] Real-time 3D quiver plots with PyVista
- [ ] Isosurface rendering (velocity magnitude)
- [ ] Streamline generation
- [ ] Interactive point selection for detailed stats

### 4.2 Automated Flume Templating
- [ ] Predefined flume geometries:
  - Rectangular open channel
  - Prismatic channel
  - Custom polygon cross-section
- [ ] Auto-calibration from template + 2 points

### 4.3 Batch Processing
- [ ] Define multiple experiments
- [ ] Queue for unattended operation
- [ ] Resume on power loss / connection drop

### 4.4 Data Analysis Dashboard
- [ ] Reynolds number contours
- [ ] Shear stress estimation
- [ ] Boundary layer detection
- [ ] Vorticity field calculation

### 4.5 Real-Time Video Integration
- [ ] Sync camera feed with ADV data
- [ ] Overlay velocity vectors on video
- [ ] Time-aligned playback

---

## Timeline Estimate

| Phase | Duration | Status |
|-------|----------|--------|
| Phase 1: Core Engine | ✅ Complete | **Delivered** |
| Phase 2: GUI Implementation | 2-3 weeks | 🚀 Ready to start |
| Phase 3: Hardware Testing | 1-2 weeks | After Phase 2 |
| Phase 4: Advanced Features | 4+ weeks | Optional |

---

## Known Limitations & Technical Debt

### Current Limitations
- No GUI (placeholder only)
- 3D visualization not yet implemented (VTK export ready)
- No data backup during acquisition
- Single Z-plane file per run (no batch processing)

### Code Quality
- All docstrings complete ✅
- Type hints implemented ✅
- Error handling with exponential backoff ✅
- Logging instrumentation ✅
- Unit test framework needed ❌

### Performance Considerations
- HDF5 write throughput: ~1000 records/minute expected
- pyqtgraph heatmap update: <100ms per position
- 3D compilation: <5s for 5 Z-planes × 20 positions

---

## Dependencies Analysis

### Core (Required)
- pyserial >= 3.5 - Serial communication
- h5py >= 3.0 - HDF5 storage
- numpy >= 1.20 - Array operations
- pyyaml >= 5.4 - Configuration

### GUI (Phase 2)
- PyQt5 >= 5.15 - Application framework
- pyqtgraph >= 0.12 - Real-time visualization

### Visualization (Phase 4)
- matplotlib >= 3.3 - Static plotting
- scipy >= 1.7 - Advanced analysis (for MATLAB export)

### Optional
- pandas >= 1.2 - Data analysis convenience
- pytest >= 6.0 - Unit testing

---

## Git Commit Strategy

```
✅ Phase 1 Commits:
- feat: Add VXC and ADV controllers
- feat: Implement data model and logger
- feat: Add acquisition sampler with Froude-based adaptation
- feat: Implement calibration system
- feat: Add utility modules (flow calculations, timing, serial)
- docs: Add README, QUICKSTART, implementation status
- chore: Add requirements.txt and configuration templates

🚀 Phase 2 Commits (Planned):
- feat: Implement PyQt5 main window
- feat: Add calibration UI with jog controls
- feat: Add acquisition UI with status display
- feat: Integrate 2D heatmap visualization
- feat: Add configuration editor
- test: Add GUI unit tests

📊 Phase 3 Commits (Planned):
- test: Add VXC integration tests
- test: Add ADV integration tests
- fix: Calibration adjustments based on hardware
- docs: Add hardware-specific troubleshooting

✨ Phase 4 Commits (Optional):
- feat: Implement 3D visualization
- feat: Add flume templating system
- feat: Implement batch processing mode
```

---

## Code Review Checklist (Phase 2 PR)

- [ ] All functions documented with docstrings
- [ ] Type hints on function signatures
- [ ] Exception handling present
- [ ] Logging at DEBUG/INFO/WARNING/ERROR levels
- [ ] GUI responsive (non-blocking operations)
- [ ] Configuration loading/saving works
- [ ] Export functions produce valid files
- [ ] Unit tests pass
- [ ] No unused imports
- [ ] Code follows PEP 8 style

---

**Last Updated**: February 2, 2026
**Author**: Development Team
**Status**: Phase 1 Complete, Phase 2 Ready to Begin
