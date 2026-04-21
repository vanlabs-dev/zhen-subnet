"""Shared synapse definitions for validator-miner communication."""

__spec_version__: int = 7
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
    5: Phase 1 cooling support. RC network model extended with separate
       heating and cooling modes and hvac_cop_cooling parameter. Test
       cases emit thermal and electrical heating/cooling outputs.
       bestest_air activated with Denver TMY weather as the sole active
       test case; bestest_hydronic and bestest_hydronic_heat_pump
       removed from manifest (directories retained on disk for
       integration test fixtures). Manifest bumped to v2.0.0.
       Invalidates v4 EMA state on load.
    6: Rank-based CVRMSE scoring with top-K cap. CVRMSE component
       (50% weight) now uses round-local rank with exponential decay
       (base=0.5) across top K=5 miners. Submissions with CVRMSE > 10.0
       are rejected at the ceiling gate and receive zero CVRMSE
       component score for the round. NMBE, R-squared, and convergence
       components unchanged. Invalidates v5 EMA state on load.
    7: CalibrationReport wired end-to-end. CalibrationSynapse gains an
       optional calibration_report response field (serialized
       CalibrationReport dict, validator-populated per miner after
       verification). ScoringDB gains a calibration_reports table
       keyed by (round_id, miner_uid) persisting the full report as
       JSON. Validator round flow builds a report per miner, persists
       to DB, and attaches each miner's own report to their response
       synapse object. Miners see None on pre-v7 clients (field is
       optional) and a populated dict on v7+. Rejected submissions
       still get reports (with NaN metrics and verification_reason
       set). Invalidates v6 scoring.db on load.
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
