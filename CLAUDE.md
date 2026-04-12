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
- Local eval harness: eval/
- Dashboard: dashboard/
- Tests: tests/
- Agent definitions: agents/AGENTS.md

## Rules
- No em dashes or en dashes anywhere in the codebase
- No generic AI commenting in code
- Conventional commits for all changes (feat, fix, test, docs, chore)
- Quality over speed
- All scoring math must use float64
- hashlib.sha256 for ALL deterministic hashing (never Python hash())
- Every function has a docstring
- Every module has a module-level docstring

## Key Architecture
Two-model design:
- Complex emulator (BOPTEST): validators only, generates ground truth
- Simplified model (RC network): miners calibrate, validators verify
- Scoring: CVRMSE 50%, NMBE 25%, R-squared 15%, convergence 10%
- Single synapse: CalibrationSynapse (challenge fields + optional result fields)
