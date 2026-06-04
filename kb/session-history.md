# Session History (archived from handoff.md)
### Session 2026-06-01 Findings (context for next agent):

#### Major Accomplishments:
- **APY formula completely rewritten** — was off by 25x for non-root subnets (units mismatch: TAO ÷ alpha). Now matches taostats within 0.1% (validated against 5 live subnets).
- **Formula validation gate created** — `scripts/validate_formulas.py` queries live chain, computes APY with taostats formula, asserts ours matches ±20%. Must pass before every deploy.
- **3 CRITICAL score bugs fixed** — pool_depth (fabricated proxy → real liquidity), emission_share (mixed alphas → TAO-normalized), APY (broken units → compound alpha yield)
- **3 HIGH metric bugs fixed** — competitive_density (mixed units → occupancy rate), churn cap removed, pool exclusion for missing data
- **14 new chain fields collected per subnet** (Tier 1: SubnetEmaTaoFlow, SubnetVolume, RegistrationsThisInterval, SubnetOwner, emissions, TotalStake, etc.)
- **Net flow EMA wired into attractiveness score** (stake history now 7 days, active)
- **CloudFront cache fix deployed** (30 min TTL + invalidation)
- **Dead code removed** — rental_profitability, entry_barrier, top_movers (123 lines + schemas + tests)
- **Daily emission collection started** — enables taoflow_health fix on 2026-06-08
- **Full chain data inventory** — 217 items catalogued (kb/chain-data-inventory.md)

#### Live Production State (post-deploy):
- 49-129 subnets (UTC day rollover, fills within hours)
- SN44: score 0.836, APY 35.8% (was 1.14% before fix)
- Score spread: 0.79 (was 0.33 — much better differentiation)
- All conformance checks passing
- CloudFront serving fresh data (no more 23h stale cache)

#### Pending Tasks (next session):

**Documentation (P1 — 1-2 hours):**
- [x] Rewrite `design.md` — DONE 2026-06-03 (2091 → 425 lines)
- [x] Rewrite `requirements.md` — DONE 2026-06-03 (43 → 19 requirements)
- [x] Full `handoff.md` refresh — DONE 2026-06-03
- [x] Regenerate `kb/metrics-reference.md` — DONE 2026-06-03 (13 → 17 metrics)

**Deferred Fixes (P2 — documented in kb/metrics-math-audit-2026-06-01.md):**
- [ ] Fix #4: Entry slippage direction — needs redesign. API price (0.044) ≠ pool spot price (0.024). Use pool_tao/pool_alpha as spot.
- [ ] Fix #6: taoflow_health always HEALTHY — wire after 2026-06-08 when emission history has 7 days.
- [ ] MEDIUM fixes: sigmoid scale tuning, hardcoded thresholds → DynamoDB, dead avg_validator_activity field.

**Backlog (P3 — next major feature):**
- [ ] DeepCollector Lambda (Tiers 2-4) — per-UID and per-hotkey chain data. Spec in `kb/backlog-deep-collector.md`. Builds historical dataset for pattern detection.
- [ ] Stage 2: RESEARCH — LLM-powered subnet researcher (GitHub scraping, code analysis, difficulty classification)

