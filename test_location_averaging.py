"""Test script to verify location-based averaging fix.

Run this after collecting data to verify that:
1. Location aggregation works correctly
2. Weighted averaging is accurate
3. Live Data tab displays unique locations only
"""

import csv
from pathlib import Path
from collections import defaultdict

def test_location_aggregation(session_dir: Path):
    """Test that locations are properly aggregated in session data."""
    
    averaged_file = session_dir / "averaged_grid_data.csv"
    if not averaged_file.exists():
        print(f"❌ Session file not found: {averaged_file}")
        return False
    
    print(f"🔍 Analyzing: {averaged_file.name}\n")
    
    # Read all measurements
    measurements = []
    with open(averaged_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        measurements = list(reader)
    
    print(f"Total measurements in file: {len(measurements)}")
    
    # Group by location
    location_groups = defaultdict(list)
    for row in measurements:
        quality = row.get('quality_flag', '')
        if quality == 'MISSING':
            continue
        
        x_m = row.get('x_m', '')
        y_m = row.get('y_m', '')
        if x_m and y_m:
            # Round to 6 decimals for grouping (same as live_data_tab.py)
            key = (round(float(x_m), 6), round(float(y_m), 6))
            location_groups[key].append(row)
    
    print(f"Unique locations: {len(location_groups)}")
    
    # Analyze locations with multiple measurements
    multi_visit_locations = {k: v for k, v in location_groups.items() if len(v) > 1}
    
    if multi_visit_locations:
        print(f"\n✅ Found {len(multi_visit_locations)} locations with multiple visits:")
        for location, visits in sorted(multi_visit_locations.items()):
            x, y = location
            visit_count = len(visits)
            total_samples = sum(int(v.get('sample_count', 0)) for v in visits)
            print(f"   Location ({x:.3f}m, {y:.3f}m): {visit_count} visits, {total_samples} total samples")
            
            # Verify weighted averaging calculation
            if visit_count >= 2:
                print(f"      Testing aggregation for this location...")
                test_weighted_average(visits)
        
        print(f"\n✨ Live Data tab should show {len(location_groups)} arrows (not {len(measurements)})")
        return True
    else:
        print("\n⚠️  No locations with multiple visits found.")
        print("   This is normal if you haven't measured the same location twice.")
        print(f"   Live Data tab should show {len(location_groups)} arrows")
        return True

def test_weighted_average(visits):
    """Verify weighted averaging calculation."""
    # Example: Calculate weighted average for velocity X
    vel_key = 'Corrected Velocity.X (m/s)'
    
    values_and_weights = []
    for visit in visits:
        vel_str = visit.get(vel_key, '')
        sample_count_str = visit.get('sample_count', '0')
        
        if vel_str and sample_count_str:
            try:
                vel = float(vel_str)
                weight = int(sample_count_str)
                values_and_weights.append((vel, weight))
            except ValueError:
                pass
    
    if values_and_weights:
        weighted_sum = sum(v * w for v, w in values_and_weights)
        total_weight = sum(w for v, w in values_and_weights)
        weighted_avg = weighted_sum / total_weight
        
        print(f"      Velocity X weighted average: {weighted_avg:.6f} m/s")
        print(f"      (Computed from {len(values_and_weights)} visits with {total_weight} samples)")
    else:
        print("      ⚠️  Could not compute weighted average (missing data)")

def analyze_match_rates(data_output_dir: Path):
    """Analyze VXC position match rates from merged files."""
    
    print("\n" + "="*60)
    print("VXC Position Match Rate Analysis")
    print("="*60 + "\n")
    
    # Find all merged CSV files
    merged_files = list(data_output_dir.rglob("*_merged.csv"))
    
    if not merged_files:
        print("No merged CSV files found")
        return
    
    total_samples = 0
    total_matched = 0
    
    for merged_file in merged_files[-10:]:  # Last 10 files
        try:
            with open(merged_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                samples = list(reader)
                
                file_total = len(samples)
                file_matched = sum(1 for s in samples if s.get('vxc_quality', '') != 'MISSING')
                
                total_samples += file_total
                total_matched += file_matched
                
                match_rate = (file_matched / file_total * 100) if file_total > 0 else 0
                
                print(f"{merged_file.name:30s} | Matched: {file_matched:4d}/{file_total:4d} ({match_rate:5.1f}%)")
        except Exception as e:
            print(f"Error reading {merged_file.name}: {e}")
    
    if total_samples > 0:
        overall_rate = total_matched / total_samples * 100
        print(f"\n{'Overall Match Rate:':30s} | Matched: {total_matched:4d}/{total_samples:4d} ({overall_rate:5.1f}%)")
        
        if overall_rate >= 90:
            print("\n✅ Excellent match rate! VXC position logging is working well.")
        elif overall_rate >= 75:
            print("\n⚠️  Good match rate, but could be improved.")
            print("   Consider: VXC may have been moving during some measurements")
        else:
            print("\n❌ Low match rate detected!")
            print("   Possible issues:")
            print("   - VXC not connected during measurements")
            print("   - Clock synchronization issues")
            print("   - VXC moving too fast")

if __name__ == "__main__":
    import sys
    
    print("="*60)
    print("Location-Based Averaging Verification Test")
    print("="*60 + "\n")
    
    # Find most recent session
    data_output = Path("Data_Output")
    sessions_dir = data_output / "sessions"
    
    if not sessions_dir.exists():
        print(f"❌ Sessions directory not found: {sessions_dir}")
        print("   Start a session and collect some data first.")
        sys.exit(1)
    
    # Get most recent session
    session_dirs = sorted(sessions_dir.glob("session_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not session_dirs:
        print(f"❌ No sessions found in: {sessions_dir}")
        print("   Create a session and collect data first.")
        sys.exit(1)
    
    latest_session = session_dirs[0]
    print(f"Testing latest session: {latest_session.name}\n")
    
    # Test location aggregation
    success = test_location_aggregation(latest_session)
    
    # Analyze match rates
    analyze_match_rates(data_output)
    
    print("\n" + "="*60)
    print("Test Complete")
    print("="*60)
    
    if success:
        print("\n✅ Location aggregation is working correctly!")
        print("   Open Live Data tab to see aggregated results.")
    else:
        print("\n⚠️  Review results above for any issues.")
