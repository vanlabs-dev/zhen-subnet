# Mining on Zhen

## What miners do

Miners receive calibration challenges from validators containing training data from a building energy simulation. They optimize a simplified RC network thermal model's parameters to match this training data as closely as possible using Bayesian optimization. Validators score the result on held-out test data using ASHRAE-standard metrics.

## Requirements

### Hardware

- CPU only, no GPU required
- Minimum: 4 cores, 8GB RAM
- The bottleneck is simulation evaluations (RC network thermal model), which are CPU-bound
- Each calibration round runs `n_calls` optimization iterations (default 100)
- A round takes approximately 30 to 60 seconds with `n_calls=100`

### Software

- Linux (Ubuntu 22.04+ recommended) or WSL2 on Windows
- Python 3.10+
- Bittensor SDK and CLI

### Network

- Axon port 8091 (default) must be accessible from the internet
- Validators query miners via HTTP on this port
- Configure firewall and port forwarding accordingly

## Quickstart

### 1. Install

```bash
git clone https://github.com/vanlabs-dev/zhen-subnet.git
cd zhen-subnet
uv sync --all-groups
```

Note: The repo is currently private during testnet. Contact the team for access.

### 2. Create wallet

```bash
btcli wallet create --wallet-name zhen-miner --wallet-hotkey default
```

Save your mnemonic securely.

### 3. Get testnet TAO

Request testnet TAO in the Bittensor Discord `#testnet-faucet` channel. You need approximately 2 TAO for registration.

### 4. Register on subnet

```bash
btcli subnet register --netuid 456 --network test --wallet-name zhen-miner --wallet-hotkey default
```

### 5. Set up test cases

Miners need local copies of test case data files for the RC network simulation:

```bash
for tc in bestest_hydronic_heat_pump bestest_air bestest_hydronic; do
  mkdir -p ~/.zhen/test_cases/$tc
  cp registry/test_cases/$tc/*.json ~/.zhen/test_cases/$tc/
done
```

Each test case directory contains three files: `config.json`, `schedules.json`, and `weather.json`.

### 6. Start mining

```bash
python -m miner.main --netuid 456 --network test
```

## CLI arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--netuid` | int | 456 | Subnet UID |
| `--network` | str | `test` | Network: `test`, `finney`, or a `ws://` URL |
| `--wallet-name` | str | `zhen-miner` | Wallet name |
| `--wallet-hotkey` | str | `default` | Wallet hotkey |
| `--algorithm` | str | `bayesian` | Calibration algorithm |
| `--n-calls` | int | 100 | Number of optimization iterations per round |
| `--axon-port` | int | 8091 | Port for the axon server to listen on |

### Environment variables

| Variable | Description |
|---|---|
| `ZHEN_NETUID` | Override default netuid |
| `ZHEN_NETWORK` | Override default network |

## How a round works

1. Validator selects a test case and generates training/test data splits from the complex emulator.
2. Validator sends a `CalibrationSynapse` to your miner's axon containing: test case ID, training data (time-series of temperatures), parameter names and bounds, and simulation budget.
3. Your miner runs Bayesian optimization (scikit-optimize) to find RC network parameters that minimize CVRMSE on the training data.
4. Miner returns calibrated parameters, simulation count, and training CVRMSE to the validator.
5. Validator re-runs the RC model with your parameters on held-out test data.
6. Validator scores using ASHRAE metrics: CVRMSE (50%), NMBE (25%), R-squared (15%), convergence efficiency (10%).
7. Scores are normalized across all miners and set as weights on-chain.

## Scoring

Scores are computed from four weighted metrics:

| Metric | Weight | Target |
|---|---|---|
| CVRMSE | 50% | Under 30% for ASHRAE compliance |
| NMBE | 25% | Near zero |
| R-squared | 15% | Close to 1.0 |
| Convergence | 10% | Fewer simulation calls is better |

Scores are tracked with an exponential moving average (alpha=0.3) across rounds, rewarding consistent performance over lucky one-offs.

See `docs/SCORING.md` for full scoring details.

## Improving performance

- Increase `--n-calls` for more optimization iterations (tradeoff: longer runtime per round).
- The default Bayesian optimizer (scikit-optimize) is a solid baseline.
- Custom algorithms can be added by implementing a new calibrator class in `miner/calibration/`.
- Focus on parameter space exploration. The RC model has meaningful physical constraints that can guide the search.

## Monitoring

Key log messages to watch for:

| Log message | Meaning |
|---|---|
| `Received challenge: test_case=...` | Validator sent you a calibration challenge |
| `Calibration complete: cvrmse=X.XXXX` | Your optimization result. Lower is better. |
| `Calibration failed: ...` | Something went wrong. Check the error details. |

## Troubleshooting

**"No such file or directory: ~/.zhen/test_cases/..."**
Run step 5 above to copy test case files to the expected location.

**Axon not receiving challenges**
Check that port 8091 is open and reachable from the internet. Verify your registration:

```bash
btcli subnets metagraph --netuid 456 --network test
```

**Registration failed**
Check your wallet balance:

```bash
btcli wallet balance --wallet-name zhen-miner --network test
```

You need approximately 2 TAO for registration.

**scikit-optimize import errors**
Ensure all dependency groups are installed:

```bash
uv sync --all-groups
```

## Rules

See `docs/RULES.md` for full subnet rules and policies.
