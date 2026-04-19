# Zhen: Technical Architecture Document

<!-- FORMATTING RULE: This document must NEVER contain em dashes or en dashes. Use commas, periods, colons, or parentheses instead. -->

**Version:** 1.0.1
**Status:** Testnet (subnet 456 live)
**Author:** vaN (vaNlabs)
**Date:** April 2026
**Depends on:** Mechanism Design Document v1.0.0

---

## 1. System Overview

### 1.1 Component Map

```
┌─────────────────────────────────────────────────────────┐
│                    SUBNET OWNER (vaN)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Test Case    │  │  Model       │  │  crustty      │  │
│  │ Builder      │  │  Registry    │  │  (agent)      │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                  │                   │          │
│         └──────────┬───────┘                   │          │
│                    │                           │          │
└────────────────────┼───────────────────────────┼──────────┘
                     │                           │
        ┌────────────▼────────────────────┐      │
        │        VALIDATORS               │      │
        │  ┌──────────────────────────┐   │      │
        │  │  Round Orchestrator      │   │◄─────┘
        │  │  Emulator Manager        │   │  (health alerts,
        │  │  Challenge Generator     │   │   test case candidates)
        │  │  Verification Engine     │   │
        │  │  Scoring Engine          │   │
        │  │  Weight Setter           │   │
        │  └──────────┬───────────────┘   │
        └─────────────┼───────────────────┘
                      │ Dendrite (CalibrationSynapse)
                      │ Axon (CalibrationSynapse)
        ┌─────────────▼───────────────────┐
        │          MINERS                  │
        │  ┌──────────────────────────┐   │
        │  │  Challenge Receiver      │   │
        │  │  Calibration Engine      │   │
        │  │  ZhenSimulator (local)   │   │
        │  │  Parameter Optimizer     │   │
        │  │  Result Packager         │   │
        │  └──────────────────────────┘   │
        └─────────────────────────────────┘
                      │
        ┌─────────────▼───────────────────┐
        │      BITTENSOR CHAIN            │
        │  Yuma Consensus                 │
        │  Weight Storage                 │
        │  Emission Distribution          │
        │  Metagraph                      │
        └─────────────────────────────────┘
```

### 1.2 Data Flow Summary

```
1. Subnet owner builds test cases (complex emulator + simplified model + config) and publishes to registry
2. Miners and validators pull test case Docker images during setup
3. Validator selects test case, computes train/test split, runs complex emulator to generate ground truth
4. Validator sends CalibrationSynapse (training measurements + metadata) to each miner via Dendrite
5. Miner runs simplified model locally with different parameter sets (calibration search)
6. Miner returns CalibrationSynapse (calibrated parameters + metadata)
7. Validator runs simplified model with miner's parameters for held-out period
8. Validator compares simplified model predictions against complex emulator ground truth
9. Validator computes CVRMSE, NMBE, R-squared, composite score
10. Validator sets weights on-chain
11. Bittensor distributes emissions via Yuma Consensus
```

### 1.3 Two-Model Architecture

The core architectural insight: validators run the COMPLEX model (BOPTEST emulator) to generate ground truth. Miners and validators run the SIMPLIFIED model (RC network or reduced-order EnergyPlus) for calibration and verification. This asymmetry is what makes the calibration problem non-trivial.

```
                  Complex Emulator (BOPTEST)
                  ┌─────────────────────┐
                  │ Detailed thermal    │
                  │ physics, multi-layer│    Validator ONLY
                  │ walls, airflow nets,│    (ground truth generation)
                  │ detailed HVAC       │
                  └──────────┬──────────┘
                             │ "measurements"
                             ▼
              ┌──────────────────────────────┐
              │      Training Data           │
              │  (zone temps, energy, HVAC)  │
              └──────┬───────────────┬───────┘
                     │               │
                     ▼               ▼
              Miner (calibrate)   Validator (verify)
              ┌──────────────┐   ┌──────────────┐
              │ Simplified   │   │ Simplified   │
              │ Model (RC    │   │ Model (RC    │
              │ network or   │   │ network or   │
              │ reduced EP)  │   │ reduced EP)  │
              └──────────────┘   └──────────────┘
              Run 100-1000x       Run 1x per miner
              with different      with miner's params
              parameters          on held-out period
```

---

## 2. Validator Architecture

The validator is the most complex component. It orchestrates rounds, manages emulators, verifies calibrations, computes scores, and sets weights.

### 2.1 Module Breakdown

