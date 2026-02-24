"""Tests for VXC position CSV parsing.

Verifies that all VXC position rows are parsed correctly.
"""

import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from vxc_adv_visualizer.data.adv_vxc_merger import ADVVXCMerger


class TestVXCParsing(unittest.TestCase):
    """Test VXC CSV parsing functionality."""

    def test_parse_all_valid_rows(self):
        """Test that all valid VXC position rows are parsed."""
        csv_content = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.123,-1.25103,0.00000,GOOD
2026-02-11 21:42:20.456,-1.25103,0.00000,GOOD
2026-02-11 21:42:21.789,-1.25103,0.00000,GOOD
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            merger = ADVVXCMerger()
            count = merger.parse_vxc_csv(temp_path)
            
            self.assertEqual(count, 3, "Should parse all 3 valid rows")
            self.assertEqual(len(merger.vxc_data), 3, "Should store all 3 records")
            
            # Verify data integrity
            self.assertEqual(merger.vxc_data[0]['x_m'], -1.25103)
            self.assertEqual(merger.vxc_data[1]['y_m'], 0.00000)
            self.assertEqual(merger.vxc_data[2]['quality'], 'GOOD')
        finally:
            Path(temp_path).unlink()

    def test_parse_rows_with_different_quality(self):
        """Test that VXC rows with any quality status are parsed (not filtered)."""
        csv_content = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.123,-1.25103,0.00000,GOOD
2026-02-11 21:42:20.456,-1.25103,0.00000,INTERPOLATED
2026-02-11 21:42:21.789,-1.25103,0.00000,MISSING
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            merger = ADVVXCMerger()
            count = merger.parse_vxc_csv(temp_path)
            
            # Should parse ALL rows regardless of quality
            self.assertEqual(count, 3, "Should parse all rows regardless of quality status")
            self.assertEqual(len(merger.vxc_data), 3)
        finally:
            Path(temp_path).unlink()

    def test_skip_invalid_timestamps_only(self):
        """Test that only unparseable timestamps are skipped."""
        csv_content = """timestamp_utc,x_m,y_m,quality
2026-02-11 21:42:19.123,-1.25103,0.00000,GOOD
INVALID_TIMESTAMP,-1.25103,0.00000,GOOD
2026-02-11 21:42:21.789,-1.25103,0.00000,GOOD
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            merger = ADVVXCMerger()
            count = merger.parse_vxc_csv(temp_path)
            
            # Should parse 2 rows (skip the one with invalid timestamp)
            self.assertEqual(count, 2, "Should skip only row with invalid timestamp")
            self.assertEqual(len(merger.vxc_data), 2)
        finally:
            Path(temp_path).unlink()


if __name__ == '__main__':
    unittest.main()
