# Metrics Math Audit — POC Findings & Fix Plan

**Date**: 2026-06-01
**Triggered by**: Deep dive code review found 3 CRITICAL, 5 HIGH, 7 MEDIUM issues

## POC: Unit Validation Against Live Chain

### Key Discovery: `real_apy_percent` is off by ~25x

**Root cause**: Units mismatch in `compute_real_apy`.

```python
# CURRENT CODE (WRONG):
numerator = emission_daily × alpha_price × (1-take) × (1-root_prop)  # units: TAO
denominator = sum(v.alpha_stake)                                       # units: alpha
# result: TAO/alpha (meaningless!)

# CORRECT:
numerator = emission_daily × (1-take)   # units: alpha
denominator = sum(v.alpha_stake)         # units: alpha
# result: alpha/alpha = dimensionless rate ✓
```

### Validated Against Live Data (2026-06-01)

| Subnet | Our Current | Correct (simple) | Correct (compound) | Expected (taostats-style) |
|--------|-------------|-------------------|-------------------|---------------------------|
| SN0 | 9.10% | 9.10% | 9.53% | ~6-7% (close✓) |
| SN1 | 0.47% | 57.32% | 77.39% | ~70-80% |
| SN4 | 2.04% | 44.46% | 55.99% | ~50% |
| SN9 | 0.94% | 36.93% | 44.67% | ~40% |
| SN44 | 1.14% | 30.64% | 35.85% | ~35% |
| SN77 | 0.17% | 35.97% | 43.28% | ~40% |
| SN97 | 5.08% | 199.05% | 631.75% | high (low stake) |

### Why SN0 Was "Accidentally Correct"

SN0's alpha_price = 1.0 (root alpha IS TAO). When price=1.0, multiplying by price
is a no-op, so the units bug cancels out. This is why SN0's APY looked reasonable
while all other subnets were 25-50x too low.

### Additional Findings

1. **mg.S (stake) is in ALPHA, not TAO** — proved by `sum(S) > SubnetTAO(netuid)`
2. **mg.AS (alpha_stake) ≡ mg.S in dTAO era** — same value on SN0
3. **mg.E is already post-root-split** — taostats formula matches without applying root_proportion
4. **Alpha APY ≠ TAO APY** — alpha grows but alpha price fluctuates. Industry standard (taostats) reports raw alpha yield.
5. **root_proportion should NOT be in the APY formula** — it affects emission allocation but mg.E already reflects it

### Impact of Today's Deployed Changes

The `root_proportion` parameter we added to `compute_real_apy` today (commit 41b1829)
makes the bug WORSE (multiplying by 0.84 on an already-understated value). However,
since the whole formula is being rewritten, this will be superseded.

---

## Complete Issue List (from code review)

### CRITICAL (3) — Wrong values in production

| # | Issue | Root Cause | Correct Approach |
|---|-------|-----------|-----------------|
| 1 | `pool_depth = alpha_price × 10000` (fabricated) | TODO never resolved | Read `roi.get("pool_tao_liquidity")` |
| 2-3 | `compute_real_apy` units mismatch (TAO ÷ alpha) | alpha_price in numerator but not denominator | Remove alpha_price AND root_proportion. Formula: emission/alpha_stake × (1-take) |
| 15 | `emission_share` sums different alphas without conversion | No TAO normalization | Multiply each subnet's emission by its alpha_price before summing |

### HIGH (5) — Dead or misleading metrics

| # | Issue | Fix |
|---|-------|-----|
| 5 | `competitive_density` always ≈ 0 (mixed units) | Replace with `earning_miners / max_uids` |
| 6 | `taoflow_health` always HEALTHY (empty input) | Wire stake history into the call |
| 4 | Entry slippage models wrong direction | Fix constant-product formula for buy side |
| 7 | Churn clamped to 1.0 | Remove cap |
| 8 | Missing pool_tao = 0% slippage | Use -1 (unknown) or exclude |

### MEDIUM (7) — Precision/config

| # | Issue | Fix |
|---|-------|-----|
| 9 | Sigmoid flow_score insensitive | Model actual distribution, choose better scale |
| 10 | Take rate hardcoded 0.18 | Move to thresholds |
| 11 | Two APY paths diverge | They serve different purposes — label clearly |
| 12 | EMA initialization bias | Init with mean instead of first value |
| 13 | Queue pressure cap hardcoded | Move to thresholds |
| 14 | avg_validator_activity always 0 | Remove dead field |

