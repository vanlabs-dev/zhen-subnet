"""Generate per-miner JSON score breakdowns.

Produces machine-readable score breakdowns with component scores, thresholds,
normalized values, weights, calibrated parameters, and round statistics.
"""

from __future__ import annotations

from typing import Any

from validator.scoring.engine import ScoringEngine, VerifiedResult
from validator.scoring.normalization import safe_clamp


def generate(
    uid: int,
    verified: VerifiedResult,
    composite: float,
    weights: dict[int, float],
    round_id: str = "",
    sim_budget: int = 1000,
) -> dict[str, Any]:
    """Generate a JSON-serializable score breakdown for a miner.

    Args:
        uid: Miner UID.
        verified: The miner's VerifiedResult.
        composite: Raw composite score (before normalization).
        weights: Normalized weight vector for all miners.
        round_id: Identifier for the current round.
        sim_budget: Maximum simulation budget allowed.

    Returns:
        Dict with full score breakdown suitable for JSON serialization.
    """
    engine = ScoringEngine()

    if verified.reason:
        return {
            "round_id": round_id,
            "miner_uid": uid,
            "status": "failed",
            "reason": verified.reason,
            "detail": verified.detail,
            "composite_score": 0.0,
            "final_weight": weights.get(uid, 0.0),
        }

    cvrmse_norm = safe_clamp(1.0 - (verified.cvrmse / engine.CVRMSE_THRESHOLD))
    nmbe_norm = safe_clamp(1.0 - (abs(verified.nmbe) / engine.NMBE_THRESHOLD))
    r2_norm = safe_clamp(verified.r_squared)
    conv_norm = safe_clamp(1.0 - (verified.simulations_used / sim_budget))

    return {
        "round_id": round_id,
        "miner_uid": uid,
        "status": "verified",
        "metrics": {
            "cvrmse": verified.cvrmse,
            "nmbe": verified.nmbe,
            "r_squared": verified.r_squared,
        },
        "component_scores": {
            "cvrmse": {
                "raw": verified.cvrmse,
                "threshold": engine.CVRMSE_THRESHOLD,
                "normalized": cvrmse_norm,
                "weight": engine.WEIGHTS["cvrmse"],
                "contribution": engine.WEIGHTS["cvrmse"] * cvrmse_norm,
            },
            "nmbe": {
                "raw": verified.nmbe,
                "threshold": engine.NMBE_THRESHOLD,
                "normalized": nmbe_norm,
                "weight": engine.WEIGHTS["nmbe"],
                "contribution": engine.WEIGHTS["nmbe"] * nmbe_norm,
            },
            "r_squared": {
                "raw": verified.r_squared,
                "normalized": r2_norm,
                "weight": engine.WEIGHTS["r_squared"],
                "contribution": engine.WEIGHTS["r_squared"] * r2_norm,
            },
            "convergence": {
                "simulations_used": verified.simulations_used,
                "budget": sim_budget,
                "normalized": conv_norm,
                "weight": engine.WEIGHTS["convergence"],
                "contribution": engine.WEIGHTS["convergence"] * conv_norm,
            },
        },
        "composite_score": composite,
        "final_weight": weights.get(uid, 0.0),
        "calibrated_params": verified.calibrated_params,
    }
