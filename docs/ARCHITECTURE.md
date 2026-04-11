# Zhen: Technical Architecture Document

<!-- FORMATTING RULE: This document must NEVER contain em dashes or en dashes. Use commas, periods, colons, or parentheses instead. -->

**Version:** 1.0.0-draft
**Status:** Pre-development
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
        │  │  Dashboard Server        │   │
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
├── config.py                  # Hyperparameters, paths, feature flags
├── round/
│   ├── orchestrator.py        # Round lifecycle management
│   ├── test_case_selector.py  # Deterministic test case selection (hashlib)
│   └── split_generator.py     # Deterministic train/test split computation
├── emulator/
│   ├── manager.py             # BOPTEST Docker container lifecycle
│   ├── data_collector.py      # Collect training + held-out measurements
│   └── boptest_client.py      # REST API client for BOPTEST emulator
├── network/
│   ├── challenge_sender.py    # Dendrite: send CalibrationSynapse
│   └── result_receiver.py     # Axon: receive CalibrationSynapse
├── verification/
│   ├── engine.py              # Run simplified model with miner params
│   ├── simulator_loader.py    # Load ZhenSimulator for verification
│   └── timeout_handler.py     # Hard timeout enforcement (5 min)
├── scoring/
│   ├── engine.py              # Composite score computation
│   ├── metrics.py             # CVRMSE, NMBE, R-squared implementations
│   ├── normalization.py       # Safe normalization, numeric hardening
│   ├── ema.py                 # Exponential moving average
│   └── breakdown.py           # Generate per-miner JSON score breakdown
├── weights/
│   └── setter.py              # Bittensor set_weights integration
├── registry/
│   ├── manifest.py            # Test case manifest management
│   └── registry_client.py     # Pull test case Docker images
├── dashboard/
│   ├── server.py              # HTTP dashboard serving
│   └── api.py                 # Programmatic score query endpoint
└── utils/
    ├── hashing.py             # hashlib.sha256 wrappers for determinism
    ├── logging.py             # Structured logging
    └── health.py              # Self-monitoring, alerting hooks
```

### 2.2 Round Orchestrator

The orchestrator runs one round per tempo (72 minutes).

```python
class RoundOrchestrator:
    async def run_round(self):
        # 1. Select test case (deterministic from round_id)
        test_case = self.test_case_selector.select(
            round_id=self.round_id,
            manifest=self.manifest
        )

        # 2. Compute train/test split (deterministic from round_id + test_case_id)
        train_period, test_period = self.split_generator.compute(
            round_id=self.round_id,
            test_case_id=test_case.id
        )

        # 3. Run complex emulator for full period (training + held-out)
        emulator = await self.emulator_manager.start(test_case.id)
        training_data = await self.data_collector.collect(emulator, train_period)
        held_out_data = await self.data_collector.collect(emulator, test_period)
        await self.emulator_manager.stop(emulator)

        # 4. Build CalibrationSynapse
        miners = self.metagraph.get_active_miners()
        challenge = CalibrationSynapse(
            test_case_id=test_case.id,
            manifest_version=self.manifest.version,
            training_data=training_data,
            parameter_names=test_case.config["parameter_names"],
            parameter_bounds=test_case.config["parameter_bounds"],
            simulation_budget=test_case.config.get("simulation_budget", 1000),
            round_id=self.round_id,
            train_start_hour=train_period.start,
            train_end_hour=train_period.end
        )

        # 5. Send challenge, wait for results
        results = await self.challenge_sender.send_and_collect(
            miners, challenge, timeout=self.tempo_seconds - 300  # 5 min buffer
        )

        # 6. Verify all submissions
        verified = await self.verification_engine.verify_all(
            results, test_case, test_period, held_out_data
        )

        # 7. Compute scores
        scores = self.scoring_engine.compute(
            verified, sim_budget=challenge.simulation_budget
        )

        # 8. Generate breakdowns (private to each miner)
        for miner_uid, score_data in scores.items():
            breakdown = self.breakdown.generate(miner_uid, score_data)
            self.dashboard.publish_breakdown(miner_uid, breakdown)

        # 9. Update EMA and set weights
        self.ema.update(scores)
        await self.weight_setter.set_weights(self.ema.get_weights())
