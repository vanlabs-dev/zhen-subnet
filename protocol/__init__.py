"""Shared synapse definitions for validator-miner communication."""

__spec_version__: int = 3
"""Protocol spec version. Increment when scoring formula, synapse format,
or verification logic changes in a backward-incompatible way.

History:
    1: Initial release. Linear weight normalization.
    2: Power-law (p=2) weight normalization with 5% relative score floor
       to neutralize Sybil dilution. Invalidates v1 EMA state on load.
    3: Removed bestest_air from active manifest pending RC model cooling
       support (Milestone 5+). Convergence component now averages across
       2 test cases. Invalidates v2 EMA state on load.
"""
