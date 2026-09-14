"""Doppler noise floor estimation and correction for Acoustic Doppler Velocimeters.

Implements the Voulgaris & Trowbridge (1998) spectral plateau method for estimating
and subtracting the Doppler instrument noise floor from normal Reynolds stresses and TKE.
"""

import math
import logging
from pathlib import Path
from typing import Sequence, Tuple, Dict, Any, Optional
import numpy as np
import yaml

logger = logging.getLogger(__name__)


def estimate_doppler_noise_floor(
    series: Sequence[float],
    fs: float = 10.0,
    high_freq_fraction: float = 0.25,
    min_samples: int = 32,
) -> float:
    """Estimate Doppler noise variance using high-frequency spectral plateau.

    In Acoustic Doppler Velocimeters (ADVs), instrument Doppler noise is white
    (flat spectrum). At high frequencies where turbulent kinetic energy drops below
    the instrument noise floor, the power spectral density levels off into a plateau.
    The noise variance is given by integrating the white noise spectral density over
    the Nyquist band: sigma_noise^2 = S_floor * (fs / 2).

    References:
        Voulgaris, G., & Trowbridge, J. H. (1998). Evaluation of the acoustic Doppler
        velocimeter (ADV) for turbulence measurements. Journal of Atmospheric and
        Oceanic Technology, 15(1), 272-289.

    Args:
        series: 1D velocity time series (m/s).
        fs: Sampling frequency in Hz (default 10.0 Hz).
        high_freq_fraction: Fraction of top spectrum used for noise plateau (default 0.25).
        min_samples: Minimum samples required to estimate spectrum (default 32).

    Returns:
        Estimated noise variance (m^2/s^2). Returns 0.0 if series is too short or clean.
    """
    if series is None or len(series) < min_samples:
        return 0.0

    arr = np.asarray(series, dtype=float)
    # Remove NaNs if any
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < min_samples:
        return 0.0

    # Mean-removed fluctuating velocity
    mean_val = np.mean(arr)
    fluctuations = arr - mean_val
    total_var = float(np.var(fluctuations))
    if total_var <= 1e-12:
        return 0.0

    # One-sided power spectral density via FFT
    # rfft returns n//2 + 1 complex values
    fft_vals = np.fft.rfft(fluctuations)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)

    # One-sided PSD normalization: integral over [0, fs/2] equals variance
    # P(f) = (2 / (N * fs)) * |X|^2 for f > 0
    psd = (2.0 / (n * fs)) * (np.abs(fft_vals) ** 2)

    # Identify high-frequency band (e.g. top 25% up to Nyquist fs/2)
    f_nyq = fs / 2.0
    f_thresh = (1.0 - high_freq_fraction) * f_nyq
    high_freq_mask = freqs >= f_thresh

    if not np.any(high_freq_mask):
        return 0.0

    # White noise plateau level is robustly estimated by the median of the high-freq tail
    s_floor = float(np.median(psd[high_freq_mask]))
    if s_floor <= 0.0:
        return 0.0

    # Noise variance across Nyquist bandwidth [0, fs/2]
    noise_var = s_floor * f_nyq

    # Sanity clamp: noise cannot exceed 90% of total measured variance
    noise_var = min(noise_var, 0.90 * total_var)
    return max(0.0, float(noise_var))


def correct_turbulence_variances(
    var_x: Optional[float],
    var_y: Optional[float],
    var_z: Optional[float],
    noise_x: float,
    noise_y: float,
    noise_z: float,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Subtract Doppler noise variance from measured normal variances and TKE.

    Reynolds shear stresses (u'w' covariance and tau_xz) are NOT corrected because
    Doppler noise is uncorrelated between receiver beams (Voulgaris & Trowbridge 1998).

    Args:
        var_x: Measured variance along X (m^2/s^2).
        var_y: Measured variance along Y (m^2/s^2).
        var_z: Measured variance along Z (m^2/s^2).
        noise_x: Estimated noise variance along X (m^2/s^2).
        noise_y: Estimated noise variance along Y (m^2/s^2).
        noise_z: Estimated noise variance along Z (m^2/s^2).

    Returns:
        Tuple of (var_x_clean, var_y_clean, var_z_clean, tke_clean).
    """
    vx_clean = max(0.0, var_x - noise_x) if var_x is not None else None
    vy_clean = max(0.0, var_y - noise_y) if var_y is not None else None
    vz_clean = max(0.0, var_z - noise_z) if var_z is not None else None

    if vx_clean is not None and vy_clean is not None and vz_clean is not None:
        tke_clean = 0.5 * (vx_clean + vy_clean + vz_clean)
    else:
        tke_clean = None

    return vx_clean, vy_clean, vz_clean, tke_clean


def load_doppler_noise_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load Doppler noise configuration from experiment_config.yaml.

    Args:
        config_path: Optional path to experiment_config.yaml.

    Returns:
        Dictionary with keys 'enabled' (bool) and 'min_samples' (int).
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"
        if not config_path.exists():
            config_path = Path("config/experiment_config.yaml")

    default_cfg = {"enabled": True, "min_samples": 32, "high_freq_fraction": 0.25}
    if not config_path.exists():
        return default_cfg

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        dn = cfg.get("doppler_noise", {})
        return {
            "enabled": bool(dn.get("enabled", True)),
            "min_samples": int(dn.get("min_samples", 32)),
            "high_freq_fraction": float(dn.get("high_freq_fraction", 0.25)),
        }
    except Exception as e:
        logger.warning(f"Could not read doppler_noise from {config_path}: {e}")
        return default_cfg
