"""Unit tests for Doppler noise floor estimation and correction (Voulgaris & Trowbridge 1998).

Validates Item 9:
1. Small segments (N < 32) safely return 0.0 noise variance (backwards compatibility).
2. Pure white Gaussian noise signal has its noise variance accurately estimated from spectral plateau.
3. Low-frequency coherent flow + white noise: spectral plateau extracts noise without destroying low-frequency energy.
4. Variance correction subtracts noise variance without creating negative values.
5. Configuration loading from YAML.
"""

import math
import tempfile
import unittest
from pathlib import Path
import numpy as np

from vxc_adv_visualizer.data.doppler_noise import (
    estimate_doppler_noise_floor,
    correct_turbulence_variances,
    load_doppler_noise_config,
)


class TestDopplerNoise(unittest.TestCase):
    """Test suite for ADV Doppler noise floor correction."""

    def test_small_sample_size_returns_zero(self):
        """Dwell segments with N < 32 must return 0.0 to prevent spurious spectral estimates."""
        short_series = [0.1, 0.2, 0.15, -0.05, 0.08]
        noise_var = estimate_doppler_noise_floor(short_series, min_samples=32)
        self.assertEqual(noise_var, 0.0)

    def test_white_noise_variance_estimation(self):
        """For a pure white Gaussian noise signal, spectral plateau must match variance."""
        np.random.seed(42)
        # N = 1000 samples at 10 Hz, true noise std = 0.02 m/s -> variance = 0.0004 m^2/s^2
        true_std = 0.02
        noise = np.random.normal(0.0, true_std, 1000)

        est_var = estimate_doppler_noise_floor(noise, fs=10.0, high_freq_fraction=0.30, min_samples=32)

        # Expected variance: true_std^2 = 0.0004
        self.assertAlmostEqual(est_var, true_std**2, delta=0.00015)

    def test_signal_plus_noise_separation(self):
        """For low-frequency wave + white noise, the spectral tail isolates the noise floor."""
        np.random.seed(42)
        t = np.linspace(0, 100, 1000)  # 10 Hz for 100 s
        # Large low-frequency coherent wave at 0.1 Hz (amplitude 0.5 m/s, var = 0.125)
        wave = 0.5 * np.sin(2 * np.pi * 0.1 * t)
        # Doppler white noise at std = 0.015 m/s (var = 0.000225)
        true_noise_std = 0.015
        noise = np.random.normal(0.0, true_noise_std, len(t))
        total_signal = wave + noise

        # The noise floor should measure the noise variance (~0.000225), NOT the wave variance (0.125)
        est_noise = estimate_doppler_noise_floor(total_signal, fs=10.0, high_freq_fraction=0.25, min_samples=32)

        self.assertAlmostEqual(est_noise, true_noise_std**2, delta=0.00015)
        self.assertLess(est_noise, 0.001)  # Must not absorb wave energy

    def test_correct_turbulence_variances(self):
        """Variance subtraction must accurately compute clean normal stresses and TKE."""
        var_x = 0.0100  # meas TI_x = 0.100 m/s
        var_y = 0.0080
        var_z = 0.0040

        noise_x = 0.0020
        noise_y = 0.0010
        noise_z = 0.0005

        vx_c, vy_c, vz_c, tke_c = correct_turbulence_variances(
            var_x, var_y, var_z, noise_x, noise_y, noise_z
        )

        self.assertAlmostEqual(vx_c, 0.0080, places=5)
        self.assertAlmostEqual(vy_c, 0.0070, places=5)
        self.assertAlmostEqual(vz_c, 0.0035, places=5)

        expected_tke = 0.5 * (0.0080 + 0.0070 + 0.0035)
        self.assertAlmostEqual(tke_c, expected_tke, places=5)

    def test_correct_turbulence_variances_clamp_zero(self):
        """When noise variance exceeds measured variance, clean variance is clamped to 0.0."""
        vx_c, vy_c, vz_c, tke_c = correct_turbulence_variances(
            var_x=0.001, var_y=0.002, var_z=0.003,
            noise_x=0.005, noise_y=0.001, noise_z=0.001,
        )
        self.assertEqual(vx_c, 0.0, "Sub-zero variance must be clamped to 0.0")
        self.assertAlmostEqual(vy_c, 0.001, places=5)
        self.assertAlmostEqual(vz_c, 0.002, places=5)
        self.assertAlmostEqual(tke_c, 0.5 * (0.0 + 0.001 + 0.002), places=5)

    def test_load_doppler_noise_config(self):
        """Test reading Doppler noise config from YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "experiment_config.yaml"
            cfg_path.write_text(
                "doppler_noise:\n  enabled: true\n  min_samples: 64\n  high_freq_fraction: 0.3\n",
                encoding="utf-8"
            )
            cfg = load_doppler_noise_config(cfg_path)
            self.assertTrue(cfg["enabled"])
            self.assertEqual(cfg["min_samples"], 64)
            self.assertEqual(cfg["high_freq_fraction"], 0.3)


if __name__ == '__main__':
    unittest.main()
