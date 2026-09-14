"""VXC Position Logger - Emits UTC-timestamped XY positions to CSV.

Logs VXC stage positions with millisecond-precision UTC timestamps for alignment
with ADV (FlowTracker2) data. Supports file rotation for 1-minute chunks.

Format: timestamp_utc,x_m,y_m,quality
Example: 2026-02-09 18:45:32.123,-0.0234,0.0567,GOOD
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import threading


logger = logging.getLogger(__name__)


class VXCPositionLogger:
    """Logs VXC XY positions with UTC timestamps to CSV files.
    
    Attributes:
        output_dir: Directory for CSV output files
        steps_per_foot: Conversion factor from motor steps to feet
        current_file: Current CSV file being written
        writer: CSV writer object
        file_handle: Open file handle
        lock: Thread lock for concurrent access
        sample_count: Total samples logged in current file
        start_time: Session start timestamp
    """
    
    def __init__(self, output_dir: str, steps_per_foot: float = 48000.0):
        """Initialize position logger.
        
        Args:
            output_dir: Directory path for CSV output
            steps_per_foot: Conversion factor (default 48000 steps/foot)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.steps_per_foot = steps_per_foot
        self.current_file: Optional[Path] = None
        self.writer: Optional[csv.writer] = None
        self.file_handle: Optional[object] = None
        self.lock = threading.RLock()
        
        self.sample_count = 0
        self.start_time: Optional[datetime] = None
        self.current_file_start: Optional[datetime] = None
        
    def start_logging(self) -> str:
        """Start a new logging session.
        
        Returns:
            Path to the new log file
            
        Raises:
            IOError: If file cannot be created
        """
        with self.lock:
            if self.file_handle:
                self.stop_logging()
                
            # Create filename with UTC timestamp
            now = datetime.now(timezone.utc)
            self.start_time = now
            self.current_file_start = now
            
            filename = f"vxc_pos_{now.strftime('%Y%m%d_%H%M%S')}.csv"
            self.current_file = self.output_dir / filename
            
            try:
                self.file_handle = open(self.current_file, 'w', newline='')
                self.writer = csv.writer(self.file_handle)
                
                # Write header
                self.writer.writerow(['timestamp_utc', 'x_m', 'y_m', 'quality'])
                self.file_handle.flush()
                
                self.sample_count = 0
                logger.info(f"Started VXC position logging: {self.current_file}")
                return str(self.current_file)
                
            except Exception as e:
                logger.error(f"Failed to start logging: {e}")
                raise IOError(f"Cannot create log file: {e}")
    
    def log_position(self, x_steps: int, y_steps: int, quality: str = "GOOD") -> None:
        """Log a single position sample with UTC timestamp.
        
        Args:
            x_steps: X position in motor steps
            y_steps: Y position in motor steps
            quality: Quality indicator (e.g., GOOD, VXC Moving)
        """
        if not self.file_handle or not self.writer:
            logger.warning("Cannot log - logging not started")
            return
            
        with self.lock:
            try:
                # Get UTC timestamp with millisecond precision
                now = datetime.now(timezone.utc)
                timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # milliseconds
                
                # Convert steps to meters (steps → feet → meters)
                x_feet = x_steps / self.steps_per_foot
                y_feet = y_steps / self.steps_per_foot
                x_m = x_feet * 0.3048  # feet to meters
                y_m = y_feet * 0.3048
                
                # Write row
                self.writer.writerow([timestamp_str, f"{x_m:.6f}", f"{y_m:.6f}", quality])
                self.sample_count += 1
                
                # Flush every 10 samples (~5s at 0.5s interval) instead of every write
                if self.sample_count % 10 == 0:
                    self.file_handle.flush()
                
                # Check if we need to rotate file (1-minute chunks)
                if self._should_rotate_file(now):
                    self._rotate_file()
                    
            except Exception as e:
                logger.error(f"Failed to log position: {e}")
    
    def _should_rotate_file(self, current_time: datetime) -> bool:
        """Check if file should be rotated based on 1-hour interval.
        
        Args:
            current_time: Current UTC timestamp
            
        Returns:
            True if file should be rotated
        """
        if not self.current_file_start:
            return False
            
        elapsed = (current_time - self.current_file_start).total_seconds()
        return elapsed >= 3600.0  # 1 hour (increased from 1 minute to prevent ADV files spanning multiple VXC logs)
    
    def _rotate_file(self) -> None:
        """Rotate to a new log file."""
        logger.info(f"Rotating log file (samples written: {self.sample_count})")
        self.stop_logging()
        self.start_logging()
    
    def stop_logging(self) -> Optional[str]:
        """Stop logging and close current file.
        
        Returns:
            Path to the closed log file, or None if not logging
        """
        with self.lock:
            if not self.file_handle:
                return None
                
            try:
                self.file_handle.close()
                filepath = str(self.current_file)
                logger.info(f"Stopped VXC logging: {filepath} ({self.sample_count} samples)")
                
                # Clear internal state but preserve reference for testing
                self.file_handle = None
                self.writer = None
                # Don't set self.current_file = None (keep for test access)
                self.sample_count = 0
                
                return filepath
                
            except Exception as e:
                logger.error(f"Error closing log file: {e}")
                return None
    
    def get_status(self) -> dict:
        """Get current logging status.
        
        Returns:
            Dict with logging status information
        """
        with self.lock:
            return {
                'logging': self.file_handle is not None,
                'current_file': str(self.current_file) if self.current_file else None,
                'sample_count': self.sample_count,
                'start_time': self.start_time.isoformat() if self.start_time else None
            }


# For testing
if __name__ == "__main__":
    import time
    
    # Test logger
    logger = VXCPositionLogger(output_dir="./test_logs")
    logger.start_logging()
    
    # Log 10 samples
    for i in range(10):
        logger.log_position(x_steps=23000 + i*100, y_steps=4600 + i*50, quality="GOOD")
        time.sleep(0.1)
    
    logger.stop_logging()
    print("Test complete - check ./test_logs/")
