"""Tests for grid-based averaging.

Verifies that all ADV data is included in averaging without quality filtering.
"""

import unittest
import tempfile
from pathlib import Path

from vxc_adv_visualizer.data.adv_vxc_merger import ADVVXCMerger


class TestGridAveraging(unittest.TestCase):
    """Test grid averaging functionality."""

    def test_vxc_quality_filtering_in_grid_averaging(self):
        """Test that non-GOOD VXC samples are excluded by default (filter_good_only=True)."""
        adv_csv = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s),Corrected Velocity.Y (m/s)
2026-02-11 21:42:19.00,2026-02-11 16:42:19.00,1,0.1,0.2
2026-02-11 21:42:20.00,2026-02-11 16:42:20.00,2,0.3,0.4
2026-02-11 21:42:21.00,2026-02-11 16:42:21.00,3,0.5,0.6
"""
        vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.000,0.00000,0.00000,GOOD
2026-02-11 21:42:20.000,0.00000,0.00000,INTERPOLATED
2026-02-11 21:42:21.000,0.00000,0.00000,MISSING
"""
        # All 3 samples at same position, different VXC qualities
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f1:
            f1.write(adv_csv)
            adv_path = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f2:
            f2.write(vxc_csv)
            vxc_path = f2.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f3:
            avg_path = f3.name

        try:
            merger = ADVVXCMerger()
            merger.parse_adv_csv(adv_path)
            merger.parse_vxc_csv(vxc_path)
            merger.merge()
            
            # Default: filter_good_only=True -> only the GOOD sample is binned
            output_path, stats = merger.write_averaged_plane_csv(
                avg_path,
                grid_spacing_m=(0.001, 0.001),
                filter_good_only=True
            )
            
            import csv
            with open(output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            self.assertEqual(len(rows), 1, "Should have 1 bin")
            row = rows[0]
            self.assertEqual(row['status'], 'OK')
            self.assertEqual(row['sample_count'], '1', "Should count only 1 sample with GOOD quality")
            self.assertAlmostEqual(float(row['Corrected Velocity.X (m/s)']), 0.1, places=5)
            self.assertAlmostEqual(float(row['Corrected Velocity.Y (m/s)']), 0.2, places=5)

            # When filter_good_only=False -> all 3 samples are binned
            output_path_all, stats_all = merger.write_averaged_plane_csv(
                avg_path,
                grid_spacing_m=(0.001, 0.001),
                filter_good_only=False
            )
            with open(output_path_all, 'r', encoding='utf-8') as f:
                rows_all = list(csv.DictReader(f))
            self.assertEqual(rows_all[0]['sample_count'], '3', "Should count all 3 samples")
            self.assertAlmostEqual(float(rows_all[0]['Corrected Velocity.X (m/s)']), 0.3, places=5)
            self.assertAlmostEqual(float(rows_all[0]['Corrected Velocity.Y (m/s)']), 0.4, places=5)
            
        finally:
            Path(adv_path).unlink()
            Path(vxc_path).unlink()
            Path(avg_path).unlink(missing_ok=True)

    def test_unmatched_records_excluded_from_averaging(self):
        """Test that ADV records without VXC matches (NaN positions) are excluded from averaging."""
        adv_csv = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s)
2026-02-11 21:42:19.00,2026-02-11 16:42:19.00,1,0.5
2026-02-11 21:42:25.00,2026-02-11 16:42:25.00,2,999.9
"""
        vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.000,0.00000,0.00000,GOOD
"""
        # 2nd ADV record has no match (>0.5s tolerance), gets NaN position
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f1:
            f1.write(adv_csv)
            adv_path = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f2:
            f2.write(vxc_csv)
            vxc_path = f2.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f3:
            avg_path = f3.name

        try:
            merger = ADVVXCMerger()
            merger.parse_adv_csv(adv_path)
            merger.parse_vxc_csv(vxc_path)
            merger.merge()
            
            output_path, stats = merger.write_averaged_plane_csv(
                avg_path,
                grid_spacing_m=(0.001, 0.001)
            )
            
            import csv
            with open(output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            # Should have 1 bin with only the matched record
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row['sample_count'], '1', "Should count only matched record")
            
            # Verify average is from first record only (0.5), not second (999.9)
            u_avg = float(row['Corrected Velocity.X (m/s)'])
            self.assertAlmostEqual(u_avg, 0.5, places=5, msg="Should average only matched records")
            
        finally:
            Path(adv_path).unlink()
            Path(vxc_path).unlink()
            Path(avg_path).unlink(missing_ok=True)

    def test_spatial_binning(self):
        """Test that records are correctly binned by spatial position."""
        adv_csv = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s)
2026-02-11 21:42:19.00,2026-02-11 16:42:19.00,1,1.0
2026-02-11 21:42:20.00,2026-02-11 16:42:20.00,2,2.0
2026-02-11 21:42:21.00,2026-02-11 16:42:21.00,3,3.0
"""
        vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.000,0.00000,0.00000,GOOD
2026-02-11 21:42:20.000,0.30480,0.00000,GOOD
2026-02-11 21:42:21.000,0.00000,0.30480,GOOD
"""
        # 3 samples at different positions
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f1:
            f1.write(adv_csv)
            adv_path = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f2:
            f2.write(vxc_csv)
            vxc_path = f2.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f3:
            avg_path = f3.name

        try:
            merger = ADVVXCMerger()
            merger.parse_adv_csv(adv_path)
            merger.parse_vxc_csv(vxc_path)
            merger.merge()
            
            output_path, stats = merger.write_averaged_plane_csv(
                avg_path,
                grid_spacing_m=(0.1, 0.1)  # Spacing smaller than position differences
            )
            
            import csv
            with open(output_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            # Should have 3 bins (one for each unique position)
            self.assertEqual(len(rows), 3, "Should have 3 bins for 3 different positions")
            
            # Each bin should have 1 sample
            for row in rows:
                self.assertEqual(row['sample_count'], '1')
                self.assertEqual(row['status'], 'OK')
            
        finally:
            Path(adv_path).unlink()
            Path(vxc_path).unlink()
            Path(avg_path).unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
