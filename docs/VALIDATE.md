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
pip install -e ".[bittensor]"
pip install scikit-optimize
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
btcli wallet create --wallet.name zhen-validator --wallet.hotkey default
```

Save your mnemonic securely.

### 4. Get testnet TAO

Request testnet TAO in the Bittensor Discord `#testnet-faucet` channel. You need approximately 2 TAO for registration plus additional TAO for staking.

### 5. Register on subnet

```bash
btcli subnet register --netuid 456 --network test --wallet.name zhen-validator --wallet.hotkey default
```

### 6. Set up test cases

Validators need local copies of test case data:

```bash
mkdir -p ~/.zhen/test_cases/bestest_hydronic_heat_pump
cp registry/test_cases/bestest_hydronic_heat_pump/*.json ~/.zhen/test_cases/bestest_hydronic_heat_pump/
```

The test case directory contains three files: `config.json`, `schedules.json`, and `weather.json`.

### 7. Start validating

#### Local mode (default, no Docker required)

The validator uses the RC network model as its own ground truth source. This skips BOPTEST but still runs the full scoring and weight-setting loop:

```bash
python -m validator.main --netuid 456 --network test
```

Local mode is the default (`--local-mode` is enabled by default). This is the recommended mode for testnet.

#### Full mode (BOPTEST ground truth)

For production validation with BOPTEST emulators providing ground truth. Requires Docker running with the BOPTEST service accessible at `http://localhost:8000`.

Note: Full BOPTEST mode is not yet available via CLI flags. The validator currently defaults to local mode for testnet.

## CLI Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--netuid` | int | 456 | Subnet UID |
| `--network` | str | `test` | Network: `test`, `finney`, or a `ws://` URL |
| `--wallet-name` | str | `zhen-validator` | Wallet name |
| `--wallet-hotkey` | str | `default` | Wallet hotkey |
| `--local-mode` | flag | `True` | Use RC network model as ground truth instead of BOPTEST |

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

## How a Validation Round Works

1. **Sync metagraph**: Validator refreshes the list of registered neurons on the subnet.
2. **Select test case**: A test case is chosen deterministically based on the round number and available registry entries.
3. **Generate data split**: Training and test periods are computed using deterministic hashing (`hashlib.sha256`). The split is unpredictable to miners but reproducible by any validator.
4. **Generate ground truth**: The complex emulator (BOPTEST in full mode, or RC model in local mode) runs the test case to produce reference time-series data for both training and test periods.
5. **Build synapse**: A `CalibrationSynapse` is constructed with the test case ID, training data, parameter names and bounds, simulation budget, and round metadata.
6. **Send to miners**: The synapse is sent to all registered miners via Bittensor dendrite. Miners have until near the end of the tempo to respond (timeout = tempo - 300 seconds, minimum 60 seconds).
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

Currently available:

- `bestest_hydronic_heat_pump`: BESTEST reference building with hydronic heating system (Brussels climate)

Additional test cases will be added as the subnet expands.

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
btcli wallet balance --wallet.name zhen-validator --network test
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
