# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-04-15 (Testnet)

### Added
- Two-model architecture: BOPTEST (EnergyPlus) ground truth vs RC network calibration
- ASHRAE-standard scoring: CVRMSE (50%), NMBE (25%), R-squared (15%), convergence (10%)
- Bayesian optimization reference miner (scikit-optimize)
- 3 BOPTEST test cases: bestest_hydronic_heat_pump, bestest_air, bestest_hydronic
- Deterministic test case rotation (SHA-256)
- EMA weight smoothing across rounds with decay for absent miners
- Testnet deployment on Bittensor subnet 456

### Infrastructure
- Automated BOPTEST warmup with health check and retry
- Unit conversion pipeline (K to C, W to kWh) with hourly resampling
- Per-metric score logging for diagnostics
