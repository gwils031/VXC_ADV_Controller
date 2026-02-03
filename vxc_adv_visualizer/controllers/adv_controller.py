"""SonTek FlowTracker2 ADV (Acoustic Doppler Velocimeter) Controller."""

import serial
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ADVSampleRaw:
    """Raw ADV sample from device."""
    timestamp: float
    u: float  # Velocity component (m/s)
    v: float  # Velocity component (m/s)
    w: float  # Velocity component (m/s)
    snr: float  # Signal-to-noise ratio (dB)
    correlation: float  # Correlation coefficient (0-100)
    depth: float  # Water depth from sensor (m)
    amplitude: float  # Acoustic amplitude
    temperature: float  # Water temperature (°C)
    valid: bool = True


class ADVController:
    """Controller for SonTek FlowTracker2 ADV device.
    
    Streams velocity data at 10Hz, providing u/v/w components, SNR, correlation,
    and depth sensor readings.
    """
    
    # Communication parameters
    SERIAL_TIMEOUT = 2.0
    SAMPLING_RATE_HZ = 10
    SAMPLE_INTERVAL = 1.0 / SAMPLING_RATE_HZ
    
    # Retry configuration
    RETRY_DELAYS = [0.5, 1.0, 2.0]
    
    def __init__(self, port: str, baudrate: int = 9600):
        """Initialize ADV controller connection.
        
        Args:
            port: COM port name (e.g., 'COM4')
            baudrate: Serial connection speed (typically 9600)
        """
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.connected = False
        self.streaming = False
        
    def connect(self) -> bool:
        """Establish serial connection to ADV device.
        
        Returns:
            True if connection successful
        """
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.SERIAL_TIMEOUT
            )
            time.sleep(0.5)
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            
            self.connected = True
            logger.info(f"ADV connected on {self.port}")
            return True
            
        except serial.SerialException as e:
            logger.error(f"Failed to connect to ADV on {self.port}: {e}")
            self.connected = False
            return False
    
    def disconnect(self) -> None:
        """Close serial connection."""
        if self.connected:
            try:
                self.stop_stream()
                time.sleep(0.2)
                if self.serial:
                    self.serial.close()
                self.connected = False
                logger.info("ADV disconnected")
            except Exception as e:
                logger.error(f"Error during ADV disconnect: {e}")
    
    def start_stream(self) -> bool:
        """Start continuous velocity data streaming.
        
        Returns:
            True if streaming started successfully
        """
        if not self.connected:
            logger.error("ADV not connected")
            return False
        
        try:
            # Send start streaming command (device-specific)
            self.serial.write(b"START\r")
            time.sleep(0.5)
            self.streaming = True
            logger.info("ADV streaming started")
            return True
        except serial.SerialException as e:
            logger.error(f"Failed to start ADV stream: {e}")
            return False
    
    def stop_stream(self) -> bool:
        """Stop velocity data streaming.
        
        Returns:
            True if successful
        """
        if not self.connected:
            return False
        
        try:
            self.serial.write(b"STOP\r")
            time.sleep(0.2)
            self.streaming = False
            logger.info("ADV streaming stopped")
            return True
        except serial.SerialException as e:
            logger.error(f"Failed to stop ADV stream: {e}")
            return False
    
    def read_sample(self) -> Optional[ADVSampleRaw]:
        """Read single ADV sample from device.
        
        Returns:
            ADVSampleRaw object or None if read failed
        """
        if not self.connected or not self.streaming:
            logger.error("ADV not connected or not streaming")
            return None
        
        try:
            # Read line from device
            line = self.serial.readline()
            if not line:
                return None
            
            # Parse sample data
            return self._parse_sample_line(line)
            
        except serial.SerialException as e:
            logger.error(f"Serial error reading ADV sample: {e}")
            return None
    
    def read_burst(self, num_samples: int) -> list[ADVSampleRaw]:
        """Read multiple ADV samples.
        
        Args:
            num_samples: Number of samples to collect
            
        Returns:
            List of ADVSampleRaw objects
        """
        samples = []
        for _ in range(num_samples):
            sample = self.read_sample()
            if sample and sample.valid:
                samples.append(sample)
            else:
                logger.warning(f"Invalid sample received")
        
        return samples
    
    def flush_buffer(self) -> None:
        """Clear serial input buffer."""
        if self.connected and self.serial:
            self.serial.reset_input_buffer()
    
    def _parse_sample_line(self, line: bytes) -> Optional[ADVSampleRaw]:
        """Parse raw byte line into ADVSampleRaw.
        
        Expected format (ASCII): U,V,W,SNR,CORR,DEPTH,AMP,TEMP
        Example: 0.123,0.045,-0.012,45.2,95.5,0.52,1200,18.5
        
        Args:
            line: Raw bytes from device
            
        Returns:
            ADVSampleRaw object or None if parse failed
        """
        try:
            # Decode and strip whitespace
            text = line.decode('ascii', errors='ignore').strip()
            if not text:
                return None
            
            # Split fields
            parts = text.split(',')
            if len(parts) < 8:
                logger.warning(f"Incomplete sample line: {text}")
                return None
            
            # Parse fields
            u = float(parts[0])
            v = float(parts[1])
            w = float(parts[2])
            snr = float(parts[3])
            correlation = float(parts[4])
            depth = float(parts[5])
            amplitude = float(parts[6])
            temperature = float(parts[7])
            
            sample = ADVSampleRaw(
                timestamp=time.time(),
                u=u, v=v, w=w,
                snr=snr,
                correlation=correlation,
                depth=depth,
                amplitude=amplitude,
                temperature=temperature,
                valid=True
            )
            
            logger.debug(f"Parsed sample: u={u:.3f}, v={v:.3f}, w={w:.3f}, SNR={snr:.1f}")
            return sample
            
        except (ValueError, IndexError) as e:
            logger.error(f"Failed to parse ADV sample line '{line}': {e}")
            return None
    
    def validate_sample(self, sample: ADVSampleRaw, 
                       min_snr: float = 5.0,
                       min_correlation: float = 70.0) -> bool:
        """Validate ADV sample quality.
        
        Args:
            sample: ADVSampleRaw to validate
            min_snr: Minimum signal-to-noise ratio (dB)
            min_correlation: Minimum correlation (%)
            
        Returns:
            True if sample passes validation
        """
        if not sample:
            return False
        
        # Check SNR
        if sample.snr < min_snr:
            logger.debug(f"Sample SNR too low: {sample.snr:.1f} < {min_snr}")
            return False
        
        # Check correlation
        if sample.correlation < min_correlation:
            logger.debug(f"Sample correlation too low: {sample.correlation:.1f} < {min_correlation}")
            return False
        
        # Check velocity magnitudes (sanity check)
        velocity_magnitude = (sample.u**2 + sample.v**2 + sample.w**2)**0.5
        if velocity_magnitude > 5.0:  # Typical max ~5 m/s in flumes
            logger.warning(f"Velocity magnitude unusually high: {velocity_magnitude:.2f} m/s")
        
        sample.valid = True
        return True
