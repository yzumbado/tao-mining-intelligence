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
2. **Current phase**: `tasks-phase4-lambdas.md` — Collector done, Processor and Finalizer next
3. **Architecture**: `design.md` in the same spec directory — full system design with algorithms
4. **Requirements**: `requirements.md` — 43 requirements covering all functionality
5. **Coding standards**: `.kiro/steering/coding-standards.md` — ALWAYS follow these
6. **Knowledge base**: `kb/` directory — research findings, architecture decisions, infrastructure assessment
7. **Validated SDK behavior**: `kb/bittensor-mining-research.md` — section "Validated Through Implementation"

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

- `blocks_since_last_step` is a **subnet-level scalar**, NOT per-neuron
- `R` (rank) and `T` (trust) fields **don't exist** in SDK v10
- Emission is in **alpha tokens per tempo** — multiply by `7200/tempo` for daily
- `mg.n` is a numpy ndarray scalar — use `int(mg.n)`
- `active` field is int64 (0/1), not bool — cast with `bool()`
- Registration cost from chain is in RAO — divide by 1e9 for TAO
- `get_subnet_price()` returns a Balance object — use `float(price)`
- Only 4/247 miners earn on SN1 (extreme Winner-Takes-All)
- Finney endpoint sometimes hangs — circuit breaker handles this

## Code Structure

```
lambda/src/
├── config.py              # PIPELINE_ENV switching (local vs aws)
├── instrumentation.py     # Tracing with trace_id propagation
├── validation.py          # Data validation at ingestion
├── circuit_breaker.py     # Circuit breaker + timeout utilities
├── thresholds.py          # Configurable parameters with defaults
├── models/
│   ├── enums.py           # All enumerations
│   └── schemas.py         # All Pydantic v2 data models
├── state/
│   └── state_manager.py   # DynamoDB FSM + config + hotkey tracking
├── storage/
│   └── storage_layer.py   # S3/local filesystem with compression
├── processor/
│   ├── metrics.py         # ALL algorithms (pure functions, no AWS)
│   └── handler.py         # [NOT YET BUILT] Processor Lambda
├── collector/
│   └── handler.py         # ✅ Collector Lambda (async SDK collection)
├── finalizer/
│   └── handler.py         # [NOT YET BUILT] Finalizer Lambda
└── site_generator/
    └── generator.py       # [NOT YET BUILT] Jinja2 HTML generation
```

## What's Next (Phase 4 Continuation)

### Immediate tasks:
1. **Processor Lambda** (`lambda/src/processor/handler.py`)
   - Receives SQS message (netuid, date, cycle_id, trace_id)
   - Reads raw snapshot from S3
   - Reads previous day snapshot for trend comparison
   - Runs MetricsEngine on the data
   - Stores derived metrics to S3 + DynamoDB
   - Updates subnet profiles (winner profile, intelligence notes)
   - Publishes completion to SNS topic
   - Full instrumentation with trace_id from SQS message

2. **Finalizer Lambda** (`lambda/src/finalizer/handler.py`)
   - Receives completion messages from SQS (via SNS fan-in)
   - Checks if all subnets in cycle are COMPLETE
   - If not all done: exit early
   - If all done: generate daily briefing, rankings, static site
   - Mark cycle complete in DynamoDB

3. **Unit tests** for both handlers (moto mocks)

4. **Property tests** for FSM transitions (Property 6) and subnet discovery (Property 12)

### After Phase 4:
- Phase 5: Jinja2 templates, CDK stack, CloudFront, deployment, smoke test

## How to Run Tests

```bash
source .venv/bin/activate
.venv/bin/pytest tests/ -v          # All 102 tests
.venv/bin/pytest tests/properties/  # Property tests only
.venv/bin/pytest tests/unit/        # Unit tests only
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
- **Property tests catch real bugs** (we found a floating-point issue in slippage)
- **Simple types for metrics functions** (lists, floats) — easier to test with Hypothesis
- **Pydantic models for storage/API boundaries** — type safety at the edges
- **Instrument everything** — trace_id makes debugging across Lambdas trivial
- **Commit after each completed task** — clean history, easy to revert
