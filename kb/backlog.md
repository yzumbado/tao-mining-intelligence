# TAO Mining Intelligence — Consolidated Backlog

**Last updated**: 2026-05-25
**Source**: Merged from existing KB items + code review findings

---

## Legend

- **Priority**: P0 (do now) → P3 (someday/maybe)
- **Effort**: XS (<15 min), S (15-60 min), M (1-3 hours), L (half day+)
- **Risk**: Impact if NOT done (data quality, reliability, correctness)

---

## P0 — Do Now (Quick Wins, High Impact)

### 1. Delete Dead Code (orchestrator/, collector/)
- **Effort**: XS (5 min)
- **Risk**: Container bloat, agent confusion, violates own coding standard
- **Source**: Code review + handoff doc ("2 dead code modules never imported")
- **Action**: Delete `lambda/src/orchestrator/` and `lambda/src/collector/`, commit with full context in message
- **Existing reference**: Handoff mentions "2 dead code modules" as known issue

### 2. Fix sys.path in Property Tests
- **Effort**: S (15 min)
- **Risk**: Import resolution bugs masked — the exact class of bug that blocked deployment before
- **Source**: Code review — `test_gini.py` uses `sys.path.insert(0, "lambda/src")` directly
- **Action**: Move all path setup to `tests/conftest.py`, use `from src.processor.metrics import MetricsEngine` everywhere
- **Existing reference**: Coding standards explicitly forbid this pattern

