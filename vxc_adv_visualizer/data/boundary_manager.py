"""
Workspace Boundary Manager

Handles loading, saving, and managing the VXC stage workspace boundaries.
Boundaries define the physical limits of the XY stage in motor steps.
"""

from pathlib import Path
from typing import Dict, Tuple
import yaml
import logging

logger = logging.getLogger(__name__)


class BoundaryManager:
    """Manages workspace boundary configuration and persistence."""
    
    # Default boundaries (motor steps) - matches legacy hard-coded values
    DEFAULT_X_MIN = 0
    DEFAULT_X_MAX = 165654  # ~1.0519 m
    DEFAULT_Y_MIN = 0
    DEFAULT_Y_MAX = 57651   # ~0.3661 m
    
    # Conversion constants
    STEPS_PER_INCH = 4000.0
    METERS_PER_FOOT = 0.3048
    
    def __init__(self, config_path: Path = None):
        """
        Initialize the boundary manager.
        
        Args:
            config_path: Path to experiment_config.yaml. If None, boundaries
                        are only available in memory with default values.
        """
        self.config_path = config_path
        self._boundaries = self.get_default_boundaries()
        
        if config_path and config_path.exists():
            self.load_boundaries()
    
    @classmethod
    def get_default_boundaries(cls) -> Dict[str, int]:
        """
        Get default workspace boundaries in motor steps.
        
        Returns:
            Dictionary with keys: x_min_steps, x_max_steps, y_min_steps, y_max_steps
        """
        return {
            'x_min_steps': cls.DEFAULT_X_MIN,
            'x_max_steps': cls.DEFAULT_X_MAX,
            'y_min_steps': cls.DEFAULT_Y_MIN,
            'y_max_steps': cls.DEFAULT_Y_MAX
        }
    
    def load_boundaries(self) -> Dict[str, int]:
        """
        Load boundaries from configuration file.
        
        Returns:
            Dictionary with boundary values in steps. Falls back to defaults
            if file doesn't exist or boundaries section is missing.
        """
        if not self.config_path or not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}. Using defaults.")
            self._boundaries = self.get_default_boundaries()
            return self._boundaries
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            
            boundaries_section = config.get('boundaries', {})
            
            if boundaries_section:
                # Load from YAML, with fallbacks to defaults
                self._boundaries = {
                    'x_min_steps': int(boundaries_section.get('x_min_steps', self.DEFAULT_X_MIN)),
                    'x_max_steps': int(boundaries_section.get('x_max_steps', self.DEFAULT_X_MAX)),
                    'y_min_steps': int(boundaries_section.get('y_min_steps', self.DEFAULT_Y_MIN)),
                    'y_max_steps': int(boundaries_section.get('y_max_steps', self.DEFAULT_Y_MAX))
                }
                logger.info(f"Loaded boundaries from {self.config_path}: {self._boundaries}")
            else:
                logger.info("No boundaries section in config. Using defaults.")
                self._boundaries = self.get_default_boundaries()
        
        except Exception as e:
            logger.error(f"Error loading boundaries from {self.config_path}: {e}")
            self._boundaries = self.get_default_boundaries()
        
        return self._boundaries
    
    def save_boundaries(self, boundaries: Dict[str, int] = None) -> bool:
        """
        Save boundaries to configuration file.
        
        Args:
            boundaries: Dictionary with x_min_steps, x_max_steps, y_min_steps, y_max_steps.
                       If None, saves current internal boundaries.
        
        Returns:
            True if save succeeded, False otherwise.
        """
        if not self.config_path:
            logger.error("Cannot save boundaries: no config path set")
            return False
        
        if boundaries is not None:
            self._boundaries = boundaries
        
        try:
            # Load existing config
            config = {}
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
            
            # Update boundaries section
            config['boundaries'] = self._boundaries
            
            # Ensure parent directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write back to file
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)
            
            logger.info(f"Saved boundaries to {self.config_path}: {self._boundaries}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving boundaries to {self.config_path}: {e}")
            return False
    
    @property
    def boundaries(self) -> Dict[str, int]:
        """Get current boundaries in motor steps."""
        return self._boundaries.copy()
    
    def update_boundaries(self, boundaries: Dict[str, int]):
        """Update internal boundaries without saving to disk."""
        self._boundaries = boundaries
    
    @classmethod
    def steps_to_meters(cls, steps: int) -> float:
        """
        Convert motor steps to meters.
        
        Args:
            steps: Motor position in steps
        
        Returns:
            Position in meters
        """
        inches = steps / cls.STEPS_PER_INCH
        feet = inches / 12.0
        meters = feet * cls.METERS_PER_FOOT
        return meters
    
    @classmethod
    def meters_to_steps(cls, meters: float) -> int:
        """
        Convert meters to motor steps.
        
        Args:
            meters: Position in meters
        
        Returns:
            Position in motor steps (rounded to nearest integer)
        """
        feet = meters / cls.METERS_PER_FOOT
        inches = feet * 12.0
        steps = inches * cls.STEPS_PER_INCH
        return int(round(steps))
    
    def get_x_range_m(self) -> Tuple[float, float]:
        """Get X axis range in meters (min, max)."""
        x_min_m = self.steps_to_meters(self._boundaries['x_min_steps'])
        x_max_m = self.steps_to_meters(self._boundaries['x_max_steps'])
        return (x_min_m, x_max_m)
    
    def get_y_range_m(self) -> Tuple[float, float]:
        """Get Y axis range in meters (min, max)."""
        y_min_m = self.steps_to_meters(self._boundaries['y_min_steps'])
        y_max_m = self.steps_to_meters(self._boundaries['y_max_steps'])
        return (y_min_m, y_max_m)
    
    def get_all_ranges_m(self) -> Tuple[float, float, float, float]:
        """
        Get all workspace ranges in meters.
        
        Returns:
            Tuple of (x_min_m, x_max_m, y_min_m, y_max_m)
        """
        x_min_m = self.steps_to_meters(self._boundaries['x_min_steps'])
        x_max_m = self.steps_to_meters(self._boundaries['x_max_steps'])
        y_min_m = self.steps_to_meters(self._boundaries['y_min_steps'])
        y_max_m = self.steps_to_meters(self._boundaries['y_max_steps'])
        return (x_min_m, x_max_m, y_min_m, y_max_m)
    
    def validate_position(self, x_steps: int, y_steps: int) -> bool:
        """
        Check if a position is within workspace boundaries.
        
        Args:
            x_steps: X position in motor steps
            y_steps: Y position in motor steps
        
        Returns:
            True if position is valid (within bounds), False otherwise
        """
        x_valid = self._boundaries['x_min_steps'] <= x_steps <= self._boundaries['x_max_steps']
        y_valid = self._boundaries['y_min_steps'] <= y_steps <= self._boundaries['y_max_steps']
        return x_valid and y_valid
