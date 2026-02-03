# 📚 Documentation Index

## Quick Navigation

### 🚀 Getting Started
1. **[COMPLETION_REPORT.md](COMPLETION_REPORT.md)** - What's been delivered (START HERE)
2. **[QUICKSTART.md](QUICKSTART.md)** - Installation, minimal examples, testing
3. **[README.md](README.md)** - Complete feature guide and usage documentation

### 📖 Reference Materials
4. **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** - Module breakdown, architecture decisions
5. **[ROADMAP.md](ROADMAP.md)** - Development phases, Phase 2 GUI specs

### 🎨 Phase 2: GUI Implementation (NEW)
6. **[../docs/PHASE2_COMPLETION_REPORT.md](../docs/PHASE2_COMPLETION_REPORT.md)** - GUI delivery summary
7. **[../docs/GUI_IMPLEMENTATION_GUIDE.md](../docs/GUI_IMPLEMENTATION_GUIDE.md)** - Architecture, tabs, data flow
8. **[../docs/GUI_TESTING_GUIDE.md](../docs/GUI_TESTING_GUIDE.md)** - 28 test cases with procedures
9. **[../docs/GUI_TROUBLESHOOTING_GUIDE.md](../docs/GUI_TROUBLESHOOTING_GUIDE.md)** - 100+ solutions

### 💻 Source Code

#### Entry Point
- **main.py** - Application orchestration, config loading, hardware init

#### GUI Components (Phase 2)
- **gui/main_window.py** - PyQt5 MainWindow class
  - 4 tabs: Calibration, Acquisition, Configuration, Export
  - Press-and-hold jog controls
  - Live status display with Froude number
  - 2D heatmap visualization (skeleton)
  - Multi-format data export
  - Non-blocking acquisition (worker thread)

#### Hardware Drivers
- **controllers/vxc_controller.py** - Velmex XY stage (VXC) driver
  - ASCII protocol implementation
  - Motion control, position queries
  - Exponential backoff retry

- **controllers/adv_controller.py** - SonTek FlowTracker2 ADV driver
  - 10Hz velocity streaming
  - Depth sensor integration
  - Data validation

#### Core Acquisition Engine
- **acquisition/sampler.py** - Main orchestration engine
  - Step-and-hold measurement workflow
  - Froude-based adaptive sampling
  - State machine (pause/resume)
  - Z-plane sequential workflow

- **acquisition/calibration.py** - Grid calibration system
  - Interactive origin/boundary capture
  - ROI (Region of Interest) zone support
  - Unit conversion (steps ↔ feet)

- **acquisition/synchronizer.py** - Motion-to-ADV synchronization
  - Position verification (±1 step)
  - Motion completion polling
  - Sample tagging with position metadata

#### Data Management
- **data/data_model.py** - Data structure definitions
  - ADVSample, MotionState, DataRecord classes
  - Automatic statistics calculation

- **data/data_logger.py** - HDF5 storage engine
  - Z-plane support with metadata
  - Run counter tracking
  - In-memory and persistent storage

- **data/exporters.py** - Multi-format export
  - CSV (spreadsheet)
  - HDF5 (Python/MATLAB)
  - VTK (ParaView 3D)
  - MATLAB .mat format

#### Utilities
- **utils/flow_calculations.py** - Hydraulic analysis
  - Froude number: Fr = V/√(gh)
  - Turbulence intensity: TI = σ_rms/V_mean
  - Adaptive sampling decision logic
  - Temperature-dependent viscosity

- **utils/timing.py** - Precise timing utilities
  - Rate limiter for 10Hz ADV
  - Precise sleep with minimal overhead

- **utils/serial_utils.py** - Serial communication helpers
  - COM port enumeration
  - Safe read/write operations

- **utils/validation.py** - Data quality checks
  - SNR and correlation thresholds
  - Invalid sample marking

#### Visualization
- **visualization/live_plots.py** - Real-time display interface
  - pyqtgraph integration point
  - Non-blocking update mechanism

- **visualization/profiles.py** - Post-processing visualization
  - 3D flow field compilation from multiple Z-planes
  - VTK export for ParaView
  - NumPy NPZ export

#### GUI (Phase 2 - Placeholder)
- **gui/main_window.py** - PyQt5 main window
  - Currently a placeholder
  - See ROADMAP.md Section 2 for specifications

### ⚙️ Configuration Files
- **config/vxc_config.yaml** - VXC motor parameters (port, speed, acceleration)
- **config/adv_config.yaml** - ADV sensor parameters (port, sampling rate, thresholds)
- **config/experiment_config.yaml** - Measurement configuration (grid spacing, ROI zones, Froude threshold)

### 📦 Metadata
- **requirements.txt** - Python package dependencies
- **README.md** - Full user guide
- **QUICKSTART.md** - Quick examples and troubleshooting
- **IMPLEMENTATION_STATUS.md** - Technical implementation details
- **COMPLETION_REPORT.md** - What's been delivered
- **ROADMAP.md** - Development roadmap
- **INDEX.md** - This file

---

## Document Reading Guide

### For New Users
1. Start with [COMPLETION_REPORT.md](COMPLETION_REPORT.md) - Understand what's done
2. Read [QUICKSTART.md](QUICKSTART.md) - Try minimal examples
3. Check [README.md](README.md) - Learn features and usage

### For Developers Extending the Code
1. Review [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) - Architecture overview
2. Check source code docstrings - Each function documented
3. Reference [ROADMAP.md](ROADMAP.md) - See planned features

