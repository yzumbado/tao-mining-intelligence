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

1. **Start here**: `.kiro/specs/tao-mining-intelligence-pipeline/tasks.md` — master index showing phase status
2. **Phase task files**: `tasks-phase1-validation.md` through `tasks-phase5-site.md` — granular task tracking per phase (checkboxes: `[x]` done, `[ ]` not started, `[~]` blocked)
3. **Current phase**: All phases complete. See `tasks.md` for status summary.
4. **Architecture**: `design.md` in the same spec directory — full system design with algorithms
5. **Requirements**: `requirements.md` — 43 requirements covering all functionality
6. **Coding standards**: `.kiro/steering/coding-standards.md` — ALWAYS follow these
7. **Knowledge base**: `kb/` directory — research findings, architecture decisions, infrastructure assessment
8. **Validated SDK behavior**: `kb/bittensor-mining-research.md` — section "Validated Through Implementation"

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
    ├── Invokes Aggregator (async) → rankings recompute
    └── Creates next EventBridge schedule (tempo-based, self-perpetuating)
                │
                ▼
Aggregator Lambda (invoked after each subnet completes)
    ├── Reads ALL current profiles from DynamoDB
    ├── Generates rankings from whatever data exists
    ├── Generates daily briefing (rolling 24h changes)
    └── Stores rankings + briefing to S3
```

## Reference Implementation: Collector Lambda

The Collector (task 4.1) is the completed reference for how Lambda handlers should be built. Use it as the pattern for Processor and Finalizer:

- **Test file**: `tests/unit/test_collector.py` — 16 tests covering idempotency, partial failure, graceful shutdown, SQS format, data validation, concurrency
- **Handler**: `lambda/src/collector/handler.py` — module-level singletons for config/state/storage, `handle()` entry point, full instrumentation
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
├── orchestrator/
│   └── handler.py         # ⚠️ Legacy Orchestrator Lambda (kept for reference)
├── discovery/
│   └── handler.py         # ✅ Discovery Lambda (hourly safety net)
├── subnet_collector/
│   └── handler.py         # ✅ SubnetCollector Lambda (one subnet per invocation)
├── collector/
│   └── handler.py         # ⚠️ Legacy monolithic collector (kept for reference)
├── processor/
│   ├── metrics.py         # ALL algorithms (pure functions, no AWS)
│   └── handler.py         # ✅ Processor Lambda (metrics + profiles + hotkeys)
├── finalizer/
│   └── handler.py         # ✅ Finalizer Lambda (briefing + ranking + site)
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
- ✅ Phase 3: Metrics Engine (11 algorithms, property + unit tests)
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
- ⚠️ Staking APY overstated by ~1.6x (reports 11.1% for SN0, real is ~6.8%) — see `kb/bug-staking-apy-overstated.md`
  - Root cause: formula uses gross validator yield without subtracting validator take rate or modeling root proportion
  - Fix requires: chain data (tao_weight, per-validator take rate)

### In Progress: Continuous Conformance System
- **Design principle**: Human-agent collaboration — agents do continuous verification, humans triage and decide
- **Concept validated**: 3 proofs completed, all produced actionable findings
- **Build plan ready**: `kb/conformance-build-plan.md`
- **Next action**: Phase A — inline post-conditions in Finalizer (30 lines, zero new infra)
- **Key docs**:
  - `kb/design-principle-agent-native-conformance.md` — philosophy + collaboration model
  - `kb/conformance-concept-index.md` — 10 areas, 5 proofs, 7 design rules
  - `kb/conformance-findings-schema.md` — finding data model (18 required fields, validated)
  - `kb/conformance-proof2-commit-history.md` — git analysis patterns
  - `kb/conformance-proof3-test-vs-production.md` — value range comparison
  - `kb/conformance-build-plan.md` — Phase A-E implementation plan

### Session 2026-05-25 Findings (context for next agent):
- SN104 investigation: self-mining subnet (1 miner, 1 validator, same coldkey, "for sale" description) — scored 0.613 mid-pack
- Const announced emission blocking for self-mining/abandoned/fraudulent subnets
- Ecosystem research: taostats, TAO Institute (SRI), Taoculator all use Net TAO Flow, real APY, VTrust, pool depth
- Our attractiveness score was effectively just net_tao_yield (recoup≈1.0, trend≈0.5 for all subnets)
- Redesigned to risk-adjusted formula with self-mining penalty — SN104 would now score near 0
- Test audit found 2 CRITICAL lies: alpha_price never reached processor (wrong S3 path), self_mining_risk never tested non-zero
- Daily stake accumulation started — Net TAO Flow will activate after 7 days of data
- 6 MEDIUM test lies remain (see backlog or ask for details)

### Session 2026-05-19 Findings (context for next agent):
- Output contract bugs: tests used idealized mock data that didn't match production shapes
- Emission alert threshold was 10% but real emission changes are < 0.2% — lowered to 1%
- 4 orphaned features in code (rental_profitability, entry_barrier, seven_day_trend, top_movers) — defined but never called
- 2 dead code modules (orchestrator/, collector/) — never imported, still in container
- competitive_density metric is effectively dead weight — never differentiates subnets in production (max 0.074, formula mixes units)
- "feat without test" commit pattern predicted 2/3 of bugs found

## How to Run Tests

```bash
# Requires Python 3.12+ (project won't install on 3.9)
# If setting up fresh: /opt/homebrew/bin/python3.12 -m venv .venv

