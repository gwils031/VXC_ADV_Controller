"""Tests for elimination of false origin (0, 0) injection on serial timeouts.

Validates Item 15: When VXC controller read fails (returns None or raises exception),
no fake (0, 0) coordinate is injected into the position log file.
"""

import tempfile
import unittest
from unittest.mock import MagicMock

from vxc_adv_visualizer.data.vxc_position_logger import VXCPositionLogger
from vxc_adv_visualizer.gui.main_window import VXCLogWorker


class TestFalseOriginSuppression(unittest.TestCase):
    """Verify that serial timeout/failure does not write (0, 0) to position log."""

    def test_no_false_origin_logged_on_serial_timeout(self):
        """When controller.get_position returns None, log_position must not be called with (0,0)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pos_logger = VXCPositionLogger(output_dir=tmpdir, steps_per_foot=48000)
            log_file = pos_logger.start_logging()

            mock_controller = MagicMock()
            worker = VXCLogWorker(
                logger=pos_logger,
                controller=mock_controller,
                write_interval_sec=0.001,
            )

            # Stop the loop after 1 iteration
            def get_position_timeout(motor):
                worker._running = False
                return None

            mock_controller.get_position.side_effect = get_position_timeout

            # start() runs synchronously because worker._running is set False in the callback
            worker.start()

            # Read logged CSV content
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Should only contain header line, NO data rows with (0, 0)
            self.assertEqual(len(lines), 1, f"Expected only header line, but got: {lines}")
            self.assertIn("timestamp_utc", lines[0])

    def test_no_false_origin_logged_on_serial_exception(self):
        """When controller.get_position raises an exception, (0,0) must not be logged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pos_logger = VXCPositionLogger(output_dir=tmpdir, steps_per_foot=48000)
            log_file = pos_logger.start_logging()

            mock_controller = MagicMock()
            worker = VXCLogWorker(
                logger=pos_logger,
                controller=mock_controller,
                write_interval_sec=0.001,
            )

            def get_position_error(motor):
                worker._running = False
                raise IOError("Serial port disconnected")

            mock_controller.get_position.side_effect = get_position_error

            worker.start()

            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 1, f"Expected only header line, but got: {lines}")


if __name__ == '__main__':
    unittest.main()
