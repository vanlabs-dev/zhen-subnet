# Subnet Rules

## Overview

Zhen is a competitive calibration subnet. Miners compete to produce the most accurate digital twin calibrations. These rules exist to ensure fair competition and protect the integrity of the scoring mechanism.

## Fair Play

### What is allowed

- Using any calibration algorithm (Bayesian, evolutionary, gradient-based, custom)
- Using any programming language or framework to implement your miner
- Pre-computing parameter search strategies
- Running multiple miners with separate registrations and wallets
- Using more powerful hardware for faster optimization

### What is NOT allowed

- Copying or intercepting other miners' calibrated parameters
- Attempting to reverse-engineer the validator's held-out test data
- Submitting pre-computed "lookup table" results that bypass actual calibration (validators use randomized train/test splits to prevent this)
- Attacking or interfering with other miners' axon endpoints
- Exploiting validator implementation bugs instead of reporting them

## How Validators Prevent Gaming

The mechanism design includes several layers of anti-gaming protection:

### 1. Randomized train/test splits

Each round uses a deterministic but unpredictable split based on round ID hashing (`hashlib.sha256`). Miners cannot predict which hours will be held out as test data.

### 2. Held-out verification

Validators score on test data that miners never see. Good training performance does not guarantee good test performance if the miner overfits.

### 3. Commit-reveal weights

When enabled, validators commit weight hashes before revealing values, preventing weight-copying between validators.

### 4. Independent verification

Validators re-run the RC model with the miner's returned parameters to verify results. Miners cannot fake metrics.

### 5. EMA smoothing

Single-round manipulation is dampened by exponential moving average tracking (alpha=0.3). Consistent performance over time is what matters.

## Scoring and Weights

- Weights are set once per tempo (~72 minutes with tempo=360)
- Scores are based solely on ASHRAE-standard metrics (see [SCORING.md](SCORING.md))
- The validator applies no subjective judgment; scoring is fully deterministic
- All miners receive the same challenge in each round
- Weights are normalized: your weight depends on your score relative to all other miners

## Immunity Period

- New miners receive an immunity period after registration (configurable by subnet owner, currently ~16.7 hours on Zhen (5000 blocks at 12 seconds per block))
- During immunity, your neuron cannot be deregistered by lower-performing newcomers
- Use this time to verify your miner is receiving and responding to challenges correctly

## Deregistration

Miners can be deregistered if:

- The subnet reaches its maximum neuron count and your score is the lowest
- You have not responded to any challenges (your axon is offline or unreachable)
- Your immunity period has expired and a new registrant's burn exceeds your position

To avoid deregistration:

- Keep your miner online and responsive
- Maintain a composite score above zero (respond to challenges, even imperfectly)
- Monitor your position:

```bash
btcli subnets metagraph --netuid 456 --network test
```

## Validator Responsibilities

Validators must:

- Run the official validator code or a compatible implementation
- Set weights honestly based on scoring results
- Not collude to artificially inflate or deflate specific miners' scores

## Reporting Issues

- **Validator bugs:** Open a GitHub issue (repo is private during testnet; contact the team directly)
- **Suspected cheating:** Contact the subnet owner with evidence
- **Scoring disputes:** All scoring is deterministic and verifiable. Run the scoring engine locally against your calibrated parameters to verify.

## Changes to Rules

- Rules may be updated during testnet as the mechanism matures
- Major rule changes will be announced before taking effect
- The scoring mechanism (weights, thresholds, metrics) is defined in code and documented in [SCORING.md](SCORING.md)
- Hyperparameter changes are visible on-chain:

```bash
btcli subnets hyperparameters --netuid 456 --network test
```
