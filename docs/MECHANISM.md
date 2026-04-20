# Zhen: Mechanism Design Document

<!-- FORMATTING RULE: This document must NEVER contain em dashes or en dashes. Use commas, periods, colons, or parentheses instead. -->

**Version:** 1.0.0-draft
**Status:** Testnet (subnet 456 live)
**Author:** vaN (vaNlabs)
**Date:** April 2026

---

## 1. Positioning

### 1.1 What Zhen Is

Zhen is a Bittensor subnet that creates a competitive marketplace for simulation model calibration. Miners compete to calibrate digital twin simulation models against real-world measurement data, producing parameter sets that minimize prediction error on unseen data. Validators verify calibration quality by running the calibrated models against held-out measurements and scoring with industry-standard metrics.

The output: calibrated simulation parameters that make digital twins faithful to reality.

**Architectural model:** The BOPTEST emulator represents a complex physical system (a building with detailed thermal physics, HVAC equipment, and occupant behavior). Validators interact with this emulator to collect "measurements," treating it as if it were a real building. Miners receive these measurements and calibrate a simplified model with adjustable parameters (wall R-value, infiltration rate, HVAC efficiency, etc.) to approximate the emulator's behavior. There may not be a perfect calibration because the simplified model cannot fully capture the emulator's complex physics. Scoring measures how close the miner's model predictions are to the emulator's outputs on unseen time periods, not whether parameters match some "true" value.

### 1.2 What Zhen Is Not

Zhen does not compete with any existing Bittensor subnet. No subnet currently performs physics-based simulation calibration, digital twin parameter optimization, or building energy model verification. Zhen occupies an entirely unoccupied space on the network.

Zhen is also not a prediction subnet. It does not forecast future values from historical data. It calibrates simulation models so their physics-based predictions match observed reality. The output is a set of physical parameters (wall insulation, infiltration rate, HVAC efficiency), not a time-series forecast.

### 1.3 Design North Star

Design the subnet so that the thing miners compete to produce is already something outsiders would pay for, and design validators so they can prove who actually produced it best.

Calibrated digital twins are what outsiders pay for. Full calibration engagements from engineering consultancies cost $10K to $100K, but that includes site visits, sensor installation, data collection, and multi-building portfolio work. The computational calibration portion, typically $5K to $20K of that engagement, is what the subnet replaces at lower cost, faster, and with provably better accuracy through competitive diversity.

### 1.4 Why This Problem

Three properties make simulation calibration uniquely suited to Bittensor:

**1. Verification is trivially cheap relative to solving.** Running a calibrated model against held-out measurements takes seconds. Finding the calibrated parameters takes hours of search across thousands of simulation evaluations. This asymmetry (cheap verification, expensive solving) is the ideal Bittensor pattern.

**2. Diversity of approaches is mathematically advantageous.** Different calibration algorithms (Bayesian optimization, evolutionary strategies, MCMC, gradient-based, surrogate-assisted) navigate the parameter space differently. No single method dominates all building types and system configurations. A portfolio of 50 competing approaches will consistently find better calibrations than any single approach.

**3. LLMs cannot do this.** Calibration requires running actual physics simulations thousands of times with different parameter values. This is pure computational search, not pattern recognition. Frontier AI labs have zero interest in building energy model calibration. This is maximally AI-compression-proof.

---

## 2. Value Flywheel

### 2.1 The Loop

```
Better miners build better calibration strategies
  > more accurate digital twins, faster convergence
    > calibration quality benchmarks improve publicly
      > reputation attracts engineering firms and building owners
        > external revenue flows into subnet
          > better economics attract better miners
            > cycle repeats
```

This is NOT: emit tokens, attract miners, hope narrative appears.

### 2.2 Phased Activation

The flywheel exists in design from day one but activates gradually. External revenue is months away, not immediate.

**Revenue Tier 1: Benchmark Dominance (Testnet + Early Mainnet, months 1 to 6)**
Revenue source: emissions only.
Value output: superior calibration results on public BOPTEST benchmarks. Every published result showing Zhen outperforming standard calibration tools is public proof of subnet output. The calibration leaderboard grows. Academic citations follow.
Flywheel status: building the credibility needed for Revenue Tier 2.

**Revenue Tier 2: First Revenue Integration (Months 6 to 12)**
Revenue source: emissions + first calibration API customers.
API integration: building owners, energy consultancies, and HVAC contractors submit uncalibrated models + measurement data via API. Zhen returns calibrated parameters. Per-calibration pricing.
Flywheel status: first external money entering the system.

**Revenue Tier 3: Sustained External Demand (Months 12+)**
Revenue source: emissions + API revenue + enterprise contracts.
Domain expansion into industrial process simulation, traffic networks, and energy grid models. Ongoing calibration subscriptions for continuous model updating as buildings change.
Flywheel status: self-sustaining. Subnet survives even if emissions shrink.

### 2.3 Who Pays If Token Speculation Disappears?

Three concrete buyer categories exist independent of emissions:

**1. Building owners and facility managers**
- Commercial buildings waste 20 to 30% of energy due to misconfigured HVAC systems
- A calibrated digital twin identifies optimal setpoints, saving $10K to $100K per year per building
- Current computational calibration cost: $5K to $20K from engineering consultancies (see Section 1.3)
- Zhen calibration cost: fraction of that, delivered in hours instead of weeks

**2. Energy efficiency consultancies**
- ASHRAE Guideline 14 requires calibrated models for Measurement and Verification (M&V) in energy performance contracts
- Every energy services company (ESCO) needs calibrated models
- Current bottleneck: calibration is the most time-consuming part of M&V workflows

**3. Smart building platforms (long-term aspiration)**
- Companies like Siemens, Johnson Controls, Honeywell, and Schneider Electric have internal simulation teams and proprietary models
- Calibrated models are the foundation for Model Predictive Control (MPC)
- These are unlikely early customers due to internal capabilities, but represent a large addressable market if the subnet proves superior accuracy on public benchmarks
- Siemens acquired Altair for $10B specifically for simulation capabilities, confirming the value of the commodity

### 2.4 Value Sinks

Concrete mechanisms that make value circulate through the subnet:
- Paid API access: external calibration requests require TAO payment
- Calibration report licensing: detailed reports with parameter analysis behind tiered access
- Owner emission discipline: owner take minimized, publicly committed
- Benchmark sponsorship: engineering firms pay to have their building types added to the test case library
- Alpha burn: % of external revenue buys + burns alpha

