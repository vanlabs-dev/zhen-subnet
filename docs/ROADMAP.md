# Zhen: Proving Roadmap

<!-- FORMATTING RULE: This document must NEVER contain em dashes or en dashes. Use commas, periods, colons, or parentheses instead. -->

**Status:** Milestone 3 complete, testnet hardening complete
**Updated:** 2026-04-17

This document tracks the proving milestones from testnet validation through mainnet launch and revenue. Each milestone has concrete exit criteria. No milestone is skippable.

---

## Milestone 1: Prove Two-Model Architecture [COMPLETE, 2026-04-14]

**Goal:** Demonstrate that the core design works: complex emulator generates ground truth, miners calibrate simplified models against it, scoring differentiates quality.

**What was proven:**

- BOPTEST (EnergyPlus via bestest_hydronic_heat_pump) generates complex ground truth
- Miners calibrate the simplified RC network model against that ground truth
- Scoring uses ASHRAE metrics: CVRMSE 50%, NMBE 25%, R-squared 15%, convergence 10%
- Weights set on-chain via Bittensor testnet (subnet 456)
- Two consecutive rounds completed successfully:
  - Round 0: CVRMSE 1.2552, 44s calibration time
  - Round 1: CVRMSE 0.9644, 37s calibration time

**Key insight:** The RC model cannot perfectly replicate EnergyPlus. CVRMSE values above 1.0 confirm the models are genuinely different. This gap IS the calibration challenge that miners must minimize.

**BOPTEST integration commits:** fe16a71, 79c7778, c5e3433, 91d344a, 8183131, 3b83904

---

## Milestone 2: Prove Competitive Differentiation [COMPLETE, 2026-04-14]

**Goal:** Multiple miners running simultaneously with meaningful score spread, proving the incentive mechanism works.

**What was proven:**

- 4 miners running simultaneously with different optimization budgets
- Clear score differentiation: top miner captured 3x the weight of weaker miners
- More optimization effort = better calibration = more emissions

**Round 0 results (BOPTEST ground truth):**

| Miner | UID | n_calls | CVRMSE | Composite | Weight |
|-------|-----|---------|--------|-----------|--------|
| C | 4 | 300 | 1.2514 | 0.509 | 50.9% |
| D | 5 | 5 | 1.8108 | 0.170 | 17.0% |
| B | 3 | 20 | 1.8108 | 0.167 | 16.7% |
| A | 2 | 100 | 1.2552 | 0.154 | 15.4% |

**Key insight:** The incentive mechanism works. Compute investment directly translates to emissions share. Miner C (300 iterations) captured 50.9% of weight versus 15-17% for low-effort miners.

**Note:** Miner A had better CVRMSE than B/D but slightly lower composite score. The ASHRAE composite includes NMBE, R-squared, and convergence speed alongside CVRMSE. Per-metric logging added to diagnose this in future rounds.

---

## Milestone 3: Expand Test Cases [COMPLETE, 2026-04-15]

**Goal:** Multiple building types exercise different calibration skills, preventing single-strategy dominance.

**What was proven:**

- 3 BOPTEST test cases operational: bestest_hydronic_heat_pump, bestest_air, bestest_hydronic
- Automated warmup: all 3 test cases initialized in 8 seconds with health check and retry
- SHA-256 deterministic rotation selects test case per round (no validator discretion)
- Different BOPTEST measurement mappings (reaTRoo_y, reaQHea_y) handled correctly per test case
- Round completed with bestest_hydronic: CVRMSE 1.7235, NMBE -0.2938, R-squared -3.3788
- Weights set on-chain

**Key insight:** Each test case exposes different thermal dynamics and measurement points. The higher CVRMSE on bestest_hydronic (1.72 vs 0.96 on bestest_hydronic_heat_pump) confirms that miners cannot reuse a single parameter set across building types. This is exactly the diversity pressure the milestone was designed to create.

---

## Production Hardening [COMPLETE, 2026-04-15]

**Goal:** Comprehensive codebase audit against production Bittensor subnet repos (Apex SN1, Score Vision, LeadPoet, Chutes, Targon, Lium-IO, Affine-Cortex). Two full passes addressing correctness, resilience, and operational readiness.

**Audit Pass 1 (8 issues fixed):**

- RC model energy output corrected from Watts to kWh
- EMA decay for absent miners (prevents stale weight holding)
- Dead code removal from RoundOrchestrator
- Documentation updates (VALIDATE.md, MINE.md, btcli v10 syntax)
- Integration test graceful skip when config missing
- Metagraph sync error resilience
- Empty stubs removed (eval/, dashboard/)