```
validator/
├── main.py                    # Entry point, Bittensor neuron lifecycle
├── scoring_db.py              # SQLite score persistence (WAL, spec-version-checked, windowed reads for EMA)
├── health.py                  # HealthServer: GET /health on 127.0.0.1:8080
├── alerts.py                  # WebhookAlerter: 600s cooldown per event_type
├── round/
│   ├── orchestrator.py        # Round lifecycle management
│   ├── test_case_selector.py  # Deterministic test case selection (hashlib.sha256)
│   └── split_generator.py     # Deterministic train/test split computation
├── emulator/
│   ├── manager.py             # BOPTESTManager: connects to external BOPTEST service
│   └── boptest_client.py      # REST API client for BOPTEST emulator
├── network/
│   ├── challenge_sender.py    # Dendrite: send CalibrationSynapse (timeout=600s)
│   └── result_receiver.py     # ResponseParser: validates and sanitizes miner responses
├── verification/
│   └── engine.py              # VerificationEngine: runs simplified model with miner params
├── weights/
│   └── setter.py              # WeightSetter: SDK process_weights_for_netuid + manual fallback
├── registry/
│   └── manifest.py            # ManifestLoader: load(), validate_manifest()
├── scoring/
│   ├── engine.py              # Composite computation wrapping shared scoring/ module
│   ├── metrics.py             # Local metric wrappers
│   ├── normalization.py       # safe_clamp and component normalization
│   ├── breakdown.py           # Per-miner score breakdown generation
│   └── window_ema.py          # compute_window_ema: pure function over windowed scoring_db rows
└── utils/
    └── logging.py             # Structured logging, ~/.zhen/logs/, 14-day rotation
```

Deleted modules (no longer in codebase): `config.py`, `emulator/data_collector.py`, `verification/simulator_loader.py`, `verification/timeout_handler.py`, `registry/registry_client.py`, `dashboard/`, `utils/hashing.py`, `utils/health.py`, `state.py` (superseded by `scoring_db.py` for score persistence; validator-level round count lives in the `validator_meta` table).

### 2.2 Round Orchestrator

The orchestrator (`validator/round/orchestrator.py`) runs one round per tempo (72 minutes). Constructor takes `manifest_path` and `boptest_url`.

Public methods: `build_verification_config` and `load_test_case_config` (previously named with underscore prefix in early design; renamed to public in the current implementation).

The module-level `validate_config_bounds` function is also public and is called by the verification engine.

High-level flow:
```python
class RoundOrchestrator:
    def __init__(self, manifest_path: str, boptest_url: str): ...

    async def run_round(self):
        # 1. Select test case (deterministic: hashlib.sha256(round_id) mod len(test_cases))
        test_case_id = self.test_case_selector.select(round_id, manifest)

        # 2. Compute train/test split (deterministic: sha256("{round_id}:{test_case_id}") mod offset)
        #    Train: 336h, Test: 168h
        train_start, train_end, test_start, test_end = self.split_generator.compute(
            round_id, test_case_id
        )

        # 3. Collect training and held-out ground truth from external BOPTEST service
        training_data = await boptest_manager.collect(train_start, train_end)
        held_out_data = await boptest_manager.collect(test_start, test_end)

        # 4. Build CalibrationSynapse (simulation_budget default = 1000)
        challenge = CalibrationSynapse(
            test_case_id=test_case_id,
            ...
            simulation_budget=config.get("simulation_budget", 1000),
        )

        # 5. Send challenge (ChallengeSender timeout = 600s), collect responses

        # 6. Verify all submissions (VerificationEngine, TIMEOUT_SECONDS=300)

        # 7. Compute scores (ScoringEngine: floor + power-law + normalize)

        # 8. Update EMA and set weights (WeightSetter)
```

### 2.3 Emulator Manager (BOPTESTManager)

The current implementation is `BOPTESTManager`, which connects to an externally-managed BOPTEST service. It does NOT start or stop Docker containers. The BOPTEST service is assumed to be running and reachable at the configured URL (env `BOPTEST_URL`).

This differs from the original design which described container lifecycle management. The change simplifies the validator: Docker operations are handled externally (e.g., via docker-compose), and the validator only interacts with the BOPTEST HTTP API.

The `boptest_client.py` module provides the REST API wrapper for querying the running BOPTEST service.

### 2.4 Verification Engine

Runs the simplified model with each miner's calibrated parameters.

Key constants:
- `TIMEOUT_SECONDS = 300` (5-minute hard limit per verification)
- `MAX_PARALLEL = 8` (semaphore size; RC runs are synchronous so concurrency is cooperative, not truly parallel)

The engine performs these checks on each miner's submission:
1. Calls `validate_config_bounds` to check that parameters are within the declared bounds. Returns `INVALID_PARAMS` on failure.
2. Anti-default check: if submitted parameters are within 0.1% relative tolerance of defaults, returns `DEFAULT_PARAMS`.
3. If the test case config is not found, the submission is skipped (logged, not scored).
4. Runs `ZhenSimulator` with the miner's parameters for the held-out test period.
5. Clamps `simulations_used` to `[0, simulation_budget]` regardless of the self-reported value.
6. Returns `SIMULATION_NAN` if any simulation output is non-finite.