### 2.5 Green-Zone Health Targets

Design the subnet to earn:
- Lower root_prop over time (less protocol subsidy dependence)
- Sustained positive net flows (not spike-and-dump)
- Durable usage metrics (API calls, calibrations completed, accuracy improvements)
- Miner quality improvement over time (measurable)

Key metrics tracked from day one:
- Net 7d / 30d flows
- root_prop trajectory
- Gini / stake concentration
- External revenue as % of total miner income
- Calibration accuracy per epoch (subnet output KPI)
- Best CVRMSE achieved per test case (public leaderboard)

---

## 3. Miner Transparency (First-Class Design Principle)

### 3.1 Why This Section Exists

The #1 cause of subnet death is miner distrust. This section traces every design decision to documented failures in other subnets.

| Subnet | What Failed | Zhen Mitigation |
|--------|------------|------------------|
| SN50 Synth | inf/NaN in reward math broke scoring | Hardened numerics, explicit edge-case handling |
| SN74 Gittensor | Quality heuristic punished tests/good code | No proxy metrics. CVRMSE is CVRMSE. |
| SN93 Bitcast | High setup burden relative to expected upside | Reference miner ships day one. 30 min to first calibration (with Docker and Python pre-installed). |
| SN22 Desearch | Validator checks incomplete/brittle | Held-out verification is deterministic. No ambiguity. |
| Multiple | Rules changing under miners' feet | Scoring formula published, versioned, changes announced with lead time |
| SN74 Gittensor | Anti-gaming measure punished honest miners | Anti-gaming rules designed to never penalize legitimate work |

**Cleanest single takeaway from cross-subnet research:**
Anti-gaming mechanisms often fail when they punish honest miners more than exploiters.

### 3.2 Transparency Commitments

**Published scoring function:** The exact scoring formula, weights, and normalization logic are public in the repo. No hidden parameters.

**Machine-readable score breakdowns:** Every round, every miner receives:
```json
{
  "round_id": "r-2026-07-15-0842",
  "test_case": "bestest_hydronic_heat_pump",
  "miner_hotkey": "5Cxyz...",
  "score": 0.694,
  "breakdown": {
    "cvrmse_hourly": { "value": 0.127, "threshold": 0.30, "normalized": 0.577, "weight": 0.50 },
    "nmbe_hourly": { "value": -0.023, "threshold": 0.10, "normalized": 0.770, "weight": 0.25 },
    "r_squared": { "value": 0.941, "normalized": 0.941, "weight": 0.15 },
    "convergence_speed": { "simulations_used": 287, "budget": 1000, "normalized": 0.713, "weight": 0.10 }
  },
  "calibrated_params": {
    "wall_r_value": 3.42,
    "infiltration_ach": 0.35,
    "hvac_cop": 3.81,
    "internal_gains_w_per_m2": 12.7
  },
  "round_stats": {
    "total_miners": 18,
    "best_cvrmse": 0.089,
    "median_cvrmse": 0.194,
    "your_rank": 4
  }
}
```

Every score has a traceable computation path. No miner should ever need to ask "why did I score low?"

**Local eval harness:** Miners run the exact same scoring logic locally before submitting. The validator's scoring module is open-source and runnable standalone. This is the #1 retention mechanism from cross-subnet analysis.

**Public dashboard:** Real-time leaderboard with per-miner, per-round composite scores, component scores, and rank. The dashboard does NOT display calibrated parameter values. Showing parameters publicly would allow miners to copy the top performer's solution as a starting point, undermining competitive diversity. Parameters are visible only to the submitting miner in their private score breakdown.

### 3.3 Miner Onboarding Design

Modeled on SN6 Numinous (strongest documented onboarding):

Required artifacts at launch:
- `MINE.md`: complete setup guide, 30-minute cold start to first calibration (Docker and Python pre-installed)
- `SCORING.md`: full formula with worked examples and edge cases
- `RULES.md`: explicit constraints, allowed tools, forbidden behavior
- `CALIBRATE.md`: tutorial on building energy calibration for newcomers (pending)
- Docker one-command startup for miner (pulls model files automatically)
- Reference miner with working Bayesian optimization + ZhenSimulator wrapper
- Local eval harness for pre-submission testing

### 3.4 Scoring Change Policy

Any change to the scoring formula:
1. Published as a proposal with rationale at least 7 days before activation
2. Tested on historical round data to verify impact
3. Announced in Discord, GitHub, and subnet dashboard
4. Old formula remains active until switchover block is reached
5. Version number incremented in SCORING.md

---

## 4. Incentive Mechanism

### 4.1 Scoring Components

Miners are scored on four components:

| Component | Weight | Metric | Better Direction |
|-----------|--------|--------|-----------------|
| Prediction accuracy (CVRMSE) | 0.50 | Coefficient of Variation of RMSE on held-out period | Lower is better |
| Bias (NMBE) | 0.25 | Normalized Mean Bias Error on held-out period | Closer to zero is better |
| Fit quality (R-squared) | 0.15 | Coefficient of determination on held-out period | Higher is better (max 1.0) |
| Convergence efficiency | 0.10 | Simulations used relative to budget | Fewer is better |

### 4.2 Metric Definitions

**CVRMSE (Coefficient of Variation of Root Mean Square Error):**
```
CVRMSE = sqrt(sum((predicted_i - measured_i)^2) / n) / mean(measured)
```
Industry standard per ASHRAE Guideline 14. Hourly threshold: < 0.30 (30%). Monthly threshold: < 0.15 (15%).

**NMBE (Normalized Mean Bias Error):**
```
NMBE = sum(predicted_i - measured_i) / (n * mean(measured))
```
Captures systematic over/under-prediction. Hourly threshold: |NMBE| < 0.10 (10%).

**R-squared:**
```
R2 = 1 - (sum((measured_i - predicted_i)^2) / sum((measured_i - mean(measured))^2))
```
Measures overall fit quality. Values above 0.85 indicate good calibration.

**Convergence efficiency:**
```
convergence_score = 1 - (simulations_used / simulation_budget)
```
Rewards miners who find good calibrations with fewer expensive simulation evaluations.

### 4.3 Normalization

Each component is normalized to [0, 1] before weighting:

**CVRMSE normalization (rank-based, spec v6):**

