# 3. Data Architecture

## DynamoDB — Single Table Design

One table (`tao-pipeline`), PAY_PER_REQUEST, PITR enabled.

### Schema

| PK Pattern | SK Pattern | Written By | Read By | Purpose |
|------------|-----------|------------|---------|---------|
| `SUBNET#{netuid}` | `STATE` | Processor | Processor, Discovery | Per-subnet FSM (IDLE/PROCESSING/COMPLETE/ERROR) |
| `SUBNET#{netuid}` | `PROFILE#basic` | Processor | Finalizer, Discovery | Reward model, gini, processed_at |
| `SUBNET#{netuid}` | `PROFILE#winner` | Processor | Finalizer | Top 5 miners by emission |
| `SUBNET#{netuid}` | `PROFILE#validator` | Processor | Finalizer | Validator landscape data |
| `SUBNET#{netuid}` | `PROFILE#intelligence` | Processor | Finalizer | Self-mining risk, anomalies |
| `SUBNET#{netuid}` | `PROFILE#composability` | Processor | — | Placeholder for subnet dependencies |
| `CONFIG` | `ACTIVE_SUBNETS` | Discovery | Processor, Finalizer | List of monitored netuids |
| `CONFIG` | `TRACKED_HOTKEYS` | Manual | Processor | Hotkey watchlist |
| `CONFIG` | `THRESHOLDS` | Manual (Console) | Finalizer | Alert thresholds, scoring params |
| `CONFIG` | `REFRESH_POLICY` | Manual (Console) | Processor | min_refresh, max_staleness |
| `CONFIG` | `PREVIOUS_ACTIVE_SUBNETS` | Finalizer | Finalizer | For new subnet detection |
| `CYCLE#{id}` | `STATUS` | Processor | Finalizer | subnets_total, subnets_complete |
| `HOTKEY#{ss58}` | `EARNINGS#{period}` | Processor | — | Per-hotkey earnings tracking |
| `HOTKEY#{ss58}` | `SNAPSHOT#{date}` | Processor | — | Daily position snapshot |
| `RANKING` | `LATEST` | Finalizer | — | Current rankings (overwritten) |
| `BRIEFING` | `{date}` | Finalizer | — | Daily briefing summary |
| `STAKE_HISTORY#{netuid}` | `{date}` | Processor | Future (Net TAO Flow) | Daily total validator stake |

### Access Pattern

**All DynamoDB access goes through StateManager** — no handler imports `_float_to_decimal` or accesses `_table` directly. Schema changes only require updating `state_manager.py`.

### DynamoDB Rules
- Never use Python `float` — always `Decimal` via `_float_to_decimal()`
- Conditional expressions for state transitions (prevent race conditions)
- Split profiles to stay under 400KB item limit

## S3 — Dual Bucket Design

### Data Bucket (private, RETAIN on destroy)

```
raw/
├── metagraph/{date}/{netuid}.json          # Raw chain data
├── alpha-prices/{date}/{netuid}.json       # Pool prices + liquidity
├── registration-costs/{date}/{netuid}.json # Reg cost in TAO
└── hyperparameters/{date}/{netuid}.json    # Subnet config

derived/
├── metrics/{date}/{netuid}.json            # Computed metrics per subnet
├── rankings/{date}.json                    # Daily rankings snapshot
└── briefings/{date}.json                   # Daily briefing
```

Lifecycle: Transition to IA after 30 days. Raw snapshots compressed after 30 days.

### Site Bucket (private, CloudFront-only access)

```
data/
├── rankings.json          # Current rankings (overwritten each update)
├── staking_rankings.json  # Staking-focused rankings
├── briefing.json          # Latest briefing
└── metadata.json          # Per-subnet freshness

index.html                 # Dashboard
rankings.html              # Sortable table
briefing.html              # Alerts and changes
llms.txt                   # Agent endpoint index
```

## Data Lifecycle

1. **Collection** (every 1-4 hours per subnet): Raw data stored with `collected_at` timestamp
2. **Processing** (immediately after collection): Derived metrics stored with `processed_at`
3. **Aggregation** (after each subnet processes): Rankings recomputed from all current data
4. **Accumulation** (daily): Stake totals stored for future Net TAO Flow computation
5. **Archival** (30 days): Raw data transitions to S3 IA, compressed

## Data Freshness Guarantees

- No subnet older than `max_staleness_hours` (default: 4 hours)
- Discovery Lambda checks every hour and creates schedules for stale subnets
- Each subnet self-schedules based on its tempo (faster subnets refresh more often)
- Rankings reflect whatever data exists — never gated on "all subnets complete"
