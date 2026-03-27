"""Tests for turbulence metrics added to merge worker/session outputs."""

import csv
import math
import tempfile
import unittest
from pathlib import Path

from vxc_adv_visualizer.data.session_manager import SessionConfig, SessionManager
from vxc_adv_visualizer.monitoring.file_monitor import MergeWorkerThread


class TestTurbulenceMetrics(unittest.TestCase):
    """Validate TI/TKE/tau outputs and raw fluctuation columns."""

    def _write_file(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def test_turbulence_metrics_written_to_raw_and_averaged(self):
        """Per-sample fluctuation terms should feed TI/TKE/tau in averaged output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            adv_path = root / "20260211-214219.csv"
            vxc_path = root / "vxc.csv"

            adv_csv = """UTC time,Corrected Velocity.X (m/s),Corrected Velocity.Y (m/s),Corrected Velocity.Z (m/s),Temperature (°C),Raw Pressure (dbar),Voltage (V),Correlation Score.Beam1 (%),Correlation Score.Beam2 (%),Correlation Score.Beam3 (%),SNR.Beam1 (dB),SNR.Beam2 (dB),SNR.Beam3 (dB)
2026-02-11 21:42:19.100,1.0,0.0,2.0,20.0,9.0,12.0,80,80,80,25,25,25
2026-02-11 21:42:20.100,2.0,0.0,0.0,20.0,9.0,12.0,80,80,80,25,25,25
2026-02-11 21:42:21.100,3.0,0.0,-2.0,20.0,9.0,12.0,80,80,80,25,25,25
"""
            vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.100,0.10,0.20,GOOD
2026-02-11 21:42:20.100,0.10,0.20,GOOD
2026-02-11 21:42:21.100,0.10,0.20,GOOD
"""

            self._write_file(adv_path, adv_csv)
            self._write_file(vxc_path, vxc_csv)

            session_mgr = SessionManager(str(root / "Data_Output"))
            session_mgr.start_session(SessionConfig(session_name="turbulence_test"))

            worker = MergeWorkerThread(
                adv_file=adv_path,
                vxc_file=vxc_path,
                output_dir=root / "Data_Output",
                tolerance_sec=0.5,
                session_manager=session_mgr,
            )
            worker.run()

            raw_file = session_mgr.session_dir / "master_merged.csv"
            avg_file = session_mgr.session_dir / "master_averaged.csv"

            with open(raw_file, "r", encoding="utf-8", newline="") as f:
                raw_rows = list(csv.DictReader(f))

            with open(avg_file, "r", encoding="utf-8", newline="") as f:
                avg_rows = list(csv.DictReader(f))

            self.assertEqual(len(raw_rows), 3)
            self.assertEqual(len(avg_rows), 1)

            # Raw rows: per-sample fluctuation columns exist and are populated.
            for row in raw_rows:
                self.assertIn("u_prime_x (m/s)", row)
                self.assertIn("u_prime_y (m/s)", row)
                self.assertIn("u_prime_z (m/s)", row)
                self.assertIn("u_prime_x2 (m2/s2)", row)
                self.assertIn("u_prime_y2 (m2/s2)", row)
                self.assertIn("u_prime_z2 (m2/s2)", row)
                self.assertIn("u_prime_x_u_prime_z (m2/s2)", row)
                self.assertNotEqual(row["u_prime_x (m/s)"], "")

            avg = avg_rows[0]

            expected_ti_x = math.sqrt(2.0 / 3.0)
            expected_ti_y = 0.0
            expected_ti_z = math.sqrt(8.0 / 3.0)
            expected_tke = 0.5 * ((2.0 / 3.0) + 0.0 + (8.0 / 3.0))
            expected_cov = -4.0 / 3.0

            t = 20.0
            expected_rho = (
                999.842594
                + 6.793952e-2 * t
                - 9.09529e-3 * (t ** 2)
                + 1.001685e-4 * (t ** 3)
                - 1.120083e-6 * (t ** 4)
                + 6.536332e-9 * (t ** 5)
            )
            expected_tau = -expected_rho * expected_cov

            self.assertAlmostEqual(float(avg["TI_x (m/s)"]), expected_ti_x, places=9)
            self.assertAlmostEqual(float(avg["TI_y (m/s)"]), expected_ti_y, places=9)
            self.assertAlmostEqual(float(avg["TI_z (m/s)"]), expected_ti_z, places=9)
            self.assertAlmostEqual(float(avg["TKE (m2/s2)"]), expected_tke, places=9)
            self.assertAlmostEqual(float(avg["u_prime_x_u_prime_z_cov (m2/s2)"]), expected_cov, places=9)
            self.assertAlmostEqual(float(avg["rho_freshwater (kg/m3)"]), expected_rho, places=6)
            self.assertAlmostEqual(float(avg["Reynolds tau_xz (Pa)"]), expected_tau, places=6)

            session_mgr.stop_session()

    def test_missing_components_leave_turbulence_fields_blank(self):
        """Missing corrected components should produce blank turbulence outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            adv_path = root / "20260211-214219.csv"
            vxc_path = root / "vxc.csv"

            adv_csv = """UTC time,Corrected Velocity.X (m/s),Temperature (°C),Raw Pressure (dbar),Voltage (V)
2026-02-11 21:42:19.100,1.0,20.0,9.0,12.0
2026-02-11 21:42:20.100,2.0,20.0,9.0,12.0
"""
            vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.100,0.10,0.20,GOOD
2026-02-11 21:42:20.100,0.10,0.20,GOOD
"""

            self._write_file(adv_path, adv_csv)
            self._write_file(vxc_path, vxc_csv)

            session_mgr = SessionManager(str(root / "Data_Output"))
            session_mgr.start_session(SessionConfig(session_name="turbulence_missing"))

            worker = MergeWorkerThread(
                adv_file=adv_path,
                vxc_file=vxc_path,
                output_dir=root / "Data_Output",
                tolerance_sec=0.5,
                session_manager=session_mgr,
            )
            worker.run()

            avg_file = session_mgr.session_dir / "master_averaged.csv"
            with open(avg_file, "r", encoding="utf-8", newline="") as f:
                avg = list(csv.DictReader(f))[0]

            self.assertNotEqual(avg["TI_x (m/s)"], "")
            self.assertEqual(avg["TI_y (m/s)"], "")
            self.assertEqual(avg["TI_z (m/s)"], "")
            self.assertEqual(avg["TKE (m2/s2)"], "")
            self.assertEqual(avg["u_prime_x_u_prime_z_cov (m2/s2)"], "")
            self.assertEqual(avg["rho_freshwater (kg/m3)"], "")
            self.assertEqual(avg["Reynolds tau_xz (Pa)"], "")

            session_mgr.stop_session()

    def test_multi_location_file_segments_into_multiple_averaged_rows(self):
        """One ADV file with three position plateaus should produce three averaged rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            adv_path = root / "20260211-214219.csv"
            vxc_path = root / "vxc.csv"

            adv_csv = """UTC time,Corrected Velocity.X (m/s),Corrected Velocity.Y (m/s),Corrected Velocity.Z (m/s),Temperature (°C),Raw Pressure (dbar),Voltage (V),Correlation Score.Beam1 (%),Correlation Score.Beam2 (%),Correlation Score.Beam3 (%),SNR.Beam1 (dB),SNR.Beam2 (dB),SNR.Beam3 (dB)
2026-02-11 21:42:19.100,1.0,0.1,0.0,20.0,9.0,12.0,80,80,80,25,25,25
2026-02-11 21:42:20.100,1.1,0.1,0.0,20.0,9.0,12.0,80,80,80,25,25,25
2026-02-11 21:42:21.100,2.0,0.2,0.0,20.0,9.0,12.0,80,80,80,25,25,25
2026-02-11 21:42:22.100,2.1,0.2,0.0,20.0,9.0,12.0,80,80,80,25,25,25
2026-02-11 21:42:23.100,3.0,0.3,0.0,20.0,9.0,12.0,80,80,80,25,25,25
2026-02-11 21:42:24.100,3.1,0.3,0.0,20.0,9.0,12.0,80,80,80,25,25,25
"""
            vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.100,0.100,0.200,GOOD
2026-02-11 21:42:20.100,0.100,0.200,GOOD
2026-02-11 21:42:21.100,0.106,0.200,GOOD
2026-02-11 21:42:22.100,0.106,0.200,GOOD
2026-02-11 21:42:23.100,0.106,0.207,GOOD
2026-02-11 21:42:24.100,0.106,0.207,GOOD
"""

            self._write_file(adv_path, adv_csv)
            self._write_file(vxc_path, vxc_csv)

            session_mgr = SessionManager(str(root / "Data_Output"))
            session_mgr.start_session(SessionConfig(session_name="segment_test"))

            worker = MergeWorkerThread(
                adv_file=adv_path,
                vxc_file=vxc_path,
                output_dir=root / "Data_Output",
                tolerance_sec=0.5,
                session_manager=session_mgr,
            )
            worker.run()

            raw_file = session_mgr.session_dir / "master_merged.csv"
            avg_file = session_mgr.session_dir / "master_averaged.csv"

            with open(raw_file, "r", encoding="utf-8", newline="") as f:
                raw_rows = list(csv.DictReader(f))
            with open(avg_file, "r", encoding="utf-8", newline="") as f:
                avg_rows = list(csv.DictReader(f))

            self.assertEqual(len(raw_rows), 6)
            self.assertEqual(len(avg_rows), 3)

            seg_counts = {}
            for r in raw_rows:
                seg_idx = int(r["segment_index"])
                seg_counts[seg_idx] = seg_counts.get(seg_idx, 0) + 1
                self.assertEqual(r["source_adv_file"], adv_path.name)
            self.assertEqual(seg_counts, {1: 2, 2: 2, 3: 2})

            for i, avg in enumerate(avg_rows, start=1):
                self.assertEqual(int(avg["segment_index"]), i)
                self.assertEqual(int(avg["segment_count"]), 3)
                self.assertEqual(int(avg["segment_sample_count"]), 2)
                self.assertEqual(int(avg["sample_count"]), 2)
                self.assertEqual(avg["source_adv_file"], adv_path.name)

            stop_result = session_mgr.stop_session()
            integrity = stop_result["metadata"].get("segment_integrity", {})
            self.assertEqual(integrity.get("segment_rows"), 3)
            self.assertEqual(integrity.get("segment_samples_total"), 6)
            self.assertEqual(integrity.get("matched_samples_total"), 6)
            self.assertTrue(integrity.get("sample_accounting_match"))


if __name__ == "__main__":
    unittest.main()
