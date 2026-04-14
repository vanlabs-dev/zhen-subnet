---
name: bittensor
description: "Bittensor and Dynamic TAO Development Reference. TRIGGER when: code imports `bittensor`/`bt`; user mentions btcli, wallet, subnet, netuid, metagraph, axon, dendrite, synapse, set_weights, staking, alpha tokens, dTAO, emissions, tempo, or registration; user asks about Bittensor testnet/finney/chain operations; debugging ExtrinsicResponse or Balance type errors. Covers SDK v10 breaking changes, dTAO economics (Taoflow model), btcli commands, subnet lifecycle, Yuma Consensus, and WSL2 development workflow."
---

# Bittensor and Dynamic TAO Development Reference

> Verified against official Bittensor documentation (docs.learnbittensor.org), SDK v10 source, btcli v9.20+, and dTAO whitepaper as of April 2026.

---

## 1. Package Architecture

Bittensor consists of THREE separate packages. They are NOT bundled together.

| Package | PyPI | Version (Apr 2026) | Purpose |
|---------|------|---------------------|---------|
| `bittensor` | bittensor | 10.2.0 | Python SDK for subnet development |
| `bittensor-cli` | bittensor-cli | 9.20.1 | CLI for wallet, subnet, staking operations |
| `bittensor-wallet` | bittensor-wallet | 4.0.1 | Rust-based wallet key management (auto-installed with SDK) |

CRITICAL: `btcli` is NOT included when you `pip install bittensor`. Install separately: `pip install bittensor-cli`

SDK repo: github.com/opentensor/bittensor. btcli repo: github.com/latent-to/btcli. Wallet repo: github.com/opentensor/btwallet.

### Windows Limitation

`bittensor-wallet` uses Rust with `std::os::unix` and will NOT build on native Windows. Pre-built wheels exist for Linux (x86_64, aarch64) and macOS only. Use WSL2 for all bittensor operations on Windows.

---

## 2. SDK v10 Breaking Changes

SDK v10 is a major breaking release. Do NOT use v8/v9 patterns.

### ExtrinsicResponse Return Type

All blockchain transaction functions now return `ExtrinsicResponse` objects instead of `bool` or tuples.

```python
# v9 (DEPRECATED)
success = subtensor.set_weights(...)  # returned bool

# v10 (CURRENT)
response = subtensor.set_weights(...)  # returns ExtrinsicResponse
if response.success:
    print(f"Block: {response.block_hash}")
```

### Balance Type Enforcement

All amount parameters require `Balance` objects. Raw floats are rejected.

```python
# v9 (DEPRECATED)
subtensor.transfer(wallet, dest, 1.0)

# v10 (CURRENT)
from bittensor.utils.balance import tao, rao
subtensor.transfer(wallet, dest, tao(1.0))
subtensor.transfer(wallet, dest, rao(1_000_000_000))
```

### Parameter Renames

Consistent `_ss58` suffix for all address parameters:
- `hotkey` becomes `hotkey_ss58`
- `coldkey` becomes `coldkey_ss58`

### Async Substrate Interface

`py-substrate-interface` removed entirely, replaced with `async-substrate-interface` (separate package, auto-installed as dependency).

### Multiple Incentive Mechanisms

SDK v10 adds support for running multiple evaluation mechanisms per subnet with independent weight matrices and emissions. Each mechanism has its own `mechid`.

```python
from bittensor.core.metagraph import Metagraph
meta = Metagraph(netuid=14, network="finney", sync=True)
print(meta.mechid)           # 0 (default mechanism)
print(meta.mechanism_count)  # e.g., 2
print(meta.emissions_split)  # e.g., [60, 40]
```

Total UIDs across all mechanisms limited to 256.

---

## 3. Dynamic TAO (dTAO)

Launched February 2025. Replaced validator-driven emission allocation with market-based mechanism.

### Core Concept

Every subnet has its own alpha token and an Automated Market Maker (AMM) pool. The AMM is a constant-product pool (like Uniswap) containing TAO and alpha. When you stake TAO into a subnet, your TAO enters the pool and you receive alpha tokens. The alpha price equals the TAO/alpha reserve ratio.

### Three Currency Pools Per Subnet

1. TAO reserve (in the AMM pool)
2. Alpha reserve (in the AMM pool)
3. Alpha outstanding (held in hotkeys of subnet participants, i.e., total stake)

### Emission Model: "Taoflow" (Post-November 2025)

