---
inclusion: always
---

# Agent Handoff: TAO Mining Intelligence Pipeline

## Who Is the User

- SDM at Amazon, strong software development knowledge
- Wants a partnership, not a boss/subordinate dynamic — push back when something is wrong
- Values rigorous thinking — proactively identify gaps, don't wait to be asked
- Prefers working backwards from usage scenarios
- Communicates in English (native Spanish speaker)
- Uses Kiro as the primary development environment

## Working Style & Expectations

- **Don't be a yes-man**: Challenge assumptions, identify what's missing, suggest improvements
- **Proactive**: If you see a gap (security, testing, architecture), raise it immediately
- **Research before answering**: This is a niche domain (Bittensor). Validate claims against live data
- **Keep documents in sync**: When you change requirements, update design, KB, and tasks too
- **TDD is mandatory**: Write property test FIRST, then implement, then verify
- **Validate assumptions with live data**: The Bittensor SDK has surprises (fields removed, types changed)
- **Commit frequently**: After completing a phase or fixing a bug, commit and push

## Project Overview

An autonomous pipeline that continuously collects Bittensor subnet data, computes mining/validating intelligence metrics, and serves structured data to Kiro for TAO accumulation strategy decisions.

**Primary goal**: Accumulate TAO through mining or validating — not USD conversion.

**Long-term vision**: A 7-stage autonomous TAO machine that discovers opportunities, researches requirements, builds mining agents, tests strategies, deploys on-chain, and self-optimizes. See `kb/product-vision-roadmap.md` for the full roadmap.

**Current stage**: Stage 1 (COLLECT) is complete and autonomous. Stage 2 (RESEARCH) is next.

## How to Orient Yourself

1. **Start here**: This file (handoff.md) — project context, pending tasks, session history
2. **Architecture**: `.kiro/specs/tao-mining-intelligence-pipeline/design.md` — 425-line system design (rewritten 2026-06-03)
3. **Requirements**: `.kiro/specs/tao-mining-intelligence-pipeline/requirements.md` — 19 requirements (rewritten 2026-06-03)
4. **Coding standards**: `.kiro/steering/coding-standards.md` — ALWAYS follow these
5. **Current work**: `kb/epic-metrics-validation.md` — active epic with pending tasks
6. **Knowledge base**: `kb/` directory — research findings, architecture decisions, validation audits
7. **Validated SDK behavior**: SDK Gotchas section below + `kb/bittensor-mining-research.md`

## Pipeline Data Flow

```
Discovery Lambda (hourly safety net)
    ├── Queries chain for active subnets
    ├── Checks each subnet's processed_at for staleness
    └── Creates EventBridge schedules for new/stale subnets
                │
                ▼
EventBridge Scheduler (one-time, per subnet, self-perpetuating)
                │
                ▼
SubnetCollector Lambda (one subnet per invocation)
    ├── Collects metagraph from Bittensor chain
    ├── Collects hyperparameters, alpha price, reg cost
    ├── Validates (warn on quality issues, don't reject)
    ├── Stores raw snapshot to S3 (with collected_at, source_block)
    └── Sends SQS message → Processing Queue
                │
                ▼
Processor Lambda (one invocation per subnet)
    ├── Reads raw snapshot from S3
    ├── Reads previous-day snapshot for trend comparison
    ├── Runs MetricsEngine (pure functions) on the data
    ├── Stores derived metrics to S3 (with processed_at)
    ├── Writes profiles to DynamoDB (with processed_at)
    ├── Invokes Finalizer (async) → rankings recompute
    └── Creates next EventBridge schedule (tempo-based, self-perpetuating)
                │
                ▼
Finalizer Lambda (invoked after each subnet completes)
    ├── Reads ALL current profiles from DynamoDB
    ├── Generates rankings from whatever data exists
    ├── Generates daily briefing (rolling 24h changes)
    └── Stores rankings + briefing to S3
```

## Reference Implementation: Collector Lambda

The SubnetCollector is the completed reference for how Lambda handlers should be built. Use it as the pattern for new handlers:

- **Handler**: `lambda/src/subnet_collector/handler.py` — module-level singletons for config/state/storage, `handle()` entry point, full instrumentation
- **Pattern**: Module caches (`_config`, `_state_manager`, `_storage`), reset in test fixtures. Tests use `@mock_aws` + moto. Each test class covers one concern.

## Key Architecture Decisions

