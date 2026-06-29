# Design Document: TAO Mining Intelligence Pipeline

## Overview

A serverless pipeline that autonomously collects Bittensor subnet data, computes mining/validating intelligence metrics, and serves structured rankings via CloudFront. Each subnet refreshes independently once per day via self-scheduling loops — no batch orchestration, no central coordinator in the hot path.

**Primary goal**: TAO accumulation through mining or validating — not USD.

**Key properties**:
- 129 subnets collected and processed autonomously
- Each subnet refreshes once per day (fixed 24h cadence)
- Self-healing: dead loops recover within 1 hour via Discovery Lambda
- Rankings recomputed twice daily (06:00 + 18:00 UTC)
- ~$0/month (8% of free tier at steady state)

### Design Principles

- **Deterministic where possible**: Scripts for collection and metrics; LLM reserved for Stage 2
- **Append-only knowledge**: Raw data never overwritten; derived metrics versioned by date
- **Free-tier constrained**: Lambda 1M req/mo, S3 5GB, DynamoDB 25GB, SQS 1M req/mo
- **Independent subnet loops**: Zero coupling between subnets (AD18)
- **Validate warns, doesn't reject**: Data quality flags in metadata; processing continues
- **Config cached per invocation**: Read once from DynamoDB, passed to all operations

### System Boundaries

**In scope (Stage 1 — current)**:
- On-chain metagraph collection for all active subnets
- Registration cost, hyperparameters, alpha token price, pool liquidity
- 17 derived metrics (risk, yield, competitive dynamics, self-mining detection)
- 7-day price trend analysis (from Market Observer history)
- Self-scheduling refresh loops via EventBridge Scheduler
- Static HTML site (Jinja2 + Tailwind CSS) via CloudFront
- Agent-consumable endpoints (llms.txt, rankings.json, metadata.json)
- Conformance post-conditions (Phase A inline checks)

**Out of scope (Stage 3+)**:
- LLM-powered Subnet Researcher enrichment (deterministic parsing deployed; LLM analysis deferred)
- Discord/YouTube intelligence
- DeepCollector (per-UID and per-hotkey historical data)
- Real-time chain event streaming
- Multi-user access / REST API

---

## Architecture

### High-Level Data Flow

```
Discovery Lambda (hourly safety net)
    ├── Queries chain for active subnets
    ├── Checks each subnet's collected_at / processed_at for staleness (>26h)
    └── Creates EventBridge one-time schedules for new/stale subnets
                │
                ▼
EventBridge Scheduler (one-time, per subnet, self-perpetuating)
                │
                ▼
SubnetCollector Lambda (one subnet per invocation)
    ├── Collects metagraph from Bittensor chain via SDK v10
    ├── Collects hyperparameters, alpha price, pool liquidity, reg cost
    ├── Validates (warn on quality issues, don't reject)
    ├── Stores raw snapshot to S3
    ├── Writes collected_at to DynamoDB (prevents Discovery re-scheduling race)
    └── Sends SQS message → Processing Queue
                │
                ▼
Processor Lambda (one subnet per invocation)
    ├── Reads raw snapshot + previous-day snapshot from S3
    ├── Converts emission from per-tempo to per-day
    ├── Runs MetricsEngine (17 pure functions) on the data
    ├── Stores derived metrics to S3
    ├── Writes split profiles to DynamoDB (with processed_at)
    ├── Stores daily stake/emission totals (for Net TAO Flow)
    └── Creates next EventBridge schedule (+24h, self-perpetuating)
                │
                ▼
Finalizer Lambda (twice daily: 06:00 + 18:00 UTC via EventBridge)
    ├── Reads ALL derived metrics from S3 (today + yesterday fallback)
    ├── Parallel reads via ThreadPoolExecutor (16 workers)
    ├── Generates rankings (20 fields per subnet, 129 subnets)
    ├── Generates daily briefing (rolling 24h changes)
    ├── Generates HTML site (Jinja2 + Tailwind)
    ├── Uploads to S3 → CloudFront
    └── Runs conformance post-conditions (logs findings)
```

