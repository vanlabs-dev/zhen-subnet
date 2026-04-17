"""Shared synapse definitions for validator-miner communication."""

__spec_version__: int = 2
"""Protocol spec version. Increment when scoring formula, synapse format,
or verification logic changes in a backward-incompatible way.

History:
    1: Initial release. Linear weight normalization.
    2: Power-law (p=2) weight normalization with 5% relative score floor
       to neutralize Sybil dilution. Invalidates v1 EMA state on load.
"""
