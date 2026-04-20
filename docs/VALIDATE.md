# Validating on Zhen

## What validators do

Validators are the backbone of the Zhen subnet. They generate calibration challenges from building energy simulations, send them to miners, verify the returned parameters on held-out test data, score results using ASHRAE-standard metrics, and set weights on-chain. Validators ensure that only miners producing genuinely accurate calibrations earn emissions.

## Requirements

### Hardware

- CPU: 8+ cores recommended (runs RC network verification for each miner)
- RAM: 16GB minimum (BOPTEST Docker containers + verification workload)
- Disk: 10GB free (Docker images, test case data, logs)
- GPU: Not required

### Software

- Linux (Ubuntu 22.04+ recommended) or WSL2 on Windows
- Python 3.10+
- Docker Desktop or Docker Engine (for BOPTEST emulators in full mode)
- Bittensor SDK and CLI

### Network

- Outbound internet access (connects to Bittensor chain and queries miners)
- No inbound ports required (validators initiate all connections to miners via dendrite)

### Stake

- Validators must have sufficient stake to participate in Yuma Consensus
- Insufficient stake means your weights may not influence emission distribution
- Check the minimum stake requirement:

```bash
btcli subnets hyperparameters --netuid 456 --network test
```

## Quickstart

### 1. Install

```bash
git clone https://github.com/vanlabs-dev/zhen-subnet.git
cd zhen-subnet
uv sync --all-groups
```

Note: The repo is currently private during testnet. Contact the team for access.

### 2. Install Docker

BOPTEST emulators run as Docker containers. Install Docker Engine or Docker Desktop for your platform.

Verify:

```bash
docker --version
```

Docker is only required for full BOPTEST mode. Local mode (the current default) does not need Docker.

### 3. Create wallet

```bash
btcli wallet create --wallet-name zhen-validator --wallet-hotkey default
```

Save your mnemonic securely.

### 4. Get testnet TAO

Request testnet TAO in the Bittensor Discord `#testnet-faucet` channel. You need approximately 2 TAO for registration plus additional TAO for staking.

### 5. Register on subnet

```bash
btcli subnet register --netuid 456 --network test --wallet-name zhen-validator --wallet-hotkey default
```

### 6. Set up test cases

Validators need local copies of test case data:

```bash
for tc in bestest_air; do
  mkdir -p ~/.zhen/test_cases/$tc
  cp registry/test_cases/$tc/*.json ~/.zhen/test_cases/$tc/
done
```

The test case directory contains three files: `config.json`, `schedules.json`, and `weather.json`.

**Important:** `registry/test_cases/<id>/` is the source of truth in the repo. `~/.zhen/test_cases/<id>/` is where the validator reads at runtime. Re-run this copy step after any config change or repo update. Forgetting to re-sync is a common footgun; the validator will run silently against stale config with no obvious error. Automated sync is on the Phase 2 backlog.

### 7. Start validating

#### Local mode (default, no Docker required)

The validator uses the RC network model as its own ground truth source. This skips BOPTEST but still runs the full scoring and weight-setting loop:

```bash
python -m validator.main --netuid 456 --network test
```

Local mode is the default (`--local-mode` is enabled by default). This is the recommended mode for testnet.

Note: In local mode, ground truth is generated using the RC model with default parameters. This is a testnet convenience. For production, use BOPTEST mode (`--no-local-mode`) which generates ground truth from the complex EnergyPlus emulator.

#### Full mode (BOPTEST ground truth)

For production validation with BOPTEST emulators providing ground truth. BOPTEST must be running via docker-compose from the project1-boptest repository. The validator includes automatic health checking and pre-warming of test cases.

```bash
python -m validator.main --netuid 456 --network test --no-local-mode --boptest-url http://localhost:8000
```

## CLI Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--netuid` | int | 456 | Subnet UID |
| `--network` | str | `test` | Network: `test`, `finney`, or a `ws://` URL |
| `--wallet-name` | str | `zhen-validator` | Wallet name |
| `--wallet-hotkey` | str | `default` | Wallet hotkey |
| `--local-mode` | flag | `True` | Use RC network model as ground truth instead of BOPTEST |
| `--no-local-mode` | flag | | Use BOPTEST emulator for ground truth generation |
| `--boptest-url` | str | `http://localhost:8000` | BOPTEST service URL (only used with `--no-local-mode`) |
| `--health-port` | int | 8080 | HTTP health check port |
| `--log-level` | str | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |

### Environment variables

| Variable | Description |
|---|---|
| `ZHEN_NETUID` | Override default netuid |
| `ZHEN_NETWORK` | Override default network |

### Constants

Bittensor defines a tempo as 360 blocks (approximately 4320 seconds at 12-second block time). The Zhen validator does not sleep a full tempo between rounds; it runs its own challenge loop at a configurable interval and relies on the chain's `weights_rate_limit` hyperparameter to gate weight commits.

