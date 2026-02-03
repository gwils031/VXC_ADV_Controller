"""Application entry point with hardware initialization and GUI launch."""

import logging
import sys
import os
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMessageBox
import yaml

from controllers.vxc_controller import VXCController
from controllers.adv_controller import ADVController
from gui.main_window import MainWindow
from utils.serial_utils import list_available_ports

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('vxc_adv_system.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class Application:
    """Main application orchestrator."""
    
    def __init__(self, config_dir: str = "./config"):
        """Initialize application.
        
        Args:
            config_dir: Path to configuration directory
        """
        self.config_dir = config_dir
        self.config = {}
        self.vxc = None
        self.adv = None
        self.main_window = None
        
        logger.info("Application initializing...")
    
    def load_configuration(self) -> bool:
        """Load configuration files.
        
        Returns:
            True if successful
        """
        try:
            config_files = {
                'vxc': 'vxc_config.yaml',
                'adv': 'adv_config.yaml',
                'experiment': 'experiment_config.yaml',
            }
            
            for key, filename in config_files.items():
                filepath = os.path.join(self.config_dir, filename)
                
                if os.path.exists(filepath):
                    with open(filepath, 'r') as f:
                        self.config[key] = yaml.safe_load(f) or {}
                    logger.info(f"Loaded configuration: {filename}")
                else:
                    self.config[key] = {}
                    logger.warning(f"Configuration not found: {filename}")
            
            return True
        
        except Exception as e:
            logger.error(f"Configuration loading failed: {e}")
            return False
    
    def initialize_hardware(self) -> bool:
        """Initialize VXC and ADV controllers.
        
        Returns:
            True if successful
        """
        try:
            # Get port information
            ports = list_available_ports()
            if not ports:
                logger.error("No serial ports available")
                return False
            
            vxc_port = self.config.get('vxc', {}).get('port', 'COM3')
            adv_port = self.config.get('adv', {}).get('port', 'COM4')
            
            # Initialize VXC
            logger.info(f"Initializing VXC on {vxc_port}...")
            self.vxc = VXCController(vxc_port)
            
            if not self.vxc.connect():
                logger.error(f"Failed to connect VXC on {vxc_port}")
                return False
            
            # Initialize ADV
            logger.info(f"Initializing ADV on {adv_port}...")
            self.adv = ADVController(adv_port)
            
            if not self.adv.connect():
                logger.error(f"Failed to connect ADV on {adv_port}")
                self.vxc.disconnect()
                return False
            
            logger.info("Hardware initialization successful")
            return True
        
        except Exception as e:
            logger.error(f"Hardware initialization failed: {e}")
            return False
    
    def launch_gui(self) -> int:
        """Launch PyQt5 GUI.
        
        Returns:
            Application exit code
        """
        try:
            qapp = QApplication(sys.argv)
            
            self.main_window = MainWindow(self.config_dir)
            self.main_window.show()
            
            logger.info("GUI launched successfully")
            return qapp.exec_()
        
        except Exception as e:
            logger.error(f"GUI launch failed: {e}")
            return 1
    
    def shutdown(self):
        """Gracefully shutdown application."""
        logger.info("Shutting down...")
        
        try:
            if self.vxc:
                self.vxc.stop_motion()
                self.vxc.disconnect()
                logger.info("VXC disconnected")
            
            if self.adv:
                self.adv.stop_stream()
                self.adv.disconnect()
                logger.info("ADV disconnected")
        
        except Exception as e:
            logger.error(f"Shutdown error: {e}")


def main():
    """Application entry point."""
    # Create config directory if needed
    config_dir = "./config"
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    
    # Initialize application
    app = Application(config_dir)
    
    # Load configuration
    if not app.load_configuration():
        logger.warning("Using default configuration")
    
    # Launch GUI (hardware connection optional - can connect in GUI)
    exit_code = app.launch_gui()
    
    # Cleanup
    app.shutdown()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
