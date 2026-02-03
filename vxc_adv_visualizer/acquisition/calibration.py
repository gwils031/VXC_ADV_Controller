"""Calibration system for XY stage with coordinate system awareness."""

import logging
from typing import Optional, Tuple, List
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


# Unit conversion: 4600 steps = 0.1 feet
STEPS_PER_FOOT = 46000  # 4600 steps / 0.1 ft


@dataclass
class CalibrationPoint:
    """Single calibration point in motor space."""
    x_steps: int
    y_steps: int
    label: str


@dataclass
class GridDefinition:
    """Definition of measurement grid."""
    origin_x: int  # Bottom-left X in steps
    origin_y: int  # Bottom-left Y in steps (water bottom depth)
    max_x: int  # Top-right X in steps
    max_y: int  # Top-right Y in steps (water surface)
    x_spacing: float  # Grid spacing in feet
    y_spacing: float  # Grid spacing in feet
    roi_zones: List[dict]  # List of ROI bounding boxes with density multipliers


class CalibrationManager:
    """Manages XY plane calibration and grid generation.
    
    Coordinate system:
    - X: Bank-to-bank (0 = left bank)
    - Y: Water depth (0 = bottom, positive upward)
    - Z: Upstream (user-specified per plane)
    """
    
    def __init__(self):
        """Initialize calibration manager."""
        self.origin: Optional[CalibrationPoint] = None
        self.boundary: Optional[CalibrationPoint] = None
        self.grid: Optional[GridDefinition] = None
        self.home_position: Optional[Tuple[int, int]] = None
    
    def set_origin(self, x_steps: int, y_steps: int) -> None:
        """Set bottom-left origin (0,0) point.
        
        Args:
            x_steps: X position in motor steps
            y_steps: Y position in motor steps (water bottom)
        """
        self.origin = CalibrationPoint(x_steps, y_steps, "origin")
        logger.info(f"Origin set to X={x_steps}, Y={y_steps} steps")
    
    def set_boundary(self, x_steps: int, y_steps: int) -> None:
        """Set top-right boundary point.
        
        Args:
            x_steps: X position in motor steps (top-right X)
            y_steps: Y position in motor steps (surface)
        """
        self.boundary = CalibrationPoint(x_steps, y_steps, "boundary")
        logger.info(f"Boundary set to X={x_steps}, Y={y_steps} steps")
    
    def generate_grid(self, x_spacing_feet: float, y_spacing_feet: float,
                     roi_zones: Optional[List[dict]] = None) -> Optional[GridDefinition]:
        """Generate measurement grid from calibration points.
        
        Args:
            x_spacing_feet: Spacing between X measurements (feet)
            y_spacing_feet: Spacing between Y measurements (feet)
            roi_zones: List of regions with custom density (optional)
                      Each zone: {"x_min": feet, "x_max": feet, "y_min": feet, 
                                  "y_max": feet, "density_multiplier": float}
            
        Returns:
            GridDefinition object or None if calibration incomplete
        """
        if self.origin is None or self.boundary is None:
            logger.error("Origin and boundary must be set before generating grid")
            return None
        
        # Create grid
        self.grid = GridDefinition(
            origin_x=self.origin.x_steps,
            origin_y=self.origin.y_steps,
            max_x=self.boundary.x_steps,
            max_y=self.boundary.y_steps,
            x_spacing=x_spacing_feet,
            y_spacing=y_spacing_feet,
            roi_zones=roi_zones or []
        )
        
        logger.info(f"Grid generated: X steps [{self.grid.origin_x}, {self.grid.max_x}], "
                   f"Y steps [{self.grid.origin_y}, {self.grid.max_y}]")
        return self.grid
    
    def get_grid_positions(self) -> Optional[List[Tuple[int, int]]]:
        """Get list of all measurement positions in grid.
        
        Returns:
            List of (x_steps, y_steps) tuples, or None if grid not generated
        """
        if self.grid is None:
            logger.error("Grid not yet generated")
            return None
        
        positions = []
        x_spacing_steps = int(self.grid.x_spacing * STEPS_PER_FOOT)
        y_spacing_steps = int(self.grid.y_spacing * STEPS_PER_FOOT)
        
        # Iterate through grid
        x = self.grid.origin_x
        while x <= self.grid.max_x:
            y = self.grid.origin_y
            while y <= self.grid.max_y:
                # Check if position is in high-density ROI zone
                x_feet = (x - self.grid.origin_x) / STEPS_PER_FOOT
                y_feet = (y - self.grid.origin_y) / STEPS_PER_FOOT
                
                in_roi = False
                for roi in self.grid.roi_zones:
                    if (roi.get('x_min', 0) <= x_feet <= roi.get('x_max', float('inf')) and
                        roi.get('y_min', 0) <= y_feet <= roi.get('y_max', float('inf'))):
                        in_roi = True
                        break
                
                # Always include grid point, ROI density handled in sampler
                positions.append((x, y))
                y += y_spacing_steps
            
            x += x_spacing_steps
        
        logger.info(f"Generated {len(positions)} measurement positions")
        return positions
    
    def steps_to_feet(self, steps: int, axis: str = 'X') -> float:
        """Convert motor steps to feet.
        
        Args:
            steps: Number of steps
            axis: Axis character (for logging)
            
        Returns:
            Distance in feet
        """
        return steps / STEPS_PER_FOOT
    
    def feet_to_steps(self, feet: float, axis: str = 'X') -> int:
        """Convert feet to motor steps.
        
        Args:
            feet: Distance in feet
            axis: Axis character (for logging)
            
        Returns:
            Number of steps (integer)
        """
        return int(feet * STEPS_PER_FOOT)
    
    def set_home_position(self, x_steps: Optional[int] = None, 
                         y_steps: Optional[int] = None) -> None:
        """Set safe return home position.
        
        Args:
            x_steps: X position in steps (None to calculate from grid)
            y_steps: Y position in steps (None to calculate from grid)
        """
        if x_steps is None or y_steps is None:
            # Default: center X, top Y (surface)
            if self.grid is None:
                logger.error("Cannot calculate home position without grid")
                return
            
            x_steps = (self.grid.origin_x + self.grid.max_x) // 2
            y_steps = self.grid.max_y
        
        self.home_position = (x_steps, y_steps)
        logger.info(f"Home position set to X={x_steps}, Y={y_steps} steps")
    
    def get_home_position(self) -> Optional[Tuple[int, int]]:
        """Get safe return home position.
        
        Returns:
            (x_steps, y_steps) tuple or None
        """
        return self.home_position
    
    def to_dict(self) -> dict:
        """Export calibration to dictionary.
        
        Returns:
            Calibration dictionary
        """
        result = {
            'origin': None,
            'boundary': None,
            'grid': None,
            'home_position': None,
        }
        
        if self.origin:
            result['origin'] = {'x_steps': self.origin.x_steps, 'y_steps': self.origin.y_steps}
        
        if self.boundary:
            result['boundary'] = {'x_steps': self.boundary.x_steps, 'y_steps': self.boundary.y_steps}
        
        if self.grid:
            result['grid'] = {
                'origin_x': self.grid.origin_x,
                'origin_y': self.grid.origin_y,
                'max_x': self.grid.max_x,
                'max_y': self.grid.max_y,
                'x_spacing': self.grid.x_spacing,
                'y_spacing': self.grid.y_spacing,
                'roi_zones': self.grid.roi_zones,
            }
        
        if self.home_position:
            result['home_position'] = {'x_steps': self.home_position[0], 'y_steps': self.home_position[1]}
        
        return result
    
    def from_dict(self, data: dict) -> None:
        """Load calibration from dictionary.
        
        Args:
            data: Calibration dictionary
        """
        if data.get('origin'):
            self.set_origin(data['origin']['x_steps'], data['origin']['y_steps'])
        
        if data.get('boundary'):
            self.set_boundary(data['boundary']['x_steps'], data['boundary']['y_steps'])
        
        if data.get('grid'):
            grid_data = data['grid']
            self.grid = GridDefinition(
                origin_x=grid_data['origin_x'],
                origin_y=grid_data['origin_y'],
                max_x=grid_data['max_x'],
                max_y=grid_data['max_y'],
                x_spacing=grid_data['x_spacing'],
                y_spacing=grid_data['y_spacing'],
                roi_zones=grid_data.get('roi_zones', []),
            )
        
        if data.get('home_position'):
            self.home_position = (data['home_position']['x_steps'], 
                                 data['home_position']['y_steps'])
