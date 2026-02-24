# VXC ADV Data Flow Tests

This directory contains test suites for validating the data flow through the VXC ADV system.

## Test Coverage

### 1. ADV Parsing Tests (`test_adv_parsing.py`)
- **Purpose**: Verify that ALL ADV data is parsed without quality filtering
- **Tests**:
  - Parse all valid rows
  - Parse rows with low SNR/correlation (not filtered)
  - Skip only unparseable timestamps
  - Skip empty timestamps

### 2. VXC Parsing Tests (`test_vxc_parsing.py`)
- **Purpose**: Verify that all VXC position data is parsed correctly
- **Tests**:
  - Parse all valid rows
  - Parse rows with any quality status (GOOD, INTERPOLATED, MISSING)
  - Skip only unparseable timestamps

### 3. Merge Alignment Tests (`test_merge_alignment.py`)
- **Purpose**: Verify timestamp-based alignment between ADV and VXC data
- **Tests**:
  - All ADV records preserved in merged output (matched or NaN)
  - Nearest neighbor matching within tolerance
  - Tolerance enforcement (reject matches >0.5s)

### 4. Grid Averaging Tests (`test_grid_averaging.py`)
- **Purpose**: Verify that all ADV data contributes to spatial averaging
- **Tests**:
  - All data included regardless of VXC quality status
  - Unmatched records (NaN positions) excluded from averaging
  - Spatial binning correctness

## Key Validation Points

✅ **No Data Filtering**: All ADV data with valid timestamps is preserved  
✅ **Quality Independence**: Low SNR/correlation does NOT cause data exclusion  
✅ **Complete Coverage**: Every ADV record appears in merged output (matched or NaN)  
✅ **Averaging Inclusivity**: All matched data contributes to grid averages (removed VXC quality filter)

## Running Tests

### Run all tests:
```powershell
python tests/run_tests.py
```

### Run specific test file:
```powershell
python -m unittest tests.test_adv_parsing
python -m unittest tests.test_vxc_parsing
python -m unittest tests.test_merge_alignment
python -m unittest tests.test_grid_averaging
```

### Run specific test case:
```powershell
python -m unittest tests.test_adv_parsing.TestADVParsing.test_parse_rows_with_low_quality
```

## Test Data

Tests use temporary CSV files with synthetic data to validate parsing and merging logic without requiring actual ADV/VXC hardware.

## Expected Results

All tests should pass, confirming:
1. No data is lost during parsing (except unparseable timestamps)
2. All ADV data makes it through to merged output
3. Averaging includes all data regardless of quality metrics
4. Spatial binning works correctly
