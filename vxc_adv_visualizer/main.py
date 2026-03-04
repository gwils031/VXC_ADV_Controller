"""Application entry point for simplified VXC/ADV testing GUI."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from vxc_adv_visualizer.gui.main_window import MainWindow

# Configure logging — rotate at 5 MB, keep 3 backups so logs never balloon on long runs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'vxc_adv_system.log',
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=3,             # Keep .log, .log.1, .log.2, .log.3
            encoding='utf-8',
        ),
        logging.StreamHandler(sys.stdout),  # Explicit stdout avoids Windows cp1252 stderr issues
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Application entry point."""
    # Create config directory if needed
    config_dir = "./config"
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting VXC/ADV Hardware Testing Application...")
    
    # Launch GUI
    qapp = QApplication(sys.argv)
    
    try:
        main_window = MainWindow(config_dir)
        main_window.show()
        
        logger.info("GUI launched successfully")
        exit_code = qapp.exec_()
        
        logger.info("Application shutdown")
        return exit_code
    
    except Exception as e:
        logger.error(f"Application error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
