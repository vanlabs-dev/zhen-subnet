"""Shared scoring logic used by both the validator and the local eval harness."""

from scoring.engine import ScoringEngine, VerifiedResult
from scoring.metrics import (
    aggregate_to_monthly,
    compute_cvrmse,
    compute_cvrmse_monthly,
    compute_nmbe,
    compute_nmbe_monthly,
    compute_r_squared,
)
from scoring.normalization import safe_clamp

__all__ = [
    "ScoringEngine",
    "VerifiedResult",
    "aggregate_to_monthly",
    "compute_cvrmse",
    "compute_cvrmse_monthly",
    "compute_nmbe",
    "compute_nmbe_monthly",
    "compute_r_squared",
    "safe_clamp",
]
