"""Shared synapse definitions for validator-miner communication."""

__spec_version__: int = 4
"""Protocol spec version. Increment when scoring formula, synapse format,
or verification logic changes in a backward-incompatible way. Internal
versioning only, NOT the on-chain weight version.

History:
    1: Initial release. Linear weight normalization.
    2: Power-law (p=2) weight normalization with 5% relative score floor
       to neutralize Sybil dilution. Invalidates v1 EMA state on load.
    3: Removed bestest_air from active manifest pending RC model cooling
       support (Milestone 5+). Convergence component now averages across
       2 test cases. Invalidates v2 EMA state on load.
    4: Expanded required_hash_fields to cover challenge payload
       (training_data, parameter_bounds, simulation_budget,
       manifest_version). Closes MITM tamper surface identified in
       audit finding 1.6. Invalidates v3 EMA state on load.
"""

WEIGHT_VERSION_KEY: int = 1000
"""On-chain weight version key for Bittensor Yuma aggregation.

All Zhen validators must use the same value so the chain can aggregate
their weight vectors coherently. This is orthogonal to __spec_version__:
bump this only when the on-chain weight interpretation changes (rare),
NOT when internal scoring logic changes.

Mainnet and testnet use the same key. Coordination is out-of-band via
docs and operator communication.
"""
