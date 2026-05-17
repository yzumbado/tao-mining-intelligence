# TAO Mining Intelligence Pipeline

Automated data collection and processing system for Bittensor subnet mining/validating intelligence. Evaluates both mining and validating opportunities across all subnets, recommending whichever path yields the highest net TAO return.

## Status

**Version**: 0.1.0 (Metrics Engine complete, Lambda handlers in progress)

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

# Run tests (178 passing as of 2026-05-17)
pytest tests/ -v

# Validate SDK connectivity (requires internet)
python scripts/validate_sdk.py
```

> **Note**: The Bittensor SDK requires Python 3.12+. If `pip install` fails with a Python version error, ensure your venv was created with `python3.12`, not the system default.

## Architecture

```
EventBridge (daily 00:00 UTC)
    │
    ▼
┌─────────────┐     SQS (per-subnet)     ┌─────────────┐     SNS (completion)     ┌─────────────┐
│  Collector   │ ──────────────────────▶  │  Processor   │ ──────────────────────▶  │  Finalizer   │
│  Lambda      │                          │  Lambda      │                          │  Lambda      │
└─────────────┘                          └─────────────┘                          └─────────────┘
    │                                        │                                        │
    ▼                                        ▼                                        ▼
 S3: raw snapshots                     S3: derived metrics                     S3: static site
 DynamoDB: cycle state                 DynamoDB: profiles                      DynamoDB: briefing
                                                                               CloudFront → user
```

- **Compute**: AWS Lambda (Container Image) — Bittensor SDK too large for zip deployment
- **Orchestration**: SQS/SNS (not Step Functions — exceeds free tier)
- **Storage**: S3 (private data) + S3 (CloudFront site) + DynamoDB (state/metrics)
- **Scheduling**: EventBridge Scheduler (daily 00:00 UTC)
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
│   │   ├── processor/        # Metrics engine
│   │   ├── collector/        # Collection Lambda handler
│   │   ├── finalizer/        # Finalization Lambda handler
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
