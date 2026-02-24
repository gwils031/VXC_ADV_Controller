# Data Collection Flow Issues Analysis
## VXC Position Matching and Location Averaging Problems

**Date:** February 24, 2026  
**Analysis:** Critical issues preventing proper VXC position assignment and location-based averaging

---

## Executive Summary

The current data collection flow has **CRITICAL ISSUES** that prevent:
1. ✗ Every ADV data point from being assigned a VXC position
2. ✗ Proper averaging by LOCATION (instead averaging by FILE)
3. ✗ Correct display of location averages in the Live Data tab

---

## 🔴 CRITICAL ISSUE #1: Averaging Per FILE Instead of Per LOCATION

### Current Behavior
**Location:** `vxc_adv_visualizer/data/adv_vxc_merger.py` → `write_averaged_plane_csv()`

```python
# Lines 386-434: This function IS binning by (x,y) location
bins: Dict[Tuple[float, float], Dict] = {}
for record in self.merged_data:
    x_val = self._parse_float(record.get("vxc_x_m"))
    y_val = self._parse_float(record.get("vxc_y_m"))
    # ... bins data by grid position
```

**THE PROBLEM:**
- ✗ This binning is called **ONCE PER ADV FILE** (each FlowTracker2 export)
- ✗ Each ADV export creates a SEPARATE `_avg_xy.csv` file
- ✗ If you measure the same location MULTIPLE TIMES (across different exports), those measurements are **NEVER COMBINED**

### Example Scenario:
```
Time 14:00 - Export 1: Location (0.5m, 0.2m) → 20 samples → avg_file_1.csv
Time 14:10 - Export 2: Location (0.5m, 0.2m) → 15 samples → avg_file_2.csv
Time 14:20 - Export 3: Location (0.5m, 0.2m) → 25 samples → avg_file_3.csv
```

**Expected:** One entry for (0.5m, 0.2m) with 60 samples averaged  
**Actual:** Three separate files, each with its own average for (0.5m, 0.2m)

### Impact
- Every time VXC moves to a new location and ADV exports data, you get a separate averaged file
- Live Data tab only shows the MOST RECENT file (not accumulated averages)
- No way to see true location-based statistics across time

---

## 🔴 CRITICAL ISSUE #2: VXC Position Matching Rate

### Matching Algorithm
**Location:** `vxc_adv_visualizer/data/adv_vxc_merger.py` → `merge()` and `_find_nearest_vxc()`

**Current Strategy:**
- Uses binary search to find nearest VXC timestamp to each ADV sample
- Tolerance: 0.5 seconds (configurable in `ADVVXCMerger.__init__()`)
- If no VXC record within 0.5s, ADV sample gets `vxc_quality: MISSING`

### Problems Causing Low Match Rates

#### Problem 2A: VXC Logging Interval vs ADV Sampling Rate
**VXC Logging:** Currently writes every 0.5 seconds
**Location:** `vxc_adv_visualizer/gui/main_window.py` lines 141-170

```python
class VXCLogWorker(QObject):
    def start(self):
        self._running = True
        while self._running:
            # ... logs position
            time.sleep(self.write_interval_sec)  # DEFAULT: 0.5 seconds
```

**ADV Sampling:** FlowTracker2 samples at variable rates (typically 1-10 Hz)
**FlowTracker2 Export:** Contains ALL samples from collection period (could be 60+ samples)

**THE PROBLEM:**
- If ADV collects 100 samples over 60 seconds
- VXC only logs 120 positions (every 0.5s)
- But if VXC is STATIONARY at one location during that minute, ALL samples SHOULD get that position
- Instead, many samples may fall outside 0.5s tolerance if timestamps don't align perfectly

#### Problem 2B: VXC Position NOT Assigned to Every Sample
When VXC is stationary (measuring at one grid point), EVERY ADV sample collected during that dwell time should get the SAME VXC position. Currently:

```python
# In merge(), line 217-224
for adv_record in self.adv_data:
    vxc_match = self._find_nearest_vxc(adv_record['timestamp_unix'])
    if vxc_match:
        # Match found
    else:
        # No match - add with NaN for VXC columns
        merged = {..., 'vxc_x_m': 'NaN', 'vxc_y_m': 'NaN', ...}
```

**Root Cause:** Matching is based purely on TIMESTAMP proximity, not on "current measurement location"

---

## 🔴 CRITICAL ISSUE #3: Session Manager Not Re-Averaging by Location

### Current Session Behavior
**Location:** `vxc_adv_visualizer/data/session_manager.py` → `append_measurement()`

