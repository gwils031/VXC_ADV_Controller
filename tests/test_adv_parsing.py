"""Tests for ADV CSV parsing.

Verifies that all ADV data rows are parsed correctly without filtering.
"""

import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from vxc_adv_visualizer.data.adv_vxc_merger import ADVVXCMerger


class TestADVParsing(unittest.TestCase):
    """Test ADV CSV parsing functionality."""

    def test_parse_all_valid_rows(self):
        """Test that all valid ADV rows are parsed."""
        csv_content = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s),Corrected Velocity.Y (m/s),Corrected Velocity.Z (m/s),SNR.X (dB),SNR.Y (dB),SNR.Z (dB),Correlation.X (%),Correlation.Y (%),Correlation.Z (%)
2026-02-11 21:42:19.00,2026-02-11 16:42:19.00,1,0.123456,-0.234567,0.345678,15.2,16.3,14.8,85,87,82
2026-02-11 21:42:20.00,2026-02-11 16:42:20.00,2,-0.111111,0.222222,-0.333333,12.5,13.6,11.9,75,78,73
2026-02-11 21:42:21.00,2026-02-11 16:42:21.00,3,0.555555,-0.666666,0.777777,18.1,19.2,17.5,92,94,89
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            merger = ADVVXCMerger()
            count = merger.parse_adv_csv(temp_path)
            
            self.assertEqual(count, 3, "Should parse all 3 valid rows")
            self.assertEqual(len(merger.adv_data), 3, "Should store all 3 records")
            
            # Verify data integrity
            self.assertEqual(merger.adv_data[0]['Corrected Velocity.X (m/s)'], '0.123456')
            self.assertEqual(merger.adv_data[1]['Corrected Velocity.Y (m/s)'], '0.222222')
            self.assertEqual(merger.adv_data[2]['Corrected Velocity.Z (m/s)'], '0.777777')
        finally:
            Path(temp_path).unlink()

    def test_parse_rows_with_low_quality(self):
        """Test that rows with low SNR/correlation are NOT filtered during parsing."""
        csv_content = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s),Corrected Velocity.Y (m/s),Corrected Velocity.Z (m/s),SNR.X (dB),SNR.Y (dB),SNR.Z (dB),Correlation.X (%),Correlation.Y (%),Correlation.Z (%)
2026-02-11 21:42:19.00,2026-02-11 16:42:19.00,1,0.123456,-0.234567,0.345678,5.2,4.3,3.8,45,47,42
2026-02-11 21:42:20.00,2026-02-11 16:42:20.00,2,-0.111111,0.222222,-0.333333,2.5,1.6,2.9,25,28,23
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            merger = ADVVXCMerger()
            count = merger.parse_adv_csv(temp_path)
            
            # Should parse ALL rows regardless of quality metrics
            self.assertEqual(count, 2, "Should parse all rows even with low SNR/correlation")
            self.assertEqual(len(merger.adv_data), 2)
        finally:
            Path(temp_path).unlink()

    def test_skip_invalid_timestamps_only(self):
        """Test that only unparseable timestamps are skipped, not data quality issues."""
        csv_content = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s),Corrected Velocity.Y (m/s),Corrected Velocity.Z (m/s)
2026-02-11 21:42:19.00,2026-02-11 16:42:19.00,1,0.123456,-0.234567,0.345678
INVALID_TIMESTAMP,2026-02-11 16:42:20.00,2,0.111111,0.222222,0.333333
2026-02-11 21:42:21.00,2026-02-11 16:42:21.00,3,0.444444,-0.555555,0.666666
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            merger = ADVVXCMerger()
            count = merger.parse_adv_csv(temp_path)
            
            # Should parse 2 rows (skip the one with invalid timestamp)
            self.assertEqual(count, 2, "Should skip only row with invalid timestamp")
            self.assertEqual(len(merger.adv_data), 2)
            self.assertEqual(merger.adv_data[0]['Sample ID'], '1')
            self.assertEqual(merger.adv_data[1]['Sample ID'], '3')
        finally:
            Path(temp_path).unlink()

    def test_empty_timestamp_skipped(self):
        """Test that rows with empty timestamps are skipped."""
        csv_content = """UTC time,Local time,Sample ID,Corrected Velocity.X (m/s)
2026-02-11 21:42:19.00,2026-02-11 16:42:19.00,1,0.123456
,2026-02-11 16:42:20.00,2,0.222222
2026-02-11 21:42:21.00,2026-02-11 16:42:21.00,3,0.333333
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            merger = ADVVXCMerger()
            count = merger.parse_adv_csv(temp_path)
            
            self.assertEqual(count, 2, "Should skip row with empty UTC timestamp")
            self.assertEqual(len(merger.adv_data), 2)
        finally:
            Path(temp_path).unlink()


if __name__ == '__main__':
    unittest.main()
