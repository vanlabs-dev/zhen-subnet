# Zhen Subnet

## What This Is
Bittensor subnet for decentralized digital twin calibration. Domain-agnostic platform where miners compete to calibrate simplified simulation models against complex ground truth. Validators verify accuracy using industry-standard metrics. First vertical: building energy simulation.

## Routing Table
- Design docs: docs/
  - Mechanism design: docs/MECHANISM.md
  - Architecture: docs/ARCHITECTURE.md
  - Implementation plan: docs/IMPLEMENTATION.md
- Scoring logic: scoring/
- Validator code: validator/
- Miner code: miner/
- Simulation backends: simulation/
- Synapse definitions: protocol/
- Test case registry: registry/
- Tests: tests/
- Agent definitions: agents/AGENTS.md
- State persistence: validator/state.py
- Health endpoint: validator/health.py
- Webhook alerts: validator/alerts.py
- Logging: validator/utils/logging.py
- PM2 scripts: scripts/
- Docker: Dockerfile.miner, Dockerfile.validator

## Rules
- No em dashes or en dashes anywhere in the codebase
- No generic AI commenting in code
- Conventional commits for all changes (feat, fix, test, docs, chore)
- Quality over speed
- All scoring math must use float64
- hashlib.sha256 for ALL deterministic hashing (never Python hash())
- Every function has a docstring
- Every module has a module-level docstring
- Spec version tracked in protocol/__init__.py, increment on breaking changes
- Design docs (docs/MECHANISM.md, docs/ARCHITECTURE.md, docs/IMPLEMENTATION.md) are gitignored reference documents from the initial design phase. Implementation may differ from spec where noted. The codebase is the source of truth, not the design docs.

## Key Architecture
Two-model design:
- Complex emulator (BOPTEST): validators only, generates ground truth
- Simplified model (RC network): miners calibrate, validators verify
- Scoring: CVRMSE 50%, NMBE 25%, R-squared 15%, convergence 10%
- Score pipeline: raw composites -> 5% relative floor vs max -> power-law (exponent 2) -> normalize to sum=1; empty dict returned on all-zero (caller copies chain weights)
- Single synapse: CalibrationSynapse (challenge fields + optional result fields)
- Spec version: 2 (v1 was linear normalization; v2 added power-law + floor; tracked in protocol/__init__.py)
