"""Measurement orchestration and adaptive sampling engine."""

import logging
import time
from typing import Optional, List, Callable
from enum import Enum
from dataclasses import dataclass

from controllers import VXCController, ADVController
from controllers.adv_controller import ADVSampleRaw
from data.data_model import DataRecord, ADVSample
from data.data_logger import DataLogger
from acquisition.synchronizer import Synchronizer
from acquisition.calibration import CalibrationManager
from utils.flow_calculations import calculate_froude, get_adaptive_sampling_duration
from utils.timing import RateLimiter

logger = logging.getLogger(__name__)


class SamplingState(Enum):
    """Acquisition state machine states."""
    IDLE = "idle"
    CALIBRATING = "calibrating"
    MOVING = "moving"
    SAMPLING = "sampling"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class SamplingPosition:
    """Single measurement position."""
    x_steps: int
    y_steps: int
    x_feet: float
    y_feet: float
    in_roi: bool  # True if in high-density region
    roi_density_multiplier: float = 1.0


class Sampler:
    """Core measurement orchestration engine.
    
    Manages:
    - Step-and-hold positioning with ADV sampling
    - Froude-based adaptive sampling duration
    - Z-plane sequential workflow with run counter
    - Pause/resume state machine
    - Data quality validation with retry logic
    """
    
    # Sampling parameters
    BASE_SAMPLING_DURATION = 10.0  # seconds
    MAX_SAMPLING_DURATION = 120.0  # seconds
    RETRY_LIMIT = 3
    RETRY_DELAYS = [0.5, 1.0, 2.0]
    
    def __init__(self, vxc: VXCController, adv: ADVController,
                 data_logger: DataLogger,
                 calibration: Optional[CalibrationManager] = None):
        """Initialize sampler.
        
        Args:
            vxc: VXCController instance
            adv: ADVController instance
            data_logger: DataLogger instance
            calibration: CalibrationManager instance
        """
        self.vxc = vxc
        self.adv = adv
        self.data_logger = data_logger
        self.calibration = calibration or CalibrationManager()
        self.synchronizer = Synchronizer(self.calibration)
        
        # State management
        self.state = SamplingState.IDLE
        self.current_z_plane = 0.0
        self.current_run_number = 1
        self.position_sequence: List[SamplingPosition] = []
        self.current_position_index = 0
        
        # Statistics
        self.positions_completed = 0
        self.samples_collected = 0
        self.measurements_failed = 0
        
        # Callbacks for GUI updates
        self.on_state_changed: Optional[Callable] = None
        self.on_position_sampled: Optional[Callable] = None
        self.on_status_update: Optional[Callable] = None
    
    def set_z_plane(self, z_value: float, run_number: int = 1) -> None:
        """Set Z-plane coordinate for next acquisition.
        
        Args:
            z_value: Z coordinate (upstream position)
            run_number: Run iteration (auto-incremented if unchanged)
        """
        if z_value == self.current_z_plane:
            self.current_run_number += 1
            logger.info(f"Z unchanged, incrementing run: {self.current_run_number}")
        else:
            self.current_z_plane = z_value
            self.current_run_number = 1
        
        logger.info(f"Z-plane set to {z_value}, run {self.current_run_number}")
    
    def initialize_measurement_sequence(self, positions: List[SamplingPosition]) -> bool:
        """Initialize list of measurement positions.
        
        Args:
            positions: List of SamplingPosition objects
            
        Returns:
            True if successful
        """
        if not positions:
            logger.error("Empty position sequence")
            return False
        
        self.position_sequence = positions
        self.current_position_index = 0
        self.positions_completed = 0
        
        logger.info(f"Initialized sequence with {len(positions)} positions")
        return True
    
    def start_acquisition(self, z_plane: float, run_number: int = 1) -> bool:
        """Start acquisition for new Z-plane.
        
        Args:
            z_plane: Z coordinate
            run_number: Run iteration number
            
        Returns:
            True if started successfully
        """
        try:
            self.set_z_plane(z_plane, run_number)
            
            # Create new data file
            self.data_logger.create_experiment(z_plane, run_number)
            
            # Start ADV streaming
            if not self.adv.start_stream():
                logger.error("Failed to start ADV stream")
                return False
            
            self.state = SamplingState.SAMPLING
            self._emit_state_change()
            logger.info(f"Acquisition started for Z={z_plane}, run={run_number}")
            return True
            
        except Exception as e:
            logger.error(f"Error starting acquisition: {e}")
            self.state = SamplingState.ERROR
            self._emit_state_change()
            return False
    
    def pause_acquisition(self) -> bool:
        """Pause acquisition, preserving current state and data.
        
        Returns:
            True if successful
        """
        if self.state not in [SamplingState.SAMPLING, SamplingState.MOVING]:
            logger.warning(f"Cannot pause from state {self.state}")
            return False
        
        try:
            self.vxc.stop_motion()
            self.adv.stop_stream()
            self.state = SamplingState.PAUSED
            self._emit_state_change()
            logger.info("Acquisition paused")
            return True
        except Exception as e:
            logger.error(f"Error pausing acquisition: {e}")
            return False
    
    def resume_acquisition(self) -> bool:
        """Resume from paused state.
        
        Returns:
            True if successful
        """
        if self.state != SamplingState.PAUSED:
            logger.warning(f"Cannot resume from state {self.state}")
            return False
        
        try:
            if not self.adv.start_stream():
                logger.error("Failed to restart ADV stream")
                return False
            
            self.state = SamplingState.SAMPLING
            self._emit_state_change()
            logger.info("Acquisition resumed")
            return True
        except Exception as e:
            logger.error(f"Error resuming acquisition: {e}")
            return False
    
    def emergency_stop(self) -> None:
        """Emergency stop all motion and acquisition."""
        try:
            self.vxc.stop_motion()
            self.adv.stop_stream()
            self.state = SamplingState.IDLE
            self._emit_state_change()
            logger.info("Emergency stop executed")
        except Exception as e:
            logger.error(f"Error during emergency stop: {e}")
    
    def return_home(self) -> bool:
        """Return XY stage to home position.
        
        Home is (X_mid, Y_max) - center X at water surface.
        Uses diagonal move (X and Y simultaneously).
        
        Returns:
            True if successful
        """
        home = self.calibration.get_home_position()
        if home is None:
            logger.error("Home position not set")
            return False
        
        x_home, y_home = home
        logger.info(f"Returning home to X={x_home}, Y={y_home}")
        
        try:
            if self.vxc.move_absolute(x=x_home, y=y_home):
                return self.synchronizer.wait_for_motion_complete(self.vxc)
            return False
        except Exception as e:
            logger.error(f"Error returning home: {e}")
            return False
    
    def sample_at_position(self, position: SamplingPosition) -> Optional[DataRecord]:
        """Collect measurements at specified position.
        
        Args:
            position: SamplingPosition to sample
            
        Returns:
            DataRecord with averaged measurements or None if failed
        """
        try:
            # Move to position
            self.state = SamplingState.MOVING
            self._emit_state_change()
            
            logger.info(f"Moving to X={position.x_steps}, Y={position.y_steps}")
            if not self.vxc.move_absolute(x=position.x_steps, y=position.y_steps):
                logger.error("Move command failed")
                return None
            
            # Wait for motion complete
            if not self.synchronizer.wait_for_motion_complete(self.vxc):
                logger.error("Motion timeout")
                return None
            
            # Verify position within tolerance
            if not self.synchronizer.verify_position_at_target(self.vxc, 
                                                               position.x_steps,
                                                               position.y_steps):
                logger.error("Position verification failed")
                return None
            
            # Transition to sampling
            self.state = SamplingState.SAMPLING
            self._emit_state_change()
            
            # Collect samples with adaptive duration
            record = self._collect_samples(position)
            
            if record:
                # Log successful measurement
                self.data_logger.append(record)
                self.positions_completed += 1
                self.samples_collected += record.num_samples
                
                self._emit_position_sampled(record)
                logger.info(f"Sampled position {self.positions_completed}/{len(self.position_sequence)}: "
                          f"Fr={record.froude_number:.2f}, samples={record.num_samples}")
                
                return record
            else:
                self.measurements_failed += 1
                return None
                
        except Exception as e:
            logger.error(f"Error sampling position: {e}")
            self.state = SamplingState.ERROR
            self._emit_state_change()
            return None
    
    def _collect_samples(self, position: SamplingPosition) -> Optional[DataRecord]:
        """Collect ADV samples at static position.
        
        Args:
            position: SamplingPosition
            
        Returns:
            DataRecord or None if failed
        """
        try:
            samples: List[ADVSample] = []
            start_time = time.time()
            
            # Initial sample to get velocity for Froude calculation
            first_sample = self._read_single_sample()
            if not first_sample or not first_sample.valid:
                logger.warning("Could not read initial sample")
                return None
            
            samples.append(first_sample)
            
            # Calculate Froude number
            velocity_magnitude = (first_sample.u**2 + first_sample.v**2 + 
                                first_sample.w**2)**0.5
            froude_number = calculate_froude(velocity_magnitude, first_sample.depth)
            
            # Determine sampling duration based on Froude number
            duration = get_adaptive_sampling_duration(
                froude_number,
                self.BASE_SAMPLING_DURATION,
                self.MAX_SAMPLING_DURATION
            )
            
            # Apply ROI density multiplier if in zone
            if position.in_roi:
                duration *= position.roi_density_multiplier
            
            logger.debug(f"Fr={froude_number:.2f}, sampling {duration:.1f}s")
            self._emit_status(f"Fr={froude_number:.2f} ({'Supercritical' if froude_number > 1.0 else 'Subcritical'}) - {duration:.0f}s sampling")
            
            # Collect remaining samples until duration met
            target_end_time = start_time + duration
            rate_limiter = RateLimiter(10.0)  # 10 Hz ADV rate
            
            while time.time() < target_end_time:
                rate_limiter.wait()
                
                sample = self._read_single_sample()
                if sample and sample.valid:
                    samples.append(sample)
            
            # Create data record from samples
            record = DataRecord.from_samples(
                x_steps=position.x_steps,
                y_steps=position.y_steps,
                x_feet=position.x_feet,
                y_feet=position.y_feet,
                z_plane=self.current_z_plane,
                samples=samples,
                froude_number=froude_number,
                run_number=self.current_run_number,
                timestamp=start_time,
                duration=time.time() - start_time
            )
            
            return record
            
        except Exception as e:
            logger.error(f"Error collecting samples: {e}")
            return None
    
    def _read_single_sample(self, retry_count: int = 0) -> Optional[ADVSample]:
        """Read and validate single ADV sample with retry logic.
        
        Args:
            retry_count: Current retry attempt
            
        Returns:
            ADVSample or None if all retries exhausted
        """
        try:
            raw_sample = self.adv.read_sample()
            if raw_sample is None:
                if retry_count < self.RETRY_LIMIT:
                    delay = self.RETRY_DELAYS[retry_count]
                    logger.debug(f"No sample, retrying in {delay}s (attempt {retry_count + 2}/{self.RETRY_LIMIT + 1})")
                    time.sleep(delay)
                    return self._read_single_sample(retry_count + 1)
                else:
                    logger.warning(f"Failed to read sample after {self.RETRY_LIMIT} retries")
                    return None
            
            # Validate sample
            if not self.adv.validate_sample(raw_sample):
                logger.debug(f"Sample validation failed: SNR={raw_sample.snr:.1f}, "
                           f"Corr={raw_sample.correlation:.1f}")
                if retry_count < self.RETRY_LIMIT:
                    delay = self.RETRY_DELAYS[retry_count]
                    time.sleep(delay)
                    return self._read_single_sample(retry_count + 1)
                else:
                    # Mark as invalid but still return for statistics
                    raw_sample.valid = False
            
            # Convert to processed ADVSample
            return ADVSample(
                u=raw_sample.u,
                v=raw_sample.v,
                w=raw_sample.w,
                snr=raw_sample.snr,
                correlation=raw_sample.correlation,
                depth=raw_sample.depth,
                amplitude=raw_sample.amplitude,
                temperature=raw_sample.temperature,
                valid=raw_sample.valid
            )
            
        except Exception as e:
            logger.error(f"Exception reading sample: {e}")
            return None
    
    def run_measurement_sequence(self) -> bool:
        """Execute full measurement sequence through all positions.
        
        Returns:
            True if completed successfully
        """
        if not self.position_sequence:
            logger.error("No measurement sequence initialized")
            return False
        
        logger.info(f"Starting measurement sequence with {len(self.position_sequence)} positions")
        
        for position in self.position_sequence:
            if self.state == SamplingState.PAUSED:
                logger.info("Paused - waiting for resume")
                while self.state == SamplingState.PAUSED:
                    time.sleep(0.5)
            
            if self.state == SamplingState.IDLE:
                logger.info("Acquisition stopped")
                break
            
            self.sample_at_position(position)
        
        logger.info(f"Sequence complete: {self.positions_completed} positions, "
                   f"{self.samples_collected} samples, {self.measurements_failed} failures")
        
        self.state = SamplingState.IDLE
        self._emit_state_change()
        return True
    
    def _emit_state_change(self) -> None:
        """Emit state change callback."""
        if self.on_state_changed:
            self.on_state_changed(self.state)
    
    def _emit_position_sampled(self, record: DataRecord) -> None:
        """Emit position sampled callback."""
        if self.on_position_sampled:
            self.on_position_sampled(record)
    
    def _emit_status(self, message: str) -> None:
        """Emit status update callback."""
        if self.on_status_update:
            self.on_status_update(message)
    
    def get_status(self) -> dict:
        """Get current sampler status.
        
        Returns:
            Status dictionary
        """
        return {
            'state': self.state.value,
            'z_plane': self.current_z_plane,
            'run_number': self.current_run_number,
            'positions_completed': self.positions_completed,
            'total_positions': len(self.position_sequence),
            'samples_collected': self.samples_collected,
            'measurements_failed': self.measurements_failed,
        }
