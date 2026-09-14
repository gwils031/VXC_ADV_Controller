"""ADV + VXC Data Merger - Aligns FlowTracker2 and VXC data by UTC timestamps.

Reads ADV CSV exports from FlowTracker2 and VXC position logs, aligns them by
nearest UTC timestamp within tolerance, and outputs merged CSV with all columns.

Alignment strategy: Nearest-neighbor with configurable tolerance (default 0.5s)
"""

import bisect
import csv
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import yaml


logger = logging.getLogger(__name__)


class ADVVXCMerger:
    """Merges FlowTracker2 ADV data with VXC position logs by timestamp alignment.
    
    Attributes:
        tolerance_sec: Maximum time delta for matching (default 0.5s)
        adv_data: Parsed ADV records
        vxc_data: Parsed VXC position records
        merged_data: Aligned output records
    """
    
    def __init__(self, tolerance_sec: float = 0.5):
        """Initialize merger.
        
        Args:
            tolerance_sec: Maximum timestamp difference for matching (seconds)
        """
        self.tolerance_sec = tolerance_sec
        self.adv_data: List[Dict] = []
        self.vxc_data: List[Dict] = []
        self.merged_data: List[Dict] = []
        self._vxc_timestamps: List[float] = []  # Sorted list for bisect lookups
        
    def parse_adv_csv(self, filepath: str) -> int:
        """Parse FlowTracker2 CSV export.
        
        Args:
            filepath: Path to ADV CSV file
            
        Returns:
            Number of records parsed
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"ADV file not found: {filepath}")
            
        self.adv_data = []
        
        try:
            # Try UTF-8 first, fallback to latin-1 for encoding issues
            encodings = ['utf-8', 'latin-1', 'cp1252']
            file_content = None
            
            for encoding in encodings:
                try:
                    with open(filepath, 'r', encoding=encoding) as f:
                        reader = csv.DictReader(f)
                        file_content = list(reader)  # read before file closes
                    break
                except UnicodeDecodeError:
                    continue
                    
            if file_content is None:
                raise ValueError(f"Cannot decode file with any supported encoding")
            
            for row in file_content:
                    # Parse UTC time column
                    utc_time_str = row.get('UTC time', '').strip()
                    if not utc_time_str:
                        continue
                        
                    try:
                        # Parse format: "2026-02-04 22:53:30.94"
                        dt = datetime.strptime(utc_time_str, '%Y-%m-%d %H:%M:%S.%f')
                        dt = dt.replace(tzinfo=timezone.utc)
                        
                        # Store record with parsed timestamp
                        record = {
                            'timestamp': dt,
                            'timestamp_unix': dt.timestamp(),
                            **row  # Keep all original columns
                        }
                        self.adv_data.append(record)
                        
                    except ValueError as e:
                        logger.warning(f"Skipping invalid ADV timestamp: {utc_time_str}")
                        continue
                        
            logger.info(f"Parsed {len(self.adv_data)} ADV records from {filepath.name}")
            return len(self.adv_data)
            
        except Exception as e:
            logger.error(f"Failed to parse ADV CSV: {e}")
            raise ValueError(f"Invalid ADV file format: {e}")
    
    def parse_vxc_csv(self, filepath: str) -> int:
        """Parse VXC position log CSV.
        
        Args:
            filepath: Path to VXC CSV file
            
        Returns:
            Number of records parsed
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"VXC file not found: {filepath}")
            
        self.vxc_data = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    # Parse timestamp_utc column
                    utc_time_str = row.get('timestamp_utc', '').strip()
                    if not utc_time_str:
                        continue
                        
                    try:
                        # Parse format: "2026-02-09 18:45:32.123"
                        dt = datetime.strptime(utc_time_str, '%Y-%m-%d %H:%M:%S.%f')
                        dt = dt.replace(tzinfo=timezone.utc)
                        
                        record = {
                            'timestamp': dt,
                            'timestamp_unix': dt.timestamp(),
                            'x_m': float(row['x_m']),
                            'y_m': float(row['y_m']),
                            'quality': row['quality']
                        }
                        self.vxc_data.append(record)
                        
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Skipping invalid VXC record: {e}")
                        continue
                        
            # Sort by timestamp for efficient nearest-neighbor search
            self.vxc_data.sort(key=lambda x: x['timestamp_unix'])
            
            logger.info(f"Parsed {len(self.vxc_data)} VXC records from {filepath.name}")
            
            # Pre-build sorted timestamp list for fast bisect lookups
            self._vxc_timestamps = [r['timestamp_unix'] for r in self.vxc_data]
            
            return len(self.vxc_data)
            
        except Exception as e:
            logger.error(f"Failed to parse VXC CSV: {e}")
            raise ValueError(f"Invalid VXC file format: {e}")
    
    def _find_nearest_vxc(self, adv_timestamp: float) -> Optional[Dict]:
        """Find nearest VXC position within tolerance using bisect.
        
        Args:
            adv_timestamp: ADV sample timestamp (Unix seconds)
            
        Returns:
            Nearest VXC record or None if no match within tolerance
        """
        if not self.vxc_data:
            return None
        
        # vxc_timestamps is kept sorted; use bisect to find insertion point
        idx = bisect.bisect_left(self._vxc_timestamps, adv_timestamp)
        
        # Check the two neighbours around the insertion point
        best_idx = None
        min_delta = float('inf')
        for i in (idx - 1, idx):
            if 0 <= i < len(self._vxc_timestamps):
                delta = abs(self._vxc_timestamps[i] - adv_timestamp)
                if delta < min_delta:
                    min_delta = delta
                    best_idx = i
        
        if best_idx is not None and min_delta <= self.tolerance_sec:
            return self.vxc_data[best_idx]
        return None
    
    def merge(self) -> Tuple[int, int, Dict]:
        """Merge ADV and VXC data by nearest timestamp alignment.
        
        Returns:
            Tuple of (matched_count, unmatched_count, statistics_dict)
        """
        if not self.adv_data:
            logger.error("No ADV data loaded")
            return (0, 0, {})
            
        if not self.vxc_data:
            logger.error("No VXC data loaded")
            return (0, len(self.adv_data), {})
        
        self.merged_data = []
        matched_count = 0
        time_deltas = []
        
        for adv_record in self.adv_data:
            vxc_match = self._find_nearest_vxc(adv_record['timestamp_unix'])
            
            if vxc_match:
                # Calculate time delta in milliseconds
                time_delta_ms = abs(vxc_match['timestamp_unix'] - adv_record['timestamp_unix']) * 1000
                time_deltas.append(time_delta_ms)
                
                # Merge records
                merged = {
                    **adv_record,  # All ADV columns
                    'vxc_x_m': vxc_match['x_m'],
                    'vxc_y_m': vxc_match['y_m'],
                    'vxc_quality': vxc_match['quality'],
                    'vxc_time_delta_ms': f"{time_delta_ms:.1f}"
                }
                self.merged_data.append(merged)
                matched_count += 1
            else:
                # No match - add with NaN for VXC columns
                merged = {
                    **adv_record,
                    'vxc_x_m': 'NaN',
                    'vxc_y_m': 'NaN',
                    'vxc_quality': 'MISSING',
                    'vxc_time_delta_ms': 'NaN'
                }
                self.merged_data.append(merged)
        
        unmatched_count = len(self.adv_data) - matched_count
        
        # Calculate statistics using direct math (avoids statistics module overhead)
        # Pre-compute mean once so the std-dev generator doesn't redo sum/len N times
        _td_avg = sum(time_deltas) / len(time_deltas) if time_deltas else 0.0
        stats = {
            'total_adv_records': len(self.adv_data),
            'matched': matched_count,
            'unmatched': unmatched_count,
            'match_rate_percent': (matched_count / len(self.adv_data)) * 100 if self.adv_data else 0,
            'time_delta_min_ms': min(time_deltas) if time_deltas else 0,
            'time_delta_avg_ms': _td_avg,
            'time_delta_max_ms': max(time_deltas) if time_deltas else 0,
            'time_delta_std_ms': (
                math.sqrt(sum((x - _td_avg) ** 2 for x in time_deltas) / len(time_deltas))
                if len(time_deltas) > 1 else 0
            )
        }
        
        logger.info(f"Merge complete: {matched_count}/{len(self.adv_data)} matched ({stats['match_rate_percent']:.1f}%)")
        logger.info(f"Time delta: min={stats['time_delta_min_ms']:.1f}ms, avg={stats['time_delta_avg_ms']:.1f}ms, max={stats['time_delta_max_ms']:.1f}ms")
        
        return (matched_count, unmatched_count, stats)
    
    def write_merged_csv(self, output_path: str) -> str:
        """Write merged data to CSV file.
        
        Args:
            output_path: Path for output CSV file
            
        Returns:
            Path to written file
            
        Raises:
            ValueError: If no merged data available
        """
        if not self.merged_data:
            raise ValueError("No merged data - run merge() first")
            
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Internal keys added during parsing — datetime objects / raw floats, not for CSV
        _internal_keys = {'timestamp', 'timestamp_unix'}

        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                # Get all unique column names, skipping internal parser keys
                if self.merged_data:
                    fieldnames = [k for k in self.merged_data[0].keys() if k not in _internal_keys]

                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for record in self.merged_data:
                    # Drop internal keys (datetime object + raw unix float)
                    output_record = {k: v for k, v in record.items() if k not in _internal_keys}
                    writer.writerow(output_record)
                    
            logger.info(f"Wrote merged CSV: {output_path} ({len(self.merged_data)} records)")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Failed to write merged CSV: {e}")
            raise IOError(f"Cannot write output file: {e}")

    def _parse_float(self, value: object) -> Optional[float]:
        """Parse a float value, returning None if invalid."""
        try:
            if value is None:
                return None
            if isinstance(value, str) and not value.strip():
                return None
            parsed = float(value)
            if math.isnan(parsed) or math.isinf(parsed):
                return None
            return parsed
        except (TypeError, ValueError):
            return None

    def _load_grid_spacing_m(self, config_path: Optional[str] = None) -> Tuple[float, float]:
        """Load grid spacing (meters) from experiment_config.yaml.

        Returns a small fallback spacing if the config is missing or invalid.
        """
        default_spacing = (0.001, 0.001)
        if config_path is None:
            config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            logger.warning(f"Grid spacing config not found: {config_path}")
            return default_spacing

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            grid = config.get("grid", {})
            x_spacing_feet = float(grid.get("x_spacing_feet", 0))
            y_spacing_feet = float(grid.get("y_spacing_feet", 0))
            if x_spacing_feet <= 0 or y_spacing_feet <= 0:
                logger.warning("Invalid grid spacing in config; using fallback spacing")
                return default_spacing

            return (x_spacing_feet * 0.3048, y_spacing_feet * 0.3048)
        except Exception as e:
            logger.warning(f"Failed to read grid spacing config: {e}")
            return default_spacing

    def _get_numeric_columns(self, records: List[Dict]) -> List[str]:
        """Return numeric columns to average, preserving original order."""
        if not records:
            return []

        excluded = {
            "timestamp",
            "timestamp_unix",
            "UTC time",
            "Local time",
            "Operation",
            "vxc_x_m",
            "vxc_y_m",
            "vxc_quality",
            "vxc_time_delta_ms",
        }

        numeric_columns: List[str] = []
        for key in records[0].keys():
            if key in excluded:
                continue
            for record in records:
                if self._parse_float(record.get(key)) is not None:
                    numeric_columns.append(key)
                    break
        return numeric_columns

    def _bin_value(self, value: float, spacing: float) -> float:
        """Bin a value to the nearest grid center."""
        if spacing <= 0:
            return value
        return round(value / spacing) * spacing

    def _load_atmospheric_pressure(self, config_path: Optional[str] = None) -> float:
        """Load atmospheric pressure (dbar) from experiment_config.yaml.

        Returns 8.5 dbar as default (Provo, Utah) if config is missing or invalid.
        """
        default_atm = 8.5  # Provo, Utah
        if config_path is None:
            config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            logger.warning(f"Config not found for atmospheric pressure: {config_path}")
            return default_atm

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            atm = float(config.get("environment", {}).get("atmospheric_pressure_dbar", default_atm))
            logger.debug(f"Atmospheric pressure loaded: {atm} dbar")
            return atm
        except Exception as e:
            logger.warning(f"Failed to read atmospheric pressure from config: {e}")
            return default_atm

    def write_averaged_plane_csv(
        self,
        output_path: str,
        grid_spacing_m: Optional[Tuple[float, float]] = None,
        config_path: Optional[str] = None,
        atmospheric_pressure_dbar: Optional[float] = None,
        filter_good_only: bool = True,
    ) -> Tuple[str, Dict]:
        """Write averaged data per (x,y) grid location.

        Excludes non-GOOD VXC samples when filter_good_only is True (default).
        If all samples in a bin are invalid, the bin is still written with status=INVALID and sample_count=0.
        
        Computes Gauge Pressure (dbar) = Raw Pressure (dbar) - atmospheric_pressure_dbar
        for each location bin, representing water-column pressure only.
        """
        if not self.merged_data:
            raise ValueError("No merged data - run merge() first")

        spacing_x, spacing_y = grid_spacing_m or self._load_grid_spacing_m(config_path)
        numeric_columns = self._get_numeric_columns(self.merged_data)

        # Load atmospheric pressure (from arg, or config, or default 8.5 dbar)
        atm_pressure = atmospheric_pressure_dbar
        if atm_pressure is None:
            atm_pressure = self._load_atmospheric_pressure(config_path)

        RAW_PRESSURE_COL = "Raw Pressure (dbar)"

        bins: Dict[Tuple[float, float], Dict] = {}
        for record in self.merged_data:
            if filter_good_only:
                quality = str(record.get("vxc_quality", "")).strip().upper()
                if quality != "GOOD":
                    continue

            x_val = self._parse_float(record.get("vxc_x_m"))
            y_val = self._parse_float(record.get("vxc_y_m"))
            if x_val is None or y_val is None:
                continue

            x_bin = self._bin_value(x_val, spacing_x)
            y_bin = self._bin_value(y_val, spacing_y)
            key = (x_bin, y_bin)

            if key not in bins:
                bins[key] = {
                    "total": 0,
                    "sums": {col: 0.0 for col in numeric_columns},
                    "counts": {col: 0 for col in numeric_columns},
                }

            bins[key]["total"] += 1
            for col in numeric_columns:
                value = self._parse_float(record.get(col))
                if value is None:
                    continue
                bins[key]["sums"][col] += value
                bins[key]["counts"][col] += 1

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Add Gauge Pressure column after Raw Pressure if available
        gauge_col = "Gauge Pressure (dbar)"
        fieldnames = ["x_m", "y_m", "sample_count", "status"] + numeric_columns
        if RAW_PRESSURE_COL in numeric_columns:
            # Insert gauge pressure immediately after raw pressure
            raw_idx = fieldnames.index(RAW_PRESSURE_COL)
            fieldnames.insert(raw_idx + 1, gauge_col)

        try:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for (x_bin, y_bin) in sorted(bins.keys(), key=lambda k: (k[1], k[0])):
                    entry = bins[(x_bin, y_bin)]
                    is_valid = entry["total"] > 0
                    row = {
                        "x_m": f"{x_bin:.6f}",
                        "y_m": f"{y_bin:.6f}",
                        "sample_count": entry["total"] if is_valid else 0,
                        "status": "OK" if is_valid else "INVALID",
                    }

                    avg_raw_pressure = None
                    for col in numeric_columns:
                        if is_valid and entry["counts"][col] > 0:
                            avg = entry["sums"][col] / entry["counts"][col]
                            row[col] = f"{avg:.6f}"
                            if col == RAW_PRESSURE_COL:
                                avg_raw_pressure = avg
                        else:
                            row[col] = "NaN"

                    # Compute gauge pressure (subtract local atmospheric pressure)
                    if RAW_PRESSURE_COL in numeric_columns:
                        if avg_raw_pressure is not None:
                            gauge = avg_raw_pressure - atm_pressure
                            row[gauge_col] = f"{gauge:.6f}"
                        else:
                            row[gauge_col] = "NaN"

                    writer.writerow(row)

            stats = {
                "avg_points_total": len(bins),
                "avg_points_valid": sum(1 for v in bins.values() if v["total"] > 0),
                "avg_points_invalid": sum(1 for v in bins.values() if v["total"] == 0),
                "atmospheric_pressure_dbar": atm_pressure,
            }

            logger.info(
                f"Wrote averaged plane CSV: {output_path} "
                f"({stats['avg_points_valid']}/{stats['avg_points_total']} valid points, "
                f"atm_pressure={atm_pressure:.2f} dbar)"
            )
            return str(output_path), stats

        except Exception as e:
            logger.error(f"Failed to write averaged plane CSV: {e}")
            raise IOError(f"Cannot write averaged output file: {e}")
    
    def get_match_report(self) -> str:
        """Generate human-readable match report.
        
        Returns:
            Formatted report string
        """
        if not self.merged_data:
            return "No merged data available"
            
        matched = sum(1 for r in self.merged_data if r['vxc_quality'] != 'MISSING')
        unmatched = len(self.merged_data) - matched
        match_rate = (matched / len(self.merged_data)) * 100
        
        time_deltas = [
            float(r['vxc_time_delta_ms']) 
            for r in self.merged_data 
            if r['vxc_time_delta_ms'] != 'NaN'
        ]
        
        _avg = sum(time_deltas) / len(time_deltas) if time_deltas else 0.0
        _std = (
            math.sqrt(sum((x - _avg) ** 2 for x in time_deltas) / len(time_deltas))
            if len(time_deltas) > 1 else 0.0
        )
        report = f"""
=== ADV + VXC Merge Report ===
Total ADV Records: {len(self.merged_data)}
Matched with VXC:  {matched} ({match_rate:.1f}%)
Unmatched:         {unmatched} ({100-match_rate:.1f}%)

Time Delta Statistics:
  Min:    {min(time_deltas):.1f} ms
  Avg:    {_avg:.1f} ms
  Max:    {max(time_deltas):.1f} ms
  StdDev: {_std:.1f} ms
  
Tolerance: {self.tolerance_sec} seconds ({self.tolerance_sec*1000} ms)
"""
        return report.strip()


# For testing
if __name__ == "__main__":
    # Test merger
    merger = ADVVXCMerger(tolerance_sec=0.5)
    
    # Would need actual files to test:
    # merger.parse_adv_csv("20260204-155330.csv")
    # merger.parse_vxc_csv("vxc_pos_20260209_184532.csv")
    # merger.merge()
    # merger.write_merged_csv("adv_vxc_aligned_20260209_184532.csv")
    # print(merger.get_match_report())
