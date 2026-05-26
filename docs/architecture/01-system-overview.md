# 1. System Overview

## Vision

A 7-stage autonomous TAO accumulation machine:

```
COLLECT → RESEARCH → STRATEGIZE → BUILD → TEST → DEPLOY → OPTIMIZE
   ✅        Next      Future      Future  Future  Future   Future
```

**Primary goal**: Accumulate TAO through mining or validating — not USD conversion.
**Current state**: Stage 1 (COLLECT) is complete and autonomous. The pipeline continuously collects Bittensor subnet data, computes mining/validating intelligence metrics, and serves structured data for TAO accumulation strategy decisions.

## Data Flow

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
    ├── Runs MetricsEngine (15 algorithms, pure functions)
    ├── Stores derived metrics to S3 (with processed_at)
    ├── Writes 5 split profiles to DynamoDB
    ├── Accumulates daily stake for Net TAO Flow
    ├── Invokes Finalizer (async) → rankings recompute
    └── Creates next EventBridge schedule (tempo-based, self-perpetuating)
                │
                ▼
Finalizer Lambda (invoked after each subnet completes)
    ├── Reads ALL current derived metrics from S3
    ├── Generates rankings (risk-adjusted attractiveness score)
    ├── Generates staking rankings (APY with take rate)
    ├── Generates daily briefing (alerts, new subnets)
    ├── Runs conformance post-conditions (5 checks)
    ├── Generates HTML site (Jinja2 + Tailwind)
    └── Uploads everything to S3 → CloudFront
```

## Deployment Topology

```
┌─────────────────────────────────────────────────────────────┐
│ AWS Account 651484323929 (us-east-1)                        │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  Discovery   │    │  Collector   │    │  Processor   │  │
│  │  (256MB/60s) │    │ (1024MB/90s) │    │ (512MB/15m)  │  │
│  │  hourly cron │    │  per-subnet  │    │  per-subnet  │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                   │           │
│         ▼                   ▼                   ▼           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  EventBridge │    │  SQS Queues  │    │  Finalizer   │  │
│  │  Scheduler   │    │  + DLQs (3)  │    │ (512MB/5m)   │  │
│  └──────────────┘    └──────────────┘    └──────┬───────┘  │
│                                                  │           │
│  ┌──────────────┐    ┌──────────────┐           ▼           │
│  │  DynamoDB    │    │  S3 (data)   │    ┌──────────────┐  │
│  │  single-table│    │  private     │    │  S3 (site)   │  │
│  │  PAY_PER_REQ │    │  lifecycle   │    │  + CloudFront│  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐                      │
│  │  SNS (2)     │    │  CloudWatch  │                      │
│  │  alerts+proc │    │  alarms (9)  │                      │
│  └──────────────┘    └──────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Principles

1. **TAO accumulation, not USD** — all metrics optimize for TAO return, not fiat
2. **Self-perpetuating loops** — each subnet schedules its own next collection (no central orchestrator in hot path)
3. **Rankings as live view** — recomputed after each subnet update, not gated on "all complete"
4. **Validation warns, doesn't reject** — data quality flags in metadata, processing continues
5. **Pure metrics, impure handlers** — MetricsEngine has zero side effects, handlers wire I/O
6. **Free tier by design** — $0/month operational cost, $1 budget hard limit
7. **Agent-native outputs** — llms.txt, JSON endpoints, structured for LLM consumption