The `validate_config_bounds` function is a public module-level function in `validator/round/orchestrator.py` and is called from the verification engine.

The `MAX_PARALLEL = 8` semaphore is present but RC network simulations are synchronous Python, so the actual concurrency benefit is limited to I/O overlap in the asyncio event loop, not true parallelism.

### 2.5 Scoring Engine

Implements the composite formula from the Mechanism Design Document (Section 4).

```python
class ScoringEngine:
    WEIGHTS = {"cvrmse": 0.50, "nmbe": 0.25, "r_squared": 0.15, "convergence": 0.10}
    CVRMSE_THRESHOLD = 0.30
    NMBE_THRESHOLD = 0.10
    POWER_EXPONENT: float = 2.0
    SCORE_FLOOR_RATIO: float = 0.05

    def compute(self, verified: Dict[int, VerifiedResult], sim_budget: int = 1000) -> Dict[int, float]:
        # Step 1: compute raw composites (failed miners = 0.0)
        scores: dict[int, float] = {}
        for uid, v in verified.items():
            if v.reason:
                scores[uid] = 0.0
                continue
            composite = self._compute_composite(v, sim_budget)
            scores[uid] = composite

        # Step 2: 5% score floor relative to the top scorer
        if scores:
            max_score = max(scores.values())
            if max_score > 0.0:
                floor = max_score * self.SCORE_FLOOR_RATIO
                scores = {uid: (s if s >= floor else 0.0) for uid, s in scores.items()}

        # Step 3: power-law amplification
        powered = {uid: s ** self.POWER_EXPONENT for uid, s in scores.items()}

        # Step 4: normalize to sum = 1.0
        total = sum(powered.values())
        if total == 0:
            return {}  # Caller copies chain weights as fallback
        return {uid: s / total for uid, s in powered.items()}
```

Note: the original spec described linear normalization (`score / sum`) with a uniform fallback. The implemented pipeline is power-law (p=2) with a 5% floor and empty-dict fallback on all-failure. The chain-weight copy fallback is handled in the validator's weight-setting code, not in the scoring engine itself.

### 2.6 Metric Implementations

Guard conditions applied before each metric is computed per output variable:

- **CVRMSE/NMBE**: skip the output variable if `abs(mean(measured)) < 1e-6` or `mean(measured)` is non-finite. Returns 1.0 if no valid outputs remain (worst-case score).
- **R-squared**: skip if `SS_tot == 0` (flat measured series). Returns 0.0 if no valid outputs remain.

If `_compute_composite` receives any of CVRMSE, NMBE, or R-squared that is non-finite, it returns 0.0 immediately without computing the weighted sum.

```python
def compute_cvrmse(predicted: dict, measured: dict) -> float:
    """CVRMSE averaged across all scoring outputs."""
    cvrmse_values = []
    for key in predicted:
        p = np.array(predicted[key], dtype=np.float64)
        m = np.array(measured[key], dtype=np.float64)
        mean_m = np.mean(m)
        if abs(mean_m) < 1e-6 or not np.isfinite(mean_m):
            continue
        rmse = np.sqrt(np.mean((p - m) ** 2))
        cvrmse_values.append(rmse / mean_m)
    return float(np.mean(cvrmse_values)) if cvrmse_values else 1.0

def compute_nmbe(predicted: dict, measured: dict) -> float:
    """NMBE averaged across all scoring outputs."""
    nmbe_values = []
    for key in predicted:
        p = np.array(predicted[key], dtype=np.float64)
        m = np.array(measured[key], dtype=np.float64)
        n = len(m)
        mean_m = np.mean(m)
        if abs(mean_m) < 1e-6 or n == 0 or not np.isfinite(mean_m):
            continue
        nmbe_values.append(np.sum(p - m) / (n * mean_m))
    return float(np.mean(nmbe_values)) if nmbe_values else 1.0

def compute_r_squared(predicted: dict, measured: dict) -> float:
    """R-squared averaged across all scoring outputs."""
    r2_values = []
    for key in predicted:
        p = np.array(predicted[key], dtype=np.float64)
        m = np.array(measured[key], dtype=np.float64)
        ss_res = np.sum((m - p) ** 2)
        ss_tot = np.sum((m - np.mean(m)) ** 2)
        if ss_tot == 0:
            continue
        r2_values.append(1.0 - (ss_res / ss_tot))
    return float(np.mean(r2_values)) if r2_values else 0.0
```

### 2.7 Weight Setter

`WeightSetter` in `validator/weights/setter.py`.

