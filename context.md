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
- **All phases complete** — ready for deployment
- **Architecture refactored**: Orchestrator + SubnetCollector (no burst load)
- **Security hardened**: SSM scoped, DLQ on all queues, S3 encryption, NaN/Inf guard, error propagation
- **180/180 tests passing** (properties: 79, unit: 76, integration: 2, CDK: 13, site: 9, sanity check)
- **Next**: Write Orchestrator/SubnetCollector unit tests, then `cdk deploy`

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
- Review before continuing — check for stale docs, field mismatches, type assumptions
- Security review before deployment — IAM scope, secrets, encryption, DLQ coverage
- Challenge constraints — "do we really need Fargate?" led to $0 batch event processing
- Configurable over hardcoded — frequencies, thresholds, all stored in DynamoDB

## Collaboration Patterns That Work
- **POC before trusting mocks**: Live chain POCs caught 5 critical bugs that unit tests hid
- **Sub-agent reviews**: Parallel security + test + doc audits find issues faster than sequential
- **Implement then review**: Build it, then ask "what did we miss?" — catches more than pre-review
- **Document decisions immediately**: Architecture decisions written same session they're made
- **Sync docs at session end**: Every session ends with all docs reflecting current state
- **Zero tech debt policy**: Fix everything before moving to next phase
- **Free tier budget tracking**: Calculate Lambda invocations + GB-seconds before committing to a frequency

## Cross-Environment Note
This project is also worked on in a separate Kiro workspace. Keep `.kiro/` files updated so either workspace can pick up seamlessly.

## Next Steps
1. Write unit tests for Orchestrator and SubnetCollector (task 4 in active task list)
2. Update E2E integration test to use new Orchestrator → SubnetCollector flow
3. `cdk deploy` — deploy all infrastructure to personal AWS account
4. Manual trigger: invoke Orchestrator Lambda from console
5. Monitor first 7 days of daily cycles
6. Phase 2: ChainEventCollector (batch events every 15min), PriceCollector, SocialCollector
