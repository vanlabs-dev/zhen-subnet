"""Composite score computation engine.

Re-exports from the shared scoring.engine module. The shared module is
the single source of truth for ScoringEngine, VerifiedResult, and scoring logic.
"""

from scoring.engine import ScoringEngine, VerifiedResult

__all__ = ["ScoringEngine", "VerifiedResult"]
