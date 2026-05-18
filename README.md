# TAO Mining Intelligence Pipeline

Autonomous data collection and processing system for Bittensor subnet mining/validating intelligence. Evaluates both mining and validating opportunities across all 129 subnets, recommending whichever path yields the highest net TAO return.

**Live data**: [`https://dkfh19zkgqq18.cloudfront.net/llms.txt`](https://dkfh19zkgqq18.cloudfront.net/llms.txt)

**Vision**: 7-stage autonomous TAO accumulation machine. Currently at Stage 1 (COLLECT). See [`kb/product-vision-roadmap.md`](kb/product-vision-roadmap.md).

## Sample Output

```
SN 0 | Score: 0.940 | 46.69 TAO/day | 30d: 1,400 TAO
SN 4 | Score: 0.935 | 49.87 TAO/day | 30d: 1,496 TAO
SN 1 | Score: 0.949 |  7.55 TAO/day | 30d:   227 TAO
```

Per-subnet intelligence includes: reward model (WTA/distributed), Gini coefficient, competitive density, deregistration risk, emission trends, validator landscape, taoflow health, and ROI estimates.

## Status

**Version**: 0.1.0 (Deployed — 129 subnets collected, 128 processed, rankings generated)

| Phase | Status | Description |
|-------|--------|-------------|
| 1. Validation | ✅ Complete | SDK connectivity, DynamoDB, SQS/SNS validated |
| 2. Core Infrastructure | ✅ Complete | StateManager, StorageLayer, Instrumentation, Validation, Circuit Breaker |
| 3. Metrics Engine | ✅ Complete | 11 algorithms with 102 passing tests (property + unit) |
| 4. Lambda Handlers | ✅ Complete | Collector ✅, Processor ✅, Finalizer ✅ |
| 5. Site & Deployment | ✅ Complete | Jinja2 site, CDK, E2E test, sanity check |

## Quick Start

```bash
# Requires Python 3.12+ (system Python 3.9 won't work)
# Install via Homebrew if needed: brew install python@3.12

# Create virtual environment with Python 3.12
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies (includes dev tools: pytest, hypothesis, moto)
pip install -e ".[dev]"

# Run tests (180 passing as of 2026-05-17)
pytest tests/ -v

# Validate SDK connectivity (requires internet)
python scripts/validate_sdk.py
```

> **Note**: The Bittensor SDK requires Python 3.12+. If `pip install` fails with a Python version error, ensure your venv was created with `python3.12`, not the system default.

## Architecture

```
Discovery Lambda (hourly safety net)
    ├── Queries chain for active subnets
    ├── Checks each subnet's processed_at for staleness
    └── Creates EventBridge one-time schedules for new/stale subnets
                │
                ▼
EventBridge Scheduler (one-time, per subnet, self-perpetuating)
                │
                ▼
SubnetCollector Lambda (one subnet per invocation)
    ├── Collects metagraph, hyperparams, alpha price, reg cost
    ├── Validates (warn on quality issues, don't reject)
    ├── Stores raw snapshot to S3
    └── Sends SQS message → Processing Queue
                │
                ▼
Processor Lambda (one subnet per invocation)
    ├── Computes metrics (pure functions)
    ├── Stores derived metrics to S3, profiles to DynamoDB
    ├── Invokes Finalizer (async) → rankings recompute
    └── Creates next EventBridge schedule (tempo-based, self-perpetuating)
                │
                ▼
Finalizer Lambda (aggregator, invoked after each subnet)
    ├── Reads ALL current profiles from DynamoDB
    ├── Generates rankings + daily briefing
    └── Generates HTML site → S3 → CloudFront
```

- **Compute**: AWS Lambda (Container Image) — Bittensor SDK too large for zip deployment
- **Orchestration**: Self-scheduling loops via EventBridge Scheduler one-time schedules
- **Storage**: S3 (private data) + S3 (CloudFront site) + DynamoDB (state/metrics)
- **Scheduling**: Discovery Lambda (hourly) + per-subnet self-scheduling (tempo-based)
- **Site**: Jinja2 + Tailwind CSS (dark theme) via CloudFront
- **Cost**: $0/month (all AWS free tier)

## Project Structure

```
├── .kiro/                    # Kiro specs and steering
│   ├── specs/                # Requirements, design, task plans
│   └── steering/             # Coding standards (auto-loaded)
├── kb/                       # Knowledge base (research, decisions)
├── lambda/
│   ├── src/                  # Application code
│   │   ├── models/           # Pydantic data models
│   │   ├── processor/        # Metrics engine + handler
│   │   ├── discovery/        # Discovery Lambda (hourly safety net)
│   │   ├── subnet_collector/ # SubnetCollector Lambda (per-subnet)
│   │   ├── collector/        # Legacy monolithic collector (reference)
│   │   ├── finalizer/        # Finalizer Lambda (aggregator)
│   │   ├── state/            # DynamoDB state manager
│   │   ├── storage/          # S3/local storage layer
│   │   └── site_generator/   # HTML site generation
│   ├── templates/            # Jinja2 HTML templates
│   ├── Dockerfile            # Lambda container image
│   └── requirements.txt      # Pinned production dependencies
├── cdk/                      # AWS CDK infrastructure
├── tests/
│   ├── properties/           # Hypothesis property-based tests
│   ├── unit/                 # Unit tests with moto
│   ├── integration/          # End-to-end tests
│   └── cdk/                  # Infrastructure tests
├── scripts/                  # Validation and utility scripts
└── config/schemas/           # JSON Schema definitions
```

## Key Design Decisions

See `kb/architecture-decisions.md` for full rationale.

- TAO accumulation as primary objective (not USD)
- Assembly-line FSM model (not agent swarm)
- Dual classification: subnet category + mining style
- Configurable thresholds in DynamoDB (editable via AWS Console)
- Two-bucket S3 isolation (private data + public site)
- TDD with mandatory property-based tests for all algorithms