Key behaviors:
- Attempts `process_weights_for_netuid` from the Bittensor SDK at import time. If unavailable, the manual fallback path (`copy_weights_from_chain`, stake-weighted) is used.
- `version_key` is set to `protocol.WEIGHT_VERSION_KEY` (currently 1000), NOT `protocol.__spec_version__`. These are orthogonal: the weight version is the on-chain Yuma coordination constant; the spec version is internal protocol/scoring versioning. Conflating them (an earlier implementation error) caused the chain to misinterpret extrinsics.
- Uses `asyncio.get_running_loop()` for async compatibility.
- `WEIGHT_TIMEOUT_SECONDS = 120`.
- If the scoring engine returns `{}` (all miners failed), `copy_weights_from_chain` copies the current chain weights unchanged rather than wiping them.

```python
class WeightSetter:
    WEIGHT_TIMEOUT_SECONDS: int = 120

    async def set_weights(self, ema_scores: dict[int, float]) -> None:
        """Set weights on-chain. Uses SDK process_weights_for_netuid with manual fallback."""
        if not ema_scores:
            await self._copy_weights_from_chain()
            return
        uids = list(ema_scores.keys())
        weights = [ema_scores[uid] for uid in uids]
        # version_key = protocol.WEIGHT_VERSION_KEY (= 1000)
        ...
```

### 2.8 Windowed EMA (compute_window_ema)

The retired stateful `EMATracker` class was replaced by a pure function, `compute_window_ema`, in `validator/scoring/window_ema.py`. The function is bit-identical to the old tracker when fed rounds sequentially, but derives state on demand from rows persisted in the SQLite `scoring_db`. This removes the separate JSON state file and makes the EMA auditable: the full input is queryable from the DB.

Alpha = 0.3 (default, matches retired tracker). Miners with EMA below 1e-6 are pruned. Non-finite composites are treated as absent (miner decays that round). If every entry decays to zero, the function returns an empty dict, signaling the caller to copy chain weights rather than publish uniform weights.

```python
def compute_window_ema(
    rows: list[RoundScoreRow],
    alpha: float = 0.3,
) -> dict[int, float]:
    """Return normalized EMA weights from windowed round scores.

    Rows ordered by received_at ASC, grouped by round_id. For each round,
    present miners with finite composite blend into the running EMA;
    absent miners (including non-finite composites) decay by (1 - alpha).
    EMA values below 1e-6 are pruned.

    Returns empty dict if no rows OR every entry decayed to zero.
    """
```

---

## 3. Miner Architecture

The miner is simpler: receive challenge, calibrate locally, return best parameters.

### 3.1 Module Breakdown

```
miner/
├── main.py                    # Entry point, Bittensor neuron lifecycle
├── network/
│   └── axon_handler.py        # Receive CalibrationSynapse from validator; manifest version
│                              #   mismatch logs a warning but processes anyway
├── calibration/
│   ├── __init__.py            # CalibrationOutput dataclass
│   ├── engine.py              # Calibration orchestration and input validation
│   ├── bayesian.py            # BayesianCalibrator (scikit-optimize reference impl)
│   └── objective.py           # CalibrationObjective: PENALTY_VALUE=10.0, sim_count tracking
```

Deleted modules (no longer in codebase): `config.py`, `utils/`, `simulation/`, `network/result_sender.py`, `calibration/evolutionary.py`, `calibration/surrogate.py`.

The miner imports `validator.utils.logging` for logging setup (shared logging infrastructure).

CLI defaults (miner/main.py): `--axon-port 8091`, `--n-calls 100`, `--algorithm bayesian`. Metagraph sync every 600s. Blacklist rejects hotkeys absent from metagraph.

### 3.2 Reference Miner Implementation

The reference miner uses Bayesian optimization (scikit-optimize) wrapping ZhenSimulator. Ships on day one as a functional baseline.

```python
class CalibrationOutput:
    """Simple container for calibration results."""
    def __init__(self, calibrated_params, simulations_used, training_cvrmse, metadata=None):
        self.calibrated_params = calibrated_params
        self.simulations_used = simulations_used
        self.training_cvrmse = training_cvrmse
        self.metadata = metadata

class ReferenceMiner:
    async def handle_challenge(self, challenge: CalibrationSynapse) -> CalibrationOutput:
        # 1. Load local simulator
        simulator = ZhenSimulator(challenge.test_case_id, params={})

        # 2. Define search space from synapse bounds
        dimensions = []
        param_names = challenge.parameter_names
        for name in param_names:
            lo, hi = challenge.parameter_bounds[name]
            dimensions.append(Real(lo, hi, name=name))

        # 3. Define objective: run simulator, compare to training data
        sim_count = 0
        scoring_outputs = list(challenge.training_data.keys())
        def objective(param_values):
            nonlocal sim_count
            params = dict(zip(param_names, param_values))
            sim = ZhenSimulator(challenge.test_case_id, params)
            predictions = sim.run(challenge.train_start_hour, challenge.train_end_hour)
            outputs = predictions.get_outputs(scoring_outputs)
            training = {k: challenge.training_data[k] for k in scoring_outputs}
            cvrmse = compute_cvrmse(outputs, training)
            sim_count += 1
            return cvrmse  # Minimize CVRMSE on training data

        # 4. Run Bayesian optimization
        result = gp_minimize(
            objective,
            dimensions,
            n_calls=min(challenge.simulation_budget, 500),
            n_initial_points=20,
            random_state=42
        )

        # 5. Package result
        best_params = dict(zip(param_names, result.x))
        return CalibrationOutput(
            calibrated_params=best_params,
            simulations_used=sim_count,
            training_cvrmse=result.fun,
            metadata={"algorithm": "bayesian_optimization", "library": "scikit-optimize"}
        )
```

