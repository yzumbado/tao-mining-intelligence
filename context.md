# TAO Mining Intelligence Pipeline

## What It Is
Automated data collection and processing system for Bittensor subnet mining/validating intelligence. Evaluates both mining and validating opportunities across all subnets, recommending whichever path yields the highest net TAO return. Personal learning project.

**Primary goal**: Accumulate TAO through mining or validating — not USD conversion.

## Tech Stack
- Python 3.12, Pydantic v2 for data models
- AWS Lambda (Container Image — Bittensor SDK is 200-300MB)
- SQS/SNS orchestration (not Step Functions — free tier)
- DynamoDB (state/metrics, single-table design)
- S3 (private data + CloudFront site)
- EventBridge Scheduler (daily 00:00 UTC)
- Jinja2 + Tailwind CSS for dashboard
- CDK for infrastructure
- Hypothesis for property-based testing, moto for AWS mocking
- Target: $0/month (all AWS free tier)

## Architecture
Assembly-line FSM model: Collector → Processor → Finalizer → Site Generator. Each Lambda receives an SQS message, does its work, publishes completion to SNS. Idempotent cycles via cycle_id + conditional DynamoDB writes. Circuit breaker + per-operation timeouts for SDK calls.

## Status
- **Phases 1-3**: Complete (validation, core infra, metrics engine — 11 algorithms, 102 property+unit tests)
- **Phase 4** (Lambda handlers): In progress
  - ✅ 4.1a-c: Collector Lambda done (16 unit tests)
  - ✅ 4.2a-c: Processor Lambda done (17 unit tests)
  - 🔲 4.3a: Finalizer Lambda unit tests — **NEXT**
  - 🔲 4.3b: Finalizer Lambda implementation
  - 🔲 4.4a-b: Property tests (FSM transitions, subnet discovery)
- **Phase 5**: Not started (Jinja2 site, CDK, CloudFront, deployment)

## Environment (this machine)
- Python 3.12.13 via Homebrew (`/opt/homebrew/bin/python3.12`)
- Virtual env: `projects/tao-mining-intelligence/.venv/`
- All deps installed (bittensor 10.3.2, boto3, hypothesis, pytest, moto)
- Test suite: 135/135 passing as of 2026-05-17
- Run tests: `.venv/bin/pytest tests/ -v`

## Repo
- GitHub: `git@github.com:yzumbado/tao-mining-intelligence.git` (private, SSH)
- Local: `projects/tao-mining-intelligence/`
- Branch: main

## Key Files
- Spec/tasks: `.kiro/specs/tao-mining-intelligence-pipeline/` (requirements.md, design.md, tasks.md + phase-specific task files)
- Handoff: `.kiro/steering/handoff.md` — full orientation for any agent picking this up
- Coding standards: `.kiro/steering/coding-standards.md`
- Knowledge base: `kb/` — research, architecture decisions, infra assessment
- Metrics engine: `lambda/src/processor/metrics.py` (pure functions, all algorithms)
- Collector: `lambda/src/collector/handler.py` (done)
- Processor handler: `lambda/src/processor/handler.py` (done)

## SDK Gotchas (important for implementation)
- `blocks_since_last_step` is subnet-level scalar, NOT per-neuron
- `mg.n` is numpy ndarray scalar — must use `int(mg.n)` for range() and JSON
- `mg.block` is numpy ndarray scalar — this is the CURRENT chain block
- `mg.block_at_registration[0]` is NOT the current block (it's UID 0's registration block)
- `R` (rank) and `T` (trust) fields don't exist in SDK v10
- Emission is in alpha tokens per tempo — multiply by `7200/tempo` for daily
- Only 4/247 miners earn on SN1 (extreme Winner-Takes-All)
- Finney endpoint sometimes hangs — circuit breaker handles this

## Agent Behavior
When working on this project:
- TDD mandatory — property test first, then implement, then verify
- Push back on assumptions — Bittensor SDK has surprises
- Keep the internal project agent (handoff.md) up to date after each session
- Commit after each completed task
- Validate with live data before building on assumptions
- All metric functions are PURE (no side effects, no AWS calls)
- Never hardcode thresholds — always use configurable thresholds
- Never use Python float in DynamoDB writes — always Decimal
- After implementation: ask "what are tests hiding?" — run POCs against live chain
- Error propagation over swallowing — raise on throttling, let SQS retry

## Next Steps
1. Begin task 4.3a: Finalizer Lambda unit tests
2. After tests pass, implement Finalizer Lambda (4.3b)
3. Remaining property tests (4.4a-b)
4. Phase 5: site generation + CDK deployment
