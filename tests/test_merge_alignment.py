"""Tests for timestamp-based merge alignment.

Verifies that ADV and VXC data are correctly aligned by nearest timestamp.
"""

import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from vxc_adv_visualizer.data.adv_vxc_merger import ADVVXCMerger


class TestMergeAlignment(unittest.TestCase):
    """Test merge alignment functionality."""

    def test_all_adv_records_preserved(self):
        """Test that ALL ADV records appear in merged output (matched or NaN)."""
        adv_csv = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s)
2026-02-11 21:42:19.10,2026-02-11 16:42:19.10,1,0.123456
2026-02-11 21:42:20.20,2026-02-11 16:42:20.20,2,0.234567
2026-02-11 21:42:21.30,2026-02-11 16:42:21.30,3,0.345678
"""
        vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.000,-1.25103,0.00000,GOOD
2026-02-11 21:42:20.100,-1.25103,0.00000,GOOD
"""
        # Note: 3rd ADV record has no nearby VXC match (>0.5s tolerance)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f1:
            f1.write(adv_csv)
            adv_path = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f2:
            f2.write(vxc_csv)
            vxc_path = f2.name

        try:
            merger = ADVVXCMerger()
            merger.parse_adv_csv(adv_path)
            merger.parse_vxc_csv(vxc_path)
            matched, unmatched, stats = merger.merge()
            
            # All 3 ADV records should be in merged_data
            self.assertEqual(len(merger.merged_data), 3, "All ADV records should be in merged output")
            
            # Check matched count
            self.assertEqual(matched, 2, "2 ADV records should have VXC matches")
            self.assertEqual(unmatched, 1, "1 ADV record should have no VXC match")
            
            # Verify unmatched record has NaN for VXC columns
            unmatched_record = merger.merged_data[2]  # 3rd record
            self.assertEqual(unmatched_record['vxc_x_m'], 'NaN')
            self.assertEqual(unmatched_record['vxc_y_m'], 'NaN')
            self.assertEqual(unmatched_record['vxc_quality'], 'MISSING')
            
            # Verify matched records have VXC data
            matched_record = merger.merged_data[0]
            self.assertEqual(matched_record['vxc_x_m'], -1.25103)
            self.assertEqual(matched_record['vxc_quality'], 'GOOD')
        finally:
            Path(adv_path).unlink()
            Path(vxc_path).unlink()

    def test_nearest_neighbor_matching(self):
        """Test that nearest VXC timestamp within tolerance is selected."""
        adv_csv = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s)
2026-02-11 21:42:20.00,2026-02-11 16:42:20.00,1,0.123456
"""
        vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.700,-0.01,0.00,GOOD
2026-02-11 21:42:20.100,-0.02,0.00,GOOD
2026-02-11 21:42:20.500,-0.03,0.00,GOOD
"""
        # ADV at 20.00, VXC at 19.70 (0.3s), 20.10 (0.1s), 20.50 (0.5s)
        # Should match with 20.10 (smallest delta)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f1:
            f1.write(adv_csv)
            adv_path = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f2:
            f2.write(vxc_csv)
            vxc_path = f2.name

        try:
            merger = ADVVXCMerger()
            merger.parse_adv_csv(adv_path)
            merger.parse_vxc_csv(vxc_path)
            matched, unmatched, stats = merger.merge()
            
            self.assertEqual(matched, 1)
            
            # Should match with second VXC record (x_m=-0.02)
            matched_record = merger.merged_data[0]
            self.assertEqual(matched_record['vxc_x_m'], -0.02)
        finally:
            Path(adv_path).unlink()
            Path(vxc_path).unlink()

    def test_tolerance_enforcement(self):
        """Test that matches beyond tolerance are rejected."""
        adv_csv = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s)
2026-02-11 21:42:20.00,2026-02-11 16:42:20.00,1,0.123456
"""
        vxc_csv = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.400,-0.01,0.00,GOOD
"""
        # Delta = 0.6s > 0.5s tolerance
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f1:
            f1.write(adv_csv)
            adv_path = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f2:
            f2.write(vxc_csv)
            vxc_path = f2.name

        try:
            merger = ADVVXCMerger()
            merger.parse_adv_csv(adv_path)
            merger.parse_vxc_csv(vxc_path)
            matched, unmatched, stats = merger.merge()
            
            # Should not match (beyond tolerance)
            self.assertEqual(matched, 0)
            self.assertEqual(unmatched, 1)
            self.assertEqual(merger.merged_data[0]['vxc_quality'], 'MISSING')
        finally:
            Path(adv_path).unlink()
            Path(vxc_path).unlink()


if __name__ == '__main__':
    unittest.main()
