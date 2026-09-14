"""Multi-visit spatial location aggregation for ADV/VXC data.

Implements the Law of Total Variance and Law of Total Covariance for pooling
repeated ADV visits to the same spatial coordinate, accounting for both within-visit
turbulence fluctuations and between-visit drift in the mean flow.
"""

import math
from typing import List, Dict, Optional, Any


def _parse_float(val: Any) -> Optional[float]:
    """Safely parse float value or return None."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def aggregate_location_rows(rows: List[Dict], x_loc: float, y_loc: float) -> Dict:
    """Aggregate multiple measurements at the same location.

    Applies the Law of Total Variance to normal Reynolds stresses (TI_x, TI_y, TI_z)
    and TKE, and the Law of Total Covariance to Reynolds shear stress (tau_xz),
    while using sample-weighted averaging for linear velocity and environmental fields.

    Args:
        rows: List of measurement dictionaries at this location.
        x_loc: X coordinate in meters.
        y_loc: Y coordinate in meters.

    Returns:
        Aggregated dictionary containing pooled metrics.
    """
    if not rows:
        return {}

    if len(rows) == 1:
        # Single measurement - return directly
        return dict(rows[0])

    # 1. Total sample counts & weights
    weights = []
    for r in rows:
        sc = _parse_float(r.get('sample_count'))
        weights.append(int(sc) if sc is not None and sc > 0 else 1)
    total_samples = sum(int(r.get('sample_count', 0)) for r in rows)
    total_w = sum(weights)
    if total_w <= 0:
        total_w = len(rows)
        weights = [1] * len(rows)

    result: Dict[str, Any] = {
        'x_m': f"{x_loc:.6f}",
        'y_m': f"{y_loc:.6f}",
        'sample_count': str(total_samples if total_samples > 0 else total_w),
        'quality_flag': 'GOOD',
        'measurement_count': str(len(rows)),
    }
    if 'timestamp_utc' in rows[-1]:
        result['timestamp_utc'] = rows[-1]['timestamp_utc']

    # 2. Linear fields (sample-weighted average)
    linear_keys = [
        'Raw Velocity.X (m/s)', 'Raw Velocity.Y (m/s)', 'Raw Velocity.Z (m/s)',
        'Correlation.Avg (%)', 'SNR.Avg (dB)',
        'Temperature (°C)', 'Temperature (C)',
        'Raw Pressure (dbar)', 'Gauge Pressure (dbar)', 'Corrected Pressure (dbar)',
        'Depth (m)', 'Voltage (V)',
    ]

    for key in linear_keys:
        pairs = []
        for r, w in zip(rows, weights):
            v = _parse_float(r.get(key))
            if v is not None:
                pairs.append((v, w))
        if pairs:
            w_sum = sum(v * w for v, w in pairs)
            sum_w = sum(w for _, w in pairs)
            if sum_w > 0:
                result[key] = f"{w_sum / sum_w:.6f}"

    # 3. Grand mean velocities for Corrected Velocity.X/Y/Z
    vel_components = {
        'x': ('Corrected Velocity.X (m/s)', 'TI_x (m/s)'),
        'y': ('Corrected Velocity.Y (m/s)', 'TI_y (m/s)'),
        'z': ('Corrected Velocity.Z (m/s)', 'TI_z (m/s)'),
    }

    grand_means: Dict[str, Optional[float]] = {}
    for comp, (vkey, _) in vel_components.items():
        pairs = []
        for r, w in zip(rows, weights):
            v = _parse_float(r.get(vkey))
            if v is not None:
                pairs.append((v, w))
        if pairs:
            w_sum = sum(v * w for v, w in pairs)
            sum_w = sum(w for _, w in pairs)
            grand_means[comp] = w_sum / sum_w if sum_w > 0 else None
            if grand_means[comp] is not None:
                result[vkey] = f"{grand_means[comp]:.6f}"
        else:
            grand_means[comp] = None

    # 4. Law of Total Variance for normal Reynolds stresses (TI_x, TI_y, TI_z)
    # Total Var = Within-group variance (E[Var]) + Between-group variance (Var[E])
    # sigma_total^2 = sum(N_i * (sigma_i^2 + (u_i - U_grand)^2)) / N_total
    total_variances: Dict[str, Optional[float]] = {}
    for comp, (vkey, tikey) in vel_components.items():
        u_grand = grand_means.get(comp)
        ti_terms = []
        for r, w in zip(rows, weights):
            ti = _parse_float(r.get(tikey))
            u_i = _parse_float(r.get(vkey))
            if ti is not None:
                within_var = ti * ti
                between_var = ((u_i - u_grand) ** 2) if (u_i is not None and u_grand is not None) else 0.0
                ti_terms.append(((within_var + between_var), w))

        if ti_terms:
            sum_w = sum(w for _, w in ti_terms)
            if sum_w > 0:
                var_tot = sum(term * w for term, w in ti_terms) / sum_w
                total_variances[comp] = max(0.0, var_tot)
                result[tikey] = f"{math.sqrt(total_variances[comp]):.6f}"
        else:
            total_variances[comp] = None

    # 5. Total Turbulent Kinetic Energy (TKE)
    # TKE_total = 0.5 * (Var_x + Var_y + Var_z)
    if all(total_variances.get(c) is not None for c in ('x', 'y', 'z')):
        tke_tot = 0.5 * (total_variances['x'] + total_variances['y'] + total_variances['z'])
        result['TKE (m2/s2)'] = f"{tke_tot:.6f}"
    else:
        # Fallback to direct weighted average if individual components not all present
        tke_pairs = []
        for r, w in zip(rows, weights):
            v = _parse_float(r.get('TKE (m2/s2)'))
            if v is not None:
                tke_pairs.append((v, w))
        if tke_pairs:
            sum_w = sum(w for _, w in tke_pairs)
            if sum_w > 0:
                result['TKE (m2/s2)'] = f"{sum(v * w for v, w in tke_pairs) / sum_w:.6f}"

    # 6. Law of Total Covariance for u'w' (u_prime_x_u_prime_z_cov)
    # Cov_total = E[Cov] + Cov(E[X], E[Z])
    # cov_total = sum(N_i * (cov_i + (u_x,i - U_x)(u_z,i - U_z))) / N_total
    cov_key = 'u_prime_x_u_prime_z_cov (m2/s2)'
    cov_terms = []
    ux_grand = grand_means.get('x')
    uz_grand = grand_means.get('z')
    for r, w in zip(rows, weights):
        c = _parse_float(r.get(cov_key))
        ux_i = _parse_float(r.get('Corrected Velocity.X (m/s)'))
        uz_i = _parse_float(r.get('Corrected Velocity.Z (m/s)'))
        if c is not None:
            between_cov = (
                (ux_i - ux_grand) * (uz_i - uz_grand)
                if (ux_i is not None and uz_i is not None and ux_grand is not None and uz_grand is not None)
                else 0.0
            )
            cov_terms.append(((c + between_cov), w))

    total_cov: Optional[float] = None
    if cov_terms:
        sum_w = sum(w for _, w in cov_terms)
        if sum_w > 0:
            total_cov = sum(term * w for term, w in cov_terms) / sum_w
            result[cov_key] = f"{total_cov:.6f}"

    # 7. Freshwater density and Reynolds shear stress
    # tau_xz = -rho * cov(u'w')
    rho_pairs = []
    for r, w in zip(rows, weights):
        r_val = _parse_float(r.get('rho_freshwater (kg/m3)'))
        if r_val is not None:
            rho_pairs.append((r_val, w))
    rho_mean = (sum(v * w for v, w in rho_pairs) / sum(w for _, w in rho_pairs)) if rho_pairs else 998.2
    if rho_pairs:
        result['rho_freshwater (kg/m3)'] = f"{rho_mean:.6f}"

    if total_cov is not None:
        tau_tot = -rho_mean * total_cov
        result['Reynolds tau_xz (Pa)'] = f"{tau_tot:.6f}"
    else:
        tau_pairs = []
        for r, w in zip(rows, weights):
            t_val = _parse_float(r.get('Reynolds tau_xz (Pa)'))
            if t_val is not None:
                tau_pairs.append((t_val, w))
        if tau_pairs:
            sum_w = sum(w for _, w in tau_pairs)
            if sum_w > 0:
                result['Reynolds tau_xz (Pa)'] = f"{sum(v * w for v, w in tau_pairs) / sum_w:.6f}"

    return result