### 3.3 Miner Innovation Surface

The reference miner is intentionally basic. Competitive miners will improve:

- **Multi-algorithm ensemble:** Run Bayesian optimization, CMA-ES, and differential evolution in parallel, submit the best result
- **Surrogate-assisted optimization:** Train a neural network on simulator evaluations, use the surrogate to pre-screen parameter candidates before expensive simulation (GPU advantage: RTX 4080)
- **Domain-informed initialization:** Use building physics heuristics to set intelligent starting points instead of random search
- **Adaptive budget allocation:** Spend more evaluations on sensitive parameters, fewer on insensitive ones (sensitivity analysis pre-pass)
- **Transfer learning:** Reuse calibration knowledge from similar buildings in previous rounds to warm-start optimization
- **Gradient estimation:** Use finite differences to estimate parameter gradients and guide search toward local optima

The mechanism rewards output quality, not tool choice. Any approach that produces lower CVRMSE on the held-out period wins.

---

## 4. Simulation Infrastructure

### 4.1 ZhenSimulator Wrapper

The unified simulation interface (`simulation/zhen_simulator.py`). Currently only the `"rc_network"` backend is supported. `get_outputs()` is fully implemented and stores results from the most recent `run()` call in `_last_result`. Calling `get_outputs()` before `run()` raises `RuntimeError`.

```python
class ZhenSimulator:
    def __init__(self, test_case_id: str, params: dict[str, float]):
        self.test_case_id = test_case_id
        self.config = self._load_config(test_case_id)
        self.backend = self._init_backend(params)
        self._last_result: dict | None = None

    def run(self, start_hour: int, end_hour: int) -> None:
        """Run simulation for the specified period. Stores results internally."""
        self._last_result = self.backend.run(start_hour, end_hour)

    def get_outputs(self, output_names: list[str]) -> dict[str, list[float]]:
        """Return predicted values for specified outputs. Must call run() first."""
        if self._last_result is None:
            raise RuntimeError("Call run() before get_outputs()")
        return {name: self._last_result[name] for name in output_names}
```

Note: the original design showed `get_outputs` raising `NotImplementedError`. It is implemented and working.

### 4.2 RC Network Backend

The grey-box thermal model used for Phase 1 test cases (`simulation/rc_network.py`). Sub-second execution. Forward Euler integration at 1-hour timestep.

Key physics:
- Wall and roof thermal resistances are treated as **parallel** conductances: `Q_envelope = (T_out - T_zone) * (1/R_wall + 1/R_roof)`.
- `self.ach` is an **effective W/K coefficient**, not true ACH. It absorbs building volume into the calibratable parameter. The physical interpretation of "infiltration_ach" in config.json is an effective lumped conductance that the optimizer finds during calibration.
- Thermostat is **heating-only** (Phase 1). Cooling logic is deferred to Phase 2 warm-climate test cases.

Parameters read from `config.json` defaults if not supplied:
- `wall_r_value`, `roof_r_value`, `zone_capacitance`, `infiltration_ach`, `hvac_cop`, `solar_gain_factor`

Outputs: `zone_air_temperature_C` (list of floats), `total_heating_energy_kWh` (list of floats).

### 4.3 BOPTEST Client

REST API client for interacting with the complex emulator (validators only).

```python
class BOPTESTClient:
    def __init__(self, api_url: str):
        self.url = api_url
        self.session = httpx.AsyncClient(timeout=30.0)

    async def initialize(self, start_time: float, warmup_period: float):
        """Initialize simulation to a start time."""
        await self.session.put(
            f"{self.url}/initialize",
            json={"start_time": start_time, "warmup_period": warmup_period}
        )

    async def advance(self, step: float = 3600) -> dict:
        """Advance simulation by one step. Returns measurements."""
        resp = await self.session.post(f"{self.url}/advance", json={})
        return resp.json()["payload"]

    async def get_results(self, point_names: list[str], start: float, end: float) -> dict:
        """Retrieve simulation results for a time period."""
        resp = await self.session.put(
            f"{self.url}/results",
            json={"point_names": point_names, "start_time": start, "final_time": end}
        )
        return resp.json()["payload"]

    async def set_step(self, step: float):
        """Set the communication step in seconds."""
        await self.session.put(f"{self.url}/step", json={"step": step})
```

---

## 5. Model Registry and Distribution

