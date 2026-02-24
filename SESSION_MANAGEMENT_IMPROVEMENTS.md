# Session Management Issues & Scientific Improvements
## Analysis and Recommendations

**Date:** February 24, 2026  
**Issue:** Session lifecycle tied to monitoring, preventing proper experimental grouping

---

## 🔴 CRITICAL ISSUES IDENTIFIED

### Issue #1: Session Never Ends During Monitoring

**Current Behavior:**
- User clicks "Monitor and Auto-Merge" → Auto-creates a session
- Session remains active until monitoring stops
- All data flows into one continuously growing session file
- Live Data tab shows **all measurements since monitoring started**

**Problem:**
```
Time 09:00 - Start monitoring → Session "Session_20260224_090000" created
Time 09:30 - Measure Grid A (9 points)
Time 10:00 - Measure Grid B (12 points)  ← Still same session!
Time 11:00 - Measure Grid C (9 points)   ← Still same session!
Time 12:00 - Stop monitoring → Session ends with 30 mixed measurements
```

**Scientific Impact:**
- Cannot separate different experimental conditions
- Cannot compare "before" vs "after" measurements
- Cannot isolate calibration runs from measurement runs
- All data mixed together in one file

### Issue #2: No Independent Session Control

**Current UI:**
- "New Session" button - Only works when no session active
- When monitoring starts, button becomes disabled
- No "End Session" button exists
- Only way to end session: Stop monitoring entirely

**Problem:**  
User cannot create logical measurement groups without stopping and restarting the entire monitoring system.

### Issue #3: Session Auto-Creation Without User Intent