```

### 2.3 Emulator Manager

Manages BOPTEST Docker containers for ground truth generation.

```python
class EmulatorManager:
    async def start(self, test_case_id: str) -> EmulatorInstance:
        """Start a BOPTEST emulator container for the given test case."""
        container = await docker.containers.run(
            image=f"zhen-registry/{test_case_id}:emulator",
            detach=True,
            ports={"5000/tcp": None},  # Dynamic port assignment
            mem_limit="2g",
            cpu_quota=200000,  # 2 CPU cores
        )
        port = container.ports["5000/tcp"][0]["HostPort"]
        return EmulatorInstance(container=container, api_url=f"http://localhost:{port}")

    async def stop(self, instance: EmulatorInstance):
        """Stop and remove emulator container."""
        await instance.container.stop()
        await instance.container.remove()
```

### 2.4 Verification Engine

Runs the simplified model with each miner's calibrated parameters.

```python
class VerificationEngine:
    TIMEOUT_SECONDS = 300  # 5 minutes hard limit
    MAX_PARALLEL = 8       # Concurrent verifications

    async def verify_all(
        self,
        results: Dict[int, CalibrationSynapse],
        test_case: TestCase,
        test_period: TimePeriod,
        held_out_data: dict
    ) -> Dict[int, VerifiedResult]:
        semaphore = asyncio.Semaphore(self.MAX_PARALLEL)

        async def bounded_verify(miner_uid, result):
            async with semaphore:
                try:
                    v = await asyncio.wait_for(
                        self._verify_single(result, test_case, test_period, held_out_data),
                        timeout=self.TIMEOUT_SECONDS
                    )
                    return miner_uid, v
                except asyncio.TimeoutError:
                    return miner_uid, VerifiedResult(
                        score=0.0,
                        reason="SIMULATION_TIMEOUT",
                        detail=f"Verification exceeded {self.TIMEOUT_SECONDS}s"
                    )
                except Exception as e:
                    return miner_uid, VerifiedResult(
                        score=0.0,
                        reason="SIMULATION_CRASHED",
                        detail=str(e)
                    )

        tasks = [bounded_verify(uid, r) for uid, r in results.items()]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        verified = {}
        for item in completed:
            if isinstance(item, Exception):
                continue  # Log and skip
            uid, result = item
            verified[uid] = result

        return verified

    async def _verify_single(
        self, result, test_case, test_period, held_out_data
    ) -> VerifiedResult:
        # Validate parameters are within bounds
        for param, value in result.calibrated_params.items():
            bounds = test_case.config["parameter_bounds"][param]
            if not (bounds[0] <= value <= bounds[1]):
                return VerifiedResult(
                    score=0.0,
                    reason="INVALID_PARAMS",
                    detail=f"{param}={value} outside bounds [{bounds[0]}, {bounds[1]}]"
                )

        # Run simplified model with miner's parameters
        simulator = ZhenSimulator(test_case.id, result.calibrated_params)
        predictions = simulator.run(test_period.start, test_period.end)

        # Extract scoring outputs
        scoring_outputs = test_case.config["scoring_outputs"]
        predicted_values = predictions.get_outputs(scoring_outputs)
        measured_values = {k: held_out_data[k] for k in scoring_outputs}

        # Compute metrics
        cvrmse = compute_cvrmse(predicted_values, measured_values)
        nmbe = compute_nmbe(predicted_values, measured_values)
        r_squared = compute_r_squared(predicted_values, measured_values)

        return VerifiedResult(
            cvrmse=cvrmse,
            nmbe=nmbe,
            r_squared=r_squared,
            simulations_used=result.simulations_used,
            calibrated_params=result.calibrated_params
        )