source .venv/bin/activate
.venv/bin/pytest tests/ -v          # All 206 tests
.venv/bin/pytest tests/properties/  # Property tests only (96 tests)
.venv/bin/pytest tests/unit/        # Unit tests only (87 tests)
.venv/bin/pytest tests/integration/ # E2E integration (2 tests)
.venv/bin/pytest tests/cdk/         # CDK assertions (13 tests)
python scripts/test_e2e_local.py    # Live chain test (needs internet)
python scripts/validate_fields.py   # SDK field validation (needs internet)
```

## How to Document Progress

- Update the relevant `tasks-phaseN-*.md` file (mark tasks [x] when done)
- Update `tasks.md` master index status table
- After significant changes: `git add -A && git commit -m "description" && git push`
- If you discover SDK behavior that differs from assumptions: update `kb/bittensor-mining-research.md`
- If you make an architecture decision: update `kb/architecture-decisions.md`

## Commit Documentation Strategy (PROPAGATE TO ALL PROJECTS)

**For the coordination agent**: This strategy should be incorporated into the
global steering for ALL coding projects. See `kb/commit-documentation-strategy.md`
for the full recommendation with adoption path.

Every fix or decision commit MUST follow this structure:

```
<type>(<scope>): <what changed>

Diagnosis: How the problem was discovered and what symptoms were observed.

Root cause: The actual underlying issue (not the symptom).

[Attempted fix N: What was tried and why it failed.] (include all failed attempts)

Fix: What was done and why this approach was chosen over alternatives.

Verification: How the fix was validated (commands, test results).

[Decision: Why this approach over alternatives — trade-offs considered.]

[When to revisit: Conditions under which this fix should be reconsidered.]
```

**Why this matters for multi-agent workflows:**
- An agent reading `git log` reconstructs full decision context without asking
- Failed approaches are documented once instead of rediscovered repeatedly
- `git log --grep="keyword"` becomes a searchable knowledge base
- Future refactors can check if workaround conditions still apply
- Dead code goes in commit messages, not in source files

**Evidence**: During TAO deployment, this saved us from repeating 3 dead-end
approaches (mkdir /dev/shm, full module mock, wrong platform type). Each was
documented in the commit that solved the problem, so no future agent will
waste time on them.

## Patterns That Work Well

- **Validate with live data** before building on assumptions
- **POC against live chain** catches bugs mocks hide (blocks_since_last_step, mg.n type, source_block_number)
- **Property tests catch real bugs** (we found a floating-point issue in slippage)
- **Simple types for metrics functions** (lists, floats) — easier to test with Hypothesis
- **Pydantic models for storage/API boundaries** — type safety at the edges
- **Instrument everything** — trace_id makes debugging across Lambdas trivial
- **Commit after each completed task** — clean history, easy to revert
- **Review after implementation** — found 7 critical bugs in the "working" code by asking "what are tests hiding?"
- **Field name alignment matters** — Collector output field names must match Processor input expectations exactly
- **Error propagation over swallowing** — StateManager now raises on throttling so SQS retries work

## Lessons Learned (Testing Process)

1. **180 passing tests can still hide a deployment-blocking bug** — if the test environment's module resolution differs from production, tests are lying
2. **Scripts are code too** — if it's meant to be run, it must be tested that it runs (import smoke test)
3. **sys.path hacks in every file = fragility** — centralize path setup in conftest.py
4. **Docker build is the real test** — unit tests validate logic, but only a container build validates packaging
5. **The E2E test doesn't test the full chain** — it seeds data manually instead of calling the real Orchestrator/Collector, so it misses SQS message format drift
6. **"All tests pass" ≠ "ready to deploy"** — we changed 5 source files (imports) and all 180 tests still passed without modification, proving they never exercised those paths. Always run `docker run --entrypoint python test-imports -c "from src.X.handler import handle"` after any import or Dockerfile change — it's the only test that can't lie about module resolution.