Emissions are based on net TAO flows (staking minus unstaking), NOT token prices.

```
net_flow_i = sum(TAO staked into subnet i) - sum(TAO unstaked from subnet i)
S_i = (1 - alpha) * S_{i-1} + alpha * net_flow_i
```

- EMA smoothing factor alpha ~ 0.000003209
- 30-day half-life, ~86.8-day effective window
- Subnets with negative net flows receive ZERO emissions
- This replaced the original price-based model which was vulnerable to "TAO treasury" gaming

Why Taoflow replaced price-based model:
- Price-based let large subnets absorb sell pressure while small subnets collapsed
- Projects could artificially pump alpha price with TAO treasuries
- Flow-based is scale-invariant: measures net flow per unit liquidity

### Emission Distribution Within a Subnet

Each block:
1. TAO injected into subnet's TAO reserve (proportional to emission share)
2. Alpha injected into alpha reserve (proportional to TAO injection, maintaining price stability)
3. Alpha allocated to alpha outstanding (distributed to participants via Yuma Consensus)

Distribution at end of each tempo (~360 blocks, ~72 min) via Yuma Consensus:
- Miners: based on incentive scores (set by validators)
- Validators: based on dividends (proportional to stake and consensus alignment)
- Subnet owner: fixed 18% of subnet alpha emissions

### Subnet Creation Under dTAO

- Creation cost is BURNED (NOT a refundable lock cost as pre-dTAO)
- Cost is dynamic: lowers gradually, doubles every time a subnet is created
- Rate limited: one creation per 14,400 blocks (~2 days)
- Check cost: `btcli subnet burn-cost --network test`
- Network currently supports 128 subnets, projected expansion to 256 in 2026

### Staking Mechanics