### Infrastructure

| Component | Service | Config |
|-----------|---------|--------|
| Compute | Lambda (Container Image, ARM64) | 512MB, 5min timeout |
| Queue | SQS (process-subnet) + DLQ | batch=1, maxReceive=3 |
| State | DynamoDB (single table, on-demand) | PK/SK, no GSI |
| Storage | S3 (private data) + S3 (CloudFront site) | gzip >30 days |
| Scheduling | EventBridge Scheduler (one-time) | per-subnet, self-cleaning |
| Discovery | EventBridge rule (hourly) | triggers Discovery Lambda |
| CDN | CloudFront | 30min TTL, invalidation on deploy |
| Alerting | SNS → email | staleness alarm |
| Secrets | SSM Parameter Store | API keys (scoped ARN) |

### Why Container Image Lambda

The Bittensor SDK (bittensor + dependencies) is 200-300MB — exceeds the 250MB zip limit. Container Image Lambda supports up to 10GB images. The image is ARM64 for cost efficiency.

### Self-Scheduling Model (AD18)

Each subnet is a self-perpetuating loop:

```
SubnetCollector → SQS → Processor → [creates next EventBridge schedule]
                                            │
                                            └── Schedule fires after 24 hours
                                                    │
                                                    └── SubnetCollector (same subnet) → ...
```

The Processor schedules the next collection at a fixed +24h delay (cost optimization).
Previous design used tempo-based refresh (20-240 min) but this exceeded free tier.

- Max staleness cap (configurable, default 26h): Discovery Lambda re-seeds if exceeded
- `collected_at` written by Collector prevents Discovery from re-scheduling during processing

EventBridge Scheduler one-time schedules with `ActionAfterCompletion=DELETE` — self-cleaning, no accumulation.

### Failure Handling

| Failure | Recovery |
|---------|----------|
| SubnetCollector timeout | SQS retries (3 attempts → DLQ) |
| Processor error | SQS retries → DLQ; subnet loop pauses |
| Dead loop (Lambda crash) | Discovery Lambda re-seeds within 1 hour |
| Chain endpoint hang | Circuit breaker (per-operation timeout) |
| Finalizer error | Next subnet's Processor re-invokes it |
| DynamoDB throttle | StateManager raises → SQS retry |

---

## Components

### Discovery Lambda

**Trigger**: EventBridge hourly rule
**Purpose**: Safety net — not a coordinator. Detects new subnets and re-seeds dead loops.

**Logic**:
1. Query chain for all active netuids
2. For each subnet, check `collected_at`, `processed_at`, and `last_updated` in DynamoDB (uses most recent)
3. If subnet is new (no record) or stale (> max_staleness_hours): create EventBridge one-time schedule
4. Update ACTIVE_SUBNETS config

### SubnetCollector Lambda

**Trigger**: EventBridge one-time schedule (per subnet)
**Purpose**: Collect all raw data for one subnet.

**Outputs** (all to S3 at `raw/{type}/{date}/{netuid}.json`):
- Metagraph (all neurons: stake, emission, incentive, dividends, hotkeys, etc.)
- Hyperparameters (tempo, immunity_period, max_validators, burn params)
- Alpha price + pool TAO/alpha liquidity
- Registration cost
- Chain metadata (14 Tier 1 fields: SubnetEmaTaoFlow, SubnetVolume, etc.)

**Side effects**:
- Writes `collected_at` to DynamoDB PROFILE#basic (prevents Discovery re-scheduling race)

### Processor Lambda

**Trigger**: SQS (process-subnet queue, batch=1)
**Purpose**: Compute all derived metrics for one subnet.