### 5.1 Registry Structure

```
zhen-registry/
├── manifest.json                  # Versioned test case library
├── test_cases/
│   ├── bestest_hydronic/
│   │   ├── emulator/
│   │   │   └── Dockerfile         # Complex BOPTEST emulator
│   │   ├── simplified/
│   │   │   ├── model.py           # RC network or reduced EP model
│   │   │   └── weather.csv        # Pre-installed weather data
│   │   ├── config.json            # Parameters, bounds, scoring outputs
│   │   ├── ZhenSimulator.py       # Unified wrapper implementation
│   │   └── README.md              # Test case documentation
│   ├── multizone_office/
│   │   └── ...
│   └── ...
└── docker-compose.yml             # Local development: all test cases
```

### 5.2 manifest.json

Current manifest version: **v1.2.0** (paired with `protocol.__spec_version__ = 4`). Two test cases are active. Both use `rc_network`, Brussels climate, 6 parameters, difficulty easy. `bestest_air` was in the earlier v1.1.0 rotation but was pulled in v3 (spec bump) because the heating-only RC model produced catastrophic CVRMSE on its FCU cooling behavior. It returns as part of the Phase 1 roadmap work (see ROADMAP.md).

```json
{
  "version": "v1.2.0",
  "test_cases": [
    {
      "id": "bestest_hydronic_heat_pump",
      "simplified_model_type": "rc_network",
      "parameter_count": 6,
      "difficulty": "easy",
      "climate": "Brussels, Belgium",
      "scoring_outputs": ["zone_air_temperature_C", "total_heating_energy_kWh"]
    },
    {
      "id": "bestest_hydronic",
      "simplified_model_type": "rc_network",
      "parameter_count": 6,
      "difficulty": "easy",
      "climate": "Brussels, Belgium",
      "scoring_outputs": ["zone_air_temperature_C", "total_heating_energy_kWh"]
    }
  ]
}
```

`ManifestLoader.load()` raises `ManifestError` on duplicate test case IDs. `validate_manifest()` returns a list of error strings (checks required fields; does not check for duplicates, which are caught at load time).

### 5.3 Distribution Channels

1. **Docker Hub** (primary): `docker pull zhen-registry/{test_case_id}:{tag}`
2. **HTTP download** (fallback): `https://registry.zhen.network/test_cases/{id}/`
3. **IPFS** (decentralized fallback): pinned CIDs in manifest

Miners and validators run `zhen setup` to pull all test cases during initial setup. New test cases added via manifest version bump trigger automatic pull on next round.

**Manifest version mismatch handling:** When a miner receives a CalibrationSynapse, it compares `synapse.manifest_version` against its local manifest. If the versions differ, the miner attempts an automatic update by pulling the latest manifest and any new test case images before proceeding. If the update fails or the required test case is unavailable, the miner returns an empty result (no calibrated_params) and receives a score of 0.0 for that round with reason code MANIFEST_MISMATCH. Validators log manifest mismatches for monitoring.

---

## 6. Bittensor SDK Integration

### 6.1 Neuron Registration

```bash
# Create wallets
btcli wallet create --wallet-name zhen-owner
btcli wallet create --wallet-name zhen-validator --hotkey default
btcli wallet create --wallet-name zhen-miner --hotkey default

# Create subnet (testnet)
btcli subnet create --network test --wallet-name zhen-owner

# Register validator
btcli subnets register --netuid {NETUID} --wallet-name zhen-validator --network test

# Register miner
btcli subnets register --netuid {NETUID} --wallet-name zhen-miner --network test

# Start subnet (activate emissions)
btcli subnet start --netuid {NETUID} --network test
```

### 6.2 Synapse Protocol Definition

Current `protocol.__spec_version__ = 4`. Version history is in `protocol/__init__.py`: v1 linear normalization; v2 power-law (p=2) + 5% score floor; v3 removed bestest_air pending cooling support; v4 expanded `required_hash_fields` to cover training_data, parameter_bounds, simulation_budget, and manifest_version (closes the MITM tamper surface from AUDIT finding 1.6). Each bump invalidates prior EMA state on load.

The on-chain weight version passed to `set_weights` as `version_key` is `protocol.WEIGHT_VERSION_KEY = 1000`, which is orthogonal to `__spec_version__` and must match across all Zhen validators so Yuma aggregation remains coherent.

```python
import bittensor as bt
from typing import Dict, List, Optional

class CalibrationSynapse(bt.Synapse):
    """Single synapse for calibration round.
    Validator fills challenge fields, miner fills result fields (Optional)."""

    # Challenge fields (validator fills)
    test_case_id: str
    manifest_version: str
    training_data: dict
    parameter_names: List[str]
    parameter_bounds: Dict[str, List[float]]
    simulation_budget: int = 1000
    round_id: str
    train_start_hour: int
    train_end_hour: int

    # Result fields (miner fills, Optional)
    calibrated_params: Optional[Dict[str, float]] = None
    simulations_used: Optional[int] = None
    training_cvrmse: Optional[float] = None
    metadata: Optional[Dict] = None

    required_hash_fields: ClassVar[list[str]] = [
        "test_case_id",
        "round_id",
        "train_start_hour",
        "train_end_hour",
        "training_data",
        "parameter_bounds",
        "simulation_budget",
        "manifest_version",
    ]
```

