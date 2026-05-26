# 2. Component Architecture

## Lambda Functions

### SubnetCollector
- **Trigger**: EventBridge one-time schedule (self-perpetuating) or Discovery Lambda
- **Concurrency**: 2 (prevents chain endpoint overload)
- **Memory/Timeout**: 1024MB / 90s
- **Responsibility**: Collect raw on-chain data for one subnet
- **Outputs**: 4 S3 files (metagraph, hyperparams, alpha-price, reg-cost) + 1 SQS message
- **Error handling**: SQS retry (3 attempts), DLQ on exhaustion
- **Key decision**: Uses `AsyncSubtensor` for non-blocking chain queries

### Processor
- **Trigger**: SQS message from SubnetCollector
- **Memory/Timeout**: 512MB / 15 minutes
- **Responsibility**: Compute all derived metrics for one subnet, invoke Finalizer, schedule next collection
- **Inputs**: Raw S3 files + previous-day snapshot
- **Outputs**: Derived metrics (S3), 5 DynamoDB profiles, daily stake record, Finalizer invocation, next schedule
- **Key decision**: Tempo conversion happens here (emission per-tempo → daily) before calling MetricsEngine
- **Critical path**: `increment_cycle_progress` — must succeed for pipeline health tracking

### Finalizer (Aggregator)
- **Trigger**: Async Lambda invoke from Processor (after each subnet)
- **Memory/Timeout**: 512MB / 5 minutes
- **Responsibility**: Recompute global rankings from whatever data exists, generate site
- **Inputs**: All derived metrics from S3 (today's date), DynamoDB profiles
- **Outputs**: Rankings JSON, briefing JSON, staking rankings, metadata, HTML site, llms.txt
- **Key decision**: Rankings are a live view — recomputed after every subnet, not batched
- **Conformance**: Runs 5 post-condition checks on every invocation

### Discovery
- **Trigger**: EventBridge hourly cron
- **Memory/Timeout**: 256MB / 60s
- **Responsibility**: Safety net — find new subnets, detect stale ones, create schedules
- **Key decision**: Not a coordinator — just ensures no subnet is forgotten

## Shared Libraries

| Module | Responsibility |
|--------|---------------|
| `config.py` | PIPELINE_ENV switching (local vs aws), singleton config |
| `instrumentation.py` | Structured logging with trace_id propagation |
| `validation.py` | Data validation at ingestion (NaN/Inf guard, field presence) |
| `circuit_breaker.py` | Circuit breaker + per-operation timeouts |
| `thresholds.py` | Configurable parameters with sensible defaults |
| `sanity_check.py` | Post-processing data quality checks |
| `lambda_patch.py` | Bittensor multiprocessing.Queue patch for Lambda environment |
| `models/enums.py` | All enumerations (RewardModel, TaoflowStatus, etc.) |
| `models/schemas.py` | All Pydantic v2 data models (Neuron, ROIEstimate, etc.) |
| `state/state_manager.py` | **Sole DynamoDB access layer** — all PK/SK patterns encapsulated |
| `storage/storage_layer.py` | S3/local filesystem abstraction with compression |
| `processor/metrics.py` | **Pure computation** — 17 algorithms, zero side effects |
| `site_generator/generator.py` | Jinja2 HTML generation (4 templates) |

## Component Contracts

### Collector → Processor (via SQS + S3)

SQS message: `{netuid: int, date: str, cycle_id: str, trace_id: str}`

S3 files (per-subnet, per-date):
- `raw/metagraph/{date}/{netuid}.json` — neurons + metadata (source_block, num_uids, max_uids)
- `raw/alpha-prices/{date}/{netuid}.json` — alpha_tao_price, pool_tao_liquidity
- `raw/registration-costs/{date}/{netuid}.json` — registration_cost_tao
- `raw/hyperparameters/{date}/{netuid}.json` — tempo, immunity_period, etc.

### Processor → Finalizer (via Lambda invoke + S3)

S3 file: `derived/metrics/{date}/{netuid}.json`
```json
{
  "metadata": { "netuid", "processed_at", "source_block_number", "schema_version" },
  "data": {
    "deregistration_risk": [...],
    "competitive_density": float,
    "emission_trend": { "current_total_emission", "change_percent", "direction" },
    "roi_estimate": { "net_tao_yield_per_day", "days_to_recoup", "alpha_tao_rate", "pool_tao_liquidity", ... },
    "reward_distribution": { "model", "gini_coefficient", "top_3_concentration" },
    "taoflow_health": { "status", "net_staking_flow_tao", "consecutive_negative_days" },
    "churn": { "daily_churn_rate", "competition_trend", ... },
    "validator_landscape": { "active_validators", "top_1_stake_share", "avg_vtrust", "min_vtrust", ... },
    "self_mining_risk": { "risk_score", "signals", "earning_miners", ... },
    "concentration_risk": { "risk", "tier", "active_validators", "top_1_stake_share" },
    "real_apy_percent": float
  }
}
```

### Finalizer → Consumer (via S3/CloudFront)

- `/data/rankings.json` — sorted by attractiveness_score, includes self_mining_risk, real_apy_percent
- `/data/staking_rankings.json` — sorted by net_apy_percent
- `/data/briefing.json` — alerts, new_subnets, summary
- `/data/metadata.json` — per-subnet freshness timestamps
- `/llms.txt` — agent-consumable endpoint index
- `/index.html`, `/rankings.html`, `/briefing.html` — human-readable site
