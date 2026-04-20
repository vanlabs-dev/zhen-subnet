# Zhen: Proving Roadmap

<!-- FORMATTING RULE: This document must NEVER contain em dashes or en dashes. Use commas, periods, colons, or parentheses instead. -->

**Status:** Phase 1 complete. Differentiated weights confirmed in live testnet round 0 post-Phase-1. bestest_air active with year-round cooling. Phase 2 planning underway.
**Updated:** 2026-04-19

This document tracks two parallel tracks: the proving milestones from testnet validation through mainnet launch and revenue, and the technical capability phases that expand what the subnet can physically calibrate. Both tracks share the same codebase and the same incentive mechanism. Neither is skippable, and they must advance together: a proving milestone that requires multi-zone buildings is gated on the technical phase that adds multi-zone support.

---

## Target Markets

Zhen is built primarily for two customer segments. Technical scope, test case selection, and algorithm choices flow from these.

**Market 1: Commercial HVAC model predictive control.** Vendors such as BrainBox AI, PassiveLogic, and internal teams at Siemens, Johnson Controls, Honeywell, and Schneider Electric who build MPC stacks for mid and large commercial buildings. They need calibrated thermal and HVAC models as the foundation of their control layer. The calibration step is the bottleneck, not the controller. Zhen sells the calibration output, not the MPC.

**Market 3: Grid services and demand response.** Utilities, aggregators, and ISO-facing platforms that need accurate thermal models to forecast building flexibility, shed load, or participate in ancillary services markets. Same core asset as Market 1 (a calibrated thermal and HVAC model) used for a different downstream decision.

**Market 4 (fallout coverage): Single-zone residential.** Current test cases (bestest_hydronic_heat_pump, bestest_hydronic) fall in this segment. It is not actively optimized for, but the subnet covers it as a byproduct of validating the core mechanism on simple geometry before scaling.

**Market 2 (deferred): M&V and ESCO compliance.** ASHRAE Guideline 14 calibrations for Measurement and Verification of energy conservation measures. Enterprise sales cycle, regulated acceptance criteria, and a procurement posture that does not fit a new subnet. Deferred indefinitely; revisit only if a channel partner shows up.

---

## Technical Capability Phases

Phases expand what the simplified model can physically represent. Each phase gates specific proving milestones and specific markets. A phase is not declared complete until the active manifest reflects its scope and miner scores stabilize there.

### Phase 1: Single-zone year-round cooling [COMPLETE, 2026-04-19]

**Goal:** Resolve the live-run finding that ~90% of rounds produce uniform 0.5/0.5 weights because the heating-only RC model cannot fit summer periods. Add cooling support and a test case that exercises it.

**Scope delivered:**
- Extended `simulation/rc_network.py` with separate heating and cooling modes, each with its own parameter set. Dual-mode thermostat with `has_cooling` gate.
- Re-activated `bestest_air` (manifest v2.0.0, spec v5). The building has a four-pipe fan coil unit; Denver TMY weather extracted directly from BOPTEST FMU via `/forecast`. 7 calibratable parameters (added `hvac_cop_cooling`). 3 scoring outputs: zone_air_temperature_C, total_heating_thermal_kWh, total_cooling_energy_kWh.
- Introduced rank-based CVRMSE scoring (spec v6): top-K=5, base=0.5 exponential decay, ceiling CVRMSE=10.0. Constants live in `scoring/engine.py`.
- Dropped `bestest_hydronic` and `bestest_hydronic_heat_pump` from active manifest. Directories retained on disk for integration test fixtures.

**Exits confirmed:**
- Uniform-weight round rate on testnet drops well below 50% (live round 0 post-Phase-1: 0.731 / 0.269 split).
- Both miners pass ceiling gate (CVRMSE 0.51 and 0.70); scores differentiate via rank-based component.
- Open finding 2.1 (CVRMSE dead zone) resolved: rank-based scoring with a year-round test case eliminates the floor-tie equilibrium.

### Phase 2: Two-zone commercial (Market 1 and 3 minimum viable scope)

**Goal:** First real multi-zone architecture work. Introduces zone-to-zone thermal coupling and shared HVAC plant modeling, which is the distinguishing requirement of commercial buildings vs. residential.

**Scope:**
- Target case: `multizone_office_simple_hydronic` (Brussels, 2 zones, fan-coils + heat pump + chiller).
- RC model gains inter-zone coupling terms and a shared-plant abstraction (single heat pump or chiller feeding multiple zone loops).
- Manifest adds the new case; rotation keeps Phase 1 cases during overlap period.

**Open decisions tracked at Phase 1 exit:**
- Whether Bayesian optimization scales to the expanded parameter space (expected: marginal; will validate empirically before picking a migration path).
- Whether convergence budgeting needs to change per test case based on simulation cost.

### Phase 3: Five-zone reference commercial (full Market 1 and 3 scope)

**Goal:** Reach a DOE-style reference commercial building. This is the canonical artifact that commercial MPC vendors evaluate against.

