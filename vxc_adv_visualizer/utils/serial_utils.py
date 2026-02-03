"""Serial communication utilities."""

import serial
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


def list_available_ports() -> List[Tuple[str, str]]:
    """Enumerate available COM ports.
    
    Returns:
        List of (port_name, description) tuples
    """
    ports = []
    try:
        from serial.tools import list_ports
        for port, desc, hwid in sorted(list_ports.comports()):
            ports.append((port, desc))
    except Exception as e:
        logger.error(f"Error enumerating COM ports: {e}")
    
    return ports


def open_serial_port(port: str, baudrate: int = 9600,
                     timeout: float = 2.0) -> Optional[serial.Serial]:
    """Open serial port with specified parameters.
    
    Args:
        port: COM port name (e.g., 'COM3')
        baudrate: Baud rate (default 9600)
        timeout: Serial timeout in seconds
        
    Returns:
        Serial object or None if failed
    """
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout
        )
        logger.info(f"Opened {port} at {baudrate} baud")
        return ser
    except serial.SerialException as e:
        logger.error(f"Failed to open {port}: {e}")
        return None


def safe_write(ser: serial.Serial, data: bytes) -> bool:
    """Safely write data to serial port.
    
    Args:
        ser: Serial object
        data: Bytes to write
        
    Returns:
        True if write successful
    """
    try:
        if ser and ser.is_open:
            ser.write(data)
            ser.flush()
            return True
    except serial.SerialException as e:
        logger.error(f"Serial write error: {e}")
    
    return False


def safe_read(ser: serial.Serial, size: int = 1) -> Optional[bytes]:
    """Safely read data from serial port.
    
    Args:
        ser: Serial object
        size: Number of bytes to read
        
    Returns:
        Bytes read or None if error
    """
    try:
        if ser and ser.is_open:
            data = ser.read(size)
            return data if data else None
    except serial.SerialException as e:
        logger.error(f"Serial read error: {e}")
    
    return None
