# Zhen: Proving Roadmap

<!-- FORMATTING RULE: This document must NEVER contain em dashes or en dashes. Use commas, periods, colons, or parentheses instead. -->

**Status:** Milestone 1 complete
**Updated:** 2026-04-14

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

## Milestone 3: Expand Test Cases

**Goal:** Multiple building types exercise different calibration skills, preventing single-strategy dominance.

**Exit criteria:**

- 3 test cases available for testnet rotation
- Different building types (residential, commercial, multi-zone)
- Validators randomly select test cases per round via deterministic hashing
- No single parameter set scores well across all test cases

---

## Milestone 4: External Miners

**Goal:** Independent miners can join and compete using only published documentation.

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