**Scope:**
- Target case: `multizone_office_simple_air` (Chicago, 5-zone VAV with reheat, DOE reference).
- Full multi-zone VAV with reheat, realistic plant model, climate with large annual thermal swings.
- Calibration algorithm likely upgrades beyond scikit-optimize Bayesian at this point. Candidate direction: surrogate-assisted search or ensemble-of-solvers. Decision deferred to Phase 3 planning.

---

## Engineering History

Foundational engineering preceded the proving milestones. Recorded here for archaeological context; all phases below are complete.

| Phase | Scope | Status |
|---|---|---|
| 0: Foundation | Repo scaffolding, `RCNetworkBackend`, first test case config, determinism test, uv/ruff/mypy/pytest toolchain | Complete |
| 1: Scoring Engine | `compute_cvrmse`, `compute_nmbe`, `compute_r_squared`, `safe_clamp`, `ScoringEngine.compute` with power-law (p=2) + 5% floor, EMA (alpha=0.3), 22 red-team adversarial tests | Complete |
| 2: Simulation Infrastructure | `ZhenSimulator` interface, `RCNetworkBackend`, `BOPTESTClient`, `ManifestLoader`, `Dockerfile.miner`, `Dockerfile.validator` | Complete |
| 3: Validator Core | `RoundOrchestrator`, deterministic test case selection and train/test split (`hashlib.sha256`), `VerificationEngine` with 5-minute hard timeout, score breakdown | Complete |
| 4: Miner Core | `BayesianCalibrator` (scikit-optimize), `CalibrationEngine`, `CalibrationOutput` | Complete |
| 5: Bittensor Integration | `CalibrationSynapse`, `ZhenValidator` and `ZhenMiner` neurons, dendrite/axon wiring, on-chain weight setting | Complete |
| 6: Testnet Deployment | Subnet 456 live on testnet, manifest v1.1.0 through v2.0.0, red-team hardening, public docs (MINE.md, SCORING.md, RULES.md, VALIDATE.md, llms.txt) | Complete |

Open engineering items not tied to a specific phase: CALIBRATE.md tutorial (pending), local eval harness (pending), public dashboard (deferred post-mainnet), external validator onboarding (tracked as Milestone 5).

### Testnet Success Criteria

Adapted for Phase 1 scope (single active test case, rank-based scoring). Mainnet launch criteria are stricter, see Milestone 6.

| Metric | Target |
|--------|--------|
| Scoring differentiation | Top miner 2x+ above median composite score |
| ASHRAE compliance | Top miner achieves CVRMSE within the ranked top-K on the active test case. Absolute thresholds re-apply as the model tier advances in Phase 2/3 and the library grows. |
| Verification consistency | All validators produce identical scores (within float tolerance) |
| Miner count | 5+ active with distinct strategies |
| Score stability | No inf/NaN/zero-div in 7 days continuous |
| Miner feedback | No unresolved scoring complaints |
| Round completion | 95%+ of rounds complete within tempo |
| Test case diversity | 1 active case in Phase 1 (bestest_air); 3+ cases in rotation by Phase 2/3 as multi-zone models come online |

### Development Risk Register

Operational and miner-trust risks are covered in the open-audit-findings table below. This table tracks development and deployment risks only.

| Risk | Contingency |
|------|-------------|
| BOPTEST emulator does not run on target hardware | Fall back to Energym models. Build custom emulator from EnergyPlus IDF files. |
| RC network model produces physically implausible results | Pivot to reduced-order EnergyPlus as Phase 1 simplified model. Slower but more realistic. |
| Bittensor SDK incompatible with synapse design | Simplify synapse (reduce field count, use JSON strings instead of typed dicts). |
| Testnet TAO insufficient | Request more from community. Reduce initial validator/miner count. |
| No external miners join testnet | Run 3 to 5 miners yourself with different algorithms. Prove differentiation internally. |
| Scoring weights produce poor differentiation | Adjust weights based on testnet data. Expected and planned for. |

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

**Update (2026-04-18):** bestest_air pulled from active rotation in manifest v1.2.0 (spec v3). The case uses a four-pipe fan coil unit that provides both heating and cooling, which the heating-only RC model cannot represent. Miner CVRMSE on bestest_air rounds was catastrophic (4 to 8, far above the 0.30 ASHRAE threshold) regardless of optimization quality. Active rotation is now bestest_hydronic_heat_pump and bestest_hydronic, both of which the RC model can physically calibrate. Re-adding bestest_air is tracked under "Test case expansion: FCU buildings" below.

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
- Validator state persistence for crash recovery (originally ~/.zhen/validator_state.json; later superseded by the SQLite ~/.zhen/scoring.db path, with legacy JSON state archived automatically on first open)
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
- Register on Bittensor mainnet

The public dashboard is deferred to post-mainnet (see ARCHITECTURE.md Section 7). It is not required for launch.

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

## Known Open Audit Findings