#### Key Patterns Discovered This Session:
1. **"Validate against an oracle FIRST"** — We built the APY formula, deployed it, and only compared to taostats 2 weeks later. The POC should have been step 1. Now we have `scripts/validate_formulas.py` as a permanent gate.
2. **"SN0 masked the bug"** — alpha_price=1.0 on root means any formula involving price multiplication "accidentally works" on SN0 but fails on all other subnets. Always test with subnets where alpha_price ≠ 1.0.
3. **"Units bugs survive all testing"** — 211 tests passed while APY was 25x wrong. Property tests (≥ 0, bounded, monotone) catch structural bugs but NOT value correctness. You need cross-provider validation.
4. **"POC before coding"** — The slippage fix (#4) would have been wrong if coded without the POC. The POC revealed a deeper issue (API price ≠ pool spot price) that changed the fix approach entirely.
5. **"Collect everything now, analyze later"** — Historical chain data can't be backfilled. Collecting Tier 1 (14 fields) and daily emission now builds the dataset for future pattern detection even before we have code to analyze it.
- SN104 investigation: self-mining subnet (1 miner, 1 validator, same coldkey, "for sale" description) — scored 0.613 mid-pack
- Const announced emission blocking for self-mining/abandoned/fraudulent subnets
- Ecosystem research: taostats, TAO Institute (SRI), Taoculator all use Net TAO Flow, real APY, VTrust, pool depth
- Our attractiveness score was effectively just net_tao_yield (recoup≈1.0, trend≈0.5 for all subnets)
- Redesigned to risk-adjusted formula with self-mining penalty — SN104 would now score near 0
- Test audit found 2 CRITICAL lies: alpha_price never reached processor (wrong S3 path), self_mining_risk never tested non-zero
- Daily stake accumulation started — Net TAO Flow will activate after 7 days of data (2026-06-01)
- 6 MEDIUM test lies remain (see backlog or ask for details)
- Deployed all changes to production at 22:24 UTC — new output expected within 1-2 hours of deploy
- Validator concentration: 47% of subnets have top1 > 50% — binary flag useless, replaced with tiered risk
- Emission trend is NOT broken: 127/129 subnets show 0% change because Bittensor emissions change slowly (30d EMA)
- Contract smoke test (Phase A) catches field renames/type changes between Processor→Finalizer

### Pending verification (next agent should check):
- [ ] New rankings output has fields: self_mining_risk, real_apy_percent, concentration_risk
- [ ] SN104 attractiveness_score is near 0 (self-mining penalty applied)
- [ ] Top subnet scores are ~0.5-0.6 (not 0.95 ceiling)
- [ ] Conformance post-condition logs appear in CloudWatch (search for "conformance")
- [ ] source_block_number is non-zero in metadata.json (was 0 before deploy)
- [ ] Staking APY for SN0 is ~9% (was 11%, reduced by take rate)

### Patterns discovered this session (propagate to future work):
1. **"Test the contract, not the unit"** — 206 unit tests passed while 2 CRITICAL contract bugs existed. The contract smoke test (run real Processor → feed to real Finalizer) catches what unit tests can't.
2. **"Research before building"** — 30 min of ecosystem research (taostats, TAO Institute, Taoculator) completely changed our scoring approach. Without it, we'd have built more of the same broken formula.
3. **"Live data validates hypotheses"** — SN104 investigation proved our score was broken. Validator concentration analysis proved the binary flag was useless. Emission trend analysis proved it wasn't a bug.
4. **"Multiplicative penalties > additive weights"** — The old score added factors (all near 1.0 = no differentiation). The new score multiplies penalties (risk=1.0 → score=0.0). Much more effective.
5. **"Deploy early, verify live"** — We deployed mid-session rather than batching. This lets us verify the new code works in production before the session ends.
6. **"Silent correctness bugs pass all tests"** — The emission_share bug (reading from wrong field, always returning 0) passed all 210 tests AND the contract smoke test. It didn't crash — it just made the score silently wrong. Contract tests catch structural breaks (missing fields, type errors) but NOT semantic bugs where a field exists but has the wrong value. Mitigation: add conformance checks that validate value ranges ("emission_share should be > 0 for at least some subnets").
7. **"Review before closing catches bugs"** — The emission_share bug was found during the session wrap-up review, not during development. Always do a critical review of your own work before declaring done.

### Pending conformance checks to add (Phase B or next session):
- [ ] emission_share > 0 for at least some subnets (catches the silent-zero bug pattern)
- [ ] self_mining_risk > 0 for at least 1 subnet (SN104 should always trigger)
- [ ] concentration_risk.tier != "healthy" for at least some subnets (47% should be non-healthy)
- [ ] real_apy_percent > 0 for subnets with active validators
- [ ] pool_tao_liquidity > 0 for subnets with alpha_price > 0
- [ ] attractiveness_score spread: max - min > 0.3 (if all scores cluster, formula is broken)

### Architecture state after this session:
- MetricsEngine: 17 algorithms (was 15), all pure functions, 607 duplicate lines removed
- StateManager: sole DynamoDB access layer (was fragmented across 3 handlers)
- Finalizer: conformance post-conditions run on every invocation (10 checks now)
- Pipeline: accumulating daily stake data (STAKE_HISTORY#{netuid}#{date})
- Contract test: Processor→Finalizer boundary validated with real data flow
- Attractiveness score: risk-adjusted (yield×0.30 + flow×0.25 + emission×0.25 + depth×0.20 × penalty)
- APY: uses pool_alpha denominator (validated against bittensor.ai within ±10%)
- Rankings output: now includes concentration_risk field

### Session 2026-06-03 Findings (context for next agent):

#### Major Accomplishments:
- **APY formula rewritten AGAIN** — was 10-16x too low (wrong denominator: mg.AS vs pool_alpha). POC against live chain confirmed pool_tao/alpha_price is the correct denominator. Now matches bittensor.ai per-staker simulation within ±10%.
- **APY overflow eliminated** — 21 subnets had APY >1000% (SN122 at 128 BILLION %). Root cause: near-zero stake + compound exponentiation. Fixed with stake guard (<100) and rate guard (>2.0).
- **Self-mining false positives fixed** — was 76/129 (59%) flagged. Root cause: Signal 1 fired on all WTA subnets (1 earning miner). Fixed: now requires validators ≤ 2 to fire.
- **607 lines of dead duplicate code removed** from metrics.py
- **design.md rewritten** — old 2091 lines (batch model) → 425 lines (actual AD18 architecture)
- **requirements.md rewritten** — old 43 requirements (600 lines, batch model) → 19 requirements (237 lines, actual system)
- **docs/architecture/ deleted** — was a stale duplicate of .kiro/specs/design.md
- **Permanent validation gate created** — `scripts/validate_all_metrics.py` queries live chain, compares 5 subnets, exits 1 on failure. MUST pass before every deploy.
- **Conformance checks 9-10 added** — APY overflow (>5000%) and APY floor (>20% for 30%+ subnets)
- **Metrics validation epic created** — `kb/epic-metrics-validation.md` (Phase 1-3 complete, Phase 4 backlog)

#### Cross-Validation Results (live chain, 5 subnets):
- alpha_price: ✅ <0.6% deviation
- net_tao_yield: ✅ <0.6% deviation
- real_apy_percent: ✅ within ±10% (new formula)
- competitive_density: ✅ correct formula
- self_mining_risk: ✅ true positives confirmed, false positive fixed

#### Key Patterns Discovered:
1. **"mg.AS ≠ pool alpha"** — mg.AS includes consensus-locked alpha beyond the staking pool. pool_tao/alpha_price is the correct denominator for per-staker yield.
2. **"Same name, different metric"** — bittensor.ai's "496% staker APY" includes price appreciation. Their per-staker simulation ("Stake 1000τ → 40.70α/day") gives 82% pure yield. Always compare against the SIMULATION, not the headline.
3. **"Property tests can't catch value bugs"** — 205 tests passed while APY was 10x wrong. Only cross-provider validation catches these.
4. **"59% false positive = broken heuristic"** — The self-mining signal was too aggressive for WTA subnets. Gate on validator count fixed it.
5. **"POC first, always"** — The live chain POC (5 min to write) immediately revealed the mg.AS issue that would have taken hours to figure out from code alone.

#### Pending Tasks (next session):

**Deployment (P0 — deploy code to Lambda):**
- [ ] Deploy current code to Lambda (APY fix, self-mining fix, concentration_risk in output)
- [ ] Run `scripts/validate_all_metrics.py` after pipeline refreshes — should show 0 failures
- [ ] Verify production APY: SN44 should be ~80-100%, not 36%

**Epic Phase 4 (P2 — findings from validation):**
- [ ] Fix briefing "new subnet" false alerts (129/129 show as new every run)
- [ ] Label slippage as "upper bound (constant-product model)"
- [ ] Monitor emission_trend for first real non-stable event

**Backlog (P3):**
- [ ] Phase 3 task 3.3: Update metrics-reference.md with "validated against" sources
- [ ] taoflow_health activation (needs 7+ days emission history — check after 2026-06-08)
- [ ] DeepCollector Lambda (per-UID chain data)
- [ ] Stage 2: RESEARCH (LLM-powered subnet researcher)

### Session 2026-05-19 Findings (context for next agent):
- Output contract bugs: tests used idealized mock data that didn't match production shapes
- Emission alert threshold was 10% but real emission changes are < 0.2% — lowered to 1%
- 4 orphaned features in code (rental_profitability, entry_barrier, seven_day_trend, top_movers) — defined but never called
- 2 dead code modules (orchestrator/, collector/) — never imported, still in container
- competitive_density metric is effectively dead weight — never differentiates subnets in production (max 0.074, formula mixes units)
- "feat without test" commit pattern predicted 2/3 of bugs found
