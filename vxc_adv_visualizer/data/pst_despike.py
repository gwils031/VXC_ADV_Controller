"""Phase-Space Thresholding (PST) Despiking Algorithm for ADV Data.

Implements the Goring & Nikora (2002) 3D phase-space thresholding despiking method
with the Wahl (2003) Median Absolute Deviation (MAD) robust scale estimator.

References:
    - Goring, D. G., & Nikora, V. I. (2002). Despiking acoustic Doppler velocimeter
      data. Journal of Hydraulic Engineering, 128(1), 117-126.
    - Wahl, T. L. (2003). Discussion of "Despiking Acoustic Doppler Velocimeter Data"
      by Derek G. Goring and Vladimir I. Nikora. Journal of Hydraulic Engineering,
      129(6), 484-487.
"""

from dataclasses import dataclass
import logging
import math
from typing import Optional, Sequence, Tuple, Union
import numpy as np


logger = logging.getLogger(__name__)


@dataclass
class DespikeResult:
    """Result of Phase-Space Thresholding despiking.

    Attributes:
        cleaned: Despiked velocity array (same length as input).
        spike_mask: Boolean array where True indicates a detected spike.
        spike_count: Total number of spikes identified.
        spike_pct: Percentage of samples flagged as spikes.
        iterations: Number of iterations performed until convergence.
    """
    cleaned: np.ndarray
    spike_mask: np.ndarray
    spike_count: int
    spike_pct: float
    iterations: int


def _robust_std(x: np.ndarray) -> float:
    """Compute robust standard deviation using Median Absolute Deviation (Wahl, 2003).

    sigma_hat = 1.4826 * median(|x - median(x)|)
    Falls back to conventional sample std if MAD is zero.
    """
    if len(x) == 0:
        return 0.0
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    sigma_hat = 1.4826 * mad
    if sigma_hat < 1e-12:
        std = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
        return max(std, 1e-12)
    return float(sigma_hat)


def _compute_derivatives(u: np.ndarray, dt: float) -> Tuple[np.ndarray, np.ndarray]:
    """Compute first and second derivatives of velocity using central differences.

    Args:
        u: 1D velocity array (mean-removed).
        dt: Sampling interval in seconds.

    Returns:
        (du, d2u): First and second derivative arrays.
    """
    n = len(u)
    du = np.zeros(n, dtype=float)
    d2u = np.zeros(n, dtype=float)

    if n < 3:
        return du, d2u

    # First derivative (central differences; forward/backward at ends)
    du[1:-1] = (u[2:] - u[:-2]) / (2.0 * dt)
    du[0] = (u[1] - u[0]) / dt
    du[-1] = (u[-1] - u[-2]) / dt

    # Second derivative
    d2u[1:-1] = (u[2:] - 2.0 * u[1:-1] + u[:-2]) / (dt ** 2)
    d2u[0] = d2u[1]
    d2u[-1] = d2u[-2]

    return du, d2u


def _interpolate_spikes(u: np.ndarray, is_spike: np.ndarray) -> np.ndarray:
    """Replace flagged spikes in 1D velocity array via linear interpolation."""
    u_clean = u.copy()
    n = len(u)
    if not np.any(is_spike) or np.all(is_spike):
        return u_clean

    valid_idx = np.where(~is_spike)[0]
    spike_idx = np.where(is_spike)[0]

    u_clean[spike_idx] = np.interp(spike_idx, valid_idx, u[valid_idx])
    return u_clean


