"""Data validation utilities."""

import logging

logger = logging.getLogger(__name__)


def check_snr(sample: dict, min_snr: float = 5.0) -> bool:
    """Check if sample SNR meets minimum threshold.
    
    Args:
        sample: Sample dictionary with 'snr' key
        min_snr: Minimum acceptable SNR in dB
        
    Returns:
        True if SNR is acceptable
    """
    snr = sample.get('snr', 0)
    return snr >= min_snr


def check_correlation(sample: dict, min_correlation: float = 70.0) -> bool:
    """Check if sample correlation meets minimum threshold.
    
    Args:
        sample: Sample dictionary with 'correlation' key
        min_correlation: Minimum acceptable correlation (%)
        
    Returns:
        True if correlation is acceptable
    """
    corr = sample.get('correlation', 0)
    return corr >= min_correlation


def mark_invalid(sample: dict) -> None:
    """Mark sample as invalid.
    
    Args:
        sample: Sample dictionary
    """
    sample['valid'] = False
