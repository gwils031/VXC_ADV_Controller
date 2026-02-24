# Session Control Quick Reference
## ADV & VXC Controller - Improved Session Management

---

## 🎯 WHAT CHANGED

**Old System:**
- Sessions auto-created when monitoring started
- Sessions auto-ended when monitoring stopped
- No way to separate experiments without restarting

**New System:**
- **Sessions independent of monitoring**
- **Explicit Start/End Session buttons**
- **Can run multiple sessions in one monitoring period**

---

## 🖥️ USER INTERFACE

### Session Controls (Top of Auto-Merge Tab)

```
┌─────────────────────────────────────────────────────────────┐
│ Session Management                                          │
├─────────────────────────────────────────────────────────────┤
│ Session Name: [Baseline_Grid_9x9____]                      │
│              [Start Session] [End Session] [Browse...]      │
│                                                              │
│ Operator: [Your Name___] Notes: [Experiment notes_____]    │
│                                [Save Notes]                 │
│                                                              │
│ Session Status: ⚪ NO SESSION                               │
│                 (or)                                        │
│ Session Status: 🟢 COLLECTING DATA - session_20260224...   │
└─────────────────────────────────────────────────────────────┘
```

### Button States

| Status | Start Session | End Session |
|--------|---------------|-------------|
| ⚪ NO SESSION | ✅ **Enabled** | ❌ Disabled |
| 🟢 COLLECTING | ❌ Disabled | ✅ **Enabled** |

---

## 📋 COMMON WORKFLOWS

### Workflow 1: Single Experiment Session

```
1. Start monitoring (if desired)
2. Enter session name: "Experiment_A"
3. Click [Start Session] → 🟢 COLLECTING DATA
4. Collect all measurements for this experiment
5. Click [End Session] → ⚪ NO SESSION
6. Stop monitoring (if done)
```

**Result:** One clean session folder with all Experiment A data

---

### Workflow 2: Multiple Sequential Experiments

```
1. Start monitoring
   
2. Session 1:
   ├─ Enter name: "Baseline_Test"
   ├─ [Start Session] → 🟢 COLLECTING
   ├─ Measure 9-point grid
   └─ [End Session] → ⚪ NO SESSION
   
3. Session 2:
   ├─ Enter name: "HighFlow_Test"
   ├─ [Start Session] → 🟢 COLLECTING
   ├─ Measure same 9-point grid
   └─ [End Session] → ⚪ NO SESSION
   
4. Stop monitoring
```

**Result:** Two independent session folders for comparison

---

### Workflow 3: Collect Without Session (Individual Files)

```
1. Start monitoring
2. DON'T start a session
3. Collect measurements

Warning shown: "⚠️ Monitoring started without active session.
                Files will be processed individually."
```

**Result:** Individual `*_merged.csv` and `*_avg_xy.csv` files in Data_Output/

---

### Workflow 4: Pause Monitoring, Keep Session

```
1. [Start Session] → 🟢 COLLECTING
2. Start monitoring
3. Collect some measurements
4. Stop monitoring (temporarily)
   
   Info shown: "ℹ️ Session still active. End session manually."
   Session Status: Still 🟢 COLLECTING DATA
   
5. Restart monitoring (same session continues)
6. Collect more measurements
7. [End Session] → ⚪ NO SESSION
```

**Result:** One session with all measurements, even across monitoring pause

---

## ⚠️ IMPORTANT NOTES

### Session Status Indicators

| Indicator | Meaning | What You Can Do |
|-----------|---------|-----------------|
| ⚪ NO SESSION | Ready to start new session | Click [Start Session] |
| 🟢 COLLECTING DATA | Session is active | Collect data, or [End Session] |

### Monitoring vs Session

**Monitoring:**
- Watches for new ADV exports
- Auto-merges with VXC positions
- Can run continuously all day

**Session:**
- Groups measurements into experiments
- Creates organized folder with metadata
- Should match your experimental protocol

**KEY:** You can start/stop sessions independently of monitoring!

---

## 📁 WHERE YOUR DATA GOES

### With Active Session