**Key responsibilities**:
- Tempo conversion: emission × (7200 / tempo) → daily
- Run MetricsEngine (17 pure functions)
- Write split profiles to DynamoDB (with processed_at)
- Accumulate daily stake/emission for Net TAO Flow
- Track hotkeys
- Schedule next collection (+24h, self-perpetuating)

### Finalizer Lambda

**Trigger**: EventBridge schedule (twice daily: 06:00 + 18:00 UTC)
**Purpose**: Recompute aggregate outputs from whatever data exists.

**Key property**: Rankings are generated from all derived metrics in S3 (today + yesterday fallback). Not gated on "all subnets complete" — uses whatever exists.

**Outputs**:
- `rankings.json` — sorted by attractiveness score
- `briefing.json` — alerts, emission changes, new subnets
- `metadata.json` — per-subnet freshness timestamps
- `llms.txt` — agent-consumable endpoint index
- HTML site (index, rankings, briefing pages)

### MetricsEngine

**Location**: `lambda/src/processor/metrics.py`
**Property**: All methods are pure functions (no AWS calls, no side effects)

17 metrics:
1. Deregistration Risk — per-miner risk score [0,1]
2. Gini Coefficient — emission inequality [0,1]
3. Reward Distribution Model — WTA / PROPORTIONAL / TIERED / UNKNOWN
4. AMM Slippage — constant-product estimate [0,1]
5. ROI Estimation — net TAO yield, days-to-recoup, 30d projection
6. Taoflow Health — HEALTHY / DECLINING / DEATH_SPIRAL_RISK
7. Miner Churn — churn rate, trend direction
8. Validator Landscape — concentration, yield, VTrust
9. Validator Opportunity — viable, min_stake, daily_roi
10. Competitive Density — earning_miners / max_uids
11. Emission Trend — direction, change_percent
12. Staking Yield — net APY for a given stake amount
13. Alpha APY (1D) — simple APR (daily_rate × 365 × 100)
14. Net TAO Flow (EMA) — 30-day smoothed stake flow
15. Attractiveness Score — risk-adjusted composite [0,1]
16. Validator Concentration Risk — tiered (critical/high/medium/low/healthy)
17. Self-Mining Risk — 4 signals, multiplicative penalty

**Source of truth**: The code in `metrics.py` with structured `Metric:` docblocks. The living reference guide at `kb/metrics-reference.md` is auto-generated from these docblocks.

### StateManager

**Location**: `lambda/src/state/state_manager.py`
**Purpose**: Sole DynamoDB access layer. Manages:
- Per-subnet FSM transitions (best-effort, not critical path)
- Cycle progress tracking
- Config reads (active subnets, tracked hotkeys, thresholds)
- Split profile writes
- Stake/emission history (for Net TAO Flow)
- Rankings and briefings

### StorageLayer

**Location**: `lambda/src/storage/storage_layer.py`
**Purpose**: S3/local filesystem abstraction with gzip support.

---

## Data Models

### DynamoDB Single-Table Design

| PK | SK | Purpose |
|----|-----|---------|
| `SUBNET#{netuid}` | `STATE` | Per-subnet FSM: status, processed_at, last_error |
| `SUBNET#{netuid}` | `PROFILE#basic` | Category, mining style, reward model, gini, collected_at, processed_at |
| `SUBNET#{netuid}` | `PROFILE#winner` | Top-5 miner analysis |
| `SUBNET#{netuid}` | `PROFILE#validator` | Validator landscape, concentration |
| `SUBNET#{netuid}` | `PROFILE#intelligence` | Anomalies, strategy observations |
| `SUBNET#{netuid}` | `HYPERPARAMS` | On-chain hyperparameters |
| `STAKE_HISTORY#{netuid}#{date}` | — | Daily total stake (for EMA flow) |
| `EMISSION_HISTORY#{netuid}#{date}` | — | Daily total emission |
| `CACHE#{netuid}\|MARKET_DATA` | — | Latest alpha_price + pool_tao (Market Observer) |
| `HISTORY#{netuid}\|{timestamp}` | — | Price time-series (30-day TTL, Market Observer) |
| `RESEARCH#{netuid}` | `latest` | Stage 2 repo analysis (GPU, model, difficulty) |
| `CONFIG` | `ACTIVE_SUBNETS` | List of monitored netuids |
| `CONFIG` | `TRACKED_HOTKEYS` | Watchlist for hotkey tracking |
| `CONFIG` | `THRESHOLDS` | Tunable parameters |
| `CONFIG` | `REFRESH_POLICY` | max_staleness_hours, min_refresh_interval |
| `RANKING` | `LATEST` | Current rankings |
| `BRIEFING` | `{date}` | Daily briefing |
| `HOTKEY#{ss58}` | `SNAPSHOT#{date}` | Per-day hotkey position |