### 6.3 Validator Main Loop

```python
class ZhenValidator(bt.neurons.BaseValidatorNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.orchestrator = RoundOrchestrator(self)
        self.ema = EMATracker(alpha=0.3)

    async def forward(self):
        """Called each tempo. Run one calibration round."""
        await self.orchestrator.run_round()
```

### 6.4 Miner Main Loop

```python
class ZhenMiner(bt.neurons.BaseMinerNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.calibrator = ReferenceMiner(config)

    async def forward(self, synapse: CalibrationSynapse) -> CalibrationSynapse:
        """Handle incoming challenge from validator."""
        result = await self.calibrator.handle_challenge(synapse)

        # Fill mutable result fields
        synapse.calibrated_params = result.calibrated_params
        synapse.simulations_used = result.simulations_used
        synapse.training_cvrmse = result.training_cvrmse
        synapse.metadata = result.metadata

        return synapse
```

---

## 7. Monitoring and Health

The `dashboard/` directory was removed. The planned dashboard is deferred to post-mainnet.

Current monitoring infrastructure:

### 7.1 Health Endpoint

`validator/health.py` runs a `HealthServer` on `127.0.0.1:8080` (loopback only). `GET /health` returns JSON with validator status. This is not a public-facing dashboard; it is intended for local process monitoring and external health checks from the host.

### 7.2 Webhook Alerts

`validator/alerts.py` provides `WebhookAlerter`. Sends HTTP POST to `ZHEN_ALERT_WEBHOOK` on key events (round failures, weight-setting errors). Cooldown: 600 seconds per `event_type` to prevent alert storms.

### 7.3 Local Eval Harness (Planned)

A standalone tool for miners to test their calibration locally before submitting. Not yet implemented. Tracked in IMPLEMENTATION.md Phase 6 deliverables.

---

## 8. Infrastructure Requirements

### 8.1 Validator Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Storage | 50 GB SSD | 200 GB SSD |
| Network | 50 Mbps | 100 Mbps |
| Docker | Required | Required |
| GPU | Not required | Not required |

Validator workload: run one BOPTEST emulator (~2 GB RAM), then verify N submissions using the simplified model (sub-second to 60s each). CPU-bound but lighter than Fuzz validators.

### 8.2 Miner Hardware

| Component | Minimum (Reference Miner) | Competitive |
|-----------|--------------------------|-------------|
| CPU | 4 cores | 8+ cores (Ryzen 7) |
| RAM | 8 GB | 32 GB |
| Storage | 50 GB SSD | 200 GB SSD |
| GPU | Not required | RTX 4080+ (surrogate-assisted optimization) |

Calibration is CPU-bound for simulation execution. GPU provides competitive advantage for building and querying surrogate models between expensive simulation evaluations.

### 8.3 Subnet Owner Infrastructure

| Component | Purpose |
|-----------|---------|
| Build machine | Compile BOPTEST emulators, build simplified models |
| Model registry | Host Docker images and test case files |
| crustty instance | Test case curation + health monitoring agent |
| Domain + web | Dashboard, docs, llms.txt, registry.zhen.network |

---

## 9. Development Environment

### 9.1 Local Development Stack

```
Prerequisites:
- Python 3.10+
- Docker Desktop (or Docker Engine on Linux)
- Bittensor SDK (pip install bittensor)
- scipy, scikit-optimize (for reference miner)
- numpy (for metric computations)

Local testing (no chain):
1. Pull a test case: docker pull zhen-registry/bestest_hydronic:simplified-v1.0.0
2. Run validator in local mode (no chain interaction)
3. Run miner against local validator
4. Verify scoring output matches expected
```

### 9.2 Testnet Deployment

```
1. Accumulate testnet TAO (taoswap.org/testnet-faucet, 50 TAO per coldkey, ~275-300 total needed)
2. Create subnet on testnet
3. Register owner validator + reference miner
4. Deploy BOPTEST test cases (minimum 3)
5. Run validator + miner, verify scoring loop
6. Invite external testnet miners
7. Calibrate scoring weights from live data
```

---

## 10. Project Directory Structure

