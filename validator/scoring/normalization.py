"""Safe normalization and numeric hardening for scoring.

Provides safe_clamp and weight vector normalization with guards against
division by zero, NaN, Inf, and zero-sum edge cases.
"""
