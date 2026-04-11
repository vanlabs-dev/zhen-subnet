"""Safe normalization and numeric hardening for scoring.

Provides safe_clamp and weight vector normalization with guards against
division by zero, NaN, Inf, and zero-sum edge cases.
"""

from __future__ import annotations

import math


def safe_clamp(value: float) -> float:
    """Clamp a value to [0.0, 1.0], treating non-finite as 0.0.

    Args:
        value: The value to clamp.

    Returns:
        Value clamped to [0.0, 1.0], or 0.0 if non-finite.
    """
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))
