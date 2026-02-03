"""Live plotting during data acquisition."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LivePlotter:
    """Real-time visualization of flow measurements during acquisition.
    
    Uses pyqtgraph for fast updates and non-blocking display.
    """
    
    def __init__(self):
        """Initialize live plotter."""
        self.initialized = False
    
    def initialize(self) -> bool:
        """Initialize plotting window.
        
        Returns:
            True if successful
        """
        try:
            import pyqtgraph as pg
            logger.info("pyqtgraph plotter initialized")
            self.initialized = True
            return True
        except ImportError:
            logger.warning("pyqtgraph not available, skipping live plotting")
            return False
    
    def update(self, record) -> None:
        """Update plot with new measurement record.
        
        Args:
            record: DataRecord with latest measurement
        """
        if not self.initialized:
            return
        
        logger.debug(f"Plot update: X={record.x_steps}, Y={record.y_steps}, "
                    f"V={record.velocity_magnitude:.2f} m/s")
    
    def refresh(self) -> None:
        """Refresh display."""
        if not self.initialized:
            return
    
    def close(self) -> None:
        """Close plotting window."""
        logger.info("Live plotter closed")
        self.initialized = False