---

## Implementation Plan

### Phase 0: Formula Validation Test (do FIRST)

Create `scripts/validate_formulas.py` that:
1. Queries live chain for 5 subnets (SN0, SN1, SN4, SN44, SN77)
2. Computes APY using our formula
3. Computes APY using taostats formula (compound, per their docs)
4. Asserts results match within ±15% tolerance
5. Prints comparison table

**This becomes the gate for all formula changes.** Run it BEFORE and AFTER every
metrics change. If it fails after a change, the change introduced a regression.

Future enhancement: query taostats API directly and compare (needs API key).

### Phase 1: Fix CRITICALs (run validation before + after)

**Fix #2-3 (APY formula):**
- Remove `alpha_tao_price` parameter from `compute_real_apy`
- Remove `root_proportion` parameter from `compute_real_apy`  
- Formula becomes: `(emission_daily × (1-take)) / alpha_stake × 365 × 100`
- Add compound option: `((1 + epoch_yield × (1-take))^epochs_year - 1) × 100`
- Rename field to `alpha_apy_percent` (clarity: this is alpha yield, not TAO yield)
- For SN0 only: formula is the same (alpha_price=1.0, it works naturally)

**Fix #1 (pool_depth):**
- Replace `alpha_price * 10000` with `roi.get("pool_tao_liquidity", 0.0)`
- One line change

**Fix #15 (emission_share):**
- Multiply each subnet's current_total_emission by alpha_price before summing
- `total_emission_all = sum(emission * alpha_price for each subnet)`
- `emission_share = (my_emission * my_alpha_price) / total_emission_all`

### Phase 2: Fix HIGHs (run validation before + after)

Each fix is independent. Test individually.

### Phase 3: Fix MEDIUMs

Batch these. Lower risk.

### After each phase:
1. Run `scripts/validate_formulas.py` — must pass
2. Run `pytest tests/` — must pass (211 tests)
3. Deploy
4. Wait 1 refresh cycle
5. Spot-check live output against taostats

---

## Formula Validation Mechanism (Permanent)

### Level 1: Unit test (every commit)
- Property tests verify invariants (non-negative, bounded, monotone)
- Already have these. They catch structural bugs but NOT value correctness.

### Level 2: Formula truth test (every deploy)
- `scripts/validate_formulas.py` queries live chain
- Computes metrics using our formulas
- Asserts against taostats-equivalent calculation
- Gate: if this fails, don't deploy

### Level 3: Cross-provider validation (weekly)
- Compare our live output against taostats API for top-10 subnets
- Alert if divergence > 20% on any metric
- Requires taostats API key (free tier: 100 requests/day)

### Level 4: Conformance post-conditions (every invocation)
- Already deployed (Phase A + B checks)
- Add: `alpha_apy_percent > 5% for at least 50% of subnets` (catches the 1% bug)
- Add: `alpha_apy_percent < 1000% for all subnets` (catches overflow)

---

## Field Renaming Plan

| Current Field | New Field | Reason |
|---------------|-----------|--------|
| `real_apy_percent` | `alpha_apy_percent` | Clarity: this is alpha yield, not TAO yield |
| (new) | `alpha_apy_compound_percent` | Compound version (matches taostats) |
| `pool_tao_liquidity` | (keep) | Already correct naming |

---

## Lessons Learned

1. **"Validate against an oracle" should be step 1, not step N** — we built a formula, deployed it, and only now compared to taostats. Should have done this POC before writing the first line of compute_real_apy.

2. **Units bugs survive all testing** — 211 tests pass because they test properties (≥ 0, bounded, monotone) not absolute correctness. A formula that's 25x too low still passes every property test.

3. **SN0's alpha_price=1.0 masked the bug** — the one subnet we compared against (because it's "simple") happened to be the one where the units bug cancels out. Adversarial testing: always validate with subnets where alpha_price ≠ 1.0.

4. **Research the domain's existing tools first** — taostats, taoyield, and the chain itself all publish their formulas openly. We could have copied their exact formula from day 1.

5. **"Overstated by 1.6x" diagnosis was wrong** — the real error was "understated by 25x" for non-root subnets. The 1.6x observation on SN0 was coincidentally accurate because alpha_price=1.0.
