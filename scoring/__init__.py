"""Shared scoring logic used by both the validator and the local eval harness."""

from scoring.ema import EMATracker
from scoring.engine import ScoringEngine, VerifiedResult
from scoring.metrics import compute_cvrmse, compute_nmbe, compute_r_squared
from scoring.normalization import safe_clamp

__all__ = [
    "EMATracker",
    "ScoringEngine",
    "VerifiedResult",
    "compute_cvrmse",
    "compute_nmbe",
    "compute_r_squared",
    "safe_clamp",
]
