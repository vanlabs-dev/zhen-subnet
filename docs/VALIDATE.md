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
for tc in bestest_hydronic_heat_pump bestest_air bestest_hydronic; do
  mkdir -p ~/.zhen/test_cases/$tc
  cp registry/test_cases/$tc/*.json ~/.zhen/test_cases/$tc/
done
```

The test case directory contains three files: `config.json`, `schedules.json`, and `weather.json`.

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

| Name | Value | Description |
|---|---|---|
| `TEMPO_BLOCKS` | 360 | Blocks per tempo |
| `BLOCK_TIME_SECONDS` | 12 | Seconds per block |
| `DEFAULT_TEMPO_SECONDS` | 4320 | Seconds between rounds (~72 minutes) |
| `CHALLENGE_TIMEOUT_SECONDS` | 600 | Max seconds miners have to respond to a challenge |
| `WEIGHT_TIMEOUT_SECONDS` | 120 | Max seconds for chain weight submission |
| `VERIFICATION_TIMEOUT_SECONDS` | 300 | Max seconds per miner verification run |

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
12. **Sleep**: Validator waits for the next tempo period (4320 seconds with default settings).

## BOPTEST Setup

BOPTEST is the Building Optimization Performance Test framework. It provides containerized building energy simulation environments.

### Architecture

The validator communicates with BOPTEST via the `BOPTESTClient` REST API (`validator/emulator/boptest_client.py`). BOPTEST v0.8+ uses a service architecture where test cases are selected via `POST /testcases/{id}/select` to obtain a running test ID.

### Starting BOPTEST locally

BOPTEST runs as a Docker service on port 8000 (default). For detailed setup instructions, see: https://github.com/ibpsa/project1-boptest

### Supported test cases

Currently available (3 test cases, deterministic rotation per round):

- `bestest_hydronic_heat_pump`: BESTEST reference building with hydronic heat pump (Brussels climate)
- `bestest_air`: BESTEST reference building with air-based heating system (Brussels climate)
- `bestest_hydronic`: BESTEST reference building with hydronic heating (Brussels climate)

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

The validator saves EMA scores and round count to `~/.zhen/validator_state.json` after each successful round. On restart, it resumes from the last known state. This prevents miners from losing accumulated reputation after a validator restart.

### Crash safety

- Saves are written to a unique temporary file (`validator_state.json.tmp.<pid>.<uuid>`) and fsynced before the atomic rename. A power failure mid-write leaves the previous good state intact.
- On startup, stale `.tmp` files from prior crashes are cleaned up automatically.
- The loaded state is validated: it must contain exactly the required keys (`round_count`, `ema_scores`, `last_round_id`, `last_round_timestamp`, `spec_version`), all EMA scores must be in [0, 1], and `spec_version` must match the running code. A version mismatch (e.g., loading spec v1 state into a v2 validator) is rejected to prevent incompatible EMA data from corrupting the weight vector.

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
