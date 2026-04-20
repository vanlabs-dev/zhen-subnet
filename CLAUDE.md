# Zhen Subnet

## What This Is
Bittensor subnet for decentralized digital twin calibration. Domain-agnostic platform where miners compete to calibrate simplified simulation models against complex ground truth. Validators verify accuracy using industry-standard metrics. First vertical: building energy simulation.

## Routing Table
- Design docs: docs/
  - Design rationale: docs/DESIGN.md
  - Architecture: docs/ARCHITECTURE.md
  - Roadmap (markets, phases, engineering history, open findings): docs/ROADMAP.md
- Scoring logic: scoring/
- Validator code: validator/
- Miner code: miner/
- Simulation backends: simulation/
- Synapse definitions: protocol/
- Test case registry: registry/
- Tests: tests/
- Agent definitions: agents/AGENTS.md
- Round score persistence: validator/scoring_db.py (SQLite, windowed EMA source)
- Windowed EMA: validator/scoring/window_ema.py (pure function compute_window_ema)
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
- `__spec_version__` (internal protocol/scoring version) and `WEIGHT_VERSION_KEY` (on-chain Yuma coordination constant) are orthogonal and live in protocol/__init__.py. Never conflate them; set_weights must use WEIGHT_VERSION_KEY only
- Design docs (docs/DESIGN.md, docs/ARCHITECTURE.md) are gitignored reference documents. DESIGN.md covers why the mechanism works the way it does; ARCHITECTURE.md covers how the system is built. Current-state facts (constants, active test cases, shipped features) live in SCORING.md, ROADMAP.md, and the code itself. The codebase is the source of truth.

## Key Architecture
Two-model design:
- Complex emulator (BOPTEST): validators only, generates ground truth
- Simplified model (RC network): miners calibrate, validators verify
- Scoring: CVRMSE 50% (rank-based, top-K=5, base=0.5 exponential decay, ceiling CVRMSE=10.0), NMBE 25%, R-squared 15%, convergence 10%
- Score pipeline: raw composites -> 5% relative floor vs max -> power-law (exponent 2) -> normalize to sum=1; empty dict returned on all-zero (caller copies chain weights)
- Single synapse: CalibrationSynapse (challenge fields + optional result fields)
- Spec version: 6 (v1 was linear normalization; v2 added power-law + floor; v3 dropped bestest_air pending cooling support; v4 expanded required_hash_fields; v5 re-activated bestest_air with cooling support, manifest v2.0.0; v6 introduced rank-based CVRMSE scoring). Tracked in protocol/__init__.py. Each bump invalidates prior EMA state on load.
