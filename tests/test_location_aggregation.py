"""Unit tests for multi-visit spatial location aggregation (Law of Total Variance).

Verifies that pooling repeated visits to the same coordinate obeys the Law of
Total Variance and Law of Total Covariance for normal and shear stresses, TKE,
and linear sample-weighted averaging.
"""

import math
import unittest
from vxc_adv_visualizer.data.location_aggregation import aggregate_location_rows


class TestLocationAggregation(unittest.TestCase):
    """Test suite for location-based multi-visit aggregation."""

    def test_single_visit_returns_unchanged(self):
        """A single visit row should be returned directly without modification."""
        row = {
            'x_m': '0.500000',
            'y_m': '0.200000',
            'sample_count': '100',
            'Corrected Velocity.X (m/s)': '0.450000',
            'TI_x (m/s)': '0.035000',
            'TKE (m2/s2)': '0.001850',
            'quality_flag': 'GOOD',
        }
        res = aggregate_location_rows([row], 0.5, 0.2)
        self.assertEqual(res['x_m'], '0.500000')
        self.assertEqual(res['Corrected Velocity.X (m/s)'], '0.450000')
        self.assertEqual(res['TI_x (m/s)'], '0.035000')
        self.assertEqual(res['TKE (m2/s2)'], '0.001850')

    def test_identical_means_pools_within_variance(self):
        """When visits have identical mean velocities, total variance is the weighted mean of variances."""
        # Visit 1: N=100, mean=1.0, TI=0.1 (var=0.01)
        # Visit 2: N=100, mean=1.0, TI=0.2 (var=0.04)
        # Pooled variance should be (0.01 + 0.04) / 2 = 0.025
        # Pooled TI should be sqrt(0.025) ≈ 0.158114
        row1 = {
            'x_m': '0.500000', 'y_m': '0.200000', 'sample_count': '100',
            'Corrected Velocity.X (m/s)': '1.000000', 'TI_x (m/s)': '0.100000',
            'Corrected Velocity.Y (m/s)': '0.000000', 'TI_y (m/s)': '0.100000',
            'Corrected Velocity.Z (m/s)': '0.000000', 'TI_z (m/s)': '0.100000',
        }
        row2 = {
            'x_m': '0.500000', 'y_m': '0.200000', 'sample_count': '100',
            'Corrected Velocity.X (m/s)': '1.000000', 'TI_x (m/s)': '0.200000',
            'Corrected Velocity.Y (m/s)': '0.000000', 'TI_y (m/s)': '0.100000',
            'Corrected Velocity.Z (m/s)': '0.000000', 'TI_z (m/s)': '0.100000',
        }
        res = aggregate_location_rows([row1, row2], 0.5, 0.2)

        expected_var_x = 0.025
        expected_ti_x = math.sqrt(expected_var_x)
        self.assertAlmostEqual(float(res['TI_x (m/s)']), expected_ti_x, places=5)
        self.assertAlmostEqual(float(res['Corrected Velocity.X (m/s)']), 1.0, places=5)
        self.assertEqual(res['sample_count'], '200')
        self.assertEqual(res['measurement_count'], '2')

    def test_shifted_means_strictly_includes_between_variance(self):
        """When mean velocity shifts between visits, between-group variance must be included."""
        # Visit 1: N=50, mean=1.0, TI=0.1 (var=0.01)
        # Visit 2: N=50, mean=2.0, TI=0.1 (var=0.01)
        # Grand mean = 1.5
        # Within-group variance = 0.01
        # Between-group variance = ( (1.0 - 1.5)^2 + (2.0 - 1.5)^2 ) / 2 = 0.25
        # Total variance = 0.01 + 0.25 = 0.26
        # Total TI = sqrt(0.26) ≈ 0.509902
        row1 = {
            'sample_count': '50',
            'Corrected Velocity.X (m/s)': '1.000000', 'TI_x (m/s)': '0.100000',
            'Corrected Velocity.Y (m/s)': '0.000000', 'TI_y (m/s)': '0.050000',
            'Corrected Velocity.Z (m/s)': '0.000000', 'TI_z (m/s)': '0.050000',
        }
        row2 = {
            'sample_count': '50',
            'Corrected Velocity.X (m/s)': '2.000000', 'TI_x (m/s)': '0.100000',
            'Corrected Velocity.Y (m/s)': '0.000000', 'TI_y (m/s)': '0.050000',
            'Corrected Velocity.Z (m/s)': '0.000000', 'TI_z (m/s)': '0.050000',
        }
        res = aggregate_location_rows([row1, row2], 0.1, 0.2)

        expected_var_x = 0.26
        expected_ti_x = math.sqrt(expected_var_x)
        self.assertAlmostEqual(float(res['TI_x (m/s)']), expected_ti_x, places=5)
        self.assertAlmostEqual(float(res['Corrected Velocity.X (m/s)']), 1.5, places=5)

    def test_total_tke_consistency(self):
        """Total TKE must equal 0.5 * (Var_x,total + Var_y,total + Var_z,total)."""
        row1 = {
            'sample_count': '100',
            'Corrected Velocity.X (m/s)': '1.0', 'TI_x (m/s)': '0.1',  # var=0.01
            'Corrected Velocity.Y (m/s)': '0.5', 'TI_y (m/s)': '0.2',  # var=0.04
            'Corrected Velocity.Z (m/s)': '0.0', 'TI_z (m/s)': '0.05', # var=0.0025
        }
        row2 = {
            'sample_count': '100',
            'Corrected Velocity.X (m/s)': '1.2', 'TI_x (m/s)': '0.1',  # shift=0.2, mean=1.1, between=(0.1)^2=0.01 -> tot_var_x=0.02
            'Corrected Velocity.Y (m/s)': '0.5', 'TI_y (m/s)': '0.2',  # shift=0 -> tot_var_y=0.04
            'Corrected Velocity.Z (m/s)': '0.0', 'TI_z (m/s)': '0.05', # shift=0 -> tot_var_z=0.0025
        }
        res = aggregate_location_rows([row1, row2], 0.0, 0.0)

        tot_var_x = 0.01 + 0.01  # 0.02
        tot_var_y = 0.04         # 0.04
        tot_var_z = 0.0025       # 0.0025
        expected_tke = 0.5 * (tot_var_x + tot_var_y + tot_var_z)

        self.assertAlmostEqual(float(res['TKE (m2/s2)']), expected_tke, places=5)

    def test_total_covariance_and_shear_stress(self):
        """Law of Total Covariance must correctly aggregate u'w' and tau_xz."""
        # Visit 1: N=50, ux=1.0, uz=0.2, cov_xz=0.005, rho=1000.0
        # Visit 2: N=50, ux=1.4, uz=0.6, cov_xz=0.005, rho=1000.0
        # Grand: ux=1.2, uz=0.4
        # Between cov:
        # Visit 1: (1.0 - 1.2)*(0.2 - 0.4) = (-0.2)*(-0.2) = 0.04
        # Visit 2: (1.4 - 1.2)*(0.6 - 0.4) = (0.2)*(0.2) = 0.04
        # Mean between cov = 0.04
        # Total cov = 0.005 + 0.04 = 0.045
        # Total tau_xz = -1000.0 * 0.045 = -45.0 Pa
        row1 = {
            'sample_count': '50',
            'Corrected Velocity.X (m/s)': '1.0',
            'Corrected Velocity.Z (m/s)': '0.2',
            'u_prime_x_u_prime_z_cov (m2/s2)': '0.005',
            'rho_freshwater (kg/m3)': '1000.0',
        }
        row2 = {
            'sample_count': '50',
            'Corrected Velocity.X (m/s)': '1.4',
            'Corrected Velocity.Z (m/s)': '0.6',
            'u_prime_x_u_prime_z_cov (m2/s2)': '0.005',
            'rho_freshwater (kg/m3)': '1000.0',
        }
        res = aggregate_location_rows([row1, row2], 0.1, 0.1)

        self.assertAlmostEqual(float(res['u_prime_x_u_prime_z_cov (m2/s2)']), 0.045, places=5)
        self.assertAlmostEqual(float(res['Reynolds tau_xz (Pa)']), -45.0, places=4)

    def test_linear_environmental_fields(self):
        """Environmental variables (temp, pressure, SNR, correlation) should use sample weighting."""
        row1 = {
            'sample_count': '100',
            'Temperature (C)': '20.0',
            'Raw Pressure (dbar)': '8.50',
            'SNR.Avg (dB)': '20.0',
            'Correlation.Avg (%)': '80.0',
        }
        row2 = {
            'sample_count': '300',
            'Temperature (C)': '24.0',
            'Raw Pressure (dbar)': '8.70',
            'SNR.Avg (dB)': '24.0',
            'Correlation.Avg (%)': '92.0',
        }
        res = aggregate_location_rows([row1, row2], 0.0, 0.0)

        # Weighted: (100*20 + 300*24)/400 = 23.0
        self.assertAlmostEqual(float(res['Temperature (C)']), 23.0, places=4)
        # Weighted: (100*8.5 + 300*8.7)/400 = 8.65
        self.assertAlmostEqual(float(res['Raw Pressure (dbar)']), 8.65, places=4)
        # Weighted: (100*20 + 300*24)/400 = 23.0
        self.assertAlmostEqual(float(res['SNR.Avg (dB)']), 23.0, places=4)
        # Weighted: (100*80 + 300*92)/400 = 89.0
        self.assertAlmostEqual(float(res['Correlation.Avg (%)']), 89.0, places=4)


if __name__ == '__main__':
    unittest.main()
