# Requirements Document

## Introduction

The TAO Mining Intelligence Pipeline is an autonomous data collection and processing system for Bittensor subnet mining/validating intelligence. It collects on-chain data from all active subnets via self-scheduling independent loops, computes 17 derived metrics, and serves structured rankings via CloudFront for TAO accumulation strategy decisions.

**Primary objective**: TAO accumulation through mining or validating — not USD conversion.

**Architecture model**: Self-scheduling independent subnet loops (AD18). Each subnet refreshes at its own tempo cadence. No batch orchestration, no central coordinator in the hot path.

**Infrastructure**: AWS free tier ($0/month) — Lambda (Container Image), DynamoDB, S3, EventBridge Scheduler, CloudFront, SQS, SNS.

---

## Glossary

| Term | Definition |
|------|-----------|
| Pipeline | End-to-end system: Discovery → SubnetCollector → Processor → Finalizer |
| SubnetCollector | Lambda that collects raw data for one subnet per invocation |
| Processor | Lambda that computes derived metrics for one subnet per invocation |
| Finalizer | Lambda that recomputes aggregate rankings after each subnet update |
| Discovery Lambda | Hourly safety net that detects new/stale subnets |
| Metagraph | Complete state of all neurons in a subnet at a point in time |
| Neuron | A miner or validator registered on a subnet |
| Tempo | Blocks between weight-setting rounds (subnet-specific, typically 99-360) |
| Alpha Token | Subnet-specific token trading against TAO on a constant-product AMM |
| Taoflow | Emission model where subnets must maintain positive net staking inflow |
| Self-scheduling loop | SubnetCollector→Processor→[create next schedule] pattern |
| Split profiles | DynamoDB records split by concern to stay under 400KB limit |

---

## Requirements

### R1: Per-Subnet Autonomous Collection

**Story**: The pipeline continuously collects metagraph data for all active subnets without manual intervention.

1. Each subnet SHALL have its own self-perpetuating collection loop via EventBridge Scheduler one-time schedules.
2. The SubnetCollector SHALL retrieve per invocation: metagraph (all neurons), hyperparameters, alpha price + pool liquidity, and registration cost.
3. Raw data SHALL be stored in S3 at `raw/{type}/{date}/{netuid}.json`.
4. Collection failures SHALL be handled by SQS retry (3 attempts → DLQ), not pipeline abort.
5. No subnet's failure SHALL affect any other subnet's collection.

### R2: Discovery and Staleness Safety Net

**Story**: New subnets are detected automatically and dead loops are re-seeded.

1. A Discovery Lambda SHALL run hourly and query the chain for active netuids.
2. New subnets (no DynamoDB record) SHALL get an EventBridge schedule created immediately.
3. Stale subnets (processed_at > max_staleness_hours) SHALL be re-seeded.
4. max_staleness_hours SHALL be configurable in DynamoDB (default: 4).

### R3: Derived Metrics Computation

**Story**: Raw snapshots are processed into actionable intelligence metrics.

1. The Processor SHALL compute 17 metrics per subnet (see design.md § MetricsEngine).
2. Emission values SHALL be converted from per-tempo to per-day before metric computation.
3. Derived metrics SHALL be stored in S3 at `derived/metrics/{date}/{netuid}.json`.
4. Split profiles SHALL be written to DynamoDB (basic, winner, validator, intelligence).
5. All metric functions SHALL be pure (no AWS calls, no side effects).

### R4: Rankings as Live View

**Story**: Rankings reflect the latest available data without waiting for all subnets.

1. The Finalizer SHALL be invoked after each subnet's Processor completes.
2. Rankings SHALL be computed from whatever derived metrics exist at invocation time.
3. Rankings SHALL be sorted by risk-adjusted attractiveness score (descending).
4. Each ranking entry SHALL include: netuid, net_tao_yield, days_to_recoup, attractiveness_score, self_mining_risk, real_apy_percent, concentration_risk, competitive_density, emission_trend, alpha_price.