Items not yet resolved from the initial pre-Phase-1 code audit. Severity and phase where resolution is expected. Documented here so the subnet does not claim a clean bill of health while items are open.

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 2.1 | CVRMSE dead zone when no miner clears the threshold. | High | **Resolved in Phase 1.** Rank-based scoring plus year-round bestest_air eliminates the floor-tie equilibrium. |
| 2.2 | Self-reported `simulations_used` is Nash-gameable; every rational miner reports 0 for the 10% convergence component. | High | Open. Lower priority now that rank-based CVRMSE dominates. Candidate fix: validator-verifiable wall-clock time, or remove component. Testnet data decides. |
| 2.3 | Near-default parameter tolerance 0.1% is bypassable by a 0.2% perturbation. | High | Open. Tolerance should scale with parameter span rather than raw percentage. |
| 2.4 | Missing-parameter fallback: RC model fills omitted params with config defaults, bypassing the all-defaults check. | High | Open. Require full parameter set in verification; reject partial submissions. |
| 2.5 | Tenacity `wait_fixed` should be `wait_exponential` for resilient retry behavior. | Medium | Open. |
| 2.12 | BOPTEST advance loop outer timeout not set. | Medium | Open. |
| 2.13 | Miner and validator disagree on zero-mean CVRMSE handling; validator skips, miner does not. | Medium | Open. |
| 2.14, 2.15 | Spec version not carried on the wire; miner logs a warning and continues on manifest mismatch rather than failing closed. | Medium | Open. |
| 2.16 | `asyncio.Lock` architectural debt in weight setter. | Medium | Open. |
| New | `validator/scoring/breakdown.py` still references `CVRMSE_THRESHOLD=0.30` for diagnostic display only. No impact on actual scoring; breakdown output may show misleading normalized values. | Low | Open. Fix when breakdown consumer is next updated. Code change required; out of scope for this docs pass. |
| New | R-squared component produces huge negative values on low-variance outputs (cooling near-zero in winter; heating near-zero in summer). Values are clipped to 0 by `max(0, R^2)`. Not blocking; consider restricting R^2 to zone_temperature output or dropping the component. | Low | Open. |
| New | Registry-to-runtime sync is manual: operators must run `cp registry/test_cases/$tc/*.json ~/.zhen/test_cases/$tc/` after any config change. Automation is on the Phase 2 backlog. | Low | Open. Documented in MINE.md and VALIDATE.md. |
| Tier-3 | Extrinsic error parsing, websocket keepalive, BOPTEST advance timeout, health endpoint completeness, and related operational items. | Low to Medium | Addressed opportunistically during validator work. Individual items tracked in code TODOs and commit history. |

---

## Phase 1 Retrospective

Key learnings confirmed by implementation and live-run data.

- Weather data alignment is not optional. The Brussels-derived weather.json paired with bestest_air's Denver FCU guaranteed catastrophic CVRMSE regardless of optimization quality. Extracting Denver TMY directly from the BOPTEST FMU via `/forecast` was the correct fix; no manual weather file construction.
- Thermal vs electrical output distinction matters for FCU test cases. bestest_air heating output is thermal power; cooling output is electrical power. Scoring must use the physically correct output type per variable; using either interchangeably produces misleading CVRMSE.
- Parameter-bounds-corner convergence on zero-signal training periods (pre-Phase-1 round 24) was a symptom of test case limitations, not a scoring bug. A year-round capable test case with a non-trivial physics floor resolves it.
- Rank-based scoring with a top-K cap is the correct composite design for a subnet with a non-trivial physics floor. Absolute-magnitude CVRMSE normalization requires re-tuning as the RC model tier advances; rank-based scoring is tier-agnostic by construction.
- Registry-to-runtime sync (registry/ to ~/.zhen/) is manual and fragile. Operators may forget to re-sync after config changes, causing stale runtime state with no obvious error. This is the most likely source of silent misconfiguration in production deployments.
- Live validation on testnet 456: Confirmed across 5 rounds over a 2+ hour observation window. Miners consistently diverge on calibrated parameters (no byte-identical convergence as observed pre-Phase-1). Training CVRMSE stays well under the 10.0 ceiling across varied period difficulty. Round-to-round winner alternates between UIDs (neither miner has structural advantage), and 5-round EMA settles near 0.54/0.46 — healthy differentiation. Two transient weight-commit errors (ExtrinsicResponse: (False, None)) both recovered on the next 60-second retry cycle without operator intervention.

---

## Non-Goals

Explicit choices not to pursue, so reviewers do not mistake absence for oversight.

- **Market 2 (M&V and ESCO compliance) is deferred.** The enterprise procurement and regulated acceptance posture is inappropriate for a new subnet. Revisited only if a channel partner materializes.
- **No period curation as a workaround for model capability.** If a round is "hard" because the RC model cannot represent the building under those conditions, the fix is more capable modeling (a phase), not hand-picking easier windows.
- **No shortcuts to mainnet.** Every proving milestone below must hit its exit criteria with evidence. Self-declared completion without data is not acceptable.
- **No post-hoc scoring tweaks.** The scoring formula is published and versioned. Changes go through the scoring change policy in DESIGN.md.

---

*This roadmap is sequential. Each milestone builds on the previous. Quality over speed. No milestone is declared complete without concrete evidence.*