```

### 2.5 Scoring Engine

Implements the composite formula from the Mechanism Design Document (Section 4).

```python
class ScoringEngine:
    WEIGHTS = {"cvrmse": 0.50, "nmbe": 0.25, "r_squared": 0.15, "convergence": 0.10}
    CVRMSE_THRESHOLD = 0.30
    NMBE_THRESHOLD = 0.10

    def compute(self, verified: Dict[int, VerifiedResult], sim_budget: int = 1000) -> Dict[int, float]:
        scores = {}

        for uid, v in verified.items():
            if v.reason:  # Failed verification
                scores[uid] = 0.0
                continue

            cvrmse_norm = safe_clamp(1.0 - (v.cvrmse / self.CVRMSE_THRESHOLD))
            nmbe_norm = safe_clamp(1.0 - (abs(v.nmbe) / self.NMBE_THRESHOLD))
            r2_norm = safe_clamp(v.r_squared)
            conv_norm = safe_clamp(1.0 - (v.simulations_used / sim_budget))

            composite = (
                self.WEIGHTS["cvrmse"] * cvrmse_norm +
                self.WEIGHTS["nmbe"] * nmbe_norm +
                self.WEIGHTS["r_squared"] * r2_norm +
                self.WEIGHTS["convergence"] * conv_norm
            )
            scores[uid] = composite

        # Normalize to weight vector
        total = sum(scores.values())
        if total > 0:
            return {uid: s / total for uid, s in scores.items()}
        else:
            n = len(scores)
            return {uid: 1.0 / n for uid in scores} if n > 0 else {}


def safe_clamp(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))
```

### 2.6 Metric Implementations

```python
def compute_cvrmse(predicted: dict, measured: dict) -> float:
    """CVRMSE averaged across all scoring outputs."""
    cvrmse_values = []
    for key in predicted:
        p = np.array(predicted[key], dtype=np.float64)
        m = np.array(measured[key], dtype=np.float64)
        mean_m = np.mean(m)
        if mean_m == 0 or not np.isfinite(mean_m):
            continue
        rmse = np.sqrt(np.mean((p - m) ** 2))
        cvrmse_values.append(rmse / mean_m)
    return np.mean(cvrmse_values) if cvrmse_values else 1.0

def compute_nmbe(predicted: dict, measured: dict) -> float:
    """NMBE averaged across all scoring outputs."""
    nmbe_values = []
    for key in predicted:
        p = np.array(predicted[key], dtype=np.float64)
        m = np.array(measured[key], dtype=np.float64)
        n = len(m)
        mean_m = np.mean(m)
        if mean_m == 0 or n == 0 or not np.isfinite(mean_m):
            continue
        nmbe_values.append(np.sum(p - m) / (n * mean_m))
    return np.mean(nmbe_values) if nmbe_values else 1.0

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
    return np.mean(r2_values) if r2_values else 0.0
```

### 2.7 Weight Setter

```python
class WeightSetter:
    async def set_weights(self, ema_scores: Dict[int, float]):
        """Set weights on-chain via Bittensor SDK."""
        uids = list(ema_scores.keys())
        weights = [ema_scores[uid] for uid in uids]

        self.subtensor.set_weights(
            wallet=self.wallet,
            netuid=self.netuid,
            uids=uids,
            weights=weights,
            wait_for_inclusion=True
        )
```

### 2.8 EMA Tracker

```python
class EMATracker:
    """Exponential Moving Average across rounds per miner."""

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self.scores: Dict[int, float] = {}

    def update(self, round_scores: Dict[int, float]):
        """Blend current round scores into EMA history."""
        for uid, score in round_scores.items():
            if uid in self.scores:
                self.scores[uid] = self.alpha * score + (1 - self.alpha) * self.scores[uid]
            else:
                self.scores[uid] = score  # First round: no history to blend

    def get_weights(self) -> Dict[int, float]:
        """Return normalized EMA scores for weight setting."""
        total = sum(self.scores.values())
        if total > 0:
            return {uid: s / total for uid, s in self.scores.items()}
        n = len(self.scores)
        return {uid: 1.0 / n for uid in self.scores} if n > 0 else {}
