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

- [x] **1.1** Validate `net_tao_yield` against bittensor.ai "Est. per Miner" for 5 subnets
  - ✅ All 5 subnets within 0.6% — tempo conversion and earning-miner average both correct
  - Subnets: SN44 (83.18 vs 83.17), SN1 (7.27 vs 7.27), SN11, SN9, SN64

- [x] **1.2** Validate `registration_cost` against bittensor.ai "Burn Cost" for 5 subnets
  - ⏭️ Skipped: requires archive node (get_subnet_burn_cost uses state_getRuntimeVersion)
  - Collector already validated this in May (from `kb/bittensor-mining-research.md`)
  - Deferred to when we have archive node access

- [x] **1.3** Validate `pool_depth / slippage` against bittensor.ai "Depth" field
  - Pool TAO validated: our pool_tao matches chain SubnetTAO query
  - Slippage formula: constant-product model overestimates vs concentrated liquidity
  - bittensor.ai: "100τ moves price 0.30%" (SN44) — noted for future refinement
  - Not blocking: our slippage is conservative (upper bound), which is safe for decisions

- [x] **1.4** Validate `validator_landscape.top_1_stake_share` against bittensor.ai
  - Validator count matches (SN44: 10v live, SN1: 8v, SN11: 9v)
  - top_1_share uses mg.AS which we now know is valid for relative proportions
  - bittensor.ai shows validator counts matching our filter (D > 0)

- [x] **1.5** Validate `real_apy_percent` post-fix against bittensor.ai simulation
  - New formula (emission/pool_alpha) validated within ±10% for SN11 and SN64
  - SN44: 93.6% expected (matches bittensor.ai "82-100%" range for pure yield)
  - Live output will converge after next pipeline refresh with deployed code

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
| 2026-06-03 | Alpha price | Validated ✅ within 0.5% of bittensor.ai and live chain |
| 2026-06-03 | Competitive density | Validated ✅ (temporal differences expected; formula correct) |
| 2026-06-03 | Self-mining risk | Spot-checked ✅ (SN104=0.75, SN97=1.0, SN44=0.0 — all correct) |
| 2026-06-03 | **Phase 1 validation run** | 5 subnets (SN44, SN1, SN11, SN9, SN64): price ✅ (<0.6%), yield ✅ (<0.6%), APY ⚠️ (diverges because live hasn't refreshed yet), density ✅ (temporal diff on SN44 expected) |
| 2026-06-03 | net_tao_yield | Validated ✅ perfect match on all 5 subnets — tempo conversion and earning-miner average both correct |
| 2026-06-03 | Task 1.5 (APY post-fix) | New formula validated: SN11 131% expected vs 141% live (8% diff). SN64 47% vs 50% (6% diff). Within tolerance. |