| Name | Location | Value | Description |
|---|---|---|---|
| `BLOCK_TIME_SECONDS` | `validator/main.py` | 12 | Seconds per Bittensor block |
| `DEFAULT_CHALLENGE_INTERVAL_SECONDS` | `validator/main.py` | 900 | Default seconds between challenge rounds (15 min) |
| `DEFAULT_WEIGHT_CHECK_INTERVAL_SECONDS` | `validator/main.py` | 60 | Polling cadence for block-gated weight commits |
| `DEFAULT_CLEANUP_INTERVAL_SECONDS` | `validator/main.py` | 86400 | Seconds between scoring DB cleanup runs (24h) |
| `DEFAULT_CLEANUP_RETENTION_HOURS` | `validator/main.py` | 168 | Hours of history the scoring DB retains (7 days) |
| `CHALLENGE_TIMEOUT_SECONDS` | `validator/main.py` | 600 | Max seconds miners have to respond to a challenge |
| `CHAIN_READ_TIMEOUT_SECONDS` | `validator/main.py` | 30 | Timeout for read-only chain RPCs |
| `METAGRAPH_SYNC_TIMEOUT_SECONDS` | `validator/main.py` | 60 | Timeout for `metagraph.sync()` calls |
| `WEIGHT_COMMIT_WATCHDOG_SECONDS` | `validator/main.py` | 180 | Watchdog threshold for hung weight commits |
| `WEIGHT_TIMEOUT_SECONDS` | `WeightSetter` | 120 | Max seconds for chain weight submission |
| `TIMEOUT_SECONDS` | `VerificationEngine` | 300 | Max seconds per miner verification run |
| `MAX_PARALLEL` | `VerificationEngine` | 8 | Verification concurrency semaphore size |

## How a Validation Round Works

1. **Sync metagraph**: Validator refreshes the list of registered neurons on the subnet.
2. **Select test case**: A test case is chosen deterministically based on the round number and available registry entries.
3. **Generate data split**: Training and test periods are computed using deterministic hashing (`hashlib.sha256`). The split is unpredictable to miners but reproducible by any validator.
4. **Generate ground truth**: The complex emulator (BOPTEST in full mode, or RC model in local mode) runs the test case to produce reference time-series data for both training and test periods.
5. **Build synapse**: A `CalibrationSynapse` is constructed with the test case ID, training data, parameter names and bounds, simulation budget, and round metadata.
6. **Send to miners**: The synapse is sent to all registered miners via Bittensor dendrite. Miners have 600 seconds (CHALLENGE_TIMEOUT_SECONDS) to respond.
7. **Parse responses**: Valid responses are extracted from returned synapses. Miners that returned `calibrated_params` are included.
8. **Verify**: The validator re-runs the RC model with each miner's calibrated parameters on the held-out test data and computes CVRMSE, NMBE, and R-squared.
9. **Score**: Composite scores are computed using the weighted formula (see [SCORING.md](SCORING.md)).
10. **Update EMA**: Scores are blended into the per-miner exponential moving average (alpha=0.3).
11. **Set weights**: Normalized EMA scores are submitted on-chain via the weight setter.
12. **Sleep**: Validator waits `challenge_interval_seconds` between rounds (default 900 seconds / 15 minutes, configurable via `--challenge-interval-seconds`). Weight commits run on a separate loop that polls block-rate-limit eligibility every `weight_check_interval_seconds` (default 60 seconds) and commits when the chain allows.

## BOPTEST Setup

BOPTEST is the Building Optimization Performance Test framework. It provides containerized building energy simulation environments.

### Architecture

The validator communicates with BOPTEST via the `BOPTESTClient` REST API (`validator/emulator/boptest_client.py`). BOPTEST v0.8+ uses a service architecture where test cases are selected via `POST /testcases/{id}/select` to obtain a running test ID.

### Starting BOPTEST locally

BOPTEST runs as a Docker service on port 8000 (default). For detailed setup instructions, see: https://github.com/ibpsa/project1-boptest

### Supported test cases

Currently active (manifest v2.0.0, 1 test case):

- `bestest_air`: BESTEST building with four-pipe fan coil unit (Denver, CO, USA climate). 7 calibratable parameters. 3 scoring outputs: zone_air_temperature_C, total_heating_thermal_kWh, total_cooling_energy_kWh.

Retained on disk but not in the active manifest: `bestest_hydronic_heat_pump`, `bestest_hydronic`. These directories are kept for integration test fixtures only. Phase 2 will add multi-zone commercial test cases.

## Scoring Reference

Validators apply the following scoring (see [SCORING.md](SCORING.md) for full details):