- **Container Image Lambda** (not zip) — Bittensor SDK is 200-300MB
- **Self-scheduling per-subnet loops** (AD18) — each subnet refreshes independently at its tempo cadence
- **EventBridge Scheduler one-time schedules** — self-cleaning, exact timing, no orchestrator in hot path
- **Discovery Lambda** (hourly) — safety net for new/stale subnets, not a coordinator
- **Rankings as live view** — recomputed after each subnet update, not gated on "all complete"
- **Two S3 buckets** — private data + CloudFront-only site
- **DynamoDB single-table** with split profiles (400KB limit)
- **Jinja2 + Tailwind CSS** (not MkDocs) — direct HTML generation
- **Configurable thresholds** in DynamoDB (editable via AWS Console)
- **Circuit breaker** + per-operation timeouts
- **Validation warns, doesn't reject** — data quality flag in metadata, processing continues

## SDK Gotchas (Validated Live)

- `blocks_since_last_step` is a **plain int scalar**, NOT per-neuron array — cannot index with `[i]`
- `mg.n` is a **numpy ndarray scalar** — use `int(mg.n)` for range() and JSON serialization
- `mg.block` is a **numpy ndarray scalar** — this is the current chain block, use `int(mg.block)`
- `mg.block_at_registration[0]` is NOT the current block — it's UID 0's registration block (historical)
- `mg.hotkeys[i]` returns plain `str` — no cast needed
- `R` (rank) and `T` (trust) fields **don't exist** in SDK v10
- Emission is in **alpha tokens per tempo** — multiply by `7200/tempo` for daily
- `active` field is int64 (0/1), not bool — cast with `bool()`
- Registration cost from chain is in RAO — divide by 1e9 for TAO
- `get_subnet_price()` returns a Balance object — use `float(price)`
- Only 4/247 miners earn on SN1 (extreme Winner-Takes-All)
- Finney endpoint sometimes hangs — circuit breaker handles this
- No NaN/Inf observed in emission arrays on SN1 (but guard against it)
- `mg.AS` includes **consensus-locked alpha beyond the pool** — NOT pure staked alpha. For APY, use `pool_tao / alpha_price` as denominator.
- `mg.S` is NOT just TAO stake — it's total effective weight (alpha + root-weighted TAO). `sum(mg.S) * price > TVL`.
- `mg.TS` = `mg.S - mg.AS` (root TAO portion only), NOT total_stake = S + AS.

## Code Structure

```
lambda/src/
├── config.py              # PIPELINE_ENV switching (local vs aws)
├── instrumentation.py     # Tracing with trace_id propagation
├── validation.py          # Data validation at ingestion (incl. NaN/Inf guard)
├── circuit_breaker.py     # Circuit breaker + timeout utilities
├── thresholds.py          # Configurable parameters with defaults
├── sanity_check.py        # Post-processing data quality checks
├── lambda_patch.py        # Bittensor multiprocessing.Queue patch for Lambda
├── models/
│   ├── enums.py           # All enumerations
│   └── schemas.py         # All Pydantic v2 data models
├── state/
│   └── state_manager.py   # DynamoDB FSM + config + hotkey tracking
├── storage/
│   └── storage_layer.py   # S3/local filesystem with compression
├── discovery/
│   └── handler.py         # ✅ Discovery Lambda (hourly safety net)
├── subnet_collector/
│   └── handler.py         # ✅ SubnetCollector Lambda (one subnet per invocation)
├── processor/
│   ├── metrics.py         # ALL algorithms (17 pure functions, no AWS)
│   └── handler.py         # ✅ Processor Lambda (metrics + profiles + hotkeys)
├── finalizer/
│   └── handler.py         # ✅ Finalizer Lambda (briefing + ranking + site + conformance)
└── site_generator/
    └── generator.py       # ✅ Jinja2 HTML generation
```

## What's Next (Post-Development)

### Deployment: COMPLETE ✅ (2026-05-17)
- Stack deployed to AWS account 651484323929 (us-east-1)
- First live run: 129 subnets collected, 128 processed, rankings generated
- CloudFront URL: `https://dkfh19zkgqq18.cloudfront.net`
- All resources within free tier ($0/month validated)

### Architecture Decision 18: Independent Subnet Refresh (FULLY IMPLEMENTED)
- All phases complete: self-scheduling loops, Discovery Lambda, Aggregator invocation, documentation overhaul
- Old batch resources removed from CDK (Orchestrator, SNS, completion queue)
- llms.txt, metadata.json, staleness alarm all deployed
- See `kb/architecture-decision-18-independent-refresh.md` for full design

