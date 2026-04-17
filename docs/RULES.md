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
- Submitting unmodified default parameters from the test case configuration (detected and rejected automatically)

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

### 6. Default parameter detection

Submissions where all parameters are within 0.1% of the config defaults are automatically rejected. This prevents miners from skipping calibration and submitting known defaults.

### 7. Absent miner decay

Miners who miss rounds have their EMA score decayed exponentially. Persistent absence results in weight removal, preventing offline miners from holding stale emissions.

### 8. Power-law weight normalization

Weights are computed using power-law normalization (scores squared before normalizing). This amplifies quality differences and makes Sybil attacks (running many low-quality miners) mathematically unprofitable. A single high-quality miner consistently captures >95% of weight against dozens of low-quality competitors.

### 9. Score floor

Miners scoring below 5% of the top scorer in a round receive zero weight. This eliminates the long tail of garbage miners that would otherwise dilute legitimate miners' emissions.

### 10. Registration cost as Sybil defense

Each miner registration requires burning TAO. Combined with power-law normalization and the score floor, running many low-quality miners is economically infeasible: registration costs scale linearly while the captured emissions for sub-quality miners are driven to zero.

## Scoring and Weights

- Weights are set once per tempo (360 blocks, approximately 72 minutes)
- Scores are based solely on ASHRAE-standard metrics (see [SCORING.md](SCORING.md))
- The validator applies no subjective judgment; scoring is fully deterministic
- All miners receive the same challenge in each round
- Weights are normalized: your weight depends on your score relative to all other miners

## Immunity Period

- New miners receive an immunity period after registration (configurable by subnet owner)
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