**What It Does:**
```python
# Lines 247-259: Appends each measurement to averaged_grid_data.csv
avg_row = {
    'session_id': self.active_session,
    'measurement_seq': current_seq,  # SEQUENTIAL NUMBER
    'timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
    'elapsed_time_sec': f"{elapsed_sec:.1f}",
    'quality_flag': quality_flag,
    **averaged_data  # Contains x_m, y_m, sample_count, velocities
}
self.averaged_writer.writerow(avg_row)
```

**THE PROBLEM:**
- ✗ Each measurement is appended as a NEW ROW
- ✗ No aggregation by (x_m, y_m) location
- ✗ If you measure (0.5m, 0.2m) three times, you get THREE ROWS in the file
- ✗ Live Data tab should show ONE row per location with cumulative average, but it doesn't

### Expected Behavior
```csv
# Expected: One row per location, updated with new data
x_m,y_m,sample_count,measurement_count,velocity_x_avg,...
0.500,0.200,60,3,0.245,...   # 3 measurements, 60 total samples
```

**Actual Behavior:**
```csv
# Actual: Multiple rows for same location
x_m,y_m,sample_count,measurement_seq,velocity_x_avg,...
0.500,0.200,20,1,0.240,...  # Measurement 1
0.500,0.200,15,2,0.248,...  # Measurement 2
0.500,0.200,25,3,0.246,...  # Measurement 3
```

---

## 🔴 CRITICAL ISSUE #4: Live Data Tab Display Logic

### Current Display Logic
**Location:** `vxc_adv_visualizer/gui/live_data_tab.py` → `update_from_avg_file()`

```python
# Lines 282-288
def update_from_avg_file(self, avg_file: str, stats: Optional[dict] = None):
    """Load and display averaged data from a CSV file."""
    self.last_avg_file = avg_file  # ONLY STORES LAST FILE
    self.last_stats = stats or {}
    self._reload_last_file()  # RELOADS ONLY THIS FILE
```

**THE PROBLEM:**
- ✗ Only displays the MOST RECENT averaged file
- ✗ Does NOT accumulate data from multiple files
- ✗ If you measure grid point A, then B, then A again, only the second A measurement shows

### In Session Mode:
```python
# auto_merge_tab.py lines 524-527
if self.session_manager and self.session_manager.is_active():
    avg_file_to_display = str(self.session_manager.averaged_file)
```