```
Data_Output/
└── sessions/
    └── session_20260224_090000_Baseline_Test/
        ├── averaged_grid_data.csv     ← Live Data tab shows this
        ├── raw_measurements.csv
        ├── metadata.yaml
        └── session_log.txt
```

### Without Active Session

```
Data_Output/
├── 20260224_141254_merged.csv
├── 20260224_141254_avg_xy.csv     ← Live Data tab shows this
├── 20260224_141300_merged.csv
└── 20260224_141300_avg_xy.csv
```

---

## 🔴 COMMON MISTAKES TO AVOID

### ❌ MISTAKE 1: Forgetting to End Session
**Problem:** Start "Baseline" session, collect data, adjust settings, collect more data  
**Result:** All data (before AND after adjustment) in one "Baseline" session  
**Fix:** Click [End Session] before changing experimental conditions

### ❌ MISTAKE 2: Starting Monitoring Without Session
**Problem:** Check monitoring box, forget to start session  
**Result:** Individual files instead of grouped session  
**Fix:** Always [Start Session] if you want grouped data

### ❌ MISTAKE 3: Not Naming Sessions Descriptively
**Problem:** Session names like "Session_09_00", "Session_10_30"  
**Result:** Can't tell what each session was for  
**Fix:** Use descriptive names: "Baseline_LowFlow", "Test_HighFlow", "Calibration_Check"

---

## ✅ BEST PRACTICES

### Good Session Names

```
✅ GOOD:
  - Baseline_Grid9x9_LowFlow
  - Vertical_Profile_X_05m
  - Calibration_Morning
  - HighFlow_Run1
  - BeamCheck_Validation

❌ BAD:
  - Session1
  - Test
  - 090000
  - Data_Collection
```

### Recommended Workflow Pattern

```
┌─────────────────────────────────────┐
│ 1. Plan your experiment             │
│    What conditions? How many runs?  │
├─────────────────────────────────────┤
│ 2. Start monitoring (once)          │
│    Leave it running all session     │
├─────────────────────────────────────┤
│ 3. For each experimental condition: │
│    ├─ Start Session (descriptive)   │
│    ├─ Collect all data               │
│    └─ End Session                   │
├─────────────────────────────────────┤
│ 4. Review sessions with [Browse...] │
│    Check quality before leaving     │
├─────────────────────────────────────┤
│ 5. Stop monitoring when done        │
└─────────────────────────────────────┘
```

---

## 🆘 TROUBLESHOOTING

### Q: I clicked [Start Session] but nothing happened
**A:** Check activity log for errors. Common causes:
- Invalid session name (empty or duplicate)
- Output directory not writable
- Session already active

### Q: Live Data stopped updating
**A:** Check:
1. Is monitoring active? (Should show "● Monitoring Active")
2. Are ADV files being exported by FlowTracker2?
3. Is session active if you want cumulative data?

### Q: I have two sessions with the same measurements
**A:** You likely:
1. Measured grid A with Session 1 active
2. Forgot to end Session 1
3. Started Session 2 (but Session 1 still has the data)
**Fix:** Use [Browse...] to check which session has the correct data

### Q: Where did my data go? I see "NO SESSION"
**A:** If you collected data without starting a session:
- Check `Data_Output/` folder (not `sessions/`)
- Look for `*_merged.csv` and `*_avg_xy.csv` files
- Filename matches ADV export timestamp

---

## 📞 QUICK REFERENCE SUMMARY

```
START SESSION:   Green button, creates new experiment group
END SESSION:     Red button, finalizes current experiment
BROWSE:          View past sessions
SAVE NOTES:      Update notes during active session

⚪ NO SESSION:   Ready state - can start new session
🟢 COLLECTING:   Active state - data being grouped

✓ Best Practice: One session per experimental condition
✓ Best Practice: Use descriptive session names
✓ Best Practice: End session before changing conditions
✓ Best Practice: Review sessions before leaving lab
```

---

**For detailed technical information, see:**
- [SESSION_MANAGEMENT_IMPROVEMENTS.md](SESSION_MANAGEMENT_IMPROVEMENTS.md) - Problem analysis
- [SESSION_IMPLEMENTATION_COMPLETE.md](SESSION_IMPLEMENTATION_COMPLETE.md) - Technical details