def pst_despike(
    velocity: Union[Sequence[float], np.ndarray],
    dt: float = 0.1,
    max_iter: int = 20,
    min_points: int = 10,
) -> DespikeResult:
    """Despike 1D velocity time series using Goring & Nikora (2002) with Wahl (2003).

    Constructs 3D phase-space (u, du/dt, d^2u/dt^2), projects onto three 2D planes,
    evaluates Universal Threshold bounds with MAD standard deviation, and iterates
    until no new spikes are found.

    Args:
        velocity: 1D sequence of velocity values.
        dt: Sampling interval in seconds (default 0.1 s for 10 Hz ADV).
        max_iter: Maximum number of detection iterations (default 20).
        min_points: Minimum sample size required to perform despiking.

    Returns:
        DespikeResult with cleaned velocity, spike mask, count, and iteration count.
    """
    arr = np.asarray(velocity, dtype=float)
    n = len(arr)

    # If too few points or flat array, return unedited
    if n < min_points or not np.isfinite(arr).all():
        # Clean any NaNs if present
        cleaned = np.nan_to_num(arr)
        return DespikeResult(
            cleaned=cleaned,
            spike_mask=np.zeros(n, dtype=bool),
            spike_count=0,
            spike_pct=0.0,
            iterations=0,
        )

    # Universal threshold parameter: lambda_U = sqrt(2 * ln(N))
    lambda_u = math.sqrt(2.0 * math.log(n))

    u_working = arr.copy()
    cumulative_spikes = np.zeros(n, dtype=bool)
    iterations_run = 0

    for it in range(1, max_iter + 1):
        iterations_run = it
        # Robust centering via median (Wahl, 2003)
        u_med = np.median(u_working)
        xi = u_working - u_med

        du, d2u = _compute_derivatives(xi, dt)

        # Scale estimates via Wahl (2003) MAD modification
        s_xi = max(_robust_std(xi), 1e-6)
        s_du = max(_robust_std(du), 1e-6)
        s_d2u = max(_robust_std(d2u), 1e-6)

        # Plane 1: (xi, du)
        a1 = lambda_u * s_xi
        b1 = lambda_u * s_du
        plane1_out = ((xi / a1) ** 2 + (du / b1) ** 2) > 1.0

        # Plane 2: (du, d2u)
        a2 = lambda_u * s_du
        b2 = lambda_u * s_d2u
        plane2_out = ((du / a2) ** 2 + (d2u / b2) ** 2) > 1.0

        # Plane 3: (xi, d2u) - rotated principal axis
        sum_xi2 = np.sum(xi ** 2)
        if sum_xi2 > 1e-12:
            theta = math.atan2(np.sum(xi * d2u), sum_xi2)
        else:
            theta = 0.0

        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        xi_rot = xi * cos_t + d2u * sin_t
        d2u_rot = -xi * sin_t + d2u * cos_t

        s_xi_rot = max(_robust_std(xi_rot), 1e-6)
        # Minor axis floor: prevents near-collinear signals (e.g. harmonic) from degenerating to numerical noise
        s_d2u_rot = max(_robust_std(d2u_rot), 0.05 * s_xi_rot, 1e-6)
        a3 = lambda_u * s_xi_rot
        b3 = lambda_u * s_d2u_rot
        plane3_out = ((xi_rot / a3) ** 2 + (d2u_rot / b3) ** 2) > 1.0

        # True velocity spike criterion: point must fall outside phase-space bounds
        # and represent a true velocity fluctuation, preventing stencil neighbor contamination
        # from the finite difference derivative.
        xi_threshold = 0.5 * a1
        current_spikes = (plane1_out | plane3_out | (plane2_out & (np.abs(xi) > xi_threshold))) & (np.abs(xi) > xi_threshold)
        new_spikes = current_spikes & (~cumulative_spikes)

        if not np.any(new_spikes):
            # Converged: no new spikes identified
            break

        cumulative_spikes |= current_spikes
        # Replace detected spikes with interpolated values for next iteration
        u_working = _interpolate_spikes(arr, cumulative_spikes)

    # Final replacement on original series using converged spike mask
    cleaned = _interpolate_spikes(arr, cumulative_spikes)
    spike_count = int(np.sum(cumulative_spikes))
    spike_pct = (spike_count / n) * 100.0 if n > 0 else 0.0

    logger.debug(
        f"PST despike complete: {spike_count}/{n} spikes ({spike_pct:.1f}%) "
        f"in {iterations_run} iterations"
    )

    return DespikeResult(
        cleaned=cleaned,
        spike_mask=cumulative_spikes,
        spike_count=spike_count,
        spike_pct=spike_pct,
        iterations=iterations_run,
    )
