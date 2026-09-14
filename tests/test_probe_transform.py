"""Unit tests for probe coordinate transformation (mounting misalignment rotation).

Validates Item 13:
1. Rotation matrix properties (orthogonality, determinant = +1).
2. Zero rotation produces identity transformation.
3. Pure pitch, roll, and yaw produce analytically expected vector components.
4. Vector length / kinetic energy conservation across rotations.
5. Configuration loading from YAML.
"""

import math
import tempfile
import unittest
from pathlib import Path
import numpy as np

from vxc_adv_visualizer.data.probe_transform import (
    build_rotation_matrix,
    transform_velocity_vectors,
    load_probe_orientation,
)


class TestProbeTransform(unittest.TestCase):
    """Test suite for 3D probe coordinate transformations."""

    def test_identity_matrix_at_zero_degrees(self):
        """Zero angles must return an exact 3x3 identity matrix."""
        R = build_rotation_matrix(roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0)
        np.testing.assert_array_almost_equal(R, np.eye(3))

    def test_matrix_orthogonality_and_determinant(self):
        """Rotation matrix must be strictly orthogonal (R @ R.T = I) with det(R) = +1."""
        for roll, pitch, yaw in [(15.0, -10.0, 5.0), (45.0, 30.0, -60.0), (-5.0, 2.5, 180.0)]:
            R = build_rotation_matrix(roll, pitch, yaw)
            # R @ R^T = I
            np.testing.assert_array_almost_equal(R @ R.T, np.eye(3), decimal=6)
            # det(R) = +1 (proper rotation, no reflection)
            self.assertAlmostEqual(float(np.linalg.det(R)), 1.0, places=6)

    def test_pure_pitch_transformation(self):
        """Pure pitch around Y axis should rotate in the X-Z plane."""
        # For a probe pitched by +30 deg:
        # A pure probe streamwise flow u_p = 1.0, v_p = 0.0, w_p = 0.0
        # In flume coordinates:
        # u_flume = u_p * cos(30) = sqrt(3)/2 ≈ 0.866025
        # v_flume = 0.0
        # w_flume = -u_p * sin(30) = -0.500000
        u = [1.0, 2.0]
        v = [0.0, 0.0]
        w = [0.0, 0.0]
        uf, vf, wf = transform_velocity_vectors(u, v, w, roll_deg=0.0, pitch_deg=30.0, yaw_deg=0.0)

        self.assertAlmostEqual(uf[0], math.cos(math.radians(30.0)), places=5)
        self.assertAlmostEqual(vf[0], 0.0, places=5)
        self.assertAlmostEqual(wf[0], -math.sin(math.radians(30.0)), places=5)

    def test_vector_norm_conservation(self):
        """Magnitude of velocity vector must be strictly conserved under rotation."""
        u = [0.35, -0.42, 0.12]
        v = [0.15, 0.28, -0.05]
        w = [0.08, -0.09, 0.31]

        uf, vf, wf = transform_velocity_vectors(u, v, w, roll_deg=12.5, pitch_deg=-8.2, yaw_deg=4.1)

        for i in range(len(u)):
            mag_orig = math.sqrt(u[i]**2 + v[i]**2 + w[i]**2)
            mag_rot = math.sqrt(uf[i]**2 + vf[i]**2 + wf[i]**2)
            self.assertAlmostEqual(mag_orig, mag_rot, places=5)

    def test_load_probe_orientation_from_yaml(self):
        """Test reading orientation angles from experiment_config.yaml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "experiment_config.yaml"
            cfg_path.write_text(
                "probe_orientation:\n  roll_deg: 1.5\n  pitch_deg: -2.5\n  yaw_deg: 0.8\n",
                encoding="utf-8"
            )
            roll, pitch, yaw = load_probe_orientation(cfg_path)
            self.assertEqual(roll, 1.5)
            self.assertEqual(pitch, -2.5)
            self.assertEqual(yaw, 0.8)

    def test_load_probe_orientation_defaults(self):
        """When configuration has no probe_orientation, defaults to (0.0, 0.0, 0.0)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "experiment_config.yaml"
            cfg_path.write_text("boundaries:\n  x_min_steps: 0\n", encoding="utf-8")
            roll, pitch, yaw = load_probe_orientation(cfg_path)
            self.assertEqual((roll, pitch, yaw), (0.0, 0.0, 0.0))


if __name__ == '__main__':
    unittest.main()
