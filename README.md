# TAO Mining Intelligence Pipeline

Automated data collection and processing system for Bittensor subnet mining/validating intelligence. Evaluates both mining and validating opportunities across all subnets, recommending whichever path yields the highest net TAO return.

## Status

**Version**: 0.1.0 (Metrics Engine complete, Lambda handlers in progress)

| Phase | Status | Description |
|-------|--------|-------------|
| 1. Validation | ✅ Complete | SDK connectivity, DynamoDB, SQS/SNS validated |
| 2. Core Infrastructure | ✅ Complete | StateManager, StorageLayer, Instrumentation, Validation, Circuit Breaker |
| 3. Metrics Engine | ✅ Complete | 11 algorithms with 102 passing tests (property + unit) |
| 4. Lambda Handlers | 🔲 Not Started | Collector, Processor, Finalizer |
| 5. Site & Deployment | 🔲 Not Started | Jinja2 site, CDK, CloudFront |

## Quick Start

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Validate SDK connectivity (requires internet)
python scripts/validate_sdk.py
```

## Architecture

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