CVRMSE is scored by rank among all submitters in the round, not against a fixed threshold. Miners above the ceiling gate (CVRMSE=10.0) receive 0.0. The top-ranked miner scores 1.0; each subsequent rank is multiplied by CVRMSE_DECAY_BASE=0.5. Only the top CVRMSE_TOP_K=5 miners receive non-zero CVRMSE scores; deeper ranks score 0.0.

Prior to spec v6, the linear formula was:
```
cvrmse_norm = max(0, 1 - (cvrmse / 0.30))
```
This formula is no longer used. It is retained here for historical reference only.

**NMBE normalization:**
```
nmbe_norm = max(0, 1 - (abs(nmbe) / nmbe_threshold))
```
Where nmbe_threshold = 0.10. An NMBE of 0.0 scores 1.0.

**R-squared normalization:**
```
r2_norm = max(0, r_squared)
```
Clamped at 0.0 floor (negative R-squared means worse than mean prediction).

**Convergence normalization:**
```
conv_norm = max(0, 1 - (sims_used / sim_budget))
```
Using zero simulations scores 1.0 (impossible in practice). Using the full budget scores 0.0.

### 4.4 Composite Score

```
composite = (0.50 * cvrmse_norm) + (0.25 * nmbe_norm) + (0.15 * r2_norm) + (0.10 * conv_norm)
```

Failed miners (missing params, crashed verification, infeasible submissions) receive composite = 0.0.

### 4.5 Weight Setting Pipeline

The weight pipeline applies three steps after composite scores are computed:

**Step 1: Score floor.** Any miner whose composite is below 5% of the top composite in the round is zeroed out. This prevents trivially weak submissions from free-riding on the power-law curve.
```
floor = max_composite * 0.05
composite_floored = composite if composite >= floor else 0.0
```

**Step 2: Power-law amplification (p=2).** Each floored composite is squared. This widens the gap between strong and weak miners, rewarding improvement at the top end more than the linear case.
```
powered = composite_floored ** 2
```

**Step 3: Normalize to sum = 1.0** for Yuma Consensus weight setting.
```
weights = powered / sum(powered)
```

**All-failure fallback.** If `sum(powered) == 0` (all miners failed or were floored), the scoring engine returns an empty dict `{}`. The validator then copies the current chain weights rather than setting uniform weights. This prevents unintentional redistribution during bad rounds.

Note: The original spec described linear normalization (`score / sum(scores)`) with a uniform-split fallback. The implemented pipeline is power-law (p=2) with a 5% floor and a chain-weight fallback on all-failure. The spec was superseded before testnet launch.

### 4.6 Scoring Output Variables

Each test case defines a `scoring_outputs` list in its `config.json` specifying which output variables are used for CVRMSE and NMBE computation. Examples: `["zone_air_temperature_C", "total_heating_energy_kWh"]`. The composite CVRMSE and NMBE are computed as the average across all scoring outputs. This is defined per test case because different building types have different relevant outputs (a residential building cares about zone temperature and heating energy; an office building might also include cooling energy and lighting).

### 4.7 EMA Smoothing

Miner scores are smoothed with an exponential moving average across rounds:
```
ema_score = alpha * current_composite + (1 - alpha) * previous_ema
alpha = 0.3
```

This rewards consistent calibrators over lucky one-offs.

**Cross-test-case blending:** Because test cases rotate, the EMA blends scores across different building types. A miner excellent at residential buildings but poor at commercial buildings will oscillate. This is a deliberate design choice: the subnet rewards calibration breadth, not narrow specialization. Miners who can calibrate any building type well are more valuable than single-domain specialists. If testnet data shows this creates excessive volatility, per-test-case-family EMA tracks are a fallback option.

### 4.8 Infeasible Submissions

If a miner's calibrated parameters produce a simulation that:
- Fails to run (crashes, timeout, invalid parameters)
- Produces outputs where any metric (CVRMSE, NMBE, R-squared) is non-finite
- Has parameters outside the declared bounds
- Looks like default/unoptimized parameters (anti-default check: 0.1% relative tolerance)
- Exceeds the verification timeout (TIMEOUT_SECONDS = 300)

The submission receives a score of 0.0 with a machine-readable reason code. Current reason codes from the verification engine:

| Code | Meaning |
|------|---------|
| INVALID_PARAMS | Parameters missing, wrong type, out of bounds, or non-finite |
| DEFAULT_PARAMS | Submitted parameters match defaults within 0.1% relative tolerance |
| SIMULATION_CRASHED | Simulator raised an exception during verification |
| SIMULATION_TIMEOUT | Verification exceeded TIMEOUT_SECONDS (300s) |
| SIMULATION_NAN | Simulation produced non-finite outputs |

Note: ACCURACY_FLOOR is not a current reason code. Submissions with very high CVRMSE are not rejected outright; they receive a low but non-zero composite score that is then likely zeroed by the 5% score floor in the weight pipeline (Section 4.5).

### 4.9 Convergence Efficiency: Self-Reported with Low Weight

The `simulations_used` field in CalibrationSynapse is self-reported. The validator cannot independently verify how many simulations a miner actually ran locally. This is acceptable because:

1. The convergence efficiency component has only 10% weight. Gaming it (reporting fewer simulations than actually used) gains at most 0.10 points on the composite score.
2. Accuracy components (CVRMSE, NMBE, R-squared) carry 90% of the weight. A miner who lies about simulation count but produces a poor calibration still scores poorly.
3. The field exists primarily for transparency and benchmarking, not as a primary scoring driver.

**Validation of the self-reported value.** The response parser applies several guards before the value reaches the scoring engine:
- Boolean values are rejected (not a valid int).
- Non-finite or negative values are rejected.
- The value is coerced to int.
- The verification engine clamps the value to `[0, simulation_budget]` regardless of what the miner reports.

If testnet data shows convergence gaming is a problem, the component will be removed or replaced with wall-clock submission time (which IS validator-verifiable).

### 4.10 Meta-Solver Strategy

Running multiple calibration algorithms in parallel (e.g., Bayesian optimization, CMA-ES, genetic algorithms, random search) and submitting the best result is explicitly legal and encouraged. This is good engineering, not an exploit. Well-resourced miners who can run multiple strategies simultaneously will have a structural advantage, and that is by design: the subnet rewards better results regardless of how they are achieved.

