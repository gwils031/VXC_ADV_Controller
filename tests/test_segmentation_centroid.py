"""Tests for position segmentation (Euclidean distance) and segment centroid calculation.

Validates:
1. Item 12: Euclidean distance metric (L2 norm) triggers segment boundary on diagonal movement
   where dx < 5mm and dy < 5mm but hypot(dx, dy) > 5mm.
2. Item 11: Segment spatial position is computed as the centroid (mean x, mean y)
   over all dwell samples, while preserving arrival position in segment_anchor_x_m/y_m.
"""

import math
import unittest
from pathlib import Path

from vxc_adv_visualizer.data.adv_vxc_merger import ADVVXCMerger
from vxc_adv_visualizer.monitoring.file_monitor import MergeWorkerThread


class DummyWorker(MergeWorkerThread):
    """Dummy worker for testing segmentation and centroid helper methods."""
    def __init__(self):
        # Initialize with dummy paths
        super().__init__(
            adv_file=Path("dummy.csv"),
            vxc_file=Path("dummy_vxc.csv"),
            output_dir=Path("dummy_out"),
            tolerance_sec=0.5,
            session_manager=None,
        )


class TestSegmentationAndCentroid(unittest.TestCase):
    """Test suite for segmentation and centroid accuracy."""

    def setUp(self):
        self.worker = DummyWorker()
        self.merger = ADVVXCMerger()

    def test_euclidean_diagonal_split(self):
        """Diagonal displacement with dx=4mm, dy=4mm has distance 5.66mm > 5mm and must split."""
        # dx = 0.004 m, dy = 0.004 m -> dist = sqrt(0.004^2 + 0.004^2) = 0.005657 m > 0.005 m
        samples = [
            {'x_m': '0.100000', 'y_m': '0.200000', 'UTC time': '2026-02-11 12:00:00.000'},
            {'x_m': '0.104000', 'y_m': '0.204000', 'UTC time': '2026-02-11 12:00:00.100'},
        ]
        segments = self.worker._segment_matched_samples(self.merger, samples)
        self.assertEqual(len(segments), 2, "Euclidean distance > 5mm must split into 2 segments")
        self.assertEqual(len(segments[0]), 1)
        self.assertEqual(len(segments[1]), 1)

    def test_euclidean_small_movement_stays_same_segment(self):
        """Displacement with dist = 3mm < 5mm must stay in the same segment."""
        # dx = 0.002, dy = 0.002 -> dist = sqrt(8) mm = 2.83 mm < 5 mm
        samples = [
            {'x_m': '0.100000', 'y_m': '0.200000', 'UTC time': '2026-02-11 12:00:00.000'},
            {'x_m': '0.102000', 'y_m': '0.202000', 'UTC time': '2026-02-11 12:00:00.100'},
            {'x_m': '0.101500', 'y_m': '0.201500', 'UTC time': '2026-02-11 12:00:00.200'},
        ]
        segments = self.worker._segment_matched_samples(self.merger, samples)
        self.assertEqual(len(segments), 1, "Distance < 5mm must remain in 1 segment")
        self.assertEqual(len(segments[0]), 3)

    def test_segment_centroid_calculation(self):
        """Segment x_m and y_m must be the centroid, while anchor preserves first arrival."""
        # Samples simulating carriage settling drift:
        # x: 0.100, 0.102, 0.104 -> mean = 0.102
        # y: 0.200, 0.203, 0.206 -> mean = 0.203
        segment_samples = [
            {
                'x_m': '0.100', 'y_m': '0.200', 'UTC time': '2026-02-11 12:00:00.000',
                'Corrected Velocity.X (m/s)': '0.5', 'Corrected Velocity.Y (m/s)': '0.0',
                'Corrected Velocity.Z (m/s)': '0.0',
            },
            {
                'x_m': '0.102', 'y_m': '0.203', 'UTC time': '2026-02-11 12:00:00.100',
                'Corrected Velocity.X (m/s)': '0.5', 'Corrected Velocity.Y (m/s)': '0.0',
                'Corrected Velocity.Z (m/s)': '0.0',
            },
            {
                'x_m': '0.104', 'y_m': '0.206', 'UTC time': '2026-02-11 12:00:00.200',
                'Corrected Velocity.X (m/s)': '0.5', 'Corrected Velocity.Y (m/s)': '0.0',
                'Corrected Velocity.Z (m/s)': '0.0',
            },
        ]

        avg = self.worker._build_segment_average(
            merger=self.merger,
            segment_samples=segment_samples,
            source_adv_file="adv_test.csv",
            segment_index=1,
            segment_count=1,
        )

        # Centroid position
        self.assertAlmostEqual(float(avg['x_m']), 0.102, places=5)
        self.assertAlmostEqual(float(avg['y_m']), 0.203, places=5)

        # Anchor position (arrival coordinate)
        self.assertEqual(avg['segment_anchor_x_m'], '0.100')
        self.assertEqual(avg['segment_anchor_y_m'], '0.200')


if __name__ == '__main__':
    unittest.main()
