# Session Management Implementation
## Scientific Session Lifecycle Improvements

**Date:** February 24, 2026  
**Status:** ✅ IMPLEMENTED  
**Files Modified:** `vxc_adv_visualizer/gui/auto_merge_tab.py`

---

## 🎯 OBJECTIVE

Decouple session lifecycle from monitoring state to enable scientifically viable data collection with proper experimental grouping.

---

## 📝 CHANGES MADE

### Change #1: Remove Auto-Session Creation from Monitoring Start

**Location:** [auto_merge_tab.py](vxc_adv_visualizer/gui/auto_merge_tab.py#L383-L398) - `_start_monitoring()` method

**Before:**
```python
def _start_monitoring(self):
    # ...
    # Check for active session or create one
    if self.session_manager is None or not self.session_manager.is_active():
        # Auto-create session
        session_name = self.session_name_edit.text().strip() or self._generate_default_session_name()
        session_config = SessionConfig(...)
        session_id = self.session_manager.start_session(session_config)
        # ... update UI ...
```

**After:**
```python
def _start_monitoring(self):
    # ...
    # Initialize session manager if needed, but DON'T auto-create session
    if self.session_manager is None:
        self.session_manager = SessionManager(output_dir)
    
    # Warn if no session active
    if not self.session_manager.is_active():
        self._log_activity(
            "⚠️ Monitoring started without active session. "
            "Files will be processed individually. Start a session to group measurements.",
            "warning"
        )
```

**Impact:**  
- Monitoring can start without creating a session
- User has explicit control over when sessions begin
- Non-session mode processes files individually

---

### Change #2: Decouple Session End from Monitoring Stop

**Location:** [auto_merge_tab.py](vxc_adv_visualizer/gui/auto_merge_tab.py#L457-L469) - `_stop_monitoring()` method

**Before:**
```python
def _stop_monitoring(self):
    if self.file_monitor:
        self.file_monitor.stop_monitoring()
        self.file_monitor = None
    
    # End active session
    self._end_current_session()
    
    self.status_indicator.setText("● Inactive")
    # ...
```

**After:**
```python
def _stop_monitoring(self):
    if self.file_monitor:
        self.file_monitor.stop_monitoring()
        self.file_monitor = None
    
    # DON'T automatically end session - let user control session lifecycle
    # Sessions now independent of monitoring state
    
    self.status_indicator.setText("● Inactive")
    # ...
    
    if self.session_manager and self.session_manager.is_active():
        self._log_activity(
            "ℹ️ Session still active. End session manually when data collection complete.",
            "info"
        )
```

**Impact:**  
- Stopping monitoring does NOT end the session
- User must explicitly end sessions
- Can stop monitoring temporarily while preserving session

---

### Change #3: Redesign Session Control UI

**Location:** [auto_merge_tab.py](vxc_adv_visualizer/gui/auto_merge_tab.py#L86-L105) - Session UI setup

**Before:**
```
[Session Name: ___________] [New Session] [Browse...]
[Operator: ___] [Notes: ___] [Save Notes]
Active Session: None
```

**After:**
```
[Session Name: ___________] [Start Session] [End Session] [Browse...]
[Operator: ___] [Notes: ___] [Save Notes]
Session Status: ⚪ NO SESSION
```

**Button Changes:**
1. "New Session" → "Start Session" (green background)
2. Added "End Session" button (red background)
3. Buttons properly enable/disable based on session state

**Code:**
```python
# Start Session button (replaces New Session)
self.new_session_btn = QPushButton("Start Session")
self.new_session_btn.clicked.connect(self._create_new_session)
self.new_session_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
session_layout.addWidget(self.new_session_btn, 0, 3)

# End Session button (new)
self.end_session_btn = QPushButton("End Session")
self.end_session_btn.clicked.connect(self._end_current_session)
self.end_session_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold;")
self.end_session_btn.setEnabled(False)  # Disabled until session starts
session_layout.addWidget(self.end_session_btn, 0, 4)
```

**Impact:**  
- Clear visual distinction between session actions
- Red/green color coding indicates session control
- Always visible, never hidden

---

### Change #4: Enhanced Session Status Display

**Location:** [auto_merge_tab.py](vxc_adv_visualizer/gui/auto_merge_tab.py#L130-L133) - Status label

**Before:**
```python
session_layout.addWidget(QLabel("Active Session:"), 2, 0)
self.session_status_label = QLabel("None")
self.session_status_label.setStyleSheet("color: #888; font-weight: bold;")
```

**After:**
```python
session_layout.addWidget(QLabel("Session Status:"), 2, 0)
self.session_status_label = QLabel("⚪ NO SESSION")
self.session_status_label.setStyleSheet("color: #888; font-weight: bold;")
```

**Status States:**
- `⚪ NO SESSION` (gray) - No active session, ready to start
- `🟢 COLLECTING DATA - Session_20260224_090000` (green) - Session active

**Impact:**  
- Instant visual feedback on session state
- Emoji indicators catch user's eye
- Full session ID displayed when active

---

### Change #5: Update Session Start Logic

**Location:** [auto_merge_tab.py](vxc_adv_visualizer/gui/auto_merge_tab.py#L651-L671) - `_create_new_session()` method

**Before:**
```python
# Update UI
self.session_status_label.setText(session_id)
self.session_status_label.setStyleSheet("color: green; font-weight: bold;")
self.new_session_btn.setEnabled(False)
```

**After:**
```python
# Update UI with session active state
self.session_status_label.setText(f"🟢 COLLECTING DATA - {session_id}")
self.session_status_label.setStyleSheet("color: green; font-weight: bold;")

# Disable Start Session, enable End Session
self.new_session_btn.setEnabled(False)
self.end_session_btn.setEnabled(True)
```

**Impact:**  
- Start Session button disabled while session active
- End Session button enabled when session starts
- Clear indication that data collection is active

---

### Change #6: Update Session End Logic

**Location:** [auto_merge_tab.py](vxc_adv_visualizer/gui/auto_merge_tab.py#L683-L706) - `_end_current_session()` method

**Before:**
```python
# Update UI
self.session_status_label.setText("None")
self.session_status_label.setStyleSheet("color: #888; font-weight: bold;")
self.new_session_btn.setEnabled(True)
```

**After:**
```python
# Update UI to show no session
self.session_status_label.setText("⚪ NO SESSION")
self.session_status_label.setStyleSheet("color: #888; font-weight: bold;")

# Enable Start Session, disable End Session
self.new_session_btn.setEnabled(True)
self.end_session_btn.setEnabled(False)
```

**Impact:**  
- Start Session button re-enabled after ending
- End Session button disabled when no session
- Clear return to ready state

---

## 🔄 NEW WORKFLOW

### Scenario: Collect Baseline Grid, Adjust Flow, Collect Comparison Grid

**Old Workflow (PROBLEMATIC):**
```
1. Start Monitoring → Auto-creates "Session_20260224_090000"
2. Measure Baseline Grid (9 points) → Goes to session
3. Adjust flow settings
4. Measure Comparison Grid (9 points) → Goes to SAME session
5. Stop Monitoring → Session ends with 18 mixed measurements

Problem: Cannot separate baseline from comparison!
```

**New Workflow (SCIENTIFICALLY VIABLE):**
```
1. Start Monitoring
   └─ Status: "⚠️ Monitoring started without active session"
   
2. Start Session: "Baseline_Grid_LowFlow"
   └─ Status: "🟢 COLLECTING DATA"
   
3. Measure Baseline Grid (9 points)
   └─ All data goes to Baseline session
   
4. End Session
   └─ Status: "⚪ NO SESSION"
   └─ Metadata saved with 9 measurements
   
5. Adjust flow settings
   
6. Start Session: "Comparison_Grid_HighFlow"
   └─ Status: "🟢 COLLECTING DATA"
   
7. Measure Comparison Grid (9 points)
   └─ All data goes to Comparison session
   
8. End Session
   └─ Status: "⚪ NO SESSION"
   └─ Metadata saved with 9 measurements
   
9. Stop Monitoring (if done for the day)

Result: Two clean, independent datasets!
```

---

## 🎛️ BUTTON STATE MATRIX

| Session State | Start Session | End Session | Session Name | Operator | Effect |
|--------------|---------------|-------------|--------------|----------|--------|
| No session   | **Enabled** ✅ | Disabled ❌ | Editable ✏️ | Editable ✏️ | Can create new session |
| Session active | Disabled ❌ | **Enabled** ✅ | Locked 🔒 | Locked 🔒 | Can end current session |

**Status Display:**
- No session: `⚪ NO SESSION` (gray)
- Session active: `🟢 COLLECTING DATA - Session_20260224_090000` (green)

---

## 📊 DATA FILE BEHAVIOR

### Session Mode (When Session Active)

**Files Created:**
```
Data_Output/sessions/session_20260224_090000_Baseline_Grid/
├── averaged_grid_data.csv        ← Cumulative, updated with each measurement
├── raw_measurements.csv          ← Cumulative, updated with each measurement
├── metadata.yaml                 ← Written when session ends
└── session_log.txt              ← Live event log
```

**Live Data Tab:**  
Shows `averaged_grid_data.csv` from active session (cumulative across all measurements in this session)

### Non-Session Mode (No Active Session)

**Files Created:**
```
Data_Output/
├── 20260224_141254_merged.csv     ← Individual merged file
├── 20260224_141254_avg_xy.csv     ← Individual averaged file
├── 20260224_141300_merged.csv
├── 20260224_141300_avg_xy.csv
└── ...
```

**Live Data Tab:**  
Shows the most recent `*_avg_xy.csv` file (only this measurement)

---

## ✅ VALIDATION TESTS

### Test 1: Start Monitoring Without Session

**Steps:**
1. Start application
2. Click "Monitor and Auto-Merge" checkbox ✅
3. Observe activity log

**Expected Behavior:**
```
✓ File monitoring started
⚠️ Monitoring started without active session. Files will be processed individually. 
  Start a session to group measurements.
```

**Result:** Monitoring is active, no session created

---

### Test 2: Create Session While Monitoring

**Steps:**
1. With monitoring active (no session)
2. Enter session name: "Test_Session"
3. Click "Start Session" button

**Expected Behavior:**
- Session Status: `🟢 COLLECTING DATA - session_20260224_HHMMSS_Test_Session`
- Start Session button: Disabled
- End Session button: Enabled
- Activity log: `✓ Session started: session_20260224_HHMMSS_Test_Session`

**Result:** Session created while monitoring continues

---

### Test 3: End Session Without Stopping Monitoring

**Steps:**
1. With active session and monitoring
2. Click "End Session" button
3. Observe monitoring checkbox

**Expected Behavior:**
- Session Status: `⚪ NO SESSION`
- Start Session button: Enabled
- End Session button: Disabled
- Monitoring checkbox: Still ✅ (remains checked)
- Activity log: `✓ Session ended: ... X measurements, Y excellent, Z good`

**Result:** Session ended, monitoring continues

---

### Test 4: Stop Monitoring While Session Active

**Steps:**
1. With active session and monitoring
2. Uncheck "Monitor and Auto-Merge"
3. Observe session status

**Expected Behavior:**
- Monitoring indicator: `● Inactive` (gray)
- Session Status: `🟢 COLLECTING DATA - ...` (unchanged!)
- Activity log: `ℹ️ Session still active. End session manually when data collection complete.`

**Result:** Monitoring stopped, session remains active

---

### Test 5: Sequential Sessions (Scientific Workflow)

**Steps:**
1. Start monitoring
2. Start session: "Session_A"
3. Collect data (9 points)
4. End session
5. Start session: "Session_B"
6. Collect data (12 points)
7. End session
8. Stop monitoring

**Expected Behavior:**
- Session A file: 9 measurements
- Session B file: 12 measurements
- Total: 2 independent session folders
- Live Data switches from Session A to Session B data

**Result:** Clean separation between experimental runs

---

## 🔧 TECHNICAL DETAILS

### Session Manager Integration

The session manager remains integrated with the file monitor:

```python
self.file_monitor = FileMonitor(
    # ... other params ...
    session_manager=self.session_manager  # Still passed, can be None or have no active session
)
```

**File Monitor Behavior:**
- If `session_manager.is_active()` → Append to session files
- If not active → Create individual `*_merged.csv` and `*_avg_xy.csv`

This dual-mode operation is already implemented in `file_monitor.py` lines 110-134.

### Signal Flow for Live Data Tab

```python
# In _on_merge_completed():
if self.session_manager and self.session_manager.is_active():
    # Session mode - use cumulative averaged file
    avg_file_to_display = str(self.session_manager.averaged_file)
elif avg_output:
    # Non-session mode - use individual averaged file
    avg_file_to_display = avg_output

if avg_file_to_display:
    self.averaged_file_ready.emit(avg_file_to_display, stats)
```

**Result:** Live Data Tab automatically displays correct file based on session state

---

## 📈 EXPECTED IMPROVEMENTS

### Before Implementation
- ❌ Sessions tied to monitoring lifecycle
- ❌ Cannot separate experiments without restarting monitoring
- ❌ All data mixed in one continuous session
- ❌ No explicit session control

### After Implementation
- ✅ Sessions independent of monitoring
- ✅ Can create/end sessions while monitoring continues
- ✅ Clean experimental data grouping
- ✅ Explicit Start/End Session buttons with visual feedback

---

## 🚀 FUTURE ENHANCEMENTS (Not Implemented Yet)

1. **Session Metadata Fields**
   - Flow rate, water depth, temperature
   - Experiment hypothesis
   - Measurement protocol description

2. **Session Browser Improvements**
   - Preview session data before loading
   - Compare two sessions side-by-side
   - Export session as zip file

3. **Session Validation**
   - Warn if starting new session without ending current
   - Confirm before ending session with unsaved notes
   - Check for minimum number of measurements

4. **Session Templates**
   - Save/load common session configurations
   - Pre-defined measurement protocols
   - Automatic metadata population

---

## 📄 FILES MODIFIED

### `vxc_adv_visualizer/gui/auto_merge_tab.py`

**Lines Modified:**
- **83-105:** Session UI layout (added End Session button, updated status label)
- **383-398:** `_start_monitoring()` - Removed auto-session creation
- **457-469:** `_stop_monitoring()` - Removed auto-session end
- **651-671:** `_create_new_session()` - Updated button states and status display
- **683-706:** `_end_current_session()` - Updated button states and status display

**Lines Added:** ~15  
**Lines Removed:** ~30  
**Net Change:** -15 lines (simpler, cleaner code!)

---

## 🧪 TESTING CHECKLIST

- [x] Code compiles without errors
- [x] Start monitoring without session works
- [x] Start session while monitoring works
- [x] End session without stopping monitoring works
- [x] Stop monitoring with active session shows warning
- [x] Button states update correctly
- [x] Session status display updates correctly
- [ ] **TODO:** Live data switches between session/non-session files correctly
- [ ] **TODO:** Sequential sessions create separate folders
- [ ] **TODO:** Session metadata saved correctly

---

## 📚 USER DOCUMENTATION (To Be Added to README)

### How to Use Sessions for Scientific Data Collection

**Step-by-Step:**

1. **Start the Application**
   - Navigate to "Auto-Merge" tab
   - Sessions start in `⚪ NO SESSION` state

2. **Start Monitoring (Optional)**
   - Check "Monitor and Auto-Merge" if you want automatic file detection
   - You can also work without monitoring and manually merge files

3. **Begin an Experiment**
   - Enter a descriptive Session Name (e.g., "Baseline_LowFlow_9x9Grid")
   - Enter Operator name
   - Add brief notes about experiment
   - Click **[Start Session]** (green button)
   - Status changes to `🟢 COLLECTING DATA`

4. **Collect Measurements**
   - Move VXC to grid points
   - Collect ADV data at each point
   - Watch Live Data tab update with session data

5. **End Experiment**
   - Click **[End Session]** (red button)
   - Status changes to `⚪ NO SESSION`
   - Session metadata and statistics are saved

6. **Repeat for Next Experiment**
   - Enter new Session Name
   - Click **[Start Session]**
   - Continue collecting data

7. **Review Sessions**
   - Click **[Browse...]** to view past sessions
   - Each session folder contains complete dataset

---

**End of Implementation Documentation**
