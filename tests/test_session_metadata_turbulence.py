"""Tests for turbulence summary block in session metadata export."""

import tempfile
import unittest
from pathlib import Path

from vxc_adv_visualizer.data.session_manager import SessionConfig, SessionManager


class TestSessionMetadataTurbulence(unittest.TestCase):
    """Ensure metadata.yaml includes turbulence summary statistics."""

    def test_metadata_contains_turbulence_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "Data_Output"
            manager = SessionManager(str(base))
            manager.start_session(SessionConfig(session_name="meta_turbulence"))

            manager.append_measurement(
                merged_data=[{"vxc_quality": "GOOD"}],
                averaged_data={
                    "status": "OK",
                    "sample_count": 10,
                    "Correlation.Avg (%)": 80,
                    "SNR.Avg (dB)": 20,
                    "TI_x (m/s)": 0.10,
                    "TI_y (m/s)": 0.20,
                    "TI_z (m/s)": 0.30,
                    "TKE (m2/s2)": 0.40,
                    "u_prime_x_u_prime_z_cov (m2/s2)": -0.01,
                    "Reynolds tau_xz (Pa)": 0.50,
                },
            )
            manager.append_measurement(
                merged_data=[{"vxc_quality": "GOOD"}],
                averaged_data={
                    "status": "OK",
                    "sample_count": 20,
                    "Correlation.Avg (%)": 82,
                    "SNR.Avg (dB)": 21,
                    "TI_x (m/s)": 0.20,
                    "TI_y (m/s)": 0.10,
                    "TI_z (m/s)": 0.40,
                    "TKE (m2/s2)": 0.60,
                    "u_prime_x_u_prime_z_cov (m2/s2)": -0.02,
                    "Reynolds tau_xz (Pa)": 0.90,
                },
            )

            result = manager.stop_session()
            metadata = result["metadata"]

            self.assertIn("turbulence_summary", metadata)
            summary = metadata["turbulence_summary"]

            self.assertEqual(summary["rows_with_turbulence"], 2)
            self.assertAlmostEqual(summary["TI_x (m/s)"]["mean"], 0.15, places=9)
            self.assertAlmostEqual(summary["TKE (m2/s2)"]["mean"], 0.5, places=9)
            self.assertAlmostEqual(summary["Reynolds tau_xz (Pa)"]["min"], 0.5, places=9)
            self.assertAlmostEqual(summary["Reynolds tau_xz (Pa)"]["max"], 0.9, places=9)


if __name__ == "__main__":
    unittest.main()
