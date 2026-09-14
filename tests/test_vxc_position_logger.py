"""Tests for VXCPositionLogger thread safety and file rotation."""

import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from vxc_adv_visualizer.data.vxc_position_logger import VXCPositionLogger


class TestVXCPositionLogger(unittest.TestCase):
    """Test re-entrant lock behavior and file rotation in VXCPositionLogger."""

    def test_file_rotation_no_deadlock(self):
        """Verify that _rotate_file() does not deadlock with RLock when called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = VXCPositionLogger(output_dir=tmpdir, steps_per_foot=48000.0)
            initial_path = logger.start_logging()
            self.assertTrue(Path(initial_path).exists())

            try:
                # Log initial sample
                logger.log_position(24000, 12000, "GOOD")

                # Advance clock by 1 second so new file gets a distinct second timestamp
                import time
                time.sleep(1.05)

                # Fake the start time to be > 1 hour ago so rotation triggers
                logger.current_file_start = datetime.now(timezone.utc) - timedelta(seconds=3700)

                # This call acquires self.lock, evaluates _should_rotate_file() -> True,
                # and calls _rotate_file() -> stop_logging() and start_logging(), both acquiring self.lock.
                # Under a non-reentrant Lock, this permanently deadlocks. Under RLock, it succeeds.
                logger.log_position(24100, 12100, "GOOD")

                # Verify rotation succeeded and a new file was created
                status = logger.get_status()
                self.assertTrue(status['logging'])
                self.assertNotEqual(status['current_file'], initial_path)
                self.assertTrue(Path(status['current_file']).exists())
            finally:
                logger.stop_logging()


if __name__ == "__main__":
    unittest.main()
