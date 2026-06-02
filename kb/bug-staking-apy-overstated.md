# Bug: Staking APY Overstated — Missing Validator Take Rate and Root Proportion

**Status**: SUPERSEDED by `kb/metrics-math-audit-2026-06-01.md`
**Resolution**: The real bug was a units mismatch (TAO ÷ alpha = meaningless), not "overstated by 1.6x".
Formula rewritten 2026-06-01: removed alpha_price, switched to compound annualization.
SN44 went from 1.14% (broken) to 35.83% (matches taostats within 0.1%).

---

*Original diagnosis below (INCORRECT — kept for historical context):*

---

## Observation

- **Expected**: SN0 staking yield ~6.8% APY (per taostats.io/yield)
- **Actual**: Our pipeline reports 11.1% APY for SN0
- **Discrepancy**: ~1.6x overstatement

## Diagnosis

`_generate_staking_rankings()` in `lambda/src/finalizer/handler.py` computes:

```python
total_daily_tao = net_yield * validators
yield_per_stake = total_daily_tao / total_stake
apy = yield_per_stake * 365 * 100
```

This is the **gross validator yield** — what validators collectively earn. It does NOT account for:

1. **Validator take rate** (typically 10-18%) — validators keep a cut before distributing to nominators
2. **Root proportion** — on mature subnets, emission is split between root stakers and alpha stakers based on `tao_weight` (currently 0.18). Our formula doesn't model this split.
3. **The difference between "validator yield" and "nominator yield"** — a staker delegating to a validator sees less than the validator earns

### Root Cause

The formula was built from the validator_landscape metric which tracks what validators earn collectively. It was never adjusted to represent what a **nominator/staker** would actually receive after the validator's cut.

### Why Tests Missed It

No test validates the staking APY against an external source. The property tests verify the formula is internally consistent (APY > 0 when yield > 0) but not that the absolute value is correct.

## Location

- **File**: `lambda/src/finalizer/handler.py`
- **Function**: `_generate_staking_rankings()` (line ~290)
- **Related**: `lambda/src/processor/metrics.py` — `compute_validator_landscape()` provides the input data

## Fix Required

```python
# Current (wrong):
yield_per_stake = total_daily_tao / total_stake
apy = yield_per_stake * 365 * 100

# Correct (needs):
validator_take_rate = 0.18  # typical, should be per-validator from chain
nominator_share = 1.0 - validator_take_rate
net_yield_per_stake = (total_daily_tao * nominator_share) / total_stake
apy = net_yield_per_stake * 365 * 100
```

But this is still incomplete — the root proportion split also needs modeling. Full fix requires:
1. Read `tao_weight` from chain (currently 0.18)
2. Compute root_proportion per subnet (depends on subnet age and alpha issued)
3. Apply validator take rate (per-validator, from chain data)
4. Result = what a nominator actually receives

## Verification

Compare output against taostats.io/yield for top 5 validators. Our SN0 should be ~6.5-7.0%, not 11.1%.

## Classification

- **Auto-fixable**: No — requires design decision on how to model root proportion
- **Risk**: Medium — users making staking decisions based on overstated APY
- **Human decision needed**: How accurate do we need to be? Options:
  - A) Apply flat 18% validator cut (simple, ~80% accurate)
  - B) Model full root proportion + per-validator take (complex, ~95% accurate)
  - C) Label as "gross validator yield" and add separate "estimated nominator yield" field
