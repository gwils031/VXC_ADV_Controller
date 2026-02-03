"""Timing utilities for precise rate control."""

import time
import logging

logger = logging.getLogger(__name__)


def now() -> float:
    """Get current time in seconds since epoch.
    
    Returns:
        Current timestamp (float)
    """
    return time.time()


def sleep_precise(duration: float) -> None:
    """Sleep for specified duration with minimal overhead.
    
    Args:
        duration: Sleep time in seconds (float)
    """
    if duration <= 0:
        return
    
    end_time = time.time() + duration
    while time.time() < end_time:
        remaining = end_time - time.time()
        if remaining > 0.001:
            time.sleep(0.0001)
        else:
            break


class RateLimiter:
    """Rate limiter for periodic operations."""
    
    def __init__(self, target_hz: float):
        """Initialize rate limiter.
        
        Args:
            target_hz: Target frequency in Hz
        """
        self.target_hz = target_hz
        self.interval = 1.0 / target_hz
        self.last_call = 0.0
    
    def wait(self) -> float:
        """Wait until next interval, return time since last call.
        
        Returns:
            Time elapsed since last call (seconds)
        """
        now = time.time()
        elapsed = now - self.last_call
        
        if elapsed < self.interval:
            sleep_precise(self.interval - elapsed)
        
        self.last_call = time.time()
        return self.last_call - now


def rate_limiter(target_hz: float) -> RateLimiter:
    """Create a rate limiter for specified frequency.
    
    Args:
        target_hz: Target frequency in Hz
        
    Returns:
        RateLimiter instance
    """
    return RateLimiter(target_hz)
