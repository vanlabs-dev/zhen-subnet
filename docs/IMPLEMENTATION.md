# Zhen: Phased Implementation Plan

<!-- FORMATTING RULE: This document must NEVER contain em dashes or en dashes. Use commas, periods, colons, or parentheses instead. -->

**Version:** 1.0.0-draft
**Status:** Phase 6 in progress (testnet live, Milestones 1-3 proven, production hardening complete)
**See also:** [ROADMAP.md](ROADMAP.md) for proving milestones from testnet to mainnet
**Author:** vaN (vaNlabs)
**Date:** April 2026
**Depends on:** Mechanism Design Document v1.0.0, Technical Architecture Document v1.0.0

---

## 1. Overview

This document defines the phased build plan for the Zhen subnet. All deliverables trace back to the Mechanism Design and Technical Architecture documents. The plan is designed around a single developer (vaN) using Claude Code for implementation, with no timeline pressure.

**Development approach:** Claude.ai for strategy and design. Claude Code for implementation. Conventional commits throughout. Quality over speed.

**Hardware:** AMD Ryzen 7, RTX 4080 (16GB VRAM), 32GB RAM. Development on Windows. Bittensor SDK integration (Phase 5) tested on Linux VPS, as bittensor-wallet requires Unix for Rust compilation.

---

## 2. Phase 0: Foundation (Weeks 1 to 2) -- COMPLETE

**Goal:** Repository scaffolding, toolchain, and first proof-of-concept simulation run.

### Deliverables

- [x] Initialize `zhen/` repository with directory structure from Architecture Document Section 10
- [x] `pyproject.toml` with uv, ruff, mypy, pytest configuration (requires-python >=3.10; numpy, scipy, httpx, docker, aiohttp>=3.13.5; dev: ruff, mypy, pytest, pytest-asyncio, scikit-optimize)
- [x] `CLAUDE.md` routing table (Architecture Document Section 11.1)
- [ ] GitHub Actions CI: lint, type check, unit tests (not yet set up)
- [x] First RC network model: implement `RCNetworkBackend` from Architecture Document Section 4.2
- [x] First test case `config.json` for `bestest_hydronic_heat_pump`
- [x] Verify RC model runs locally: input parameters, output zone temperature + heating energy
- [x] Physics sanity test: increasing insulation R-value reduces heating energy (automated test)

### Exit Criteria

RC network model runs, produces physically plausible outputs, and passes determinism test (same params = same outputs across 10 runs). **Met.**

---

## 3. Phase 1: Scoring Engine (Weeks 3 to 4) -- COMPLETE

**Goal:** Complete scoring pipeline that takes predicted/measured time-series and produces composite scores.

### Deliverables

- [x] Implement `compute_cvrmse`, `compute_nmbe`, `compute_r_squared`
- [x] Implement `safe_clamp` normalization
- [x] Implement `ScoringEngine.compute()` with all four components (CVRMSE 50%, NMBE 25%, R-squared 15%, convergence 10%) plus power-law (p=2) amplification and 5% score floor. Introduced in spec_version 2; current spec_version is 6, see `protocol/__init__.py` for the full history. CVRMSE is rank-based as of spec_version 6.
- [x] Implement weight-setting with chain-weight fallback on all-failure
- [x] Implement `EMATracker` (alpha=0.3, non-finite decay, prune 1e-6)
- [x] Unit tests: every edge case (zero submissions, all infeasible, single miner, all tied, NaN/Inf inputs)
- [x] Unit tests: metric implementations with known inputs and hand-computed expected outputs
- [x] 22 red-team adversarial tests covering score floor, power-law, Sybil neutralization, parser rejection, manifest dup ids, malformed configs, concurrent saves

### Exit Criteria

Scoring engine passes all unit tests including adversarial inputs. **Met.**

---

## 4. Phase 2: ZhenSimulator and Test Case Infrastructure (Weeks 5 to 7) -- COMPLETE

**Goal:** Complete simulation wrapper, first BOPTEST integration, and model registry.

### Deliverables