### R5: Daily Briefing

**Story**: Significant changes are surfaced as alerts.

1. The Finalizer SHALL generate a briefing with alerts for: emission changes > 1%, new subnets detected, subnets with high self-mining risk.
2. The briefing SHALL be stored in S3 and served via CloudFront.

### R6: Self-Mining Risk Detection

**Story**: Subnets gaming emissions via self-mining are flagged.

1. The Processor SHALL compute self_mining_risk from 4 signals: single/no earning miner, single validator, coldkey overlap, low neuron diversity.
2. Self-mining risk SHALL apply a multiplicative penalty to the attractiveness score (risk=1.0 → score=0.0).

### R7: APY Calculation

**Story**: Real annualized yield is computed matching industry methodology.

1. APY SHALL use compound annualization: `((1 + daily_rate)^365 - 1) × 100`.
2. Subnets with total_validator_stake < 100 alpha SHALL return APY = 0 (insufficient data).
3. Subnets with daily_yield_rate > 1.0 SHALL return APY = 0 (anomalous data).
4. APY is alpha yield (not TAO yield) — matches TaoYield/taostats methodology.

### R8: Net TAO Flow Tracking

**Story**: Staking inflows/outflows are tracked to detect declining subnets.

1. The Processor SHALL store daily total stake per subnet in DynamoDB.
2. The Finalizer SHALL compute a 30-day EMA of net flow from stake history.
3. Net flow EMA SHALL be used as a component of the attractiveness score.

### R9: Validator Concentration Risk

**Story**: Subnets with fragile validator sets are flagged.

1. Concentration risk SHALL be tiered: critical (1 validator), high (>90% top-1), medium (>70%), low (>50%), healthy.
2. Concentration risk SHALL be included in the rankings output.

### R10: Agent-Consumable Output

**Story**: AI agents can discover and consume pipeline data programmatically.

1. The site SHALL serve `/llms.txt` with an index of all data endpoints.
2. `/data/rankings.json` SHALL contain the current rankings.
3. `/data/metadata.json` SHALL contain per-subnet freshness timestamps.
4. `/data/briefing.json` SHALL contain the latest briefing.
5. All JSON outputs SHALL include metadata: processed_at, source_block_number, schema_version.

### R11: Static HTML Site

**Story**: Humans can visually inspect pipeline output.

1. The Finalizer SHALL generate HTML pages via Jinja2 + Tailwind CSS (dark theme).
2. Pages generated: index.html, rankings.html, briefing.html.
3. The site SHALL be served via CloudFront with 30-minute TTL.

### R12: Pipeline State Management

**Story**: Per-subnet state is tracked for observability.

1. DynamoDB SHALL store per-subnet state: processed_at, last_error, current_status.
2. Per-subnet FSM transitions SHALL be best-effort (not on critical path).
3. Self-scheduling (next EventBridge schedule creation) SHALL be the critical path.

### R13: Historical Data Preservation

**Story**: All collected data is preserved for trend analysis.

1. Raw and derived data SHALL use date-partitioned S3 paths (append-only).
2. Data older than 30 days SHALL be compressed (gzip).
3. Total storage SHALL stay within 5GB free tier (projected: 20+ months).

### R14: Configurable Parameters

**Story**: Thresholds are adjustable without code changes.

1. All tunable parameters SHALL be stored in DynamoDB (CONFIG|THRESHOLDS).
2. Parameters SHALL be read once per Lambda invocation and cached.
3. Missing parameters SHALL fall back to hardcoded defaults with a warning log.

### R15: Instrumentation and Tracing

**Story**: Operations are traceable across Lambda invocations.

1. A trace_id SHALL propagate through SQS messages.
2. Every significant operation SHALL be instrumented with component, operation, netuid, duration.
3. Structured JSON logs SHALL be written to CloudWatch.

### R16: Data Validation