### 4.11 Normalization Note

CVRMSE/NMBE/R-squared normalization is still linear within each component (e.g., the difference between 0.05 and 0.10 is rewarded the same as the difference between 0.20 and 0.25). However, the power-law step in the weight pipeline (Section 4.5) compensates for this at the weight level: miners with higher composites receive disproportionately more weight than miners with lower composites. The effective result rewards top-end performance more heavily than a purely linear pipeline would.

Per-component non-linear normalization (exponential or sigmoid) remains a testnet calibration option if the power-law step proves insufficient.

### 4.12 Hardened Numerics

All scoring computations use:
- Explicit checks for division by zero (mean(measured) == 0)
- NaN/Inf guards on every intermediate calculation
- Clamping of all normalized scores to [0.0, 1.0]
- Float64 precision throughout
- Deterministic rounding for weight setting

---

## 5. Simulation Architecture

### 5.1 Miner-Local Execution Model

Miners run all simulations locally on their own hardware. Validators do NOT host simulation execution for miners. The validator's role is limited to: (a) generating training data from the emulator, (b) sending challenges, (c) running ONE verification simulation per miner submission on held-out data.

This means:
- Miners must have the simulation model files (FMU/IDF) pre-installed locally
- Model files are NOT sent via synapse (too large, 50-200MB per FMU)
- Miners interact with their local simulation instance, not the validator's BOPTEST deployment

### 5.2 Model File Distribution

Model files are distributed via a Zhen Model Registry, a versioned collection of Docker images and FMU files:

```
zhen-registry/
  manifest.json              # Versioned list of test cases, pinned per round
  test_cases/
    bestest_hydronic/
      model.fmu              # Functional Mockup Unit file
      config.json            # Parameter bounds, names, defaults
      Dockerfile             # One-command local deployment
      README.md              # Test case documentation
    multizone_office/
      ...
```

Distribution channels (in priority order):
1. Docker images on Docker Hub (one-command pull and run)
2. Direct HTTP download from Zhen registry server
3. IPFS as decentralized fallback

Miners and validators pull model files during setup, not during rounds. Round synapses contain only the test_case_id reference, not the model itself.

### 5.3 Simplified Model Architecture

The BOPTEST emulator represents a complex building with detailed physics (multi-layer wall conduction, airflow networks, detailed HVAC component models). Miners do NOT calibrate the full emulator. Instead, each test case ships with a **simplified calibration model**: a reduced-complexity representation of the same building with explicitly adjustable parameters.

The simplified model architecture varies by test case and is defined in `config.json`:

**Grey-box (RC network) models:** Thermal resistance-capacitance networks that approximate building thermal dynamics. Parameters include R-values (thermal resistance of walls, roof, floor), C-values (thermal capacitance of zones), infiltration rates, solar gain coefficients, and HVAC efficiency curves. Fast to simulate (sub-second per evaluation). Suitable for Difficulty Tier 1 (easy) test cases.

**Reduced-order EnergyPlus models:** Simplified EnergyPlus IDF files with fewer zones and coarser HVAC representations than the BOPTEST emulator. Parameters include material properties, infiltration schedules, equipment efficiencies, and setpoint offsets. Slower to simulate (10 to 60 seconds per evaluation). Suitable for Difficulty Tier 2 (medium) test cases.

**Surrogate-assisted models:** Miners may build their own ML surrogate models trained on simulator evaluations, then use the surrogate to guide parameter search. The final submission is still a set of parameters for the simplified model, evaluated by the validator on the actual simplified model, not on the surrogate.

Each test case's `config.json` specifies:
```json
{
  "simplified_model_type": "rc_network",
  "parameter_names": ["wall_r_value", "roof_r_value", "infiltration_ach", "hvac_cop", "solar_gain_factor"],
  "parameter_bounds": {
    "wall_r_value": [0.5, 8.0],
    "roof_r_value": [1.0, 12.0],
    "infiltration_ach": [0.1, 2.0],
    "hvac_cop": [1.5, 6.0],
    "solar_gain_factor": [0.3, 0.9]
  },
  "scoring_outputs": ["zone_air_temperature_C", "total_heating_energy_kWh"],
  "simulation_time_seconds_approx": 0.5
}
```

The key architectural insight: the validator runs the COMPLEX emulator to generate ground truth. The miner runs the SIMPLIFIED model to calibrate parameters. The scoring compares the simplified model's predictions against the complex emulator's outputs. This asymmetry (complex ground truth, simplified calibration target) is what makes the calibration problem non-trivial and ensures there is no "perfect" solution, only better approximations.

### 5.4 Unified Simulation Interface

BOPTEST provides a RESTful HTTP API. Energym provides a Python Gym interface. To avoid fragmentation, Zhen defines a unified Python interface that wraps both:

```python
class ZhenSimulator:
    def __init__(self, test_case_id: str, params: dict[str, float]):
        """Initialize simulator with calibratable parameters.
        Loads model files and weather data from local test case directory."""

    def run(self, start_hour: int, end_hour: int) -> dict:
        """Run simulation for the specified period using pre-installed weather data.
        Returns time-series predictions."""

    def get_outputs(self, output_names: list[str]) -> dict[str, list[float]]:
        """Return predicted values for specified scoring outputs."""
```

All test cases ship with a ZhenSimulator wrapper. Miners interact with this interface, not raw BOPTEST or Energym APIs. Weather data is pre-installed with the test case Docker image and loaded automatically by the wrapper, not passed as a parameter. This also abstracts the critical difference between BOPTEST (designed for control signal overwriting) and calibration (which requires modifying model-level parameters like wall R-values, infiltration rates, and HVAC coefficients).

For BOPTEST test cases: the wrapper modifies the FMU's initialization parameters before simulation start, then runs the simulation via the BOPTEST API.

For Energym test cases: the wrapper modifies parameters via the Energym environment interface.

### 5.5 Simulation Determinism

All test case simulations must be fully deterministic. Given identical parameters, weather data, and schedules, the simulator must produce bit-identical outputs on any machine. This is verified during test case onboarding:

- Stochastic components (random occupancy, probabilistic events) are disabled or seeded with fixed values
- EnergyPlus version is pinned per test case in the manifest (not hardcoded in this document; see manifest.json for current versions)
- Modelica solver settings (tolerance, step size) are fixed in the FMU
- All validators and miners use the same Docker image, eliminating platform differences