- [x] Implement `ZhenSimulator` unified interface (`simulation/zhen_simulator.py`). `get_outputs()` is implemented; raises `RuntimeError` if called before `run()`. Only `rc_network` backend supported.
- [x] `reduced_energyplus.py` exists as a Phase 2 placeholder (docstring only, not implemented).
- [x] Create complete test cases: `bestest_hydronic_heat_pump`, `bestest_hydronic`, and `bestest_air`
  - [x] RC network simplified model with dual heating/cooling modes (has_cooling gate, hvac_cop_cooling parameter)
  - [x] `config.json` with parameter bounds, `scoring_outputs` list, defaults
  - [x] Weather data: Denver TMY (bestest_air, extracted from BOPTEST FMU via /forecast); Brussels (bestest_hydronic cases, retained on disk)
- [x] BOPTEST integration via `BOPTESTClient` REST API wrapper
- [x] Implement manifest.json schema and `ManifestLoader`. Current active manifest is v2.0.0 (bestest_air only, paired with `protocol.__spec_version__ = 6`).
- [x] Docker: `Dockerfile.miner` and `Dockerfile.validator`, base `python:3.12-slim`.
- [x] Determinism test: same params produce same outputs.

### Exit Criteria

Full test case pipeline works. **Met.**

---

## 5. Phase 3: Validator Core (Weeks 8 to 10)

**Goal:** Validator can run a complete round locally (no network, no chain).

### Deliverables

- [ ] Implement `RoundOrchestrator` from Architecture Document Section 2.2
- [ ] Implement deterministic test case selection (`hashlib.sha256`)
- [ ] Implement deterministic train/test split computation
- [ ] Implement `EmulatorManager` (Docker container lifecycle)
- [ ] Implement `DataCollector` (collect training + held-out measurements from emulator)
- [ ] Implement `VerificationEngine` with parallel verification (semaphore, asyncio.gather)
- [ ] Implement 5-minute hard timeout per verification
- [ ] Implement parameter bounds validation
- [ ] Implement score breakdown generation
- [ ] Wire orchestrator: select test case, run emulator, verify mock submissions, compute scores
- [ ] Integration test: full round with 3 mock miners (hardcoded parameter sets), verify score differentiation
- [ ] Integration test: cross-validator consistency (two orchestrators produce identical scores)

### Exit Criteria

Validator runs a complete round locally with mock miners. Two independent validator instances produce identical scores for the same mock submissions.

---

## 6. Phase 4: Miner Core (Weeks 11 to 12)

**Goal:** Reference miner can receive a challenge and return calibrated parameters.

### Deliverables

- [ ] Implement `ReferenceMiner` with Bayesian optimization (scikit-optimize) from Architecture Document Section 3.2
- [ ] Implement objective function: run ZhenSimulator, compare to training data, return CVRMSE
- [ ] Implement `CalibrationOutput` result container
- [ ] Verify: reference miner achieves CVRMSE < 0.20 on `bestest_hydronic_heat_pump` within 200 evaluations
- [ ] Integration test: validator sends mock challenge, miner calibrates, validator scores result
- [ ] Benchmark: measure wall-clock time for 500 evaluations on RC network model (target: < 5 minutes)
- [ ] Add second calibration algorithm (CMA-ES via `cmaes` package) as optional alternative

### Exit Criteria

Reference miner calibrates the bestest_hydronic test case to CVRMSE < 0.20 in under 5 minutes. End-to-end local loop works: validator generates challenge, miner calibrates, validator scores.

---

## 7. Phase 5: Bittensor Integration (Weeks 13 to 15)

**Goal:** Validator and miner communicate via Bittensor synapse protocol on local subtensor.

### Deliverables

- [ ] Implement `CalibrationSynapse` from Architecture Document Section 6.2
- [ ] Implement `ZhenValidator` neuron (Architecture Document Section 6.3)
- [ ] Implement `ZhenMiner` neuron (Architecture Document Section 6.4)
- [ ] Implement Dendrite challenge sending (validator to miner)
- [ ] Implement Axon challenge receiving (miner from validator)
- [ ] Implement weight setting via `subtensor.set_weights()`
- [ ] Test on local subtensor (bittensor local chain for development)
- [ ] Implement manifest version check: miner rejects challenge if manifest mismatch
- [ ] Implement EMA persistence across rounds
- [ ] Integration test: full round on local subtensor with 2 miners, verify weights set correctly

### Exit Criteria

Full round loop works on local Bittensor chain. Validator sends challenge, miners calibrate, validator verifies and sets weights. Weights reflect calibration accuracy.

---

## 8. Phase 6: Testnet Deployment (Weeks 16 to 20)

**Goal:** Zhen runs on Bittensor testnet with real network conditions.

