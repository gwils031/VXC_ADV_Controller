"""Tests for Phase-Space Thresholding (PST) despiking algorithm."""

import math
import unittest
import numpy as np

from vxc_adv_visualizer.data.pst_despike import pst_despike, _robust_std, _compute_derivatives


class TestPSTDespiking(unittest.TestCase):
    """Test suite for PST despiking with Wahl (2003) MAD modification."""

    def test_clean_signal_no_false_positives(self):
        """A clean sinusoidal signal should have zero spikes detected."""
        t = np.linspace(0, 10, 200)
        clean = 0.5 + 0.1 * np.sin(2 * math.pi * 0.5 * t)
        result = pst_despike(clean, dt=0.05)
        self.assertEqual(result.spike_count, 0)
        self.assertEqual(result.spike_pct, 0.0)
        np.testing.assert_allclose(result.cleaned, clean, rtol=1e-5)

    def test_injected_spikes_detected_and_cleaned(self):
        """Injected velocity spikes should be detected and interpolated."""
        np.random.seed(42)
        n = 300
        # Background turbulent-like signal
        t = np.linspace(0, 30, n)
        signal = 0.4 + 0.05 * np.sin(t) + np.random.normal(0, 0.01, n)

        # Inject extreme spikes (e.g. boundary reflection / Doppler aliasing)
        spike_indices = [50, 120, 210]
        corrupted = signal.copy()
        corrupted[50] = 2.5   # Massive positive spike
        corrupted[120] = -1.8 # Massive negative spike
        corrupted[210] = 3.0  # Massive positive spike

        result = pst_despike(corrupted, dt=0.1)

        self.assertGreaterEqual(result.spike_count, 3)
        for idx in spike_indices:
            self.assertTrue(result.spike_mask[idx], f"Spike at index {idx} should be detected")
            # Cleaned value should be close to original underlying signal
            self.assertAlmostEqual(result.cleaned[idx], signal[idx], delta=0.08)

    def test_small_sample_size_skipped(self):
        """Short dwell segments (N < min_points) should gracefully skip despiking."""
        short_data = [0.1, 0.2, 5.0, 0.1]
        result = pst_despike(short_data, min_points=10)
        self.assertEqual(result.spike_count, 0)
        self.assertEqual(result.iterations, 0)
        np.testing.assert_array_equal(result.cleaned, np.array(short_data))

    def test_robust_std_resists_outliers(self):
        """Wahl MAD robust std should remain stable despite huge outlier."""
        data = np.random.normal(0, 1.0, 100)
        clean_std = _robust_std(data)

        # Add single massive outlier
        data_corrupt = data.copy()
        data_corrupt[10] = 1000.0

        robust_std_corrupt = _robust_std(data_corrupt)
        normal_std_corrupt = float(np.std(data_corrupt, ddof=1))

        # Normal std blows up to ~100; robust std remains near ~1.0
        self.assertAlmostEqual(robust_std_corrupt, clean_std, delta=0.25)
        self.assertGreater(normal_std_corrupt, 50.0)

    def test_derivatives_calculation(self):
        """First and second derivatives should correctly approximate analytic derivatives."""
        dt = 0.01
        t = np.arange(0, 2.0, dt)
        # u = sin(t) -> du/dt = cos(t), d2u/dt2 = -sin(t)
        u = np.sin(t)
        du, d2u = _compute_derivatives(u, dt)

        # Check central difference points (avoiding boundary points)
        expected_du = np.cos(t)
        expected_d2u = -np.sin(t)

        np.testing.assert_allclose(du[10:-10], expected_du[10:-10], atol=0.02)
        np.testing.assert_allclose(d2u[10:-10], expected_d2u[10:-10], atol=0.05)


if __name__ == "__main__":
    unittest.main()