**Story**: Corrupt data doesn't propagate silently.

1. Metagraph snapshots SHALL be validated: neuron count > 0, emissions non-negative, no NaN/Inf.
2. Validation failures SHALL log warnings but NOT reject data (processing continues with quality flag).

### R17: Security

**Story**: The pipeline follows least-privilege and data isolation.

1. Two S3 buckets: private (data) and public (site, CloudFront-only access).
2. No secrets in environment variables — SSM Parameter Store only.
3. No wildcard IAM actions, no delete permissions on data.
4. Coldkeys logged truncated to 12 chars. Error messages truncated to 500 chars.
5. Dependencies pinned to exact versions.

### R18: Alerting

**Story**: Operational issues are surfaced proactively.

1. A CloudWatch alarm SHALL fire when any subnet exceeds max_staleness_hours.
2. The alarm SHALL publish to SNS → email notification.
3. DLQ depth > 0 SHALL trigger an alarm.

### R19: Infrastructure as Code

**Story**: The entire stack is deployable with one command.

1. All resources SHALL be defined in AWS CDK (Python).
2. Lambda SHALL use Container Image deployment (ARM64).
3. `cdk deploy` SHALL create all resources; `cdk destroy` SHALL remove them.

---

## Descoped Requirements (Stage 2+)

The following were in the original spec but are not implemented. They remain as future work:

| ID | Description | Reason |
|----|-------------|--------|
| Old R28 | Cloud hardware rental profitability | Requires external pricing APIs + hardware tier classification from Stage 2 |
| Old R29 | Cross-subnet composability | Requires Stage 2 Subnet Researcher |
| Old R15 | Subnet category/mining style classification | Manual today; automated classification deferred to Stage 2 |
| Old R16 | Entry barrier assessment | Requires hardware tier mapping from Stage 2 |
| Old R19 | "How Mining Works" / context description | Requires Stage 2 LLM analysis |
| Old R20 | JSON Schema files in S3 | Descoped — Pydantic validates at runtime |
| Old R39 | CI/CD pipeline | GitHub Actions deferred |
| Old R33 | Graceful shutdown (partial results) | Not needed — each invocation handles one subnet |
| Old R42 | AWS Budget alarm | Not created (free tier, $0 validated) |

---

## Traceability

| Requirement | Implemented In | Tested By |
|-------------|----------------|-----------|
| R1 | subnet_collector/handler.py | tests/unit/test_collector.py |
| R2 | discovery/handler.py | tests/properties/test_discovery.py |
| R3 | processor/handler.py, processor/metrics.py | tests/unit/test_processor.py, tests/properties/* |
| R4 | finalizer/handler.py | tests/unit/test_finalizer.py |
| R5 | finalizer/handler.py | tests/unit/test_finalizer.py |
| R6 | processor/metrics.py | tests/properties/test_self_mining.py |
| R7 | processor/metrics.py | tests/properties/test_proven_metrics.py |
| R8 | processor/handler.py, finalizer/handler.py | tests/properties/test_proven_metrics.py |
| R9 | processor/metrics.py | tests/properties/test_proven_metrics.py |
| R10 | finalizer/handler.py | tests/integration/test_contract_processor_to_finalizer.py |
| R11 | site_generator/generator.py | tests/unit/test_site_generator.py |
| R12 | state/state_manager.py | tests/properties/test_fsm.py |
| R13 | storage/storage_layer.py | tests/integration/test_pipeline_e2e.py |
| R14 | thresholds.py | tests/properties/test_briefing_thresholds.py |
| R15 | instrumentation.py | tests/unit/test_instrumentation.py |
| R16 | validation.py | tests/unit/test_validation.py |
| R17 | cdk/stacks/ | tests/cdk/test_pipeline_stack.py |
| R18 | cdk/stacks/ | tests/cdk/test_pipeline_stack.py |
| R19 | cdk/stacks/ | tests/cdk/test_pipeline_stack.py |