```

---

## 3. Miner Architecture

The miner is simpler: receive challenge, calibrate locally, return best parameters.

### 3.1 Module Breakdown

```
miner/
├── main.py                    # Entry point, Bittensor neuron lifecycle
├── config.py                  # Algorithm selection, resource limits
├── network/
│   ├── axon_handler.py        # Receive CalibrationSynapse from validator
│   └── result_sender.py       # Return CalibrationSynapse
├── calibration/
│   ├── engine.py              # Calibration orchestration
│   ├── bayesian.py            # Bayesian optimization (reference implementation)
│   ├── evolutionary.py        # CMA-ES / genetic algorithms (optional)
│   ├── surrogate.py           # Surrogate-assisted optimization (optional, GPU)
│   └── objective.py           # Objective function: run simulator, compute error
├── simulation/
│   ├── simulator_cache.py     # Local test case cache management
│   └── simulator_runner.py    # ZhenSimulator wrapper for local execution
└── utils/
    └── logging.py
```

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

The unified simulation interface that abstracts BOPTEST and Energym backends.

```python
class ZhenSimulator:
    def __init__(self, test_case_id: str, params: dict[str, float]):
        self.test_case_id = test_case_id
        self.config = self._load_config(test_case_id)
        self.backend = self._init_backend(params)

    def _load_config(self, test_case_id: str) -> dict:
        """Load config.json from local test case directory."""
        config_path = Path.home() / ".zhen" / "test_cases" / test_case_id / "config.json"
        return json.loads(config_path.read_text())

    def _init_backend(self, params: dict):
        """Initialize the appropriate simulation backend."""
        model_type = self.config["simplified_model_type"]
        if model_type == "rc_network":
            return RCNetworkBackend(self.config, params)
        elif model_type == "reduced_energyplus":
            return ReducedEnergyPlusBackend(self.config, params)
        else:
            raise ValueError(f"Unknown model type: {model_type}")

    def run(self, start_hour: int, end_hour: int) -> SimulationResult:
        """Run simulation for the specified period."""
        return self.backend.run(start_hour, end_hour)

    def get_outputs(self, output_names: list[str]) -> dict[str, list[float]]:
        """Return predicted values for specified scoring outputs."""
        return self.backend.get_outputs(output_names)
```

### 4.2 RC Network Backend

The grey-box thermal model used for Phase 1 test cases. Sub-second execution.

```python
class RCNetworkBackend:
    """Resistance-Capacitance thermal network model.

    Models building as a circuit of thermal resistors (walls, windows, infiltration)
    and capacitors (zone thermal mass). Solves the ODE system using scipy.integrate.
    """

    def __init__(self, config: dict, params: dict):
        self.dt = 3600  # 1-hour timestep
        self.weather = self._load_weather(config)
        self.schedules = self._load_schedules(config)

        # Calibratable parameters from miner
        self.R_wall = params.get("wall_r_value", config["defaults"]["wall_r_value"])
        self.R_roof = params.get("roof_r_value", config["defaults"]["roof_r_value"])
        self.C_zone = params.get("zone_capacitance", config["defaults"]["zone_capacitance"])
        self.ach = params.get("infiltration_ach", config["defaults"]["infiltration_ach"])
        self.cop = params.get("hvac_cop", config["defaults"]["hvac_cop"])
        self.solar_gain = params.get("solar_gain_factor", config["defaults"]["solar_gain_factor"])

    def run(self, start_hour: int, end_hour: int) -> SimulationResult:
        """Solve thermal ODE for the specified period.
        
        Note: Phase 1 limitation: heating-only thermostat. Cooling logic will be
        added for warm-climate test cases in Phase 2.
        """
        n_steps = end_hour - start_hour
        T_zone = np.zeros(n_steps)
        Q_heating = np.zeros(n_steps)
        T_zone[0] = self.weather["temperature"][start_hour]  # Initialize from outdoor temp

        for i in range(1, n_steps):
            hour = start_hour + i
            T_out = self.weather["temperature"][hour]
            Q_solar = self.weather["solar_radiation"][hour] * self.solar_gain
            Q_internal = self.schedules["internal_gains"][hour]
            # Infiltration heat exchange
            # Note: self.ach here is an effective infiltration coefficient (W/K), not true ACH.
            # It absorbs building volume into the calibratable parameter for simplicity.
            # The optimizer will find the correct effective value during calibration.
            Q_infiltration = 1200 * self.ach * (T_out - T_zone[i-1]) / 3600

            # Heat flow through envelope (walls and roof in PARALLEL)
            Q_envelope = (T_out - T_zone[i-1]) * (1.0/self.R_wall + 1.0/self.R_roof)
            Q_total = Q_envelope + Q_solar + Q_internal + Q_infiltration

            # Simple thermostat logic
            T_setpoint = self.schedules["heating_setpoint"][hour]
            if T_zone[i-1] < T_setpoint:
                Q_hvac = (T_setpoint - T_zone[i-1]) * self.C_zone / self.dt
                Q_heating[i] = Q_hvac / self.cop
            else:
                Q_hvac = 0

            dT = (Q_total + Q_hvac) * self.dt / self.C_zone
            T_zone[i] = T_zone[i-1] + dT

        return SimulationResult(
            outputs={
                "zone_air_temperature_C": T_zone.tolist(),
                "total_heating_energy_kWh": Q_heating.tolist()
            }
        )