**Testnet hardening batch completed 2026-04-17.** See [ROADMAP.md](ROADMAP.md) for milestone details.

### Deliverables

- [x] Accumulate testnet TAO (received 10 TAO from Rapido to owner wallet)
- Development environment: gaming PC (Ryzen 7 + RTX 4080 + 32GB RAM) running WSL2 for Bittensor operations
- [x] Create subnet on testnet: subnet 456 is LIVE
- [x] Register owner validator + reference miner (UIDs 0, 1, 2)
- [ ] Deploy BOPTEST emulator images to Docker Hub
- [ ] Deploy simplified model images to Docker Hub
- [x] Publish initial `manifest.json` v1.1.0 (current active manifest: v2.0.0)
- [x] Run first successful calibration round (CVRMSE 0.0399 with n_calls=500, then 0.1912 with n_calls=100 in 44 seconds)
- [x] Wire BOPTEST ground truth path for two-model architecture (commits: fe16a71, 79c7778, c5e3433, 91d344a, 8183131, 3b83904)
- [x] Prove two-model architecture: BOPTEST generates ground truth, miner calibrates RC model, scored via ASHRAE metrics. Two consecutive rounds: CVRMSE 1.2552 and 0.9644 (see [ROADMAP.md](ROADMAP.md) Milestone 1)
- [x] Testnet hardening: introduced spec_version=2 (power-law + floor); subsequent bumps to v3 (bestest_air pulled), v4 (expanded required_hash_fields), v5 (bestest_air re-activated with cooling support, manifest v2.0.0), and v6 (rank-based CVRMSE scoring) each invalidate prior EMA state on load. Challenge timeout 600s, cap metadata size (MAX_METADATA_BYTES=10000, MAX_PARAMS=50), miner manifest version mismatch warnings, copy_weights_from_chain fallback. JSON state file (fsync + per-call unique tmp files) replaced by SQLite scoring_db with WAL; legacy JSON is archived on first open.
- [ ] Run validator + miner for 48h continuous, verify stability
- [x] Add test cases: bestest_hydronic_heat_pump, bestest_hydronic, bestest_air (bestest_air pulled from the active manifest in v3; stays in the registry and returns with Phase 1 cooling support, see ROADMAP.md)
- [ ] Implement and deploy public dashboard (planned for post-mainnet)
- [ ] Implement and deploy local eval harness (planned, not yet built)
- [x] Write MINE.md
- [x] Write SCORING.md
- [x] Write RULES.md
- [ ] Write CALIBRATE.md (building energy calibration tutorial)
- [x] Write VALIDATE.md
- [x] Publish llms.txt
- [ ] Invite 3 to 5 external testnet miners

### Testnet Success Criteria (from Mechanism Design Section 10.4)