**Split profile rationale**: DynamoDB 400KB item limit. Each profile stays well under independently. Consumers read only what they need (1 GetItem, not a fat blob).

### S3 Structure

```
tao-intelligence-{account-id}/
├── raw/
│   ├── metagraph/{date}/{netuid}.json
│   ├── registration-costs/{date}/{netuid}.json
│   ├── hyperparameters/{date}/{netuid}.json
│   └── alpha-prices/{date}/{netuid}.json
├── derived/
│   ├── metrics/{date}/{netuid}.json
│   ├── rankings/{date}.json
│   └── briefings/{date}.json
└── site/    (separate bucket, CloudFront-only)
    ├── index.html
    ├── rankings.html
    ├── briefing.html
    ├── llms.txt
    └── data/
        ├── rankings.json
        ├── briefing.json
        └── metadata.json
```

### Output Schemas

All outputs include a metadata header:
```json
{
  "metadata": {
    "schema_version": "1.0.0",
    "pipeline_version": "1.0.0",
    "source_block_number": 8327822,
    "processed_at": "2026-06-03T18:43:54+00:00"
  },
  "data": { ... }
}
```

Pydantic v2 models (`lambda/src/models/schemas.py`) are the schema definition — no separate JSON Schema files (descoped; Pydantic validates at runtime).

### Rankings Output

```json
[
  {
    "netuid": 44,
    "net_tao_yield": 83.5,
    "days_to_recoup": 0.1,
    "thirty_day_projection": 2503.0,
    "competitive_density": 0.78,
    "emission_trend": 0.003,
    "alpha_price": 0.044,
    "attractiveness_score": 0.825,
    "self_mining_risk": 0.0,
    "real_apy_percent": 36.8,
    "concentration_risk": {"risk": 0.0, "tier": "healthy", "active_validators": 64, "top_1_stake_share": 0.12},
    "pool_tao_liquidity": 65000.0,
    "registration_cost_tao": 0.0005,
    "earning_miners_count": 14,
    "liquidity_warning": false,
    "reward_model": "TIERED",
    "gini_coefficient": 0.48,
    "price_trend_7d": 0.05,
    "price_volatility_7d": 0.012,
    "trend_direction": "up"
  }
]
```

### Storage Budget

| Data Type | Daily | Monthly | Notes |
|-----------|-------|---------|-------|
| Raw snapshots | ~7 MB | ~210 MB | Compressed >30 days |
| Derived metrics | ~1 MB | ~30 MB | |
| Rankings + briefing | ~100 KB | ~3 MB | |
| Site (HTML) | ~2 MB | 2 MB | Regenerated, not accumulated |
| **Total** | ~10 MB/day | ~245 MB/mo | 5GB free tier = 20+ months |

---

## Algorithms

All algorithms are implemented as pure static methods on `MetricsEngine` in `lambda/src/processor/metrics.py`. Each method has a structured `Metric:` docblock that is the source of truth for formula, status, and known issues.

**Do not duplicate algorithm pseudocode here.** The living reference is auto-generated:
```bash
python scripts/generate_metrics_reference.py
# Outputs: kb/metrics-reference.md (17 metrics + price trends documented)
```

