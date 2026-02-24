"""VXC log matcher for finding VXC position logs matching ADV timestamps."""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

# VXC filename pattern: vxc_pos_YYYYMMDD_HHMMSS.csv (e.g., vxc_pos_20260209_220704.csv)
VXC_FILENAME_PATTERN = re.compile(r'^vxc_pos_(\d{8})_(\d{6})\.csv$')
# ADV filename pattern: YYYYMMDD-HHMMSS.csv (e.g., 20260209-144849.csv)
ADV_FILENAME_PATTERN = re.compile(r'^(\d{8})-(\d{6})\.csv$')


class VXCLogMatcher:
    """Matches ADV export files with corresponding VXC position logs."""
    
    def __init__(self, vxc_log_directory: str):
        """Initialize matcher.
        
        Args:
            vxc_log_directory: Directory containing VXC position logs
        """
        self.vxc_log_dir = Path(vxc_log_directory)
    
    @staticmethod
    def is_valid_vxc_filename(filename: str) -> bool:
        """Validate VXC filename format: vxc_pos_YYYYMMDD_HHMMSS.csv
        
        Args:
            filename: Filename to validate
            
        Returns:
            True if filename matches VXC log format
        """
        if not filename or not isinstance(filename, str):
            return False
        
        match = VXC_FILENAME_PATTERN.match(filename)
        if not match:
            return False
        
        # Validate date/time components
        date_str, time_str = match.groups()
        try:
            year = int(date_str[0:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            hour = int(time_str[0:2])
            minute = int(time_str[2:4])
            second = int(time_str[4:6])
            
            # Basic range validation
            if not (1900 <= year <= 2100):
                return False
            if not (1 <= month <= 12):
                return False
            if not (1 <= day <= 31):
                return False
            if not (0 <= hour <= 23):
                return False
            if not (0 <= minute <= 59):
                return False
            if not (0 <= second <= 59):
                return False
            
            return True
        except ValueError:
            return False
    
    @staticmethod
    def is_valid_adv_filename(filename: str) -> bool:
        """Validate ADV filename format: YYYYMMDD-HHMMSS.csv
        
        Args:
            filename: Filename to validate
            
        Returns:
            True if filename matches ADV export format
        """
        if not filename or not isinstance(filename, str):
            return False
        
        match = ADV_FILENAME_PATTERN.match(filename)
        return match is not None
    
    def find_matching_vxc_log(self, adv_file: Path, time_window_minutes: int = 90) -> Optional[Path]:
        """Find VXC log file matching ADV export timestamp.
        
        Args:
            adv_file: ADV CSV file with timestamp in name (YYYYMMDD-HHMMSS.csv)
            time_window_minutes: Maximum time difference in minutes (default 90 for 1-hour rotation + buffer)
            
        Returns:
            Path to matching VXC log file, or None if not found
        """
        if not self.vxc_log_dir.exists():
            logger.warning(f"VXC log directory not found: {self.vxc_log_dir}")
            return None
        
        # Validate ADV filename format first
        if not self.is_valid_adv_filename(adv_file.name):
            logger.error(f"Invalid ADV filename format: {adv_file.name}")
            return None
        
        try:
            # Parse ADV timestamp from filename: 20260204-155330.csv
            adv_timestamp_local = datetime.strptime(adv_file.stem, '%Y%m%d-%H%M%S')
            local_tz = datetime.now().astimezone().tzinfo
            adv_timestamp = adv_timestamp_local.replace(tzinfo=local_tz).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError as e:
            logger.error(f"Invalid ADV filename format: {adv_file.name} - {e}")
            return None
        
        # Search for VXC logs within time window
        # NOTE: VXC logs can span up to 1 hour, so we need a wider window than 5 minutes
        # The filename timestamp is when logging STARTED, not the full time range covered
        best_match = None
        min_time_diff = float('inf')
        
        # Pattern: vxc_pos_20260204_155330.csv or similar
        for vxc_file in self.vxc_log_dir.glob("vxc_pos_*.csv"):
            # Validate VXC filename format
            if not self.is_valid_vxc_filename(vxc_file.name):
                logger.debug(f"Skipping invalid VXC filename: {vxc_file.name}")
                continue
            
            try:
                # Extract timestamp from VXC filename
                # Try format: vxc_pos_YYYYMMDD_HHMMSS.csv
                name_parts = vxc_file.stem.replace('vxc_pos_', '')
                vxc_timestamp = datetime.strptime(name_parts, '%Y%m%d_%H%M%S')
                
                # Calculate time difference
                time_diff_sec = abs((adv_timestamp - vxc_timestamp).total_seconds())
                time_diff_min = time_diff_sec / 60.0
                
                # Check if within window and better than previous match
                if time_diff_min <= time_window_minutes and time_diff_sec < min_time_diff:
                    min_time_diff = time_diff_sec
                    best_match = vxc_file
                    
            except (ValueError, IndexError) as e:
                logger.debug(f"Skipping VXC file {vxc_file.name}: {e}")
                continue
        
        if best_match:
            logger.info(f"Matched {adv_file.name} with {best_match.name} (dt={min_time_diff:.1f}s)")
        else:
            logger.warning(f"No VXC log found for {adv_file.name} within {time_window_minutes} min window")
        
        return best_match
    
    def get_all_vxc_logs(self) -> List[Path]:
        """Get list of all valid VXC log files in directory.
        
        Returns:
            List of VXC log file paths, sorted by modification time
        """
        if not self.vxc_log_dir.exists():
            return []
        
        # Filter for valid VXC filenames only
        vxc_files = [
            f for f in self.vxc_log_dir.glob("vxc_pos_*.csv")
            if self.is_valid_vxc_filename(f.name)
        ]
        vxc_files.sort(key=lambda f: f.stat().st_mtime)
        return vxc_files
