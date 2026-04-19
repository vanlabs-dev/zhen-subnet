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
- Returns 1.0 (worst) if no valid outputs
- Outputs where `abs(mean(measured)) < 1e-6` (near-zero mean) are skipped to avoid division instability
- Outputs with non-finite values are skipped

**CVRMSE is scored using a rank-based mechanism, not a linear normalization against a fixed threshold.** The raw CVRMSE value determines a miner's rank among all submitters in the round. The rank-based component score is computed as follows:

1. Sort all miners by CVRMSE ascending (lower is better).
2. Apply a ceiling gate: any miner with CVRMSE above `CVRMSE_CEILING = 10.0` receives a CVRMSE component score of 0.0.
3. Assign rank-based scores to miners that pass the ceiling gate. The top-ranked miner scores 1.0. Each subsequent rank scores the previous rank multiplied by `CVRMSE_DECAY_BASE = 0.5` (exponential decay). Ranks beyond `CVRMSE_TOP_K = 5` score 0.0.

Example with 4 miners sorted by CVRMSE: rank 1 scores 1.0, rank 2 scores 0.5, rank 3 scores 0.25, rank 4 (if CVRMSE > 10.0) scores 0.0.

These constants live at module scope in `scoring/engine.py`:
- `CVRMSE_CEILING = 10.0`
- `CVRMSE_TOP_K = 5`
- `CVRMSE_DECAY_BASE = 0.5`

**Historical note:** Prior to spec v6, CVRMSE was normalized as `clamp(1.0 - (cvrmse / 0.30), 0.0, 1.0)`. This created a dead zone where all miners above the 0.30 threshold received 0.0 on the 50% component, collapsing differentiation. Rank-based scoring resolves this regardless of the absolute CVRMSE level.

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
cvrmse_norm  = rank-based (see CVRMSE section above)
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

- CVRMSE: rank-based (no fixed threshold; ceiling gate at CVRMSE=10.0). See CVRMSE section above.
- NMBE threshold: 0.10 (achieving |NMBE| <= 0.10 gives full marks on that component). From ASHRAE Guideline 14 for hourly calibration data.
- Scores that exceed thresholds are clamped to 0.0 (no negative scores)
- All linear normalization uses `safe_clamp(x) = max(0.0, min(1.0, x))`, returning 0.0 for NaN or Inf inputs

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

### Example 1: Two miners competing (rank-based CVRMSE)

Round with 2 miners. Miner A has CVRMSE 0.51, miner B has CVRMSE 0.70.

Both are below the ceiling gate (CVRMSE_CEILING=10.0). Miner A ranks 1st, miner B ranks 2nd.

```
cvrmse_norm (A) = 1.0   (rank 1)
cvrmse_norm (B) = 0.5   (rank 2: 1.0 * CVRMSE_DECAY_BASE^1 = 0.5)
```

Assume both miners have NMBE=0.05, R-squared=0.70, 200 of 1000 simulations used:

```
nmbe_norm    = clamp(1.0 - 0.05/0.10)  = 0.500
r2_norm      = clamp(0.70)              = 0.700
conv_norm    = clamp(1.0 - 200/1000)    = 0.800

composite (A) = 0.50 * 1.000 + 0.25 * 0.500 + 0.15 * 0.700 + 0.10 * 0.800
              = 0.500 + 0.125 + 0.105 + 0.080 = 0.810

composite (B) = 0.50 * 0.500 + 0.25 * 0.500 + 0.15 * 0.700 + 0.10 * 0.800
              = 0.250 + 0.125 + 0.105 + 0.080 = 0.560
```

After power-law (p=2) and normalization: A captures approximately 68% of weight, B approximately 32%.

### Example 2: Miner above ceiling gate

- CVRMSE: 12.0 (above CVRMSE_CEILING=10.0)
- cvrmse_norm = 0.0 regardless of rank

```
composite = 0.50 * 0.000 + 0.25 * nmbe_norm + 0.15 * r2_norm + 0.10 * conv_norm
```

The miner still scores on the other three components but is heavily penalized.

### Example 3: Failed submission

- Miner returns no result or invalid parameters
- All metrics default to worst values
- Composite = 0.0

## Key Takeaways for Miners

- CVRMSE dominates scoring (50%). Focus on minimizing prediction error first. CVRMSE is scored by rank: beating other miners matters more than clearing any fixed threshold.
- NMBE is the second priority (25%). Avoid systematic bias in your calibration. The ASHRAE threshold (|NMBE| < 0.10) still applies as a normalization boundary.
- The CVRMSE ceiling gate (CVRMSE=10.0) is a soft floor, not a meaningful target. Any calibration that runs will likely be below 10.0. Focus on outranking competitors, not on the ceiling.
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

The simulations_used field is self-reported by miners (10% of composite score). A miner can claim fewer simulations than actually used for a small convergence bonus. This advantage is bounded at 10% of the composite score and does not affect the 90% that depends on actual calibration quality. The component remains gameable at its Nash equilibrium (every rational miner reports 0), and is tracked as an open tier-2 hardening item in ROADMAP.md. Candidate replacements: validator-verifiable wall-clock submission time, or removal of the component. Testnet data drives the decision.

### CVRMSE physics floor

The bestest_air test case with the current 7-parameter 1R-1C RC model against BOPTEST Modelica FCU has a physics-imposed CVRMSE floor of approximately 0.5. Miners converge toward this floor regardless of optimization budget. Tighter fits require a richer RC model with more zones or more parameters. This is a Phase 2+ concern, not a scoring bug.

The old CVRMSE dead zone (pre-spec-v6) occurred when the linear formula collapsed all above-threshold miners to zero on the 50% component. Rank-based scoring (spec v6) resolves this: differentiation is relative to competitors, not relative to a fixed threshold. See ROADMAP.md for the historical context.

### R-squared on low-variance outputs

The R-squared component can produce very large negative values on outputs with near-zero variance (for example, cooling energy in winter or heating energy in summer). These are clipped to 0 by `max(0, R^2)`. The clip saves the scoring pipeline from instability, but the R-squared component provides little signal on those outputs. Consider restricting R-squared to zone_temperature output only, or dropping the component in a future spec version. Tracked as a new open item in ROADMAP.md.

### Breakdown diagnostic divergence

`validator/scoring/breakdown.py` still references `CVRMSE_THRESHOLD=0.30` for diagnostic display. This does not affect actual scoring (which is rank-based). The breakdown output may show misleading normalized CVRMSE component values when consulted for debugging. A code change is required to align it with rank-based scoring; tracked in ROADMAP.md.

### Zero-mean CVRMSE handling

The validator skips scoring outputs whose measured mean is near zero (to avoid division instability). The miner's local objective may compute CVRMSE differently on those outputs, so a miner's self-reported training CVRMSE can diverge from the validator's held-out CVRMSE in edge cases where the training series has a near-zero mean. The shared scoring module is the authoritative reference. This is tracked as audit finding 2.13.