If a test case cannot guarantee determinism, it is rejected from the library.

### 5.6 Verification Simulation

When a validator receives a miner's CalibrationSynapse, the validator:
1. Loads the test case's ZhenSimulator wrapper locally
2. Initializes with the miner's calibrated parameters
3. Runs the simulation for the held-out test period
4. Compares predicted outputs against the emulator's "ground truth" outputs
5. Hard timeout: 5 minutes per verification simulation. Submissions exceeding timeout receive score 0.0 with reason code SIMULATION_TIMEOUT.

This is cheap: one simulation run per miner. For Difficulty Tier 1 test cases (RC network models), verification takes sub-second per miner. For Difficulty Tier 2 test cases (reduced-order EnergyPlus), 10 to 60 seconds per miner.

---

## 6. Round Flow

### 6.1 Round Structure

Each round corresponds to one Bittensor tempo (360 blocks, approximately 72 minutes).

### 6.2 Sequence

```
1. Validator selects test case from library
   (deterministic selection based on round_id hash, ensuring all validators pick the same test case)

2. Validator computes deterministic train/test split
   - Training period and held-out period derived from hashlib.sha256(round_id:test_case_id)
   - All validators compute the same split (see Section 6.5)

3. Validator runs BOPTEST emulator for the FULL period (training + held-out)
   - Phase A: Collects training measurements for the training period (sent to miners)
   - Phase B: Collects held-out measurements for the test period (kept secret, used for scoring)
   - Both phases use the same emulator instance with the same complex physics
   - Records: zone temperatures, energy consumption, HVAC status, weather conditions
   - Duration: 1 to 5 minutes depending on temporal resolution

4. Validator sends CalibrationSynapse to each miner via Dendrite
   - Contains: test_case_id, manifest_version, training measurements, parameter bounds, simulation budget
   - Does NOT contain: model files, weather data, or held-out measurements (miners have model/weather locally)

5. Miners calibrate locally
   - Run the SIMPLIFIED model (not the complex emulator) with their preferred calibration algorithm
   - Execute simulations with different parameter sets on their own hardware
   - Converge toward parameters that minimize prediction error on training data
   - Must complete within tempo time budget

6. Miners submit CalibrationSynapse
   - Contains: calibrated parameter values, number of simulations used, optional metadata

7. Validator verifies
   - Runs the SIMPLIFIED model with each miner's calibrated parameters for the HELD-OUT period
   - Compares simplified model predictions against the complex emulator's held-out outputs (from step 3B)
   - Computes CVRMSE, NMBE, R-squared on held-out data
   - Computes convergence efficiency from reported simulation count
   - Computes composite score

8. Validator sets weights on-chain
```

### 6.3 Synapse Definitions

**CalibrationSynapse:**
```python
class CalibrationSynapse(bt.Synapse):
    """Single synapse for calibration round.
    Validator fills challenge fields. Miner fills result fields (Optional)."""

    # Challenge fields (validator fills)
    test_case_id: str                    # References pre-installed test case from manifest
    manifest_version: str                # Pinned manifest version (all validators must match)
    training_data: dict                  # Time-series measurements (training period only)
    parameter_names: list[str]           # Names of parameters to calibrate
    parameter_bounds: dict               # Min/max for each calibratable parameter
    simulation_budget: int               # Maximum simulation evaluations allowed
    round_id: str                        # Round identifier
    train_start_hour: int                # Start hour of training period
    train_end_hour: int                  # End hour of training period

    # Result fields (miner fills, Optional)
    calibrated_params: Optional[dict[str, float]] = None
    simulations_used: Optional[int] = None          # Self-reported (see Section 4.9)
    training_cvrmse: Optional[float] = None         # Self-reported training accuracy
    metadata: Optional[dict] = None                 # Algorithm used, convergence history
```

Note: `model_spec` and `weather_data` are NOT in the synapse. Miners have these locally from the pre-installed test case Docker image. The synapse is lightweight (challenge fields + metadata only, result fields filled by miner).

**Parameter bounds authority:** `parameter_bounds` and `parameter_names` appear in both the synapse and the local `config.json`. The synapse values are authoritative. This allows validators to adjust bounds (e.g., tighten ranges for harder rounds) without requiring a full manifest update. Miners should use synapse values, not local config values, for their calibration search.

### 6.4 Test Case Selection and Manifest Versioning