### For Hardware Integration
1. See [QUICKSTART.md](QUICKSTART.md) "Testing Without Hardware" section
2. Check [QUICKSTART.md](QUICKSTART.md) "Common Operations" section
3. Follow [README.md](README.md) "Troubleshooting" section if issues

### For 3D Visualization
1. See [README.md](README.md) "3D Compilation" section
2. Check [visualization/profiles.py](visualization/profiles.py) docstrings
3. Reference export formats in [data/exporters.py](data/exporters.py)

### For Contributing to Phase 2 (GUI)
1. Read [ROADMAP.md](ROADMAP.md) Section 2 (Phase 2 Specifications)
2. Check [ROADMAP.md](ROADMAP.md) Section 3 (GUI Architecture)
3. Review existing callback system in [acquisition/sampler.py](acquisition/sampler.py)

---

## Code Architecture Overview

### Layered Design

```
┌─────────────────────────────────────┐
│   GUI (PyQt5) - Phase 2             │  ← Next to implement
│   [gui/main_window.py]              │
└──────────────┬──────────────────────┘
               │ (callbacks/signals)
┌──────────────▼──────────────────────┐
│   Acquisition Engine                │  ← Core
│   [acquisition/sampler.py]          │
│   ┌──────────────────────────────┐  │
│   │ State Machine               │  │
│   │ Froude-based Adaptation     │  │
│   │ Z-plane Sequential Workflow │  │
│   └──────────────────────────────┘  │
└──────────────┬──────────────────────┘
      ┌────────┼────────┬────────┐
      │        │        │        │
┌─────▼──┐ ┌──▼──────┐ ┌─▼──────┐ ┌──▼───────┐
│  VXC   │ │  ADV    │ │ Data   │ │ Utils    │
│Control │ │Control  │ │ Layer  │ │          │
└────────┘ └─────────┘ └────────┘ └──────────┘

Hardware ←────────────────────────→ Software
```

### Data Flow

```
User Interface (GUI)
    ↓
Sampler State Machine
    ├→ Move (VXCController)
    ├→ Sample (ADVController)
    ├→ Analyze (flow_calculations)
    ├→ Store (DataLogger → HDF5)
    └→ Visualize (pyqtgraph)
    
Post-Processing
    ├→ Export (CSV/VTK/HDF5)
    └→ 3D Compilation (multi-plane stacking)
```

---

## Key Concepts

### Froude Number
```
Fr = V / √(g·h)

Fr < 1.0: Subcritical (slower flow)
          → Standard 10s sampling

Fr > 1.0: Supercritical (faster flow, waves)
          → Extended 30-120s sampling
          
Calculated from: Live velocity (m/s) + depth sensor (m)
```

### Coordinate System
```
X: Bank-to-bank (0 = left bank)
Y: Water depth (0 = bottom, +Y = upward)
Z: Upstream position (user-specified)

Conversion: 4600 steps = 0.1 feet (46000 steps/foot)
```

### Adaptive Sampling Duration
```
Base: 10 seconds (subcritical)
Maximum: 120 seconds (highly supercritical)
ROI Multiplier: 1.0-5.0x in zones of interest

Example: Fr=1.4 in ROI → ~25s sampling
```

### Run Counter
```
First measurement of Z=0.5  → plane_Z0.5_run1.h5
Repeat Z=0.5 measurement   → plane_Z0.5_run2.h5
Different Z=1.0 measurement → plane_Z1.0_run1.h5 (counter resets)
```

---

## File Size Summary

| Category | Lines | Files |
|----------|-------|-------|
| Source Code | 3,095 | 17 |
| Documentation | 1,700+ | 6 |
| Configuration | ~50 | 3 |
| **Total** | **4,845+** | **26** |

---

## Quick Command Reference

### Installation
```bash
pip install -r requirements.txt
```

### Configuration
```bash
# Edit these files with your hardware COM ports:
nano config/vxc_config.yaml
nano config/adv_config.yaml
```

### Running
```bash
python main.py
```

### Testing (No Hardware)
```bash
# See QUICKSTART.md for complete examples
python -c "from utils.flow_calculations import calculate_froude; print(calculate_froude(0.5, 0.5))"
```

---

## Troubleshooting Navigation

- **COM Port Issues** → See QUICKSTART.md "Testing Without Hardware"
- **Motion Problems** → See README.md "Troubleshooting"
- **ADV Not Responding** → See README.md "Troubleshooting"
- **Data Not Saving** → See README.md "Troubleshooting"
- **Need Examples** → See QUICKSTART.md "Common Operations"

---

## Next Steps

### Immediate (This Week)
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Review COMPLETION_REPORT.md
- [ ] Run examples from QUICKSTART.md (no hardware needed)

### Short Term (Next 1-2 Weeks)
- [ ] Connect VXC motor via USB
- [ ] Connect ADV sensor via USB
- [ ] Update config files with your COM ports
- [ ] Test hardware communication (see QUICKSTART.md)
- [ ] Run calibration workflow

### Medium Term (2-3 Weeks)
- [ ] Implement Phase 2 GUI (see ROADMAP.md Section 2)
- [ ] Collect test data from your flume
- [ ] Export and analyze results

### Long Term (4+ Weeks)
- [ ] Implement optional Phase 4 features (ROADMAP.md Section 4)
- [ ] Develop domain-specific analysis tools
- [ ] Integrate with other flume instruments

---

**Last Updated**: February 2, 2026  
**Status**: Phase 1 Complete ✅ | Phase 2 Ready 🚀

See [COMPLETION_REPORT.md](COMPLETION_REPORT.md) for full status.