- Staking TAO into a subnet swaps TAO for alpha via the AMM
- Unstaking swaps alpha back for TAO at current exchange rate
- Slippage applies (constant-product AMM)
- Staking is per-subnet, per-validator (you stake to a specific validator's hotkey on a specific subnet)

### Root Subnet (Subnet Zero)

- Special subnet with no miners and no validation work
- Validators can register and TAO holders can stake
- Staking to root validator provides exposure across all subnets where that validator is active
- Root alpha dividends can be kept as alpha or auto-sold (configurable via `set_root_claim_type`)

---

## 4. Wallet Management

### CLI Commands

```bash
# Create complete wallet (coldkey + hotkey)
btcli wallet create --wallet.name zhen-owner --wallet.hotkey default

# Create coldkey only
btcli wallet new_coldkey --wallet.name zhen-owner

# Create additional hotkey for existing coldkey
btcli wallet new_hotkey --wallet.name zhen-owner --wallet.hotkey my-hotkey

# List all wallets with addresses
btcli wallet list

# Check balance
btcli wallet balance --wallet.name zhen-owner --network test

# Transfer TAO
btcli wallet transfer --dest <SS58_ADDRESS> --wallet.name zhen-owner --amount 10 --network test
```

### Python SDK

```python
from bittensor_wallet import Wallet

wallet = Wallet(name='zhen-owner', hotkey='default')
wallet.create_if_non_existent()
print(wallet.coldkey.ss58_address)
print(wallet.hotkey.ss58_address)
```

### Storage

- Path: `~/.bittensor/wallets/`
- Config: `~/.bittensor/config.yml`
- Debug log: `~/.bittensor/debug.txt`
- Metagraph cache: `~/.bittensor/metagraphs/`

### Zhen Wallet Plan

| Wallet | Purpose | TAO Needed |
|--------|---------|-----------|
| `zhen-owner` | Creates and owns the subnet | Most (subnet burn cost, ~100+ testnet TAO) |
| `zhen-validator` | Runs the validator | Registration fee + staking |
| `zhen-miner` | Runs the reference miner | Registration fee |

---

## 5. Subnet Lifecycle

### Step 1: Create Subnet

```bash
btcli subnet create --network test --wallet.name zhen-owner
# Outputs a netuid. Save this.
```

### Step 2: Start Subnet (REQUIRED, subnets are INACTIVE by default)

```bash
btcli subnet start --netuid <NETUID> --network test
```

Without this step, the subnet will NOT emit. This is a new requirement.

### Step 3: Register Neurons

```bash
btcli subnet register --netuid <NETUID> --network test \
    --wallet.name zhen-validator --wallet.hotkey default

btcli subnet register --netuid <NETUID> --network test \
    --wallet.name zhen-miner --wallet.hotkey default
```

### Step 4: Configure Hyperparameters

```bash
btcli sudo set --netuid <NETUID> --network test \
    --wallet.name zhen-owner \
    --param tempo --value 360
```

Only the coldkey that created the subnet can set hyperparameters.

### Step 5: View Subnet State

```bash
btcli subnets list --network test
btcli subnets hyperparameters --netuid <NETUID> --network test
btcli subnets metagraph --netuid <NETUID> --network test
```

---

## 6. Subnet Hyperparameters

Owner-settable parameters relevant to Zhen (block time = 12 seconds):

| Parameter | Zhen Value | Description |
|-----------|-----------|-------------|
| `tempo` | 360 (~72 min) | Blocks per epoch. One calibration round per tempo. |
| `immunity_period` | 14400 (~48h) | Blocks before new neuron can be deregistered |
| `min_allowed_weights` | 8 | Minimum UIDs a validator must set weights for |
| `max_weight_limit` | 455 (~1.8% per UID) | Max weight per UID (u16: 65535 = 100%) |
| `weights_rate_limit` | 100 (~20 min) | Min blocks between weight-setting calls |
| `activity_cutoff` | 5000 (~16.7h) | Blocks of inactivity before neuron excluded |
| `commit_reveal_enabled` | true | Prevent validators copying weights |
| `commit_reveal_period` | 3 | Tempo delay for commit-reveal |
| `registration_allowed` | true | Whether new registrations accepted |
| `max_validators` | 64 | Maximum validator slots |

Conversion: `blocks * 12 / 3600 = hours`

---

## 7. SDK Programmatic Patterns (v10)

### Subtensor Connection

```python
import bittensor as bt

subtensor = bt.Subtensor(network="test")      # testnet
subtensor = bt.Subtensor(network="finney")    # mainnet
subtensor = bt.Subtensor(network="ws://127.0.0.1:9945")  # local
```

### Synapse Definition

```python
import bittensor as bt
from typing import Optional

class CalibrationSynapse(bt.Synapse):
    """All fields MUST have defaults for Pydantic deserialization."""
    test_case_id: str = ""
    training_data: dict = {}
    parameter_names: list[str] = []
    parameter_bounds: dict = {}
    simulation_budget: int = 1000
    calibrated_params: Optional[dict] = None
    simulations_used: Optional[int] = None
```

### Dendrite (Validator queries miners)

```python
dendrite = bt.Dendrite(wallet=wallet)
metagraph = subtensor.metagraph(netuid=NETUID)

responses = await dendrite(
    axons=metagraph.axons,
    synapse=CalibrationSynapse(...),
    timeout=300,
)
```

### Axon (Miner serves validators)

```python
axon = bt.Axon(wallet=wallet)
axon.attach(forward_fn=forward, blacklist_fn=blacklist, priority_fn=priority)
axon.serve(netuid=NETUID, subtensor=subtensor)
axon.start()
```

### Setting Weights (v10 pattern)

```python
response = subtensor.set_weights(
    wallet=wallet,
    netuid=NETUID,
    uids=uids,        # list[int]
    weights=weights,   # list[float], normalized to sum ~1.0
    wait_for_inclusion=True,
    wait_for_finalization=True,
)
if response.success:
    print(f"Weights set at block {response.block_hash}")
```

### Metagraph

```python
metagraph = subtensor.metagraph(netuid=NETUID)
for neuron in metagraph.neurons:
    print(neuron.uid, neuron.hotkey, neuron.stake)
metagraph.sync()  # refresh
```

---

## 8. Network Endpoints

| Network | URL | Purpose |
|---------|-----|---------|
| finney | `wss://entrypoint-finney.opentensor.ai:443` | Mainnet |
| test | `wss://test.finney.opentensor.ai:443` | Testnet |
| local | `ws://127.0.0.1:9945` | Local chain |

---

## 9. Testnet TAO

- `btcli wallet faucet` is DISABLED. Must obtain from Discord or contacts.
- Request in Discord: #testnet-faucet channel
- Need coldkey SS58 addresses: get from `btcli wallet list`
- Subnet creation: ~100+ testnet TAO (dynamic burn cost)
- Registration: small amount per neuron

---

## 10. Yuma Consensus

Converts validator weight-setting into emission distribution.

- Validators set weights on miners via `subtensor.set_weights()`
- Yuma Consensus aggregates weights across multiple validators
- Consensus determines emission splits (incentive for miners, dividends for validators)
- Validators with outlier scores lose consensus alignment
- `commit_reveal_enabled` prevents weight copying

---

## 11. Development Environment (Zhen-specific)

```
Windows (core development):
  Scoring, simulation, RC model, tests
  BOPTEST via Docker Desktop
  No bittensor package
  Venv: D:\Coding\Bittensor\zhen-subnet\.venv

WSL2 Ubuntu (bittensor operations):
  btcli commands, validator/miner processes, synapse testing
  Venv: /home/van/.venv/zhen-subnet (separate from Windows venv)
  Repo: /mnt/d/Coding/Bittensor/zhen-subnet
  Sync with: uv sync --all-extras --all-groups
```

---

## 12. Common Gotchas

1. btcli is a SEPARATE package from bittensor SDK
2. Subnets are INACTIVE by default, must `btcli subnet start`
3. Subnet creation BURNS TAO under dTAO (not refundable)
4. SDK v10 returns ExtrinsicResponse, not bool
5. SDK v10 requires Balance objects (use `tao()` / `rao()`)
6. Synapse fields need defaults (Pydantic)
7. bittensor-wallet won't build on Windows (use WSL2)
8. Wallet path: `~/.bittensor/wallets/`
9. set_weights expects normalized weights (~sum to 1.0)
10. Subnet creation rate limited: one per ~2 days
11. Registration costs TAO (burns)
12. btcli uses dot notation: `--wallet.name`, `--wallet.hotkey`
13. Emissions based on net TAO flow, not alpha price
14. Owner take fixed at 18%
15. btcli faucet is DISABLED
16. `from __future__ import annotations` breaks bt.Synapse subclasses. Pydantic needs real type objects at class definition time. Never use it in files that define Synapse subclasses.
17. `from __future__ import annotations` also breaks axon.attach(). The SDK inspects forward_fn type annotations with issubclass() at runtime. Deferred string annotations cause "issubclass() arg 1 must be a class" errors. Remove it from any file containing functions passed to axon.attach().
18. Axon blacklist/priority functions must use `typing.Tuple[bool, str]` not `tuple[bool, str]` for return annotations. The SDK compares signatures using typing.Tuple internally.
19. Axon blacklist/priority must be standalone module-level functions, not bound methods or nested functions. The SDK inspects signatures and nested/bound functions don't match expected patterns.
20. `required_hash_fields` on a Synapse subclass must be a class attribute (list), not a method or property. The SDK iterates it directly. Suppress the Pydantic shadow warning with warnings.filterwarnings.
21. HOME directory on WSL2 may default to `/` instead of `/root`. Verify with `echo $HOME`. Fix in /etc/passwd or .bashrc. Wallets, test cases, and configs all use `~/.bittensor/` and `~/.zhen/` which resolve relative to HOME.
22. BOPTEST v0.8+ URL pattern uses `/{endpoint}/{testid}` (e.g., `/results/{testid}`, `/stop/{testid}`), NOT `/{testid}/{endpoint}`.
23. BOPTEST returns measurement data at its internal timestep (~30s, ~120 points/hour), NOT at the configured communication step size. You must resample to hourly resolution after retrieval.
24. BOPTEST "time" variable returned by get_results has a different array length than measurement variables. Do NOT use timestamps for resampling. Use array chunking instead: `values_per_hour = len(values) // n_hours`.
25. MinIO credentials in `.env` must match: `AWS_ACCESS_KEY_ID=user`, `AWS_SECRET_ACCESS_KEY=password` (matching `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` in the BOPTEST docker-compose).
26. BOPTEST web container starts before MinIO bucket exists. May need `docker compose restart web` after first `docker compose up -d`.
27. `config.json` for test cases must be recopied to `~/.zhen/test_cases/` after any changes to the registry copy.

---

## 13. Reference Links

- Docs: https://docs.learnbittensor.org
- SDK v10 migration: https://docs.learnbittensor.org/sdk/migration-guide
- btcli reference: https://docs.learnbittensor.org/btcli
- Subnet hyperparameters: https://docs.learnbittensor.org/subnets/subnet-hyperparameters
- Create a subnet: https://docs.learnbittensor.org/subnets/create-a-subnet
- Emissions: https://docs.learnbittensor.org/learn/emissions
- dTAO whitepaper: https://bittensor.com/dtao-whitepaper
- Subnet template: https://github.com/opentensor/bittensor-subnet-template
