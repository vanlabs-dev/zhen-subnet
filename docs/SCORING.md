# Scoring on Zhen

## Overview

Validators score miners on how accurately their calibrated parameters reproduce building behavior on held-out test data. Scoring uses four ASHRAE-standard metrics combined into a weighted composite score. Scores are tracked across rounds with an exponential moving average to reward consistency.

## Metrics

### CVRMSE (Coefficient of Variation of Root Mean Square Error)

```
CVRMSE = sqrt(mean((predicted - measured)^2)) / mean(measured)
```

- Measures prediction accuracy
- Lower is better
- Averaged across all scoring outputs (e.g., zone temperature, heating power)
- ASHRAE Guideline 14 compliance threshold: 30% (0.30)
- Returns 1.0 (worst) if no valid outputs
- Outputs where `abs(mean(measured)) < 1e-6` (near-zero mean) are skipped to avoid division instability
- Outputs with non-finite values are skipped

### NMBE (Normalized Mean Bias Error)

```
NMBE = sum(predicted - measured) / (n * mean(measured))
```

- Measures systematic over/under-prediction
- Closer to zero is better (can be negative)
- Scored as absolute value: |NMBE|
- ASHRAE Guideline 14 compliance threshold: 10% (0.10)
- Returns 1.0 (worst) if no valid outputs
- Outputs where `abs(mean(measured)) < 1e-6` (near-zero mean) are skipped
- Outputs with non-finite values are skipped

### R-squared (Coefficient of Determination)

```
R^2 = 1 - SS_res / SS_tot

where:
  SS_res = sum((measured - predicted)^2)
  SS_tot = sum((measured - mean(measured))^2)
```

- Measures how well the model explains variance in measured data
- Higher is better (max 1.0, can be negative for very poor fits)
- Returns 0.0 (no explanatory power) if no valid outputs
- Skipped when `SS_tot == 0` (constant measured signal, no variance to explain)

### Convergence Efficiency

```
convergence = 1 - (simulations_used / simulation_budget)
```

- Rewards miners who find good solutions with fewer simulation calls
- Using 100 of 1000 budget = 0.9 efficiency
- Using all budget = 0.0 efficiency
- `simulations_used` is clamped to `[0, simulation_budget]` by the response parser before scoring
- The response parser rejects boolean values, non-finite values, and negative simulation counts

## Composite Score

Each metric is normalized to [0, 1] then weighted:

```
cvrmse_norm  = clamp(1.0 - (cvrmse / 0.30),  0.0, 1.0)
nmbe_norm    = clamp(1.0 - (|nmbe| / 0.10),   0.0, 1.0)
r2_norm      = clamp(r_squared,                0.0, 1.0)
conv_norm    = clamp(1.0 - (sims / budget),    0.0, 1.0)

composite = 0.50 * cvrmse_norm
          + 0.25 * nmbe_norm
          + 0.15 * r2_norm
          + 0.10 * conv_norm
```

If any of cvrmse, nmbe, or r_squared is non-finite (NaN or Inf) when the composite is assembled, the composite is forced to 0.0 immediately. This guard runs before the per-metric guards above and protects the weight vector from corruption.

### Weight breakdown

| Metric | Weight | What it rewards |
|---|---|---|
| CVRMSE | 50% | Prediction accuracy |
| NMBE | 25% | Absence of systematic bias |
| R-squared | 15% | Overall fit quality |
| Convergence | 10% | Efficient parameter search |

### Normalization thresholds

- CVRMSE threshold: 0.30 (achieving CVRMSE <= 0.30 gives full marks on that component)
- NMBE threshold: 0.10 (achieving |NMBE| <= 0.10 gives full marks)
- Both thresholds come from ASHRAE Guideline 14 for hourly calibration data
- Scores that exceed thresholds are clamped to 0.0 (no negative scores)
- All normalization uses `safe_clamp(x) = max(0.0, min(1.0, x))`, returning 0.0 for NaN or Inf inputs

## Weight Setting

After computing composite scores, the pipeline runs in three steps:

**Step 1: Score floor.** Miners whose composite score is below 5% of the top scorer in the round have their composite set to 0.0. This eliminates the long tail of very low-quality submissions.

**Step 2: Power-law.** Each non-zero composite is squared:

```
powered_i = composite_i ^ 2.0
```

Squaring amplifies quality differences. A miner scoring 0.9 gets 0.81 powered weight; one scoring 0.3 gets only 0.09. This makes Sybil attacks (many low-quality miners) mathematically unprofitable.