Test cases rotate across rounds. Selection is deterministic using cryptographic hashing (NOT Python's built-in `hash()`, which is non-deterministic across processes due to PYTHONHASHSEED):

```python
import hashlib

def select_test_case(round_id: str, manifest: dict) -> str:
    digest = hashlib.sha256(round_id.encode()).hexdigest()
    index = int(digest[:8], 16) % len(manifest["test_cases"])
    return manifest["test_cases"][index]
```

**Manifest versioning:** The test case library is defined in a versioned `manifest.json`. Each round's CalibrationSynapse includes a `manifest_version` field. If a validator or miner has a different manifest version, they must update before participating. The manifest is hosted on the Zhen registry and versioned with semantic versioning (e.g., `v1.2.0`). Adding a test case increments the minor version. Removing one increments the major version.

### 6.5 Training/Test Split

For each round, the training and held-out periods are determined deterministically using cryptographic hashing:

```python
import hashlib

def compute_split(round_id: str, test_case_id: str, total_hours: int, train_length: int, test_length: int):
    seed_str = f"{round_id}:{test_case_id}"
    digest = hashlib.sha256(seed_str.encode()).hexdigest()
    seed_int = int(digest[:16], 16)
    rng = random.Random(seed_int)
    train_start = rng.randint(0, total_hours - train_length - test_length)
    train_end = train_start + train_length
    test_start = train_end
    test_end = test_start + test_length
    return train_start, train_end, test_start, test_end
```

All validators compute the same split. Miners receive only training data. Held-out data is never sent to miners.

---

## 7. Test Case Management

### 7.1 Initial Library (Difficulty Tier 1)

Sourced from BOPTEST and Energym:

| Test Case | Building Type | HVAC System | Climate | Source |
|-----------|--------------|-------------|---------|--------|
| bestest_hydronic_heat_pump | Residential single-zone | Hydronic heat pump | Brussels, Belgium | BOPTEST |
| bestest_air | Residential single-zone | Four-pipe fan coil unit (heating + cooling) | Denver, CO, USA | BOPTEST |
| multizone_office_simple | Commercial 5-zone office | VAV with reheat | Chicago, USA | BOPTEST |
| singlezone_commercial | Commercial single-zone | RTU | Multiple | BOPTEST |
| apartments_thermal | Multi-unit residential | Radiator heating | Northern Europe | Energym |
| seminarcenter | Seminar center | Mixed HVAC | Central Europe | Energym |

### 7.2 Test Case Requirements

Every test case must provide:
1. A containerized simulation model (FMU or Docker image)
2. A ZhenSimulator wrapper implementation conforming to the unified interface (Section 5.4)
3. Defined calibratable parameters with physically realistic bounds in `config.json`
4. A `scoring_outputs` list defining which output variables are scored (Section 4.6)
5. At least 1 year of simulation capability at hourly resolution
6. Pre-installed weather data for the test case's climate zone
7. Documentation of inputs, outputs, and system configuration
8. Verified simulation determinism (Section 5.5)

### 7.3 Adding New Test Cases

New test cases follow a proposal process:
1. Proposer submits test case with documentation
2. Validator team verifies API compliance and parameter bounds
3. Test case runs on testnet for at least 7 days
4. If stable, added to mainnet library with announcement

### 7.4 Difficulty Graduation

Test cases vary in difficulty:

**Difficulty Tier 1 (Easy):** Single-zone buildings with 5 to 10 calibratable parameters. Fast simulation (< 30 seconds per evaluation). Clear parameter sensitivities.

**Difficulty Tier 2 (Medium):** Multi-zone buildings with 15 to 30 parameters. Coupled thermal zones. Non-linear HVAC behavior. 1 to 2 minutes per evaluation.

**Difficulty Tier 3 (Hard):** Complex commercial buildings with 50+ parameters. District energy systems. Renewable integration. 3 to 5 minutes per evaluation.

Mixing difficulties across rounds ensures both newcomers and experts find appropriate challenges.

---

## 8. Validator Design

### 8.1 Validator Architecture

```
Validator Node
  |
  +-- Emulator Manager (COMPLEX model, ground truth)
  |     +-- BOPTEST test case deployment (Docker containers)
  |     +-- Training data generation (emulator API interaction)
  |     +-- Held-out ground truth collection
  |
  +-- Challenge Generator
  |     +-- Deterministic test case selection (hashlib.sha256)
  |     +-- Deterministic train/test split
  |     +-- CalibrationSynapse construction
  |
  +-- Verification Engine (SIMPLIFIED model, miner parameters)
  |     +-- Load miner's calibrated parameters into simplified model
  |     +-- Run simplified model for held-out period
  |     +-- Compare simplified model predictions against emulator ground truth
  |     +-- Compute CVRMSE, NMBE, R-squared
  |     +-- Hard timeout: 5 minutes per verification
  |
  +-- Scoring Engine
  |     +-- Normalize metrics
  |     +-- Compute composite score
  |     +-- Apply EMA smoothing
  |     +-- Generate score breakdowns
  |
  +-- Weight Publisher
        +-- Set weights on-chain via Bittensor SDK
```

### 8.2 Validator Responsibilities

1. Deploy and manage BOPTEST emulator containers (complex model for ground truth)
2. Compute deterministic train/test split from round_id
3. Generate training and held-out data by running the complex emulator
4. Send CalibrationSynapse to miners via Dendrite
5. Receive CalibrationSynapse submissions
6. Run verification by executing the SIMPLIFIED model with each miner's calibrated parameters
7. Compare simplified model predictions against complex emulator ground truth
8. Compute scores using published formula
9. Publish weights to blockchain

### 8.3 Cross-Validator Consistency

All validators must produce identical scores for the same miner submission. This is ensured by:

1. **Deterministic test case selection:** `hashlib.sha256(round_id)` produces the same result for every validator (see Section 6.4)
2. **Deterministic train/test split:** same cryptographic seed derived from round_id
3. **Deterministic complex emulator:** containerized BOPTEST emulators produce identical ground truth outputs for identical configurations
4. **Deterministic simplified model:** ZhenSimulator wrapper produces identical predictions for identical parameters (verified during test case onboarding, see Section 5.5)
5. **Deterministic scoring:** published formula with no random components

If validator scores diverge, the problem is a bug, not a design flaw. Yuma Consensus will flag outlier validators.

### 8.4 Owner Validator Stance

The subnet owner (vaN) will run a validator. This is normal Bittensor practice. However:

- External validator participation is fully supported from day one
- Complete validator setup documentation is published
- Scoring logic is open-source and reproducible
- The subnet does NOT depend on owner-only validation for legitimacy
- Any validator running the published code will produce the same scores for the same inputs

The legitimacy pattern: owner validates AND others can validate under identical published rules.

### 8.5 Validator Compute Requirements

Per round, a validator must:
- Run one BOPTEST emulator container (~2GB RAM)
- Generate ground truth data from complex emulator (~1 to 5 minutes depending on temporal resolution)
- Verify N miner submissions by running the simplified model with each miner's parameters
  - RC network models: sub-second per miner
  - Reduced-order EnergyPlus models: 10 to 60 seconds per miner
- For 50 miners on RC network test cases: ~2 minutes of verification compute
- For 50 miners on EnergyPlus test cases: ~25 to 50 minutes of verification compute

Difficulty Tier 1 test cases (RC network models) fit comfortably within the 72-minute tempo. Difficulty Tier 2 test cases (reduced-order EnergyPlus) require more careful time budgeting and may limit concurrent miner count on slower validator hardware.

---

## 9. Game Theory

### 9.1 Attack Vectors and Defenses

| Attack | Defense | Confidence |
|--------|---------|-----------|
| Fabricated parameters | Verification simulation. Deterministic. Unfakeable. | Very high |
| Overfitting to training data | Held-out test period. Miners never see test data. | Very high |
| Parameter copying between miners | Parameters are submitted privately to validator. Copying requires collusion. | High |
| Validator gaming scores | Multi-validator consensus. Deterministic scoring. | High |
| Memoizing test case solutions | Test case rotation + deterministic but varied train/test splits per round | High |
| Running zero simulations | convergence_score rewards efficiency but score is 90% accuracy-based | High |
| Submitting default parameters | Detected by DEFAULT_PARAMS check (0.1% relative tolerance). Score 0.0. | Very high |
| Poisoning training data | Validators generate training data independently from emulator. Miners cannot influence it. | Very high |
| Sybil attacks (many low-quality miners) | Power-law (p=2) amplification concentrates weight on top performers. The 5% floor zeroes out near-zero submissions. Multiple weak identities dilute each other without lifting any individual score. | High |

### 9.2 Anti-Gaming Design Principles

1. Never use proxy metrics that can punish quality work
2. The scoring function IS the actual objective (prediction accuracy on unseen data)
3. Make manipulation more expensive than honest participation
4. Keep anti-gaming rules explicit and stable
5. Parameter bounds enforce physical realism (R-value can't be negative, COP can't be 100)

### 9.3 Nash Equilibrium

The dominant strategy for a rational miner:
1. Build the best calibration algorithm you can
2. Use your simulation budget efficiently (surrogate models, smart search)
3. Validate against training data before submitting (local eval harness)
4. Diversify your approach across different algorithm families

This IS the desired behavior.

### 9.4 Collusion Analysis

**Miner-miner collusion:** Two miners share calibrated parameters. One of them gets a free ride. Defense: both score identically, which means the colluder gains nothing extra (they split the emission that one good miner would have earned). The honest miner is better off NOT sharing.

**Validator-miner collusion:** A colluding validator leaks held-out measurement data to a favored miner, allowing the miner to optimize against the test period instead of just the training data. This is an acknowledged residual risk. The attack is undetectable because all validators independently verify the submission and produce the same (legitimately high) score. No score divergence occurs.

Realistic defenses:
1. The advantage is ephemeral: test case and train/test split rotate every round, so the leaked data is useless next round.
2. The validator risks reputation and stake if the out-of-band communication is discovered.
3. This is the same fundamental attack surface that exists in every Bittensor subnet. Yuma Consensus tolerates it within bounds because the cost of sustained collusion exceeds the benefit.
4. EMA smoothing dilutes any single-round advantage across the miner's score history.

This risk is documented honestly rather than claiming it is fully defended.

---

## 10. Cold Start Strategy (First 30 Days)

Modeled on successful launch patterns from SN6, SN44, SN68.

### 10.1 Day 1 Requirements

- [ ] Reference miner ships (Bayesian optimization + ZhenSimulator wrapper)
- [ ] MINE.md with 30-minute cold start guide (Docker and Python pre-installed)
- [ ] SCORING.md with full formula + worked examples
- [ ] RULES.md with explicit constraints
- [ ] CALIBRATE.md with building energy calibration tutorial
- [ ] Docker one-command startup for miner and validator
- [ ] BOPTEST test cases deployed (minimum 3)
- [ ] Public dashboard live
- [ ] Local eval harness functional
- [ ] llms.txt + agent-friendly docs published

### 10.2 Week 1

- [ ] First miners onboarded and scoring
- [ ] Scoring differentiation visible (top miner achieving CVRMSE < 0.15 while median > 0.25)
- [ ] Score breakdown feedback confirmed working
- [ ] At least 2 distinct calibration approaches active

### 10.3 Week 2 to 4

- [ ] Additional test cases introduced (target: 6 total)
- [ ] At least 3 distinct calibration approaches active
- [ ] Scoring weight calibration based on testnet data
- [ ] Edge cases identified and resolved
- [ ] First external validator onboarded

### 10.4 Testnet Success Criteria

These are mainnet launch criteria. Testnet targets are relaxed: 3+ test cases (not 6+), CVRMSE < 15% on at least 2 test cases (not 4). See IMPLEMENTATION.md Section 8 for testnet-specific criteria.

| Metric | Target |
|--------|--------|
| Scoring differentiation | Top miner 2x+ above median composite score |
| ASHRAE compliance | Top miner achieves CVRMSE < 15% monthly on at least 4 test cases |
| Verification consistency | All validators produce identical scores (within float tolerance) |
| Miner count | 5+ active with distinct strategies |
| Score stability | No inf/NaN/zero-div in 7 days continuous |
| Miner feedback | No unresolved scoring complaints |
| Round completion | 95%+ of rounds complete within tempo |
| Test case diversity | 6+ test cases in rotation |

---

## 11. Agent Integration

### 11.1 Agent-Discoverable Subnet

- llms.txt at web root
- JSON-LD structured data on web presence
- Sitemap covering all documentation
- Machine-readable test case library endpoint
- Programmatic miner registration and score query APIs
- HOW-TO-MINE.md parseable by agents for autonomous miner setup

### 11.2 crustty as Subnet Health Monitor

Tracks: score distributions, flow trends, root_prop, scoring anomalies, miner churn, test case coverage.
Output: health alerts for subnet owner intervention.

### 11.3 crustty as Test Case Curator

Monitors: BOPTEST releases, new Energym models, academic building simulation benchmarks.
Output: test case candidates for library expansion.

---

## 12. Subnet Hyperparameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| tempo | 360 (72 min, 4320 seconds) | Standard. One calibration round per tempo. |
| min_allowed_weights | 8 | Prevent weight concentration |
| max_weight_limit | 455 | ~1.8% max per miner |
| immunity_period | 14400 (~48h) | New miners need time to build calibration strategies |
| commit_reveal_enabled | true | Prevent weight copying |
| commit_reveal_period | 3 | 3 tempo delay |
| weights_rate_limit | 100 | Set every ~100 blocks |

Key validator timing constants:

Bittensor defines a tempo as 360 blocks (approximately 4320 seconds at 12-second block time). The Zhen validator does not sleep a full tempo between rounds; it runs its own challenge loop at a configurable interval and relies on the chain's `weights_rate_limit` hyperparameter to gate weight commits.

- `BLOCK_TIME_SECONDS = 12` (`validator/main.py`): seconds per Bittensor block.
- `DEFAULT_CHALLENGE_INTERVAL_SECONDS = 900` (`validator/main.py`): default seconds between challenge rounds (15 minutes); configurable via CLI.
- `DEFAULT_WEIGHT_CHECK_INTERVAL_SECONDS = 60` (`validator/main.py`): polling cadence for block-gated weight commits.
- `CHALLENGE_TIMEOUT_SECONDS = 600` (`validator/main.py`): max seconds miners have to respond to a challenge.
- `WEIGHT_TIMEOUT_SECONDS = 120` (`WeightSetter`, `validator/weights/setter.py`): max seconds for chain weight submission.
- `TIMEOUT_SECONDS = 300` (`VerificationEngine`, `validator/verification/engine.py`): max seconds per miner verification run.

Note: `min_allowed_weights` is set to 1 on testnet during early development (insufficient miners for the target value of 8). Will be increased as miner count grows toward mainnet.

---

## 13. Risk Register

| # | Risk | L | I | Mitigation |
|---|------|---|---|-----------|
| R1 | Simulation execution exceeds tempo | M | H | Start with fast test cases, surrogate-assisted optimization, anytime submissions |
| R2 | Parameter fabrication | L | C | Mandatory verification simulation on held-out data |
| R3 | Test case staleness | M | M | Library expansion pipeline, community contributions |
| R4 | Miner monoculture | M | M | Test case diversity, difficulty graduation, rotation |
| R5 | BOPTEST dependency risk | L | H | Energym as fallback, custom FMU pipeline as backup |
| R6 | Validator compute burden | L | M | Verification is cheap (sub-second to 60s per miner depending on model type), Docker containerization |
| R7 | Domain expertise barrier | M | M | Reference miner, CALIBRATE.md tutorial, worked examples |
| R8 | Low initial miner count | H | M | Reference miner, docs, agent onboarding, Discord engagement |
| R9 | Scoring edge cases | L | H | Hardened numerics, adversarial testing, local eval harness. **Status: mitigated.** 22 red-team tests cover NaN/Inf composites, score floor, power-law equality and amplification, Sybil neutralization, concurrent state saves, parser rejection of bool/NaN/Inf/negative simulations, manifest dup ids, and malformed configs. |
| R10 | Miner trust erosion | M | H | Published scoring, reason codes, eval harness, change policy |
| R11 | Emissions-only dependency | H | C | Phased revenue integration, API development |
| R12 | Cross-validator score divergence | L | H | Deterministic everything: hashlib, pinned manifest, Docker images |
| R13 | Real-world data quality | M | M | Use validated BOPTEST emulators as ground truth initially |
| R14 | Parameter bound gaming | L | M | Physically realistic bounds reviewed per test case |
| R15 | Model file distribution failure | M | M | Multiple channels (Docker Hub, HTTP, IPFS). Pre-pull during setup. |
| R16 | EnergyPlus version mismatch | L | H | Pinned version in manifest. Docker images enforce exact version. |
| R17 | Simulation non-determinism | L | C | Determinism verified during test case onboarding. Fixed seeds. Docker isolation. |
| R18 | Verification simulation timeout/hang | L | H | Hard 5-minute timeout per verification. Score 0.0 with reason code. |
| R19 | Top miner parameter copying via dashboard | M | M | Dashboard shows scores only, not calibrated parameters. Parameters private to submitter. |
| R20 | Validator-miner collusion (held-out data leak) | L | M | Ephemeral advantage (rotates every round), EMA dilutes single-round gains, same attack surface as all subnets. Documented as acknowledged residual risk. |

---

## 14. Expansion Path

### 14.1 Domain Expansion

| Vertical | Domain | Tools | Timeline | Status |
|----------|--------|-------|----------|--------|
| 1 | Building energy | BOPTEST, EnergyPlus, Modelica | Months 1 to 6 | Planned |
| 2 | HVAC control optimization | BOPTEST control API | Months 6 to 9 | Planned |
| 3 | Industrial processes | Custom FMU models | Months 9 to 12 | Aspirational |
| 4 | Traffic simulation | SUMO (open source) | Months 12 to 15 | Aspirational |
| 5 | Energy grid | OpenDSS, PyPSA | Months 15 to 18 | Aspirational |
| 6 | General FMU calibration | Any Modelica/FMI model | Months 18+ | Aspirational |

Verticals 3 through 6 are aspirational. Each involves significant mechanism design differences from building energy calibration (different parameter types, different simulation tools, different verification metrics). These will only be pursued after Verticals 1 and 2 are stable and generating revenue. The core subnet architecture (miner-local simulation, held-out verification, deterministic scoring) transfers, but the test case library and wrapper interfaces require domain-specific engineering per vertical.

### 14.2 Multi-Mechanism Potential

Bittensor now supports multiple incentive mechanisms per subnet. Zhen could use:

- **Mechanism 0 (70%):** Standard calibration competition (accuracy-focused)
- **Mechanism 1 (30%):** Uncertainty quantification competition (miners produce probability distributions over parameters, scored by log-likelihood on held-out data)

This would be introduced after Vertical 1 stabilizes.

---

## 15. Open Questions for Testnet Resolution

1. Simulation budget per round: 500 / 1000 / 2000 evaluations? Testnet data decides.
2. Scoring weights: 0.50/0.25/0.15/0.10 is hypothesis. Testnet calibrates.
3. Training period length: 2 weeks / 4 weeks / 8 weeks? Testnet calibrates.
4. Test period length: 1 week / 2 weeks? Testnet calibrates.
5. EMA alpha: 0.3 is starting value. May need adjustment.
6. Model file distribution: Docker Hub vs HTTP registry vs IPFS. Docker Hub is default.
7. Multi-mechanism timing: when to introduce uncertainty quantification track.
8. Real-world data integration: when to supplement BOPTEST emulators with actual building data.
9. API pricing model: per-calibration vs subscription vs tiered.
10. Temporal resolution: CVRMSE should be computed at what resolution? Test cases may report at different intervals (5-min, 15-min, hourly). Should all data be resampled to a common resolution, or should CVRMSE be computed at the test case's native resolution? Native resolution is simpler but makes cross-test-case comparison harder.
11. CVRMSE normalization shape: linear (current) vs non-linear (sigmoid/exponential) to better reward marginal improvements at the top end. Testnet calibrates.
12. Convergence efficiency: keep as self-reported (current), replace with wall-clock submission time, or remove entirely? Testnet data decides.
13. EnergyPlus determinism verification: systematic testing of all Difficulty Tier 1 test cases across Linux distros and Docker versions to confirm bit-identical outputs.
14. EMA cross-test-case blending: global EMA (current) vs per-test-case-family EMA tracks. Testnet calibrates based on observed score volatility.

---

*This document is the living reference for Zhen subnet mechanism design. All implementation decisions trace back to principles defined here. Versioned, public, and designed to be read by humans and agents alike.*
