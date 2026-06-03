# Epic: Cross-Provider Metrics Validation

**Created**: 2026-06-03
**Status**: In Progress
**Priority**: P1
**Goal**: Every metric in our pipeline output is validated against at least one external source (bittensor.ai, taostats, or live chain query). No metric ships without a cross-validation gate.

---

## Context

Session 2026-06-03 discovered that APY was 10-16x wrong despite 205 passing tests. Root cause: property tests verify structural properties (≥0, bounded, monotone) but NOT value correctness. The only way to catch value bugs is cross-provider validation.

### Lessons Driving This Epic
1. Field semantics can't be assumed from names (mg.AS ≠ what you'd guess)
2. Different sites compute the same-named metric differently (yield vs total return)
3. A live POC against chain data takes 5 minutes and catches bugs mocks hide
4. This validation must be a permanent gate, not a one-time effort

---

## Tasks

### Phase 1: Validate P1 Metrics (can use existing live data)

- [ ] **1.1** Validate `net_tao_yield` against bittensor.ai "Est. per Miner" for 5 subnets
  - Compare our per-miner average vs their displayed value
  - Check if our tempo conversion (×7200/tempo) matches their "daily tao" figures
  - Subnets: SN44, SN1, SN11, SN9, SN64

- [ ] **1.2** Validate `registration_cost` against bittensor.ai "Burn Cost" for 5 subnets
  - Our reg cost is in TAO (divided from RAO by 1e9)
  - bittensor.ai shows burn cost directly
  - Subnets: SN44, SN1, SN11, SN84, SN32

- [ ] **1.3** Validate `pool_depth / slippage` against bittensor.ai "Depth" field
  - They show "100τ moves price 0.30%" — derive our equivalent
  - Our constant-product model vs their concentrated liquidity reality
  - Quantify how much our slippage is overestimated
  - Subnets: SN44 (moderate), SN84 (thin), SN1 (moderate)

- [ ] **1.4** Validate `validator_landscape.top_1_stake_share` against bittensor.ai
  - Our calculation uses `v.stake` — check which field gives correct share
  - Compare validator count (our filter: D>0) vs their displayed count
  - Subnets: SN44 (9 validators), SN1 (8), SN84 (2)

- [ ] **1.5** Validate `real_apy_percent` post-fix against bittensor.ai simulation
  - Confirm our new formula (emission / pool_alpha) matches their "Stake 1000τ → X α/day"
  - Run on 5 subnets with varying pool sizes
  - Tolerance: ±20%
  - Subnets: SN44, SN1, SN11, SN9, SN64

### Phase 2: Validate P2 Metrics (require multi-day data or manual review)

- [ ] **2.1** Validate `emission_trend` against bittensor.ai "90d emission %" 
  - Compare our day-over-day change direction vs their 7d/30d/90d trends
  - Check if our "stable" subnets match their "→" indicator

- [ ] **2.2** Validate `self_mining_risk` signals against community knowledge
  - SN104: known self-mining subnet (1 miner, "for sale") — should score high ✓
  - SN97: known abandoned — should score 1.0 ✓
  - Find 3 subnets community considers legitimate but our heuristic flags
  - Calibrate signal weights if false positives found

- [ ] **2.3** Validate `miner_churn` against bittensor.ai "Registration Activity"
  - Compare our new_registrations count vs their "This Interval" figure
  - Check churn_rate plausibility against "Slots Available: Competitive"

### Phase 3: Build Permanent Validation Gate

- [ ] **3.1** Build `scripts/validate_all_metrics.py`
  - Queries live chain for 5 reference subnets (SN0, SN1, SN9, SN44, SN84)
  - Fetches our live rankings.json
  - Computes expected values from chain data (matching bittensor.ai methodology)
  - Asserts each metric within tolerance
  - Outputs comparison table + pass/fail
  - MUST run before every deploy

- [ ] **3.2** Add conformance post-condition: APY range check
  - At least 50% of subnets with pool_tao > 1000 should have APY > 30%
  - No subnet should have APY > 5000% (catches overflow regression)
  - Add to Finalizer `_verify_outputs()`

- [ ] **3.3** Document metric definitions with "validated against" source
  - Update `kb/metrics-reference.md` Metric blocks with validation source
  - Add "Validated against: bittensor.ai [field name]" to each proven metric
  - Re-run `scripts/generate_metrics_reference.py`

---

## Acceptance Criteria

1. All P1 metrics (yield, reg cost, pool depth, validator share, APY) validated within ±20% of bittensor.ai
2. `scripts/validate_all_metrics.py` exists and passes on current live data
3. Conformance post-condition catches APY regression in production
4. No metric ships to production without a documented external validation source

---

## Progress Log

| Date | Task | Finding |
|------|------|---------|
| 2026-06-03 | APY investigation | Was 10-16x wrong. Root cause: wrong denominator (mg.AS vs pool_alpha). Fixed + validated via POC. |
| 2026-06-03 | Alpha price | Validated ✅ within 0.5% of bittensor.ai |
| 2026-06-03 | Competitive density | Validated ✅ (SN44: 7/256 = 0.027 matches "Miners: 0" + earning check) |
| 2026-06-03 | Self-mining risk | Spot-checked ✅ (SN104=0.75, SN97=1.0, SN44=0.0 — all correct) |
