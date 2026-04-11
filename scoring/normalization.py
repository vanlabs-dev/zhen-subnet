"""Safe normalization utilities (shared).

Provides safe_clamp and weight vector normalization with guards against
division by zero, NaN, Inf, and zero-sum edge cases.
"""

from __future__ import annotations

import math


def safe_clamp(value: float) -> float:
    """Clamp a value to [0.0, 1.0], returning 0.0 for non-finite inputs.

    Args:
        value: The value to clamp.

    Returns:
        The value clamped to [0.0, 1.0], or 0.0 if NaN/Inf.
    """
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))