| Metric | Target |
|--------|--------|
| Scoring differentiation | Top miner 2x+ above median composite score |
| ASHRAE compliance | Top miner achieves CVRMSE within the ranked top-K on the active test case (relaxed from 4 cases in Mechanism Design Section 10.4: Phase 1 consolidated to a single active case, bestest_air, and the physics floor of the 7-parameter 1R-1C RC model against BOPTEST's Modelica FCU sits near CVRMSE 0.5; absolute thresholds re-apply as the model tier advances in Phase 2/3 and the library grows) |
| Verification consistency | All validators produce identical scores (within float tolerance) |
| Miner count | 5+ active with distinct strategies |
| Score stability | No inf/NaN/zero-div in 7 days continuous |
| Miner feedback | No unresolved scoring complaints |
| Round completion | 95%+ of rounds complete within tempo |
| Test case diversity | 1 active case in Phase 1 (bestest_air); 3+ cases in rotation by Phase 2/3 as multi-zone models come online |

### Exit Criteria

All testnet success criteria met for at least 7 consecutive days. No critical bugs. At least one external validator running.

---

## 9. Phase 7: Mainnet Launch (Weeks 21+)

**Goal:** Zhen goes live on Bittensor mainnet.

### Pre-Launch Checklist

- [ ] All testnet success criteria met for 7+ consecutive days
- [ ] At least 5 active miners with distinct strategies on testnet
- [ ] At least 1 external validator confirmed on testnet
- [ ] 6+ test cases in rotation
- [ ] Documentation complete: MINE.md, SCORING.md, RULES.md, CALIBRATE.md, VALIDATE.md
- [ ] Dashboard operational
- [ ] Local eval harness operational
- [ ] llms.txt published
- [ ] Scoring weights calibrated from testnet data
- [ ] Open questions from Mechanism Design Section 15 resolved or deferred with rationale

### Launch Sequence

1. Create subnet on mainnet: `btcli subnet create --network main`
2. Register owner validator
3. Register reference miner
4. Set hyperparameters (Mechanism Design Section 12)
5. Announce in Bittensor Discord, X/Twitter, IntoTAO
6. Monitor first 48h intensively

---

## 10. Phase 8: Post-Launch (Months 2 to 6)

**Goal:** Stabilize, expand, and begin revenue integration.

### Month 2 to 3: Stabilization

- [ ] Monitor scoring stability and miner feedback
- [ ] Calibrate scoring weights from mainnet data
- [ ] Add test cases to reach 6+ in rotation
- [ ] Resolve any scoring edge cases discovered in production
- [ ] First external validator fully operational

### Month 3 to 4: Expansion

- [ ] Add medium-difficulty test cases (multi-zone buildings, 15 to 30 parameters)
- [ ] Add reduced-order EnergyPlus simplified models (Phase 2 model type)
- [ ] Begin HVAC control optimization track design (Mechanism Design Section 14, Phase 2)

### Month 5 to 6: Revenue

- [ ] Design calibration API for external customers
- [ ] First beta API customer (energy consultancy or building owner)
- [ ] Track subnet health metrics (root_prop, net flows, external revenue %)

---

## 11. Dependency Graph

```
Phase 0 (Foundation)
  └── Phase 1 (Scoring Engine)
        └── Phase 2 (Simulation Infrastructure)
              ├── Phase 3 (Validator Core)
              │     └── Phase 5 (Bittensor Integration)
              │           └── Phase 6 (Testnet)
              │                 └── Phase 7 (Mainnet)
              │                       └── Phase 8 (Post-Launch)
              └── Phase 4 (Miner Core)
                    └── Phase 5 (Bittensor Integration)
```

Phases 3 and 4 can run in parallel after Phase 2 completes. All other phases are sequential.

---

## 12. Risk-Contingent Milestones

Operational risks (emissions dependency, miner trust, collusion, scoring edge cases) are tracked in the Mechanism Design Document risk register (Section 13, 20 items). This section covers development and deployment risks only.

| Risk | Trigger | Contingency |
|------|---------|-------------|
| BOPTEST emulator doesn't run on target hardware | Phase 2, Week 5 | Fall back to Energym models only. Build custom emulator from EnergyPlus IDF files. |
| RC network model produces physically implausible results | Phase 0, Week 2 | Pivot to reduced-order EnergyPlus as Phase 1 simplified model. Slower but more realistic. |
| Bittensor SDK incompatible with synapse design | Phase 5, Week 13 | Simplify synapse (reduce field count, use JSON strings instead of typed dicts). |
| Testnet TAO insufficient | Phase 6, Week 16 | Request more from community. Reduce initial validator/miner count. |
| No external miners join testnet | Phase 6, Week 18 | Run 3 to 5 miners yourself with different algorithms. Prove differentiation internally. |
| Scoring weights produce poor differentiation | Phase 6, Week 17 | Adjust weights based on testnet data. This is expected and planned for. |

---

## 13. Development Tools and Conventions

### Toolchain

- **Language:** Python 3.10+
- **Package manager:** uv
- **Linter:** ruff
- **Type checker:** mypy (strict mode)
- **Testing:** pytest
- **CI:** GitHub Actions
- **Docker:** Docker Desktop (local), Docker Hub (distribution)
- **Bittensor:** SDK latest stable

### Commit Convention

```
feat(validator): implement round orchestrator
fix(scoring): handle division by zero in CVRMSE
test(miner): add bayesian optimization convergence test
docs(mine): write 30-minute cold start guide
chore(ci): add mypy strict mode to GitHub Actions
```

### Code Quality Rules

- No em dashes or en dashes anywhere in the codebase
- No generic AI commenting in code
- All scoring math must use float64
- hashlib.sha256 for ALL deterministic hashing (never Python hash())
- Every function has a docstring
- Every module has a module-level docstring
- 100% test coverage on scoring/ module

---

*This document is the build plan for Zhen. All deliverables trace back to the Mechanism Design and Technical Architecture documents. The plan is designed to be executed incrementally with quality gates at each phase boundary.*
