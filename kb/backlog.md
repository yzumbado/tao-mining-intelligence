# TAO Mining Intelligence — Consolidated Backlog

**Last updated**: 2026-05-21
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

### 6. Conformance System Phase A — Inline Post-Conditions
- **Effort**: S (30 min)
- **Risk**: Silent data quality regressions go undetected
- **Source**: `kb/conformance-build-plan.md` — Phase A
- **Action**: Add `_verify_outputs()` to Finalizer. Checks: rankings count, no NaN, sorted, date matches, source_block > 0. Log structured JSON + CloudWatch metric on failure.
- **Existing reference**: Full design in `kb/conformance-build-plan.md`

### 7. StateManager Encapsulation — Stop Direct `_table` Access
- **Effort**: S (30 min)
- **Risk**: Finalizer breaks silently if StateManager internals change
- **Source**: Code review — Finalizer accesses `_state_manager._table` directly in 5+ places
- **Action**: Add methods: `store_ranking(date, rankings)`, `store_briefing(date, briefing)`, `scan_basic_profiles()`, `store_previous_active_subnets(netuids)`. Update Finalizer to use them.

### 8. Deep Validation Strategy — Contract Test Pattern
- **Effort**: M (2 hours)
- **Risk**: The "180 tests pass but 3 bugs ship" problem recurs
- **Source**: `kb/backlog-validation-strategy-review.md` (existing, HIGH priority)
- **Action**: 
  - Define shared output TypedDicts for each cross-component boundary
  - Make test data factories generated from these schemas
  - Add CI check: template field references must exist in producer schema
- **Enhancement from review**: Also add a contract test that `_generate_staking_rankings()` output matches what the site would consume (currently untested)

### 9. Fix Staking APY — Apply Validator Take Rate (Option A)
- **Effort**: S (30 min)
- **Risk**: Users making staking decisions on 1.6x overstated APY
- **Source**: `kb/bug-staking-apy-overstated.md` (existing, OPEN)
- **Action**: Apply flat 18% validator take rate as interim fix. Add "estimated" label. Document that full fix (root proportion + per-validator take) requires chain data from Stage 2.
- **Enhancement from review**: Also fix the `pool_tao` estimation bug in `_generate_staking_rankings()` — currently uses `alpha_tao_rate * 1000` which is nonsensical. Use actual `pool_tao_liquidity` from derived metrics.

### 10. Fix Staking Rankings Pool Data Bug
- **Effort**: XS (10 min)  
- **Risk**: Staking slippage estimates are meaningless
- **Source**: Code review — `_generate_staking_rankings()` line: `pool_tao = _safe_float(data.get("roi_estimate", {}).get("alpha_tao_rate", 0)) * 1000`
- **Action**: Read actual pool_tao_liquidity. The data IS available in derived metrics (from ROI computation). Just wire it correctly.

---

## P2 — This Week (Valuable, Larger Effort)

### 11. Conformance System Phase B — Auditor Lambda
- **Effort**: L (1-2 sessions)
- **Risk**: Drift between code and spec goes undetected
- **Source**: `kb/conformance-build-plan.md` — Phase B
- **Action**: Separate Lambda, hourly trigger, randomized checks (dead code, orphaned features, schema drift, never-fires). Output to `/data/audit_report.json`.

### 12. Activate Taoflow Health Metric
- **Effort**: M (1-2 hours)
- **Risk**: 10% of attractiveness score is permanently dormant
- **Source**: Code review + metrics.py docstring ("CURRENTLY DORMANT — always returns HEALTHY")
- **Action**: 
  - Add `total_validator_stake` to DynamoDB per subnet per day (one extra write in Processor)
  - After 7 days of accumulation, switch Processor to pass real history to `compute_taoflow_health()`
  - Re-enable taoflow weight in attractiveness score
- **Dependency**: Needs 7 days of data accumulation before becoming useful

### 13. Replace competitive_density with Occupancy Rate
- **Effort**: S (30 min)
- **Risk**: Current formula "mixes units" and never differentiates subnets
- **Source**: Code review + handoff ("max 0.074, formula mixes units")
- **Action**: Replace with `occupancy_rate = earning_miners / max_miners`. Simple, interpretable, actually varies across subnets. Update property tests.

### 14. EventBridge Schedule Retry on Throttling
- **Effort**: S (20 min)
- **Risk**: Subnet self-perpetuating loop dies silently on throttle
- **Source**: Code review — both `_schedule_next_collection` and `_create_schedule` swallow all exceptions
- **Action**: Re-raise `ThrottlingException` and `TooManyRequestsException` so SQS retries the Processor invocation. Keep swallowing `ConflictException` (schedule already exists = fine).

---

## P3 — Someday/Maybe (Stage 2 Prerequisites)

### 15. Full Staking APY Model (Root Proportion + Per-Validator Take)
- **Effort**: L (half day)
- **Risk**: APY remains ~80% accurate instead of ~95%
- **Source**: `kb/bug-staking-apy-overstated.md` — Option B
- **Action**: Read `tao_weight` from chain, compute root proportion per subnet, read per-validator take rate. Requires SubnetCollector changes.
- **Dependency**: Needs chain data not currently collected

### 16. Remove 4 Orphaned Features
- **Effort**: S (20 min)
- **Risk**: Low — code exists but is never called
- **Source**: Handoff ("4 orphaned features: rental_profitability, entry_barrier, seven_day_trend, top_movers")
- **Action**: Remove from schemas.py and metrics.py. Document in commit message what they were and when to re-add.
- **Note**: `rental_profitability` and `entry_barrier` are Stage 2 features (need external pricing data). Keep the algorithm code in metrics.py but remove from DerivedMetricsData model until activated.

### 17. Stage 2: LLM-Powered Subnet Researcher
- **Effort**: XL (multi-session)
- **Source**: `kb/product-vision-roadmap.md`
- **Action**: Design and implement RESEARCH stage. Reads raw data + rankings, uses LLM to classify subnets, identify strategies, and produce human-readable intelligence reports.

---

## Cross-Reference: What Was Already Tracked

| Existing Item | Location | Status in This Backlog |
|---------------|----------|----------------------|
| Staking APY bug | `kb/bug-staking-apy-overstated.md` | Enhanced → items #9, #10, #15 |
| Validation strategy review | `kb/backlog-validation-strategy-review.md` | Enhanced → item #8 |
| Conformance Phase A | `kb/conformance-build-plan.md` | Unchanged → item #6 |
| Conformance Phase B | `kb/conformance-build-plan.md` | Unchanged → item #11 |
| Dead code (orchestrator/collector) | Handoff doc | Promoted to P0 → item #1 |
| competitive_density dead weight | Handoff doc | Split → items #3 (neutralize) + #13 (replace) |
| Taoflow dormant | Handoff doc (implicit) | New explicit task → item #12 |
| Orphaned features | Handoff doc | Moved to P3 → item #16 |

## Items Added From Code Review (Not Previously Tracked)

| # | Item | Why Not Caught Before |
|---|------|---------------------|
| 2 | sys.path in tests | Pattern existed since Phase 3, never audited |
| 4 | pyproject.toml pinning | Dev vs prod divergence not tested |
| 5 | Repo artifacts | Accumulated during debugging sessions |
| 7 | StateManager encapsulation | Worked fine, but fragile coupling |
| 10 | Pool data bug in staking | Staking rankings added late, not reviewed |
| 14 | Schedule retry on throttle | Happy path worked in first run |