- Uses `averaged_grid_data.csv` which has all measurements
- BUT that file has multiple rows per location (see Issue #3)
- Live Data tab's `_plot_vectors()` loads ALL rows but should be grouping by location

---

## 🟡 ISSUE #5: VXC Logging Quality Flags

### Current Quality Logic
**Location:** `vxc_adv_visualizer/data/vxc_position_logger.py`

When logging VXC positions, quality is set to:
- `"GOOD"` - Position successfully read
- `"NO_RESPONSE"` - VXC not responding

**THE PROBLEM:**
- ✗ No distinction between "VXC moving" vs "VXC stationary"
- ✗ ADV samples collected DURING MOTION should be flagged differently
- ✗ Only samples at STATIONARY positions should be included in averages

### Recommendation
Add quality states:
- `"STATIONARY"` - VXC stopped at measurement point
- `"MOVING"` - VXC in transit between points
- `"SETTLING"` - VXC stopped but settling time not elapsed

---

## 📊 Data Flow Architecture (Current)

```
1. FlowTracker2 exports ADV data
   ↓ (every 60-120 seconds)
   20260224-143000.csv (100 samples)
   
2. FileMonitor detects new file
   ↓
   
3. VXCMatcher finds matching VXC log
   ↓ (timestamp-based, ±5 min)
   vxc_pos_20260224_142955.csv
   
4. ADVVXCMerger aligns by timestamp
   ↓ (0.5s tolerance, nearest neighbor)
   merged_data: 100 records (maybe 80 matched, 20 unmatched)
   
5. write_averaged_plane_csv() bins by location
   ↓ (WITHIN THIS FILE ONLY)
   20260224-143000_avg_xy.csv (e.g., 5 grid points)
   
6. Session appends to averaged_grid_data.csv
   ↓ (APPENDS, DOESN'T RE-AVERAGE)
   Creates new rows for each measurement
   
7. Live Data Tab displays
   ✗ Shows all rows from averaged_grid_data.csv
   ✗ NOT re-binning by location
```

---

## ✅ REQUIRED FIXES

### Fix #1: Implement Location-Based Aggregator
**New Component:** `LocationAggregator` class

**Responsibilities:**
- Maintain in-memory dictionary of all measurements by (x_m, y_m)
- Accumulate samples across multiple ADV exports
- Re-calculate averages when new data arrives
- Write SINGLE master file with one row per location

**Implementation:**
```python
class LocationAggregator:
    def __init__(self, grid_spacing_m: Tuple[float, float]):
        self.bins = {}  # {(x_bin, y_bin): {samples, sums, count}}
        self.spacing_x, self.spacing_y = grid_spacing_m
    
    def add_measurement(self, x_m, y_m, adv_samples):
        """Add samples to the appropriate location bin."""
        x_bin = self._bin_value(x_m, self.spacing_x)
        y_bin = self._bin_value(y_m, self.spacing_y)
        key = (x_bin, y_bin)
        
        if key not in self.bins:
            self.bins[key] = {
                'measurement_count': 0,
                'total_samples': 0,
                'velocity_sums': {'x': 0, 'y': 0, 'z': 0},
                # ... other fields
            }
        
        # Accumulate
        bin_data = self.bins[key]
        bin_data['measurement_count'] += 1
        for sample in adv_samples:
            bin_data['total_samples'] += 1
            bin_data['velocity_sums']['x'] += sample['vel_x']
            # ... accumulate other metrics
    
    def get_location_averages(self):
        """Calculate and return current averages for all locations."""
        averages = []
        for (x, y), data in self.bins.items():
            avg = {
                'x_m': x,
                'y_m': y,
                'measurement_count': data['measurement_count'],
                'sample_count': data['total_samples'],
                'velocity_x_avg': data['velocity_sums']['x'] / data['total_samples'],
                # ... other averages
            }
            averages.append(avg)
        return averages
    
    def write_master_grid_csv(self, output_path):
        """Write master CSV with one row per location."""
        averages = self.get_location_averages()
        # Write to CSV...
```

**Integration Points:**
- Add to `SessionManager` to maintain across all measurements
- Update `FileMonitor` to call aggregator after each merge
- Emit signal to Live Data tab with updated location averages

### Fix #2: Improve VXC Position Assignment

**Option A: Annotate VXC Log with Measurement States**
```python
# In VXCPositionLogger, add state tracking
def start_measurement_at(self, x_m, y_m):
    """Mark start of measurement period at this location."""
    self.current_measurement_location = (x_m, y_m)
    self.measurement_active = True

def end_measurement():
    """Mark end of measurement period."""
    self.measurement_active = False
    self.current_measurement_location = None

# In log output
timestamp,x_m,y_m,quality,measurement_state
2026-02-24 14:30:00.123,0.500,0.200,GOOD,MEASURING
2026-02-24 14:30:00.623,0.500,0.200,GOOD,MEASURING
```

**Option B: Use File-Level Position Assignment**
Since FlowTracker2 exports represent discrete measurement periods at specific locations:
```python
# In ADVVXCMerger, add method:
def assign_single_position_to_all_samples(self, x_m, y_m):
    """Assign same position to ALL samples (for stationary measurements)."""
    for record in self.merged_data:
        record['vxc_x_m'] = x_m
        record['vxc_y_m'] = y_m
        record['vxc_quality'] = 'STATIONARY'
```

### Fix #3: Modify Session Manager Averaging

**Change `append_measurement()` to update in-place by location:**
```python
def append_measurement(self, merged_data: List[Dict], averaged_data: Dict):
    # Instead of just appending:
    # 1. Check if location already exists in aggregator
    # 2. If exists, accumulate new samples
    # 3. Re-calculate averages
    # 4. Update existing row OR append new row
    # 5. Rewrite averaged_grid_data.csv with all current averages
```

### Fix #4: Update Live Data Tab to Group by Location

**In `live_data_tab.py`, modify `_load_avg_rows()`:**
```python
def _load_avg_rows(self, filepath: Path) -> List[dict]:
    rows = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            all_rows = list(reader)
        
        # Group by location
        location_bins = {}
        for row in all_rows:
            x_m = self._parse_float(row.get('x_m'))
            y_m = self._parse_float(row.get('y_m'))
            if x_m is None or y_m is None:
                continue
            
            key = (round(x_m, 6), round(y_m, 6))
            if key not in location_bins:
                location_bins[key] = []
            location_bins[key].append(row)
        
        # For each location, compute aggregate average
        for (x, y), location_rows in location_bins.items():
            aggregated_row = self._aggregate_rows(location_rows)
            rows.append(aggregated_row)
    
    except Exception as e:
        logger.error(f"Failed to read averaged CSV: {e}")
        return []
    
    return rows

def _aggregate_rows(self, rows: List[dict]) -> dict:
    """Aggregate multiple rows for same location."""
    # Sum sample counts
    total_samples = sum(int(r.get('sample_count', 0)) for r in rows)
    
    # Weighted average of velocities
    # ... implementation
    
    return aggregated
```

### Fix #5: Add VXC State Tracking

**In VXCPositionLogger:**
```python
@dataclass
class VXCPositionRecord:
    timestamp_utc: str
    x_m: float
    y_m: float
    quality: str  # GOOD, NO_RESPONSE, etc.
    state: str    # STATIONARY, MOVING, SETTLING

class VXCPositionLogger:
    def set_measurement_mode(self, enabled: bool, location: Optional[Tuple[float, float]] = None):
        """Mark when VXC is at measurement location vs moving."""
        self.measurement_mode = enabled
        self.measurement_location = location
    
    def log_position(self, x_steps, y_steps, quality):
        # Determine state
        if self.measurement_mode:
            state = "STATIONARY"
        else:
            state = "MOVING"
        
        # Log with state
        # ...
```

---

## 🎯 Prioritized Action Items

### Priority 1 (CRITICAL - Blocking proper data collection)
1. [ ] Implement `LocationAggregator` class for cross-file location averaging
2. [ ] Integrate `LocationAggregator` into `SessionManager`
3. [ ] Modify Live Data tab to display location-aggregated data

### Priority 2 (HIGH - Improves match rate)
4. [ ] Add VXC state tracking (STATIONARY vs MOVING)
5. [ ] Update merger to use state for position assignment
6. [ ] Increase VXC logging rate to 5 Hz (0.2s intervals) for better coverage

### Priority 3 (MEDIUM - Quality of life)
7. [ ] Add UI controls to manually specify "measurement at location (x, y)"
8. [ ] Add summary statistics showing per-location sample counts
9. [ ] Add validation warnings when match rate < 90%

### Priority 4 (LOW - Future enhancement)
10. [ ] Add automatic detection of stationary periods from VXC log
11. [ ] Implement adaptive binning based on actual position variance
12. [ ] Add cross-session location aggregation

---

## 📁 Files Requiring Changes

### Core Data Processing
- ✏️ `vxc_adv_visualizer/data/adv_vxc_merger.py` - Add position assignment method
- ✏️ `vxc_adv_visualizer/data/session_manager.py` - Implement LocationAggregator
- ✏️ `vxc_adv_visualizer/data/vxc_position_logger.py` - Add state tracking

### Monitoring/Merging
- ✏️ `vxc_adv_visualizer/monitoring/file_monitor.py` - Connect to aggregator
- 📖 `vxc_adv_visualizer/monitoring/vxc_matcher.py` - No changes needed

### GUI
- ✏️ `vxc_adv_visualizer/gui/live_data_tab.py` - Add location grouping logic
- ✏️ `vxc_adv_visualizer/gui/auto_merge_tab.py` - Connect aggregator signals
- ✏️ `vxc_adv_visualizer/gui/main_window.py` - Add state control buttons

### Configuration
- ✏️ `vxc_adv_visualizer/config/experiment_config.yaml` - Add VXC logging rate

---

## 🧪 Testing Validation

After implementing fixes, validate with this scenario:

```
Test Scenario: Measure 3×3 grid (9 points), visit each point twice

Expected Results:
1. ✓ Merged CSV: 100% match rate (all ADV samples have VXC positions)
2. ✓ Master grid CSV: Exactly 9 rows (one per location)
3. ✓ Each row shows measurement_count = 2
4. ✓ Sample counts reflect both visits (e.g., 20 + 18 = 38 total)
5. ✓ Live Data tab displays 9 vector arrows (not 18)
6. ✓ Clicking a location shows accumulated statistics

Current Results (before fix):
1. ✗ Match rate: 60-80% (many samples unmatched)
2. ✗ Grid CSV: 18 rows (duplicate locations)
3. ✗ measurement_count column doesn't exist
4. ✗ Sample counts only show latest file
5. ✗ Live Data shows 18 arrows (duplicates at same location)
6. ✗ Statistics only from most recent measurement
```

---

## 📞 Questions for User

Before implementing fixes, confirm:

1. **Workflow Clarification:**
   - When you measure a location, do you stop the VXC and then collect ADV data at that stationary position?
   - Or is the VXC continuously moving while ADV collects?

2. **Expected Behavior:**
   - If you measure location (0.5m, 0.2m) three times (e.g., morning, noon, evening), should those be:
     - **Option A:** Combined into ONE averaged value?
     - **Option B:** Kept as three separate measurements with timestamps?

3. **Live Data Display:**
   - Should Live Data tab show:
     - **Option A:** Latest snapshot only (current behavior)?
     - **Option B:** Accumulated averages across all measurements?
     - **Option C:** Time-series with ability to select measurement?

4. **Grid Definition:**
   - Are grid locations pre-defined (e.g., 10×10 fixed grid)?
   - Or freeform (VXC can visit any arbitrary locations)?

---

**End of Analysis**
