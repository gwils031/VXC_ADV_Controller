"""Tests for USGS TM 3-A4 minimum beam quality filtering in MergeWorkerThread."""

import unittest
from pathlib import Path
from vxc_adv_visualizer.data.adv_vxc_merger import ADVVXCMerger
from vxc_adv_visualizer.monitoring.file_monitor import MergeWorkerThread


class TestBeamQualityFiltering(unittest.TestCase):
    """Verify that all 3 acoustic beams must pass quality thresholds."""

    def setUp(self):
        self.worker = MergeWorkerThread(
            adv_file=Path("dummy.csv"),
            vxc_file=Path("dummy.csv"),
            output_dir=Path("dummy"),
            tolerance_sec=0.5,
        )
        self.merger = ADVVXCMerger()

    def test_single_degraded_beam_fails_usgs_filter(self):
        """Beam 1=95%, Beam 2=95%, Beam 3=25% has average=71.7% but minimum=25%.
        Under USGS TM 3-A4, it must FAIL a 70% correlation threshold.
        """
        sample = {
            'Correlation Score.Beam1 (%)': '95.0',
            'Correlation Score.Beam2 (%)': '95.0',
            'Correlation Score.Beam3 (%)': '25.0',
            'SNR.Beam1 (dB)': '20.0',
            'SNR.Beam2 (dB)': '20.0',
            'SNR.Beam3 (dB)': '20.0',
        }
        # Under USGS standard (min), this fails 70% threshold
        passes = self.worker._sample_passes_filter_gates(
            self.merger,
            sample,
            min_corr_avg_pct=70.0,
            min_snr_avg_db=15.0,
        )
        self.assertFalse(passes, "Sample with one degraded beam (25%) must not pass 70% threshold")

    def test_all_good_beams_pass(self):
        """When all beams are above thresholds, sample passes."""
        sample = {
            'Correlation Score.Beam1 (%)': '85.0',
            'Correlation Score.Beam2 (%)': '75.0',
            'Correlation Score.Beam3 (%)': '90.0',
            'SNR.Beam1 (dB)': '18.0',
            'SNR.Beam2 (dB)': '22.0',
            'SNR.Beam3 (dB)': '19.0',
        }
        passes = self.worker._sample_passes_filter_gates(
            self.merger,
            sample,
            min_corr_avg_pct=70.0,
            min_snr_avg_db=15.0,
        )
        self.assertTrue(passes, "Sample with all beams >= 70% and SNR >= 15dB must pass")

    def test_single_low_snr_beam_fails(self):
        """SNR Beam 1=25dB, Beam 2=25dB, Beam 3=5dB fails 15dB threshold."""
        sample = {
            'Correlation Score.Beam1 (%)': '85.0',
            'Correlation Score.Beam2 (%)': '85.0',
            'Correlation Score.Beam3 (%)': '85.0',
            'SNR.Beam1 (dB)': '25.0',
            'SNR.Beam2 (dB)': '25.0',
            'SNR.Beam3 (dB)': '5.0',
        }
        passes = self.worker._sample_passes_filter_gates(
            self.merger,
            sample,
            min_corr_avg_pct=70.0,
            min_snr_avg_db=15.0,
        )
        self.assertFalse(passes, "Sample with one low SNR beam (5dB) must fail 15dB threshold")


if __name__ == "__main__":
    unittest.main()