### 3. Neutralize Dormant Metrics in Attractiveness Score
- **Effort**: XS (10 min)
- **Risk**: Rankings are 25% noise (15% competitive_density that doesn't differentiate + 10% taoflow always=1.0)
- **Source**: Code review + handoff ("competitive_density effectively dead weight")
- **Action**: Set `competitive_density` weight to 0.0 and `taoflow` weight to 0.0 in `_compute_attractiveness_score()`. Redistribute to yield (0.55) and recoup (0.35). Add TODO comment for when these metrics are fixed.
- **Existing reference**: Handoff mentions both issues but no task existed

### 4. Pin pyproject.toml Dependencies
- **Effort**: XS (2 min)
- **Risk**: Local dev environment drift from production
- **Source**: Code review — pyproject.toml uses `>=` while requirements.txt is pinned
- **Action**: Change to `bittensor~=10.3`, `boto3~=1.38`, `jinja2~=3.1`, `pydantic~=2.13`

### 5. Clean Up Repo Artifacts
- **Effort**: XS (5 min)
- **Risk**: Low — cosmetic, but confuses new agents
- **Source**: Code review
- **Action**: Delete `FIX-PLAN-IMPORTS.md`, `context.md`. Add `output/` and `cdk.out/` to `.gitignore`.

---

## P1 — Next Session (Important, Moderate Effort)

### 6. ~~Redesign Attractiveness Score as Risk-Adjusted Yield~~ ✅ DONE (2026-05-25)
- **Effort**: M (1-2 hours)
- **Risk**: Current score is misleading — ranks self-mining scams (SN104) mid-pack, doesn't penalize WTA subnets where you'd earn 0, ignores liquidity
- **Source**: Live data analysis (2026-05-25) + self-mining risk metric implementation
- **Known issues with current formula**:
  1. **Effectively just yield**: recoup_score ≈ 1.0 for all subnets (reg costs near-zero), trend ≈ 0.5 for all (stable). Score collapses to linear rescaling of net_tao_yield.
  2. **No risk adjustment**: SN104 (self-mining, 1 miner, 1 validator, same coldkey, about to lose emissions) scores 0.613 — same as legitimate subnets earning similar yield.
  3. **No WTA penalty**: On WTA subnets, "average earning miner" yield is misleading. You need to be top-3 or you earn 0. Score doesn't reflect probability of actually earning.
  4. **No liquidity/slippage penalty**: Paper yield means nothing if alpha pool is too thin to convert to TAO.
  5. **Normalization ceiling**: `min(yield/100, 1.0)` caps top 10 subnets at same score — no differentiation among the best.
  6. **Two inputs permanently zeroed**: competitive_density and taoflow contribute nothing (documented in #3, #12, #13).
- **Proposed formula** (risk-adjusted):
  ```
  raw_yield_score = normalize(net_tao_yield)  # better normalization than /100
  wta_discount = 1.0 if PROPORTIONAL else (top_3_probability or 0.3 if WTA)
  slippage_penalty = 1.0 - slippage_estimate
  self_mining_penalty = 1.0 - self_mining_risk_score
  recoup_factor = max(0, 1.0 - days_to_recoup / 30)  # 30 days = zero, not 365
  
  score = raw_yield_score × wta_discount × slippage_penalty × self_mining_penalty × recoup_factor
  ```
- **Data already available** (no new collection needed):
  - `self_mining_risk.risk_score` — from compute_self_mining_risk() (just shipped)
  - `reward_distribution.model` + `top_3_concentration` — from detect_reward_distribution_model()
  - `roi_estimate.slippage_estimate_percent` — from compute_roi_estimates()
  - `validator_landscape.concentrated` — from compute_validator_landscape()
- **Action**:
  1. Redesign `_compute_attractiveness_score()` in Finalizer with multiplicative penalties
  2. Update property tests in `test_ranking.py` (bounds, monotonicity, penalty behavior)
  3. Validate against live data: SN104 should drop significantly, top legitimate subnets should remain top
  4. Update `kb/metrics-reference.md` via generator script
- **Acceptance criteria**: Self-mining subnets score < 0.3; WTA subnets without top-3 path score lower than equivalent PROPORTIONAL subnets; thin-liquidity subnets penalized
- **Dependency**: Self-mining risk metric (done), all other inputs already in derived metrics

### 7. ~~Conformance System Phase A~~ ✅ DONE (2026-05-25) — Inline Post-Conditions
- **Effort**: S (30 min)
- **Risk**: Silent data quality regressions go undetected
- **Source**: `kb/conformance-build-plan.md` — Phase A
- **Action**: Add `_verify_outputs()` to Finalizer. Checks: rankings count, no NaN, sorted, date matches, source_block > 0. Log structured JSON + CloudWatch metric on failure.
- **Existing reference**: Full design in `kb/conformance-build-plan.md`

### 8. ~~Complete StateManager as Single DynamoDB Access Layer (DAO)~~ ✅ DONE (2026-05-25)
- **Effort**: M (1-2 hours)
- **Risk**: Fragile coupling — 3 handlers bypass the DAO, accessing `_table` directly and importing private `_float_to_decimal`. Schema changes require updating both StateManager AND handlers.
- **Source**: Code review — 6 violations across Finalizer (4), Processor (1 block of 5 writes), Discovery (1)
- **Action**:
  1. Add 5 methods to StateManager:
     - `store_ranking(date, rankings)` — RANKING|LATEST
     - `store_briefing(date, summary, alerts_count, subnets_processed)` — BRIEFING|{date}
     - `get_previous_active_subnets()` — CONFIG|PREVIOUS_ACTIVE_SUBNETS
     - `scan_basic_profiles()` → dict[int, dict] — all PROFILE#basic items
     - `write_subnet_profiles(netuid, basic, winner, validator, intelligence, composability)` — 5 split profile writes
  2. Update Finalizer handler: replace 4 direct `_table` accesses with new methods
  3. Update Processor handler: replace `_write_split_profiles` internals with `write_subnet_profiles`
  4. Update Discovery handler: replace `_get_profile` internals with `scan_basic_profiles` or add `get_basic_profile(netuid)`
  5. Remove `_float_to_decimal` imports from Finalizer and Processor (now internal to StateManager)
  6. Update documentation:
     - `kb/backlog.md` — mark complete
     - `.kiro/steering/handoff.md` — update "Code Structure" section to note StateManager is the single DynamoDB access layer
     - `.kiro/steering/coding-standards.md` — add DynamoDB rule: "ALL DynamoDB access MUST go through StateManager. No handler may import `_float_to_decimal` or access `_table` directly."
- **Acceptance criteria**: `grep -r "_state_manager._table\|_float_to_decimal" lambda/src/ | grep -v state_manager.py` returns empty
- **Existing reference**: Handoff doc already lists DynamoDB PK/SK patterns — StateManager should be the only file that knows them

### 9. ~~Deep Validation Strategy — Contract Test Pattern~~ ✅ Phase A DONE (2026-05-25), Phase B pending
- **Effort**: M (2 hours)
- **Risk**: The "180 tests pass but 3 bugs ship" problem recurs
- **Source**: `kb/backlog-validation-strategy-review.md` (existing, HIGH priority)
- **Action**: 
  - Define shared output TypedDicts for each cross-component boundary
  - Make test data factories generated from these schemas
  - Add CI check: template field references must exist in producer schema
- **Enhancement from review**: Also add a contract test that `_generate_staking_rankings()` output matches what the site would consume (currently untested)

### 10. ~~Fix Staking APY — Apply Validator Take Rate (Option A)~~ ✅ DONE (2026-05-25)
- **Effort**: S (30 min)
- **Risk**: Users making staking decisions on 1.6x overstated APY
- **Source**: `kb/bug-staking-apy-overstated.md` (existing, OPEN)
- **Action**: Apply flat 18% validator take rate as interim fix. Add "estimated" label. Document that full fix (root proportion + per-validator take) requires chain data from Stage 2.
- **Enhancement from review**: Also fix the `pool_tao` estimation bug in `_generate_staking_rankings()` — currently uses `alpha_tao_rate * 1000` which is nonsensical. Use actual `pool_tao_liquidity` from derived metrics.

### 11. ~~Fix Staking Rankings Pool Data Bug~~ ✅ DONE (2026-05-25)
- **Effort**: XS (10 min)  
- **Risk**: Staking slippage estimates are meaningless
- **Source**: Code review — `_generate_staking_rankings()` line: `pool_tao = _safe_float(data.get("roi_estimate", {}).get("alpha_tao_rate", 0)) * 1000`
- **Action**: Read actual pool_tao_liquidity. The data IS available in derived metrics (from ROI computation). Just wire it correctly.

---

## P2 — This Week (Valuable, Larger Effort)

### 12. Conformance System Phase B — Auditor Lambda
- **Effort**: L (1-2 sessions)
- **Risk**: Drift between code and spec goes undetected
- **Source**: `kb/conformance-build-plan.md` — Phase B
- **Action**: Separate Lambda, hourly trigger, randomized checks (dead code, orphaned features, schema drift, never-fires). Output to `/data/audit_report.json`.

### 13. Activate Taoflow Health Metric
- **Effort**: M (1-2 hours)
- **Risk**: 10% of attractiveness score is permanently dormant
- **Source**: Code review + metrics.py docstring ("CURRENTLY DORMANT — always returns HEALTHY")
- **Action**: 
  - Add `total_validator_stake` to DynamoDB per subnet per day (one extra write in Processor)
  - After 7 days of accumulation, switch Processor to pass real history to `compute_taoflow_health()`
  - Re-enable taoflow weight in attractiveness score
- **Dependency**: Needs 7 days of data accumulation before becoming useful

### 14. Replace competitive_density with Occupancy Rate
- **Effort**: S (30 min)
- **Risk**: Current formula "mixes units" and never differentiates subnets
- **Source**: Code review + handoff ("max 0.074, formula mixes units")
- **Action**: Replace with `occupancy_rate = earning_miners / max_miners`. Simple, interpretable, actually varies across subnets. Update property tests.

### 15. EventBridge Schedule Retry on Throttling
- **Effort**: S (20 min)
- **Risk**: Subnet self-perpetuating loop dies silently on throttle
- **Source**: Code review — both `_schedule_next_collection` and `_create_schedule` swallow all exceptions
- **Action**: Re-raise `ThrottlingException` and `TooManyRequestsException` so SQS retries the Processor invocation. Keep swallowing `ConflictException` (schedule already exists = fine).

---

## P3 — Someday/Maybe (Stage 2 Prerequisites)

### 16. Full Staking APY Model (Root Proportion + Per-Validator Take)
- **Effort**: L (half day)
- **Risk**: APY remains ~80% accurate instead of ~95%
- **Source**: `kb/bug-staking-apy-overstated.md` — Option B
- **Action**: Read `tao_weight` from chain, compute root proportion per subnet, read per-validator take rate. Requires SubnetCollector changes.
- **Dependency**: Needs chain data not currently collected

### 17. Remove 4 Orphaned Features
- **Effort**: S (20 min)
- **Risk**: Low — code exists but is never called
- **Source**: Handoff ("4 orphaned features: rental_profitability, entry_barrier, seven_day_trend, top_movers")
- **Action**: Remove from schemas.py and metrics.py. Document in commit message what they were and when to re-add.
- **Note**: `rental_profitability` and `entry_barrier` are Stage 2 features (need external pricing data). Keep the algorithm code in metrics.py but remove from DerivedMetricsData model until activated.

### 18. Stage 2: LLM-Powered Subnet Researcher
- **Effort**: XL (multi-session)
- **Source**: `kb/product-vision-roadmap.md`
- **Action**: Design and implement RESEARCH stage. Reads raw data + rankings, uses LLM to classify subnets, identify strategies, and produce human-readable intelligence reports.

---

## Cross-Reference: What Was Already Tracked

| Existing Item | Location | Status in This Backlog |
|---------------|----------|----------------------|
| Staking APY bug | `kb/bug-staking-apy-overstated.md` | Enhanced → items #10, #11, #16 |
| Validation strategy review | `kb/backlog-validation-strategy-review.md` | Enhanced → item #9 |
| Conformance Phase A | `kb/conformance-build-plan.md` | Unchanged → item #7 |
| Conformance Phase B | `kb/conformance-build-plan.md` | Unchanged → item #12 |
| Dead code (orchestrator/collector) | Handoff doc | Promoted to P0 → item #1 |
| competitive_density dead weight | Handoff doc | Split → items #3 (neutralize) + #14 (replace) |
| Taoflow dormant | Handoff doc (implicit) | New explicit task → item #13 |
| Orphaned features | Handoff doc | Moved to P3 → item #17 |
| Attractiveness score unreliable | Live analysis 2026-05-25 | New → item #6 |

## Items Added From Code Review (Not Previously Tracked)

| # | Item | Why Not Caught Before |
|---|------|---------------------|
| 2 | sys.path in tests | Pattern existed since Phase 3, never audited |
| 4 | pyproject.toml pinning | Dev vs prod divergence not tested |
| 5 | Repo artifacts | Accumulated during debugging sessions |
| 8 | StateManager encapsulation | Worked fine, but fragile coupling |
| 11 | Pool data bug in staking | Staking rankings added late, not reviewed |
| 15 | Schedule retry on throttle | Happy path worked in first run |