```

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

```json
{
  "version": "v1.0.0",
  "test_cases": [
    {
      "id": "bestest_hydronic_heat_pump",
      "simplified_model_type": "rc_network",
      "parameter_count": 6,
      "difficulty": "easy",
      "climate": "Brussels, Belgium",
      "building_type": "residential_single_zone",
      "hvac_type": "hydronic_heat_pump",
      "emulator_image": "zhen-registry/bestest_hydronic:emulator-v1.0.0",
      "simplified_image": "zhen-registry/bestest_hydronic:simplified-v1.0.0",
      "simulation_time_approx_seconds": 0.5,
      "scoring_outputs": ["zone_air_temperature_C", "total_heating_energy_kWh"]
    }
  ],
  "energyplus_version": "24.1.0",
  "modelica_version": "4.0.0"
}
```

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
    simulation_budget: int
    round_id: str
    train_start_hour: int
    train_end_hour: int

    # Result fields (miner fills, Optional)
    calibrated_params: Optional[Dict[str, float]] = None
    simulations_used: Optional[int] = None
    training_cvrmse: Optional[float] = None
    metadata: Optional[Dict] = None
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

## 7. Dashboard and Monitoring

### 7.1 Public Dashboard

Serves at `http://validator:8080/dashboard`. Shows:

- Current round status (test case, time remaining)
- Leaderboard (per-miner EMA scores, rank history)
- Per-round score breakdowns (composite scores and metric components, NO calibrated parameters)
- Test case library (all test cases, difficulty, usage history)
- Network stats (active miners, best CVRMSE achieved, accuracy trends)

### 7.2 Programmatic API

```
GET /api/v1/scores/{round_id}           # All miner scores for a round
GET /api/v1/scores/{round_id}/{uid}     # Single miner breakdown (private params only to owner)
GET /api/v1/leaderboard                 # Current EMA rankings
GET /api/v1/test_cases                  # Test case library
GET /api/v1/test_cases/{id}             # Test case details
GET /api/v1/health                      # Validator health status
GET /api/v1/manifest                    # Current manifest version
```

### 7.3 Local Eval Harness

Shipped as a standalone tool miners run locally. Requires Docker to run the BOPTEST emulator for ground truth generation.

```bash
# Miner runs locally to test their calibration before submitting
# This starts a local emulator container, generates ground truth, then scores
zhen-eval --test-case bestest_hydronic_heat_pump \
          --params '{"wall_r_value": 3.42, "infiltration_ach": 0.35}' \
          --train-start 0 \
          --train-end 336 \
          --test-start 336 \
          --test-end 504
```

The harness automatically starts a local BOPTEST emulator container, generates ground truth measurements for the test period, runs the simplified model with the provided parameters, and outputs the identical JSON score breakdown a validator would produce. Miners should use this to verify their calibration before submitting to avoid wasting rounds on poor parameter sets.

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
