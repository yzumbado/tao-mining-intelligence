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
- **All phases complete** (validation, core infra, metrics engine, Lambda handlers, site + CDK)
- **Phase 4**: Collector ✅, Processor ✅, Finalizer ✅, FSM + Discovery property tests ✅
- **Phase 5**: Jinja2 site ✅, CDK stack ✅, E2E integration test ✅, sanity check ✅
- **Security hardening**: SSM scoped, DLQ on all queues, S3 encryption, NaN/Inf guard, error propagation
- **Next**: `cdk deploy` to personal AWS account

## Environment (this machine)
- Python 3.12.13 via Homebrew (`/opt/homebrew/bin/python3.12`)
- Virtual env: `projects/tao-mining-intelligence/.venv/`
- All deps installed (bittensor 10.3.2, boto3, hypothesis, pytest, moto)
- Test suite: 178/178 passing as of 2026-05-17
- Run tests: `.venv/bin/pytest tests/ -v`

## Repo
- GitHub: `git@github.com:yzumbado/tao-mining-intelligence.git` (private, SSH)
- Local: `projects/tao-mining-intelligence/`
- Branch: main

## Key Files
- Spec/tasks: `.kiro/specs/tao-mining-intelligence-pipeline/`
- Handoff: `.kiro/steering/handoff.md`
- Coding standards: `.kiro/steering/coding-standards.md`
- Knowledge base: `kb/` — research, architecture decisions
- Metrics engine: `lambda/src/processor/metrics.py`
- Collector: `lambda/src/collector/handler.py`
- Processor: `lambda/src/processor/handler.py`
- Finalizer: `lambda/src/finalizer/handler.py`
- Site generator: `lambda/src/site_generator/generator.py`
- CDK stack: `cdk/stacks/pipeline_stack.py`
- E2E test: `tests/integration/test_pipeline_e2e.py`

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
1. `cdk deploy` — deploy all infrastructure to personal AWS account
2. Manual trigger: invoke Collector Lambda from console
3. Monitor first 7 days of daily cycles
4. Create OPERATIONS.md runbook
5. Populate subnet classifications for top 10 subnets