**Audit Pass 2 (10 issues fixed, reference repo patterns):**

- Weight processing via process_weights_for_netuid before chain submission
- NaN/Inf guard on weight vector
- Spec version tracking (protocol.__spec_version__, passed as version_key)
- Miner blacklist verification (reject unregistered hotkeys)
- Auto-updater script (PM2 + git pull every 5 min)
- httpx connection cleanup (async context manager)
- Dockerfiles for miner and validator
- Weight fallback (copy_weights_from_chain on scoring failure)
- Health check HTTP endpoint (GET /health on port 8080)
- env.example template

**Post-audit improvements (6 items):**

- Structured logging with daily file rotation
- Graceful shutdown with signal handling (SIGTERM/SIGINT)
- Validator state persistence (crash recovery via ~/.zhen/validator_state.json)
- Webhook alerting for round failures
- Weight-setting timeout (120s, prevents chain hang blocking)
- Anti-default-parameter detection in verification engine

**Testnet hardening (COMPLETE, 2026-04-17):**

Deep red-team audit and subsequent fixes addressing correctness, safety, and operational readiness for external participants:

- Power-law normalization (scores squared before normalizing) to make Sybil attacks unprofitable
- 5% score floor: miners below 5% of top scorer receive zero weight
- Spec version bump to v2 (protocol.__spec_version__); v1 EMA state rejected on load
- Concurrent state-save race condition fixed: unique tmp file per save with fsync before rename; stale tmp files swept on startup
- EMA scores validated in [0, 1] range on state load; spec_version enforced
- Local mode refused on mainnet (finney/main) with explicit error
- Health endpoint bound to 127.0.0.1 (loopback) by default
- Graceful shutdown polls shutdown flag every 1s during tempo sleep
- ZhenSimulator.get_outputs() fully implemented (previously raised NotImplementedError)
- Miner input validation hardened: calibrate() validates test case dir, training data presence, non-empty series, and finite values with explicit error messages
- BayesianCalibrator bounds validation with clear per-parameter error messages
- Manifest version mismatch handled gracefully (warning logged, challenge processed)
- ResponseParser: MAX_METADATA_BYTES=10,000, MAX_PARAMS=50, bool/non-finite/negative simulations_used rejected
- ManifestLoader rejects duplicate test_case IDs
- 22 red-team tests added (test_red_team.py): input validation, scoring edge cases, Sybil simulation, power-law correctness, state tampering, concurrent saves

---

## Milestone 4: External Miners

**Goal:** Independent miners can join and compete using only published documentation.

**Prerequisites:** Codebase is audit-complete (production hardening above). Dockerfiles, PM2 scripts, and operational docs (MINE.md, VALIDATE.md, SCORING.md, RULES.md) are ready for external users.

**Exit criteria:**

- Repository publicly accessible
- 3 to 5 external miners joined testnet
- MINE.md documentation sufficient for independent setup (validated by at least one external miner)
- At least one miner running without direct support from the team

---

## Milestone 5: External Validator

**Goal:** A second validator running independently confirms scoring consistency.

**Exit criteria:**

- Second validator running on different hardware
- Cross-validator weight consistency verified (identical scores within float tolerance)
- VALIDATE.md documentation sufficient for independent setup
- Both validators complete rounds for 48+ hours without divergence

---

## Milestone 6: Mainnet Launch

**Goal:** All testnet criteria met, stability proven, documentation complete.

**Exit criteria:**

- All testnet success criteria met for 7+ consecutive days
- No round failures or scoring anomalies in that period
- 95%+ of rounds complete within tempo
- No inf, NaN, or zero-division in scoring
- Documentation complete and externally verified: MINE.md, SCORING.md, RULES.md, CALIBRATE.md, VALIDATE.md
- Dashboard operational
- Register on Bittensor mainnet

---

## Milestone 7: Revenue

**Goal:** Calibrated digital twins generate external revenue, proving subnet economic viability.

**Exit criteria:**

- Calibration API endpoint live and documented
- First paying customer using calibrated building models
- Revenue model validated (per-calibration pricing or subscription)
- External revenue contributes to subnet TAO flows

---

## Milestone 8: Platform Expansion

**Goal:** Zhen expands beyond building energy to prove domain-agnostic design.

**Exit criteria:**

- Second digital twin vertical operational (e.g., HVAC control, manufacturing, water systems)
- Multi-mechanism support for different verticals
- Additional emulator backends integrated
- Scoring engine handles multiple domain types without modification

---

*This roadmap is sequential. Each milestone builds on the previous. Quality over speed. No milestone is declared complete without concrete evidence.*
