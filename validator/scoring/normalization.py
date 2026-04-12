"""Safe normalization and numeric hardening for scoring.

Re-exports from the shared scoring.normalization module.
"""

from scoring.normalization import safe_clamp

__all__ = ["safe_clamp"]