### Completed:
- ✅ Phase 1: SDK validation (connectivity, DynamoDB, SQS/SNS)
- ✅ Phase 2: Core infrastructure (StateManager, StorageLayer, Instrumentation, Validation, Circuit Breaker)
- ✅ Phase 3: Metrics Engine (17 algorithms, property + unit tests)
- ✅ Phase 4: Lambda Handlers (Collector 16 tests, Processor 17 tests, Finalizer 12 tests, FSM + Discovery property tests)
- ✅ Phase 5: Site & Deployment (Jinja2 site 9 tests, CDK 11 tests, E2E integration 2 tests, sanity check)
- ✅ Security hardening: SSM scoped ARN, DLQ on all queues, S3 encryption, NaN/Inf validation, error propagation
- ✅ Deployment: Docker import fix, ARM64, lambda_patch, DLQ alarms, OPERATIONS.md
- ✅ First live run: 129/129 collected, 128 processed, rankings generated
- ✅ AD18 Phase 1: Configurable refresh policy, processed_at timestamps, validation relaxation
- ✅ Tech debt: zero known issues
- ✅ Metrics data fix: active field misinterpretation (deregistration risk, density, attractiveness ceiling)
- ✅ Staking Intelligence: compute_staking_yield metric + staking_rankings.json endpoint
- ✅ HTML site generation: index.html, rankings.html, briefing.html via Jinja2
- ✅ SNS alerting: staleness alarm → yzumbado@gmail.com
- ✅ Auto-generated metrics reference: kb/metrics-reference.md from code docstrings
- ✅ Agent plan execution research: kb/agent-plan-execution-research.md
- ✅ Self-mining risk detection: compute_self_mining_risk() — 4 signals, 7 property tests
- ✅ Proven ecosystem metrics: real APY, Net TAO Flow (EMA), VTrust surfacing, daily stake accumulation
- ✅ Attractiveness score redesign: risk-adjusted formula (yield×0.30 + flow×0.25 + emission×0.25 + depth×0.20 × self_mining_penalty)
- ✅ Test audit + fixes: 2 CRITICAL (S3 path mismatch, missing mock fields) + 4 HIGH (ranking toy test, dereg always 0, unrealistic emissions, threshold by accident)

### Descoped (Phase 2+):
- `subnet.html` and `health.html` templates (4 templates shipped, 2 deferred)
- Docker Compose local dev environment
- Smoke test script (E2E integration test covers this with moto)
- JSON Schema files in config/schemas/ (outputs are validated by Pydantic models instead)
- LLM-powered Subnet Researcher

### Open Bugs:
- None critical. All known bugs from previous sessions have been fixed.

### Known Limitations (not bugs):
- Slippage model uses constant-product formula but Bittensor now uses concentrated liquidity (v3) — our estimate is a conservative upper bound
- Emission trend shows "stable" for all 129 subnets (correct: emissions are EMA-smoothed and rarely change >1%/day)
- Briefing shows all 129 subnets as "new" on each run (stale baseline comparison — see epic Phase 4.1)
- bittensor.ai's headline "staker APY" (496%) includes alpha price appreciation; ours reports pure dividend yield (~82%) — intentionally different metric

### Conformance System: DEPLOYED (Phase A+B)
- Inline post-conditions run in Finalizer on every invocation (10 checks)
- Checks: rankings count, NaN/Inf, sort order, briefing date, source_block, score spread, self-mining, APY range (overflow + floor)
- Logs structured findings to CloudWatch (never blocks pipeline)
- Phase C-E (cross-day drift, automated remediation) remain as backlog



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

> **Previous sessions**: See `kb/session-history.md` for 2026-06-01 and earlier findings.


## How to Run Tests

```bash
# Requires Python 3.12+ (project won't install on 3.9)
# If setting up fresh: /opt/homebrew/bin/python3.12 -m venv .venv

source .venv/bin/activate
.venv/bin/pytest tests/ -v          # All 205 tests
.venv/bin/pytest tests/properties/  # Property tests only
.venv/bin/pytest tests/unit/        # Unit tests only
.venv/bin/pytest tests/integration/ # E2E integration
.venv/bin/pytest tests/cdk/         # CDK assertions
python scripts/validate_all_metrics.py  # Cross-provider validation gate (needs internet)
python scripts/test_e2e_local.py    # Live chain test (needs internet)
```