**Location:** [auto_merge_tab.py](vxc_adv_visualizer/gui/auto_merge_tab.py#L433-453)

```python
def _start_monitoring(self):
    # Check for active session or create one
    if self.session_manager is None or not self.session_manager.is_active():
        # Auto-create session
        session_name = self.session_name_edit.text().strip() or self._generate_default_session_name()
        # ... creates session automatically
```

**Problem:**
- Session created automatically when monitoring starts
- User may not realize a session is active
- Generic timestamp-based name if user didn't enter one
- No explicit "Yes, I want to start collecting data for this experiment"

### Issue #4: Live Data Accumulation

**Consequence of Issue #1:**
- Live Data tab receives `averaged_grid_data.csv` file path
- This file keeps appending forever during session
- My recent fix groups by location (good!) but across entire session history
- If user measures same location in Grid A and Grid C, they get combined

**Example:**
```
09:30 - Measure location (0.5m, 0.2m) during Grid A → 100 samples
11:00 - Measure location (0.5m, 0.2m) during Grid C → 98 samples
Live Data shows: (0.5m, 0.2m) with 198 samples combined

But Grid A and Grid C are DIFFERENT experiments!
```

---

## ✅ SCIENTIFICALLY VIABLE SOLUTION

### Design Principles

1. **Session = Experiment** - One session groups measurements for one specific purpose
2. **Explicit Control** - User must explicitly start and end sessions
3. **Monitoring ≠ Session** - Monitoring can run continuously; sessions are logical groupings
4. **Data Isolation** - Each session produces independent, analyzable dataset

### Recommended Session Lifecycle

```
User Workflow:

1. Start Application
   └─ Start Monitoring (always on, watching for files)
   
2. Begin Experiment Run
   ├─ Enter Session Name: "Baseline_Calibration"
   ├─ Enter Operator, Notes
   ├─ Click "Start Session"
   └─ Session folder created, files initialized
   
3. Collect Data
   ├─ Move VXC to grid points
   ├─ Collect ADV data at each point
   ├─ Auto-merge appends to this session
   └─ Live Data shows THIS SESSION ONLY
   
4. End Experiment Run
   ├─ Click "End Session"
   ├─ Metadata written, statistics calculated
   ├─ Session files closed
   └─ Ready for next session
   
5. Begin New Experiment Run
   ├─ Enter Session Name: "High_Flow_Test_Run1"
   ├─ Click "Start Session"
   └─ Fresh session, clean slate

6. Continue...
   (Monitoring never stops, just sessions change)
```

---

## 🔧 IMPLEMENTATION CHANGES

### Change #1: Decouple Monitoring from Session

**Current:** Monitoring start → Auto-create session  
**Fixed:** Monitoring and session are independent

```python
def _start_monitoring(self):
    # ... setup monitoring ...
    
    # DO NOT auto-create session here
    # User must explicitly click "Start Session"
    
    # If no session active, show warning
    if not self.session_manager or not self.session_manager.is_active():
        self._log_activity(
            "⚠️ Monitoring active but NO SESSION. Data will be saved individually. "
            "Start a session to group measurements.",
            "warning"
        )
```

### Change #2: Add Session Control Buttons

**New UI Elements:**

```python
# Session control buttons (always enabled)
self.start_session_btn = QPushButton("Start Session")
self.start_session_btn.clicked.connect(self._start_session)
self.start_session_btn.setStyleSheet("background-color: #28a745; color: white;")

self.end_session_btn = QPushButton("End Session")
self.end_session_btn.clicked.connect(self._end_session)
self.end_session_btn.setStyleSheet("background-color: #dc3545; color: white;")
self.end_session_btn.setEnabled(False)  # Disabled until session starts
```

**Button Behavior:**

| State | Start Session Button | End Session Button | Effect |
|-------|---------------------|-------------------|--------|
| No session | Enabled | Disabled | Click to create new session |
| Session active | Disabled | Enabled | Click to finalize and close |
| Monitoring off | Enabled* | Enabled* | Can manage sessions offline |

*Can start/end sessions even when monitoring is off

### Change #3: Session State Indicators

**Clear Visual Feedback:**

```python
# Session status with color coding
if session_active:
    self.session_indicator.setText("🟢 COLLECTING DATA")
    self.session_indicator.setStyleSheet("color: green; font-weight: bold;")
    # Show session info
    self.session_info_label.setText(
        f"Session: {session_name}\n"
        f"Started: {start_time}\n"
        f"Measurements: {measurement_count}"
    )
else:
    self.session_indicator.setText("⚪ NO SESSION")
    self.session_indicator.setStyleSheet("color: gray;")
    self.session_info_label.setText("Click 'Start Session' to begin")
```

### Change #4: Non-Session Mode Behavior

**When monitoring but NO session active:**

```python
def _on_merge_completed(self, filename: str, stats: dict):
    if self.session_manager and self.session_manager.is_active():
        # Session mode - append to cumulative file
        self.session_manager.append_measurement(...)
        avg_file = str(self.session_manager.averaged_file)
    else:
        # Non-session mode - create individual files
        avg_file = output_dir / f"{filename}_avg_xy.csv"
        # Each file is independent
        
    # Live Data shows only this file
    self.averaged_file_ready.emit(avg_file, stats)
```

### Change #5: Session Metadata Enhancements

**Add scientific metadata fields:**

```python
@dataclass
class SessionConfig:
    # Existing fields...
    session_name: str
    operator: str
    notes: str
    
    # New scientific fields
    experiment_goal: str = ""  # What are we testing?
    hypothesis: str = ""  # What do we expect?
    flow_rate: Optional[float] = None  # L/s
    water_depth: Optional[float] = None  # m
    temperature: Optional[float] = None  # °C
    
    # Equipment settings
    grid_origin: Optional[List[float]] = None
    grid_extent: Optional[List[float]] = None
    measurement_protocol: str = ""  # Description of procedure
```

---

## 📊 COMPARISON: Current vs Improved

### Scenario: Measure 3 Different Grid Configurations

**Current System:**
```
09:00 - Start monitoring
        ↓ Auto-creates "Session_20260224_090000"
09:30 - Measure Dense Grid (25 points)
        ↓ All goes to same session
10:30 - Measure Coarse Grid (9 points)
        ↓ Still same session
11:30 - Measure Cross-Section (15 points)
        ↓ Still same session
12:00 - Stop monitoring
        ↓ Session ends with 49 mixed measurements

Result: averaged_grid_data.csv has 49 rows from 3 different experiments
        Live Data shows all 3 overlapped
        Cannot analyze separately
```

**Improved System:**
```
09:00 - Start monitoring (stays on all day)

09:30 - Session 1: "Dense_Grid_Baseline"
        ├─ Start Session
        ├─ Measure 25 points
        ├─ End Session
        └─ Clean dataset: 25 measurements

10:30 - Session 2: "Coarse_Grid_Validation"
        ├─ Start Session
        ├─ Measure 9 points
        ├─ End Session
        └─ Clean dataset: 9 measurements

11:30 - Session 3: "Vertical_Profile_CrossSection"
        ├─ Start Session
        ├─ Measure 15 points
        ├─ End Session
        └─ Clean  dataset: 15 measurements

18:00 - Stop monitoring (all sessions already closed)

Result: 3 independent session folders
        Each with its own averaged_grid_data.csv
        Each can be analyzed separately
        Live Data shows only current session
```

---

## 🎯 USER WORKFLOW IMPROVEMENTS

### For Researcher Collecting Data

**Morning Calibration:**
```
1. Start monitoring
2. Session: "Morning_Calibration"
3. Measure known flow at 5 points
4. End session
5. Verify quality in Live Data
```

**Baseline Measurements:**
```
6. Session: "Baseline_Grid_9x9"
7. Measure entire grid (81 points)
8. End session
9. Review statistics
```

**After Flow Adjustment:**
```
10. Session: "HighFlow_Grid_9x9"
11. Measure same grid (81 points)
12. End session
13. Compare to baseline
```

**Evening Verification:**
```
14. Session: "Evening_Calibration"
15. Re-measure same 5 calibration points
16. End session
17. Stop monitoring
```

**Result:** 4 clean, independent datasets ready for analysis

---

## 🔬 SCIENTIFIC BENEFITS

### 1. Experimental Reproducibility
- Each session documents specific conditions
- Metadata includes when/who/why/how
- Can replicate exact measurement protocol

### 2. Quality Control
- Each session has quality statistics
- Can identify and exclude poor sessions
- Don't have to discard entire day's work

### 3. Comparative Analysis
- Session A vs Session B is trivial
- Export each as separate CSV
- Load into analysis software side-by-side

### 4. Data Integrity
- No accidental mixing of experiments
- Clear boundaries between runs
- Easy to trace which data belongs where

### 5. Collaboration
- Hand off clean session to colleague
- "Here's the Grid_A data you requested"
- Not "Here's 500 measurements, figure out which are Grid_A"

---

## 📁 PROPOSED FILE STRUCTURE

```
Data_Output/
└── sessions/
    ├── session_20260224_093000_Dense_Grid_Baseline/
    │   ├── averaged_grid_data.csv          (25 rows)
    │   ├── raw_measurements.csv            (2500 samples)
    │   ├── metadata.yaml                   (complete experiment info)
    │   ├── session_log.txt                 (event timeline)
    │   ├── README.txt                      (human-readable summary)
    │   └── raw_exports/                    (original FT2 files)
    │
    ├── session_20260224_103000_Coarse_Grid_Validation/
    │   ├── averaged_grid_data.csv          (9 rows)
    │   ├── raw_measurements.csv            (900 samples)
    │   └── ...
    │
    ├── session_20260224_113000_Vertical_Profile/
    │   └── ...
    │
    └── experiment_index.csv                (catalog of all sessions)
```

---

## ⚙️ IMPLEMENTATION PRIORITY

### Phase 1: Critical (Immediate)
1. ✅ Decouple monitoring from session creation
2. ✅ Add "Start Session" and "End Session" buttons
3. ✅ Update UI to show session state clearly
4. ✅ Allow monitoring without active session (individual file mode)

### Phase 2: Important (This Week)
5. [ ] Add session metadata fields (flow rate, depth, etc.)
6. [ ] Add session summary display after end
7. [ ] Add "Load Session in Live Data" browser
8. [ ] Add session comparison view

### Phase 3: Enhancement (Future)
9. [ ] Session templates for common protocols
10. [ ] Auto-save session notes periodically
11. [ ] Session validation checks
12. [ ] Export entire session as zip

---

## 🧪 TESTING VALIDATION

**Test Scenario:**  
Start two sessions with same grid, verify data separation

```python
# Test script
import csv
from pathlib import Path

# Session 1: Morning measurement
session1_file = Path("sessions/session_20260224_090000_Morning/averaged_grid_data.csv")
with open(session1_file) as f:
    session1_data = list(csv.DictReader(f))

# Session 2: Afternoon measurement  
session2_file = Path("sessions/session_20260224_140000_Afternoon/averaged_grid_data.csv")
with open(session2_file) as f:
    session2_data = list(csv.DictReader(f))

# Verify independence
assert len(session1_data) + len(session2_data) > 0
assert session1_file != session2_file

# Both measured same location (0.5, 0.2)
morning_point = [p for p in session1_data if p['x_m'] == '0.500' and p['y_m'] == '0.200'][0]
afternoon_point = [p for p in session2_data if p['x_m'] == '0.500' and p['y_m'] == '0.200'][0]

# Data should be different (different times, different samples)
assert morning_point['timestamp_utc'] != afternoon_point['timestamp_utc']

print("✓ Sessions are properly isolated!")
```

---

**End of Analysis**

**Next Step:** Implement Phase 1 changes to make sessions scientifically viable.
