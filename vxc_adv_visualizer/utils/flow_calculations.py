"""Flow calculations and utilities."""

import logging
import math
from typing import Tuple

logger = logging.getLogger(__name__)

# Physical constants
GRAVITY = 9.81  # m/s²
WATER_DENSITY = 1000  # kg/m³


def calculate_froude(velocity_magnitude: float, depth: float) -> float:
    """Calculate Froude number.
    
    Fr = V / sqrt(g * h)
    
    Supercritical flow: Fr > 1.0
    Subcritical flow: Fr < 1.0
    
    Args:
        velocity_magnitude: Total velocity magnitude (m/s)
        depth: Water depth (m)
        
    Returns:
        Froude number (dimensionless)
    """
    if depth <= 0:
        logger.warning("Invalid depth for Froude calculation")
        return 0.0
    
    fr = velocity_magnitude / math.sqrt(GRAVITY * depth)
    return fr


def calculate_turbulence_intensity(u_std: float, v_std: float, w_std: float,
                                   u_mean: float, v_mean: float, w_mean: float) -> float:
    """Calculate turbulence intensity.
    
    TI = sqrt(u'² + v'² + w'²) / sqrt(u² + v² + w²)
    
    Where primes are standard deviations.
    
    Args:
        u_std, v_std, w_std: Standard deviations of velocity components
        u_mean, v_mean, w_mean: Mean velocity components
        
    Returns:
        Turbulence intensity (0-1, typically 0.01-0.2 for flumes)
    """
    rms = math.sqrt(u_std**2 + v_std**2 + w_std**2)
    magnitude = math.sqrt(u_mean**2 + v_mean**2 + w_mean**2)
    
    if magnitude < 1e-6:
        return 0.0
    
    return rms / magnitude


def get_water_kinematic_viscosity(temperature_c: float) -> float:
    """Get kinematic viscosity of water at given temperature.
    
    Approximation for fresh water.
    
    Args:
        temperature_c: Water temperature in Celsius
        
    Returns:
        Kinematic viscosity (m²/s)
    """
    # Simplified approximation (valid 0-30°C)
    # ν ≈ 1.787e-3 * exp(-0.0337 * T)  for T in °C
    return 1.787e-3 * math.exp(-0.0337 * temperature_c) / WATER_DENSITY


def reynolds_number(velocity: float, characteristic_length: float, 
                   temperature_c: float = 20.0) -> float:
    """Calculate Reynolds number.
    
    Re = V * L / ν
    
    Args:
        velocity: Flow velocity (m/s)
        characteristic_length: Characteristic length scale, typically probe diameter (m)
        temperature_c: Water temperature (default 20°C)
        
    Returns:
        Reynolds number (dimensionless)
    """
    nu = get_water_kinematic_viscosity(temperature_c)
    if nu == 0:
        return 0.0
    return velocity * characteristic_length / nu


def convert_steps_to_feet(steps: int) -> float:
    """Convert motor steps to feet.
    
    Conversion: 4600 steps = 0.1 feet
    
    Args:
        steps: Number of motor steps
        
    Returns:
        Distance in feet
    """
    STEPS_PER_FOOT = 46000  # 4600 / 0.1
    return steps / STEPS_PER_FOOT


def convert_feet_to_steps(feet: float) -> int:
    """Convert feet to motor steps.
    
    Conversion: 4600 steps = 0.1 feet
    
    Args:
        feet: Distance in feet
        
    Returns:
        Number of motor steps (integer)
    """
    STEPS_PER_FOOT = 46000  # 4600 / 0.1
    return int(feet * STEPS_PER_FOOT)


def get_adaptive_sampling_duration(froude_number: float, 
                                   base_duration: float = 10.0,
                                   max_duration: float = 120.0) -> float:
    """Determine adaptive sampling duration based on Froude number.
    
    Supercritical flow (Fr > 1.0) gets extended sampling for better statistics.
    
    Args:
        froude_number: Calculated Froude number
        base_duration: Base sampling time for subcritical flow (seconds)
        max_duration: Maximum sampling time (seconds)
        
    Returns:
        Recommended sampling duration (seconds)
    """
    if froude_number < 1.0:
        # Subcritical flow - use base duration
        return base_duration
    else:
        # Supercritical flow - increase duration proportionally
        # At Fr=1.0: base_duration
        # At Fr=2.0: ~1.5x base
        # At Fr=3.0: ~2x base (capped at max)
        multiplier = 1.0 + (froude_number - 1.0) * 0.5
        duration = base_duration * multiplier
        return min(duration, max_duration)


def is_supercritical(froude_number: float) -> bool:
    """Check if flow is supercritical.
    
    Args:
        froude_number: Calculated Froude number
        
    Returns:
        True if Fr > 1.0
    """
    return froude_number > 1.0
