"""Synchronization between motor motion and ADV sampling."""

import time
import logging
from typing import Optional
from .calibration import CalibrationManager

logger = logging.getLogger(__name__)


class Synchronizer:
    """Aligns motor position with ADV data collection.
    
    Ensures ADV samples are collected only when motor is at target position,
    and verifies position within ±1 step tolerance.
    """
    
    # Motion verification constants
    POSITION_TOLERANCE_STEPS = 1
    MOTION_POLL_INTERVAL = 0.05  # seconds
    MOTION_TIMEOUT = 60.0  # seconds
    
    def __init__(self, calibration: Optional[CalibrationManager] = None):
        """Initialize synchronizer.
        
        Args:
            calibration: CalibrationManager instance for coordinate conversion
        """
        self.calibration = calibration or CalibrationManager()
    
    def timestamp(self) -> float:
        """Get monotonic timestamp for synchronization.
        
        Returns:
            Current time in seconds
        """
        return time.time()
    
    def tag_sample(self, sample: dict, x_steps: int, y_steps: int) -> dict:
        """Attach position metadata to sample.
        
        Args:
            sample: ADV sample dictionary
            x_steps: X motor position in steps
            y_steps: Y motor position in steps
            
        Returns:
            Sample dict with added position tags
        """
        sample['x_steps'] = x_steps
        sample['y_steps'] = y_steps
        sample['x_feet'] = self.calibration.steps_to_feet(x_steps)
        sample['y_feet'] = self.calibration.steps_to_feet(y_steps)
        sample['timestamp'] = self.timestamp()
        return sample
    
    def wait_for_motion_complete(self, vxc_controller, timeout: Optional[float] = None) -> bool:
        """Block until VXC motion is complete.
        
        Args:
            vxc_controller: VXCController instance
            timeout: Maximum wait time in seconds (None for default)
            
        Returns:
            True if motion completed, False if timeout
        """
        if timeout is None:
            timeout = self.MOTION_TIMEOUT
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            is_complete = vxc_controller.is_motion_complete()
            if is_complete is True:
                logger.debug("Motion complete confirmed")
                return True
            elif is_complete is False:
                time.sleep(self.MOTION_POLL_INTERVAL)
            else:
                logger.error("Error querying motion status")
                return False
        
        logger.warning(f"Motion wait timeout after {timeout}s")
        return False
    
    def verify_position_at_target(self, vxc_controller, target_x: int, 
                                 target_y: int, timeout: float = 5.0) -> bool:
        """Verify that motor is at target position within tolerance.
        
        Args:
            vxc_controller: VXCController instance
            target_x: Target X position in steps
            target_y: Target Y position in steps
            timeout: Maximum wait time for verification
            
        Returns:
            True if position verified within tolerance
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            pos = vxc_controller.get_position()
            if pos is None:
                time.sleep(self.MOTION_POLL_INTERVAL)
                continue
            
            x_error = abs(pos['X'] - target_x)
            y_error = abs(pos['Y'] - target_y)
            
            if (x_error <= self.POSITION_TOLERANCE_STEPS and 
                y_error <= self.POSITION_TOLERANCE_STEPS):
                logger.debug(f"Position verified: X={pos['X']}, Y={pos['Y']} "
                           f"(target X={target_x}, Y={target_y})")
                return True
            
            logger.debug(f"Position error: ΔX={x_error}, ΔY={y_error} steps")
            time.sleep(self.MOTION_POLL_INTERVAL)
        
        logger.warning(f"Position verification timeout at X={pos['X']}, Y={pos['Y']}")
        return False
    
    def interpolate_sample_position(self, samples: list, positions: list) -> list:
        """Interpolate position for samples collected during motion (future use).
        
        Args:
            samples: List of ADV samples with timestamps
            positions: List of (x_steps, y_steps, timestamp) tuples
            
        Returns:
            Samples with interpolated positions
        """
        # Placeholder for motion interpolation
        # Currently samples are only collected at static positions
        logger.debug("Position interpolation not needed for step-and-hold sampling")
        return samples