### Attractiveness Score Formula (key algorithm)

The composite score that drives rankings:

```
yield_score   = min(net_tao_yield / 200, 1.0)           # 200 TAO/day = ceiling
flow_score    = sigmoid(net_flow_ema / 500)              # centered at 0
emission_score = min(emission_share / 0.02, 1.0)         # 2% of network = perfect
depth_score   = min(pool_depth_tao / 20000, 1.0)        # 20k TAO = deep

raw = yield×0.30 + flow×0.25 + emission×0.25 + depth×0.20
score = raw × (1.0 - self_mining_risk)                   # multiplicative penalty
```

### APY Calculation

Simple APR (intentionally NOT compound — see Dead Ends #1 in handoff):
```
pool_alpha = pool_tao_liquidity / alpha_price
daily_yield_rate = total_validator_emission_daily / pool_alpha
apr = daily_yield_rate × 365 × 100

Guards:
- pool_alpha < 100 → return 0 (insufficient data / new subnet)
- pool_tao_liquidity <= 0 or alpha_price <= 0 → return 0
```

Note: TaoYield and taostats use compound APY which produces higher numbers
(~1.2-1.6× ours at typical rates). We report simple APR because Bittensor
staking does not auto-compound — the user must manually restake.

---

## Configurable Parameters

Stored in DynamoDB (`CONFIG|THRESHOLDS`, `CONFIG|REFRESH_POLICY`). Editable via AWS Console without redeployment.

| Parameter | Default | Purpose |
|-----------|---------|---------|
| max_staleness_hours | 26 | Discovery re-seeds if subnet older than this |
| min_refresh_interval_minutes | 15 | Floor on refresh frequency |
| briefing_emission_change_pct | 1.0 | Alert threshold for emission changes |
| wta_top3_threshold | 0.70 | Top-3 concentration for WTA classification |
| gini_proportional_max | 0.50 | Max Gini for PROPORTIONAL classification |
| queue_pressure_cap | 10 | Registrations/day normalizer |
| validator_take_rate | 0.18 | Default validator cut for APY |

---

## Cross-Cutting Concerns

### Instrumentation

Every significant operation wrapped in `instrument(component, operation, netuid)`. Outputs structured JSON logs with `trace_id` propagated through SQS messages.

### Security

- No secrets in env vars (SSM Parameter Store, scoped ARN)
- S3 data bucket: no public access
- IAM: no wildcard actions, no delete permissions
- Dependencies pinned to exact versions
- Hotkeys logged truncated to 12 chars
- Error messages truncated to 500 chars

### Idempotency

- SubnetCollector: overwrites S3 path for same date/netuid (safe)
- Processor: conditional DynamoDB writes for state transitions
- Finalizer: full recompute from current state (naturally idempotent)
- EventBridge schedules: named by subnet, creating an existing name is no-op

---

## Future State (Stage 3+)

### Subnet Researcher — DEPLOYED ✅ (Stage 2)
Deterministic GitHub repo analysis: extracts GPU requirements, model type, difficulty.
Runs on 7-day refresh cycle, triggered by Discovery Lambda.
LLM enrichment via S3 drop-box is Phase 3 (backlog).

### DeepCollector Lambda
Per-UID and per-hotkey chain data collection. Historical dataset for pattern detection. Spec at `kb/backlog-deep-collector.md`.

### Taoflow Health
Currently returns HEALTHY for all subnets (correct: emissions are EMA-smoothed and rarely change >1%/day). Would activate with 7+ days of stake history showing sustained negative flow.

### Chain Event Processing
Batch Lambda (every 15 min) queries historical blocks for: NeuronRegistered, StakeAdded/Removed, NetworkAdded/Removed, HotkeySwapped. $0 (Lambda free tier).

### Conformance System
Continuous verification that production data matches expectations. Phase A (inline post-conditions) deployed. Phases B-E pending. See `kb/conformance-build-plan.md`.