```
zhen/
├── CLAUDE.md                   # Orchestration doc (routing table)
├── README.md                   # Project overview
├── docs/
│   ├── MECHANISM.md            # Mechanism Design Document
│   ├── ARCHITECTURE.md         # This document
│   ├── IMPLEMENTATION.md       # Phased Implementation Plan
│   ├── MINE.md                 # Miner setup guide
│   ├── VALIDATE.md             # Validator setup guide
│   ├── SCORING.md              # Full scoring formula + examples
│   ├── CALIBRATE.md            # Building energy calibration tutorial
│   ├── RULES.md                # Explicit constraints
│   └── CHANGELOG.md            # Versioned changes
├── validator/                  # Validator codebase (Section 2)
├── miner/                      # Miner codebase (Section 3)
├── protocol/                   # Shared synapse definitions
├── scoring/                    # Shared scoring logic (used by validator + eval harness)
├── simulation/
│   ├── zhen_simulator.py       # Unified ZhenSimulator interface
│   ├── rc_network.py           # RC network backend
│   └── reduced_energyplus.py   # Reduced EnergyPlus backend
├── registry/
│   ├── manifest.json           # Test case library
│   └── test_cases/             # Test case files for development
├── eval/                       # Local eval harness tool
├── dashboard/                  # Dashboard frontend
├── agents/                     # Claude Code agent definitions
│   └── AGENTS.md               # Agent role definitions
├── .claude/skills/             # Project-specific Claude Code skills
├── tests/
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests (validator + miner loop)
│   └── adversarial/            # Scoring edge case tests
├── docker-compose.yml          # Local dev: validator + miner + emulators
├── llms.txt                    # Agent-discoverable subnet description
└── pyproject.toml              # Python project config (uv)
```

---

## 11. Agent and Tooling Integration

### 11.1 CLAUDE.md Structure

```markdown
# Zhen Subnet - CLAUDE.md

## Routing Table
- Mechanism design: docs/MECHANISM.md
- Architecture: docs/ARCHITECTURE.md
- Implementation plan: docs/IMPLEMENTATION.md
- Scoring logic: scoring/
- Validator code: validator/
- Miner code: miner/
- Simulation backends: simulation/
- Test case registry: registry/
- Tests: tests/
- Agent definitions: agents/AGENTS.md

## Rules
- No em dashes or en dashes anywhere in the codebase
- No generic AI commenting in code
- Conventional commits for all changes
- Quality over speed
- All scoring math must use float64
- hashlib.sha256 for ALL deterministic hashing (never Python hash())
```

### 11.2 Agent Definitions

```
Agents:
- validator-agent: Owns validator/ directory. Emulator management, verification, scoring.
- miner-agent: Owns miner/ directory. Reference miner, calibration algorithms.
- protocol-agent: Owns protocol/ + scoring/. Shared definitions.
- simulation-agent: Owns simulation/. ZhenSimulator, RC network, reduced EP backends.
- infra-agent: Owns registry/, docker-compose. Test case build + deploy.
- docs-agent: Owns docs/. Keeps documentation current and clean.
```

### 11.3 Claude Code Commands

```
/zhen-score-test    Run adversarial scoring edge case tests
/zhen-sim-test      Test simplified model against known calibration
/zhen-lint          Project-specific linting (no em dashes, no AI slop)
/zhen-build-case    Build a new test case (emulator + simplified model)
```

---

## 12. Testing Strategy

### 12.1 Unit Tests

- Scoring engine: every component, every edge case (zero submissions, all infeasible, single miner, all tied, inf/NaN inputs)
- Metric implementations: CVRMSE, NMBE, R-squared with known inputs and expected outputs
- ZhenSimulator: determinism verification (same params = same outputs across runs)
- RC network: physics sanity checks (heating increases temperature, insulation reduces heat loss)
- Normalization: safe_clamp with all edge case inputs (negative, >1, NaN, Inf)
- Hashing: hashlib.sha256 produces identical results across platforms

### 12.2 Integration Tests

- Full round loop: validator runs emulator, sends challenge, miner calibrates, validator verifies, scores computed
- Multi-miner rounds: 3+ miners with varying performance, verify score differentiation
- Cross-validator consistency: two validators independently produce identical scores for same miner
- Manifest versioning: validator and miner with different manifest versions, verify rejection
- Emulator determinism: same test case produces identical measurements across runs

### 12.3 Adversarial Tests

- Out-of-bounds parameters: submit values outside parameter_bounds. Verify rejection.
- Hanging simulation: submit parameters that cause extremely slow convergence. Verify timeout.
- All-zero parameters: submit all parameters as 0.0. Verify low score, not crash.
- Empty submission: submit no parameters. Verify rejection with reason code.
- NaN injection: submit NaN as a parameter value. Verify rejection.
- Identical submissions: two miners submit identical parameters. Verify identical scores.
- Budget gaming: report simulations_used = 1 with good accuracy. Verify convergence score is high but accuracy carries 90% weight.

---

*This document is the technical blueprint for implementing Zhen. All design decisions trace back to the Mechanism Design Document. Implementation details will be refined during development and captured in the Phased Implementation Plan.*
