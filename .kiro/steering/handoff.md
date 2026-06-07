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

## Bittensor in 60 Seconds

Bittensor is a decentralized network where ~129 **subnets** compete for TAO tokens (like ETH for Ethereum). Each subnet is a marketplace for a specific AI task — computer vision, LLM inference, data storage, etc. Two roles:

- **Miners** provide work (GPU compute, AI inference) and earn TAO based on quality
- **Validators** score miners' work and earn TAO for maintaining quality

Each subnet has its own **alpha token** (like an LP token) that trades against TAO on an AMM pool. When you stake/mine on a subnet, you earn alpha which you convert to TAO.

**Our pipeline answers**: "Which of the 129 subnets should I register on to earn the most TAO?" — considering yield, competition, risk, and liquidity. Think of it as a Bloomberg terminal for Bittensor mining opportunities.

## How the Output Is Used

The user (or Kiro agent) reads our `rankings.json` and makes decisions like:
- "SN44 has 82% APY and low self-mining risk → stake 1000τ there"
- "SN97 scores 0.0 (self-mining=1.0) → avoid, emissions will be blocked"
- "SN9 yields 95τ/day but only 1 earning miner → extreme WTA, only enter if I can be top"

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
├── site_generator/
│   └── generator.py       # ✅ Jinja2 HTML generation
├── researcher/
│   └── handler.py         # ✅ Stage 2 subnet repo research
└── market_observer/
    └── handler.py         # ✅ High-frequency cache + time-series (10-min cadence)
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
- ✅ All 5 development phases complete (SDK validation → core infra → metrics → handlers → site/deploy)
- ✅ 205 tests passing (property, unit, integration, CDK)
- ✅ 17 metric algorithms, all cross-validated against live chain
- ✅ Security hardening, SNS alerting, conformance post-conditions
- ✅ AD18 independent refresh fully implemented (old batch model removed)

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



### Session 2026-06-07 Findings (context for next agent):

#### Major Accomplishments:
- **APY formula finalized** — switched to simple APR (`daily_rate × 365 × 100`). No compound, no threshold, no overflow possible. Validated against all 129 live subnets: max 2787%, median 93%.
- **Self-mining risk fixed** — tightened thresholds (diversity <10%, coldkey overlap ≥50% of validators). 98/129 false positives → 11/129 correctly flagged.
- **Market Observer deployed and cleaned** — captures price + pool_tao every 10 min for all 129 subnets. Stripped dead alpha_out/pool_alpha fields.
- **Stage 2 RESEARCH complete and deployed** — SubnetResearcher Lambda live, 22 repos mapped, CDK wired, Discovery staleness check working.
- **Full audit completed** — all docs synced with code, stale tasks updated, dead code annotated.

#### Key Lessons Learned (apply to future work):
1. **Don't use compound annualization for yield that isn't auto-compounded.** Bittensor staking doesn't reinvest automatically. Simple APR is the honest number.
2. **POC BEFORE building** — the "observed APY from Market Observer" effort (3 commits) was wasted because SubnetAlphaOut doesn't isolate emission from staker flow. A 5-minute POC would have caught this.
3. **Threshold-based guards are whack-a-mole.** Edge cases always fall just below the threshold. Linear formulas that can't overflow are better than guarded exponential formulas.
4. **Build consumers before infrastructure.** The Market Observer cache has zero readers. We built write-side first, but nothing benefits from it yet.
5. **Static repo mappings rot fast.** 38-56% of community-maintained Bittensor repo links are dead within months. Always validate URLs on use.

#### Current Production State:
- Pipeline: 129 subnets self-refreshing (avg 30 min freshness)
- Market Observer: running every 10 min, accumulating price/pool history
- Researcher: deployed, researches repos on 7-day cycle via Discovery
- Rankings: live at https://dkfh19zkgqq18.cloudfront.net
- Tests: 203 passing
- Cost: $0/month (free tier)

#### Pending Tasks (next session):

**P1 — APR Convergence (monitor):**
- [ ] Verify all 129 subnets show APR < 3000% (simple formula deployed June 7)
- [ ] Verify SN44 APR ~65% (was 91% compound, 37% before that)

**P2 — Wire Cache Consumers (when needed):**
- [ ] Market Observer cache has no readers yet — wire when building API or alerts
- [ ] Consider price volatility metric from history (7+ days of data available)

**P3 — Backlog:**
- [ ] Stage 2 RESEARCH: LLM enrichment S3 drop-box (Phase 3 of research design)
- [ ] Stage 3: STRATEGIZE design (given resources, which subnets to enter?)
- [ ] Label slippage as "upper bound" in site HTML (done in JSON/schema, not in template)

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

