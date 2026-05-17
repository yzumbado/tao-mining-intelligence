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

An automated pipeline that collects Bittensor subnet data daily, computes mining/validating intelligence metrics, and serves structured data to Kiro for TAO accumulation strategy decisions.

**Primary goal**: Accumulate TAO through mining or validating — not USD conversion.

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
EventBridge (daily 00:00 UTC)
    │
    ▼
Collector Lambda
    ├── Connects to Bittensor chain (AsyncSubtensor)
    ├── Collects metagraphs for all active subnets
    ├── Validates data, stores raw snapshots to S3
    ├── Updates DynamoDB cycle state (FSM)
    └── Publishes one SQS message per subnet → Processing Queue
                │
                ▼
Processor Lambda (one invocation per subnet)
    ├── Reads raw snapshot from S3
    ├── Reads previous-day snapshot for trend comparison
    ├── Runs MetricsEngine (pure functions) on the data
    ├── Stores derived metrics to S3 + DynamoDB profiles
    ├── Tracks hotkey earnings and deregistrations
    └── Publishes completion to SNS → Completion Topic
                │
                ▼
Finalizer Lambda (triggered when all subnets complete)
    ├── Checks cycle completeness via StateManager
    ├── Generates daily briefing + rankings
    ├── Generates static HTML site (Jinja2 + Tailwind)
    ├── Uploads site to CloudFront S3 bucket
    └── Marks cycle complete in DynamoDB
```

## Reference Implementation: Collector Lambda

The Collector (task 4.1) is the completed reference for how Lambda handlers should be built. Use it as the pattern for Processor and Finalizer:

- **Test file**: `tests/unit/test_collector.py` — 16 tests covering idempotency, partial failure, graceful shutdown, SQS format, data validation, concurrency
- **Handler**: `lambda/src/collector/handler.py` — module-level singletons for config/state/storage, `handle()` entry point, full instrumentation
- **Pattern**: Module caches (`_config`, `_state_manager`, `_storage`), reset in test fixtures. Tests use `@mock_aws` + moto. Each test class covers one concern.

## Key Architecture Decisions

- **Container Image Lambda** (not zip) — Bittensor SDK is 200-300MB
- **SQS/SNS orchestration** (not S3 events) — reliable completion detection
- **Two S3 buckets** — private data + CloudFront-only site
- **DynamoDB single-table** with split profiles (400KB limit)
- **Jinja2 + Tailwind CSS** (not MkDocs) — direct HTML generation
- **Configurable thresholds** in DynamoDB (editable via AWS Console)
- **Circuit breaker** + per-operation timeouts
- **Idempotent cycles** via cycle_id + conditional DynamoDB writes

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
├── models/
│   ├── enums.py           # All enumerations
│   └── schemas.py         # All Pydantic v2 data models
├── state/
│   └── state_manager.py   # DynamoDB FSM + config + hotkey tracking
├── storage/
│   └── storage_layer.py   # S3/local filesystem with compression
├── orchestrator/
│   └── handler.py         # ✅ Orchestrator Lambda (discover + dispatch)
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

### All phases complete. Deployment steps:
1. `cdk deploy` — deploy all infrastructure to AWS
2. Docker image builds automatically via CDK's `DockerImageCode.from_image_asset`
3. Manual trigger: invoke Collector Lambda from console
4. Watch pipeline flow: Collector → SQS → Processor → SNS → Finalizer
5. Check CloudFront URL for generated site

### Post-deployment monitoring:
- Monitor first 7 days of daily cycles
- Verify data accumulation in S3
- Validate ROI estimates against manual calculations
- Populate subnet classifications for top 10 subnets (manual)
- Add your own hotkeys to tracked_hotkeys config
- Create OPERATIONS.md runbook

### Completed:
- ✅ Phase 1: SDK validation (connectivity, DynamoDB, SQS/SNS)
- ✅ Phase 2: Core infrastructure (StateManager, StorageLayer, Instrumentation, Validation, Circuit Breaker)
- ✅ Phase 3: Metrics Engine (11 algorithms, property + unit tests)
- ✅ Phase 4: Lambda Handlers (Collector 16 tests, Processor 17 tests, Finalizer 12 tests, FSM + Discovery property tests)
- ✅ Phase 5: Site & Deployment (Jinja2 site 9 tests, CDK 11 tests, E2E integration 2 tests, sanity check)
- ✅ Security hardening: SSM scoped ARN, DLQ on all queues, S3 encryption, NaN/Inf validation, error propagation
- ✅ Tech debt: zero known issues

### Descoped (Phase 2+):
- `subnet.html` and `health.html` templates (4 templates shipped, 2 deferred)
- Docker Compose local dev environment
- Smoke test script (E2E integration test covers this with moto)
- JSON Schema files in config/schemas/ (outputs are validated by Pydantic models instead)
- LLM-powered Subnet Researcher
- OPERATIONS.md runbook

## How to Run Tests

```bash
# Requires Python 3.12+ (project won't install on 3.9)
# If setting up fresh: /opt/homebrew/bin/python3.12 -m venv .venv

source .venv/bin/activate
.venv/bin/pytest tests/ -v          # All 180 tests
.venv/bin/pytest tests/properties/  # Property tests only (79 tests)
.venv/bin/pytest tests/unit/        # Unit tests only (76 tests)
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