| Metric | Weight | What it measures |
|---|---|---|
| CVRMSE | 50% | Prediction accuracy against held-out test data |
| NMBE | 25% | Absence of systematic prediction bias |
| R-squared | 15% | Overall model fit quality |
| Convergence | 10% | Efficiency of parameter search |

All scoring is deterministic. Two validators running the same code against the same miner responses will produce identical scores.

## Monitoring

Key log messages from the validator:

| Log message | Meaning |
|---|---|
| `=== round-N starting ===` | New validation round beginning |
| `Metagraph: N neurons` | Number of registered neurons seen after sync |
| `Test case: X` | Which test case was selected for this round |
| `Train period: hours A-B` | Training data window sent to miners |
| `Test period: hours C-D` | Held-out test data window (not sent to miners) |
| `Sending challenge to N miners (timeout=Xs)` | Challenge dispatched to miners |
| `Received N valid submissions` | Valid responses collected from miners |
| `Scores: {uid: score}` | Raw composite scores per miner |
| `EMA weights: {uid: weight}` | Smoothed weights for on-chain submission |
| `Weights set on chain successfully` | Weights committed to chain |
| `=== round-N complete ===` | Round finished |
| `Sleeping Ns until next round...` | Waiting for next tempo period |

## Health Monitoring

The validator exposes an HTTP health endpoint for external monitoring:

```bash
curl http://localhost:8080/health
```

Returns JSON with uptime, round count, and last round status. Configure the port with `--health-port`.

The health server binds to `127.0.0.1` (loopback) by default. It is not reachable from outside the host without additional configuration (e.g., a reverse proxy). This is intentional: the endpoint contains operational state that should not be publicly exposed without authentication.

## State Persistence

The validator persists every miner's verified result per round into a local SQLite database (`~/.zhen/scoring.db` by default) via `validator/scoring_db.py`. The weighted EMA is recomputed from the windowed rows each time weights are set, so no separate JSON snapshot is required. `round_count` is stored in the `validator_meta` table; on restart the validator resumes from the last persisted value rather than replaying challenges from zero.

### Crash safety

- SQLite runs in WAL mode with a single long-lived connection. Commits are atomic; partial writes from a crash are rolled back on next open.
- Schema is versioned via `PRAGMA user_version` and cross-checked against `protocol.__spec_version__`. A spec-version mismatch (e.g., opening a v3 DB under a v4 validator) archives the old file and recreates a fresh DB. Incompatible EMA data cannot leak into the current weight vector.
- Any legacy `~/.zhen/validator_state.json` from an earlier JSON-based persistence layer is automatically renamed on first open. No manual migration is required.

### Local mode safeguard

Local mode (RC-based ground truth) is rejected with an error if `--network` is set to `finney` or `main`. This prevents accidental testnet-quality ground truth being used on mainnet.

## Alerting

Set the `ZHEN_ALERT_WEBHOOK` environment variable to receive notifications on round failures and startup events. Supports Discord and Slack webhook URLs.

```bash
export ZHEN_ALERT_WEBHOOK=https://discord.com/api/webhooks/your/url
```

## Graceful Shutdown

The validator handles SIGTERM and SIGINT (Ctrl-C) gracefully. It polls for a shutdown signal every 1 second during the tempo sleep. When a signal is received, the current round completes (or is abandoned if mid-challenge) and the process exits cleanly, saving state. On Windows, SIGTERM is not available and the KeyboardInterrupt fallback is used instead.

## PM2 Deployment

For production, use PM2 with the provided scripts:

```bash
./scripts/start_validator.sh
```

This starts the validator and an auto-updater that checks for code updates every 5 minutes.

## Troubleshooting

**"No such file or directory: ~/.zhen/test_cases/..."**
Run step 6 above to copy test case files to the expected location.

**"No miners available to query"**
No miners are registered on the subnet, or all registered miners have offline axons (IP `0.0.0.0` or port `0`). Check the metagraph:

```bash
btcli subnets metagraph --netuid 456 --network test
```

**"Failed to set weights on chain"**
Insufficient stake or rate-limited by the chain. Check your wallet balance and the `weights_rate_limit` hyperparameter:

```bash
btcli wallet balance --wallet-name zhen-validator --network test
btcli subnets hyperparameters --netuid 456 --network test
```

**"Round failed" with traceback**
Check the specific error in the traceback. Most common causes are missing test case files or BOPTEST connection issues (in full mode).

**Docker issues in full mode**
Ensure Docker is running and BOPTEST is accessible:

```bash
docker ps
curl http://localhost:8000
```

## Validator Responsibilities

As a validator, you are expected to:

- Run the official validator code or a fully compatible implementation
- Keep your validator online and responsive
- Set weights honestly based on scoring results
- Not collude to inflate or deflate specific miners' scores
- Report bugs or scoring anomalies to the subnet owner

See [RULES.md](RULES.md) for the full subnet rules.
