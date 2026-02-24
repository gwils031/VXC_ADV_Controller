"""Diagnostic script to identify file matching issues."""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from vxc_adv_visualizer.monitoring.vxc_matcher import VXCLogMatcher

# Directories
adv_dir = Path("ADV_Data")
vxc_dir = Path("VXC_Positions")
output_dir = Path("Data_Output")

# Get all ADV files
adv_files = sorted([f for f in adv_dir.glob("*.csv") if not ('_merged' in f.stem or '_avg' in f.stem)])

# Get processed files
processed = set()
for output_file in output_dir.glob("*_merged.csv"):
    adv_stem =output_file.stem.replace('_merged', '')
    processed.add(adv_stem)

# Create matcher
matcher = VXCLogMatcher(str(vxc_dir))

print(f"Total ADV files: {len(adv_files)}")
print(f"Processed: {len(processed)}")
print(f"Unprocessed: {len(adv_files) - len(processed)}")
print("\n" + "="*80)
print("UNPROCESSED FILES:")
print("="*80)

unprocessed_count = 0
for adv_file in adv_files:
    if adv_file.stem in processed:
        continue
    
    unprocessed_count += 1
    
    # Try to find matching VXC file
    vxc_file = matcher.find_matching_vxc_log(adv_file, time_window_minutes=10)
    
    # Parse ADV timestamp
    try:
        adv_timestamp_local = datetime.strptime(adv_file.stem, '%Y%m%d-%H%M%S')
        local_tz = datetime.now().astimezone().tzinfo
        adv_timestamp_utc = adv_timestamp_local.replace(tzinfo=local_tz).astimezone(timezone.utc)
        adv_time_str = f"{adv_timestamp_local.strftime('%H:%M:%S')} local ({adv_timestamp_utc.strftime('%H:%M:%S')} UTC)"
    except:
        adv_time_str = "parse error"
    
    if vxc_file:
        print(f"[ OK ] {adv_file.name:25} | {adv_time_str:35} | VXC: {vxc_file.name}")
    else:
        print(f"[FAIL] {adv_file.name:25} | {adv_time_str:35} | NO VXC MATCH")

print("\n" + "="*80)
print(f"Unprocessed files: {unprocessed_count}")

# Show VXC file range
vxc_files = sorted(vxc_dir.glob("vxc_pos_*.csv"))
if vxc_files:
    print(f"\nVXC file range:")
    print(f"  First: {vxc_files[0].name}")
    print(f"  Last:  {vxc_files[-1].name}")