**Step 3: Normalize.** Weights sum to 1.0:

```
weight_i = powered_i / sum(all powered)
```

If all composites are zero (all miners failed), `compute()` returns an empty dict and the validator falls back to copying existing on-chain weights (stake-weighted average across validators with permit). No weights are set to equal values.

## EMA (Exponential Moving Average)

Scores are smoothed across rounds to prevent single-round variance from dominating:

- Alpha: 0.3
- Formula: `ema_new = 0.3 * current_score + 0.7 * previous_ema`
- First round for a miner: score is set directly (no history to blend)
- If a miner's score is non-finite in a round, it is treated as absent and the EMA decays rather than freezing or crashing
- Final weights for on-chain submission come from the normalized EMA scores
- Miners whose EMA falls below 1e-6 are pruned from the state

This means consistent performance is rewarded over lucky single rounds.

## Scoring Examples

### Example 1: Strong miner

- CVRMSE: 0.05 (well below 0.30 threshold)
- NMBE: 0.02 (well below 0.10 threshold)
- R-squared: 0.95
- Simulations used: 150 of 1000 budget

```
cvrmse_norm  = clamp(1.0 - 0.05/0.30)  = clamp(0.833) = 0.833
nmbe_norm    = clamp(1.0 - 0.02/0.10)  = clamp(0.800) = 0.800
r2_norm      = clamp(0.95)              = 0.950
conv_norm    = clamp(1.0 - 150/1000)    = clamp(0.850) = 0.850

composite = 0.50 * 0.833 + 0.25 * 0.800 + 0.15 * 0.950 + 0.10 * 0.850
          = 0.417 + 0.200 + 0.143 + 0.085
          = 0.844
```

### Example 2: Weak miner

- CVRMSE: 0.40 (above threshold)
- NMBE: 0.15 (above threshold)
- R-squared: 0.60
- Simulations used: 900 of 1000 budget

```
cvrmse_norm  = clamp(1.0 - 0.40/0.30)  = clamp(-0.333) = 0.000
nmbe_norm    = clamp(1.0 - 0.15/0.10)  = clamp(-0.500) = 0.000
r2_norm      = clamp(0.60)              = 0.600
conv_norm    = clamp(1.0 - 900/1000)    = clamp(0.100)  = 0.100

composite = 0.50 * 0.000 + 0.25 * 0.000 + 0.15 * 0.600 + 0.10 * 0.100
          = 0.000 + 0.000 + 0.090 + 0.010
          = 0.100
```

### Example 3: Failed submission

- Miner returns no result or invalid parameters
- All metrics default to worst values
- Composite = 0.0

## Key Takeaways for Miners

- CVRMSE dominates scoring (50%). Focus on minimizing prediction error first.
- NMBE is the second priority (25%). Avoid systematic bias in your calibration.
- Beating the ASHRAE thresholds (CVRMSE < 0.30, |NMBE| < 0.10) is the minimum viable performance. Going well below earns proportionally more.
- Convergence efficiency matters at the margin (10%). If two miners achieve similar accuracy, the one using fewer simulations scores higher.
- Consistency across rounds matters due to EMA smoothing. A miner scoring 0.7 every round will outrank one alternating between 0.9 and 0.3.

## EMA Decay

Miners who do not submit in a round, or whose score is non-finite, have their EMA score decayed by (1 - alpha) = 0.7 per round. After approximately 10 consecutive absences, the miner's weight drops below the pruning threshold (1e-6) and is removed from the weight vector. This prevents offline miners from holding stale weight.

## Anti-Gaming Protections

Submissions where all parameters are within 0.1% of config defaults are rejected. Miners must run actual calibration. Additionally, validators use deterministic but unpredictable train/test splits, and held-out test data is never sent to miners.

## Known Limitations

### Sybil dilution

Running many low-quality miners to dilute a legitimate miner's share is mitigated by three layers: (1) power-law normalization (scores squared) makes low-quality weight capture negligible, (2) the 5% score floor zeroes out the weakest submissions entirely, and (3) Bittensor registration cost requires burning TAO per miner slot. The residual risk is that a large number of moderately good Sybil miners (above the floor) could still dilute top miners. Registration cost scales that attack linearly while returns are diminishing due to power-law normalization.

### Self-reported convergence

The simulations_used field is self-reported by miners (10% of composite score). A miner can claim fewer simulations than actually used for a small convergence bonus. This advantage is bounded at 10% of the composite score and does not affect the 90% that depends on actual calibration quality.
