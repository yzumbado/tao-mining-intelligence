# Architecture Decisions Log

> **Last Updated**: 2026-05-14  
> **Purpose**: Record architectural decisions and rationale as we refine the design

---

## Decision 1: Assembly Line over Agent Swarm

**Context**: Multi-agent coordination is expensive and error-prone when agents need to negotiate or share state in real-time.

**Decision**: Model the system as a **digital commodity assembly line** — a series of data pipeline stages where the output of one stage is the input of the next. Use a **finite state machine (FSM)** to model the lifecycle of data as it moves through the pipeline.

**Rationale**:
- Predictable behavior — each stage has defined inputs and outputs
- Easier to debug — you can inspect the state at any transition
- LLMs are used only where they add value (unstructured → structured), not for coordination
- Normal scripts handle deterministic transformations
- Scales linearly — add more subnets, add more pipeline instances
- Failure isolation — one stage failing doesn't cascade unpredictably

**Implications**:
- Need to define clear data contracts between stages
- Each stage is independently deployable and testable
- State machine transitions are the "orchestration" — not an LLM deciding what to do next
- EventBridge / Step Functions are natural AWS implementations of this pattern

---

## Decision 2: Subnet Researcher as First-Class Component

**Context**: The cold start problem — we need to analyze ~128 subnets with wildly different codebases, and handle new subnets appearing, existing ones dying, and code changing.

**Decision**: Build a **Subnet Researcher** that is a well-defined pipeline stage with:
- A classification taxonomy it applies to any subnet
- A structured output schema (Subnet Intelligence Card)
- The ability to ask the user when it encounters ambiguity
- Self-awareness of what it doesn't know (confidence scores)

**The Subnet Researcher knows**:
1. What to look for in any subnet repo (scoring function, hardware reqs, task type, model requirements)
2. How to classify subnets into categories (LLM, vision, compute, storage, financial, scientific)
3. When to escalate to a human ("I found the scoring function but can't determine if it's gameable")
4. How to detect meaningful changes vs. noise in repo updates

**Classification Taxonomy** (first draft):
```
Subnet Category:
├── AI Inference
│   ├── Text/LLM (SN1, SN3...)
│   ├── Vision/Image (SN19...)
│   ├── Audio/Speech
│   └── Multimodal
├── AI Training
│   ├── Distributed Training
│   └── Fine-tuning
├── Compute
│   ├── General GPU
│   └── Specialized (protein folding, etc.)
├── Data/Storage
│   ├── Decentralized Storage
│   └── Data Indexing
├── Financial
│   ├── Prediction Markets
│   └── Trading Signals
└── Infrastructure
    ├── Networking
    └── Oracles
```

**What the Researcher extracts per subnet**:
1. **Task Definition**: What does a miner actually DO on this subnet?
2. **Scoring Function**: How is quality measured? (code location + explanation)
3. **Hardware Requirements**: GPU type, VRAM, CPU, RAM, bandwidth, storage
4. **Model Requirements**: What models/weights are needed?
5. **Competitive Dynamics**: How many miners, what's the skill floor?
6. **Gameability Assessment**: Can the scoring be exploited? How?
7. **Entry Barrier**: Cost to start mining (hardware + registration + setup time)
8. **Revenue Potential**: Current emissions × miner share ÷ active miners
9. **Trend**: Is this subnet growing, stable, or declining?
10. **Dependencies**: External APIs, datasets, or services required

---

## Decision 3: Discord is Phase 2+

**Context**: Discord monitoring has high value but high noise ratio, and requires the Subnet Researcher context to know what signals matter.

**Decision**: Defer Discord integration to Phase 2. Focus Phase 1 on on-chain data and code analysis.

**Rationale**:
- On-chain data is deterministic and structured — better foundation
- Code analysis gives us the context needed to filter Discord signals later
- Discord API has rate limits and permission complexities
- We can manually monitor Discord during Phase 1 and note what signals would have been valuable

---

## Decision 4: LLM Where It Adds Value, Scripts Everywhere Else

**Context**: Not every stage needs an LLM. Using LLMs for deterministic data transformations is wasteful and introduces non-determinism.

**Decision**: Clear separation of concerns:

| Stage | LLM? | Rationale |
|-------|-------|-----------|
| Metagraph data collection | No | Deterministic API calls |
| Data normalization/storage | No | Schema mapping, no interpretation needed |
| Registration cost tracking | No | Numeric time series |
| Derived metrics (risk scores, trends) | No | Mathematical formulas |
| Subnet code analysis | **Yes** | Unstructured code → structured understanding |
| Change detection (meaningful vs. noise) | **Yes** | Requires judgment |
| Strategy recommendations | **Yes** | Requires reasoning over multiple factors |
| Report generation | **Yes** | Natural language output |
| Discord signal filtering | **Yes** (Phase 2) | Requires NLU |
| YouTube transcript analysis | **Yes** (Phase 2) | Requires NLU |

**Cost implication**: LLM costs are concentrated in the Subnet Researcher and Strategy layers. Data collection is cheap to run at scale.

---

## Decision 5: Design for Subnet Lifecycle

**Context**: Subnets are born, grow, decline, and die. They get renamed, deregistered, forked. The system must handle this gracefully.

**Decision**: Model subnets as entities with a lifecycle state machine:

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ DISCOVERED│────▶│ ANALYZED │────▶│ MONITORED│────▶│ ARCHIVED │
│           │     │          │     │          │     │          │
│ New subnet│     │ Initial  │     │ Active   │     │ Dead or  │
│ detected  │     │ research │     │ tracking │     │ dormant  │
│ on chain  │     │ complete │     │          │     │          │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                       │                 │
                       │                 ▼
                       │          ┌──────────┐
                       └─────────▶│ RE-ANALYZE│
                                  │          │
                                  │ Code or  │
                                  │ mechanism│
                                  │ changed  │
                                  └──────────┘
```

**Subnet identity tracking**:
- Primary key: `netuid` (on-chain identifier)
- Track: name changes, repo URL changes, owner changes
- Never delete — archive with full history
- Link historical data across identity changes

---

## Decision 6: Finite State Machine for Pipeline Orchestration

**Context**: We need predictable, debuggable orchestration that handles failures gracefully.

**Decision**: Model the entire data pipeline as an FSM where:
- **States** = stages of data processing
- **Transitions** = completion of a stage (success/failure)
- **Events** = triggers (scheduled, webhook, manual)

### Pipeline FSM (per subnet, per collection cycle)

```
[IDLE] 
  │ trigger: schedule/webhook
  ▼
[COLLECTING_METAGRAPH]
  │ success → data stored
  ▼
[COMPUTING_METRICS]
  │ success → derived metrics stored
  ▼
[CHECKING_CODE_CHANGES]
  │ no changes → skip to UPDATING_CARD
  │ changes detected → 
  ▼
[ANALYZING_CODE] (LLM stage)
  │ success → new analysis stored
  │ low confidence → [NEEDS_HUMAN_INPUT]
  ▼
[UPDATING_CARD]
  │ success → Subnet Intelligence Card updated
  ▼
[EVALUATING_RISK]
  │ success → risk scores updated
  ▼
[COMPLETE]
  │ → back to [IDLE], wait for next trigger
```

### Error Handling States
```
[ERROR_RETRYABLE] → retry with backoff → original state
[ERROR_FATAL] → alert + log → [IDLE] (skip this cycle)
[NEEDS_HUMAN_INPUT] → queue for user → resume when answered
```

**AWS Implementation**:
- AWS Step Functions = natural FSM implementation
- Each state = Lambda function or ECS task
- Built-in retry, error handling, timeout
- Visual debugging in console
- EventBridge for scheduling triggers

---

## Decision 7: Append-Only Knowledge with Versioning

**Context**: Historical context is the moat. We never want to lose data.

**Decision**:
- All data is append-only (new snapshots, never overwrite)
- Subnet Intelligence Cards are versioned (v1, v2, v3...)
- Every analysis includes: timestamp, source commit, confidence score
- "Current" is always a pointer to the latest version
- Archived subnets retain full history

**Storage model**:
```
s3://tao-intelligence/
├── metagraph-snapshots/
│   ├── 2026-05-14/
│   │   ├── subnet-1.json
│   │   ├── subnet-8.json
│   │   └── ...
│   └── 2026-05-15/
├── subnet-cards/
│   ├── subnet-1/
│   │   ├── v1-2026-03-01.json
│   │   ├── v2-2026-04-15.json
│   │   └── current.json → v2
│   └── subnet-19/
├── registration-costs/
│   └── timeseries.parquet
├── events/
│   ├── 2026-05-14.jsonl
│   └── ...
└── research-notes/
    ├── youtube-extracts/
    └── manual-notes/
```

---

## Decision 8: Miner Submission Analysis as Knowledge Source

**Context**: Beyond analyzing subnet code (the "rules of the game"), we can also analyze what successful miners actually DO — their code, model choices, response patterns. This is ground-truth data about "what wins."

**Decision**: Add a **Miner Submission Analyzer** stage to the pipeline that:
- Identifies top-performing miners per subnet (from metagraph: high incentive, high trust)
- Finds their public repos/code when available
- Analyzes their approach: what model, what optimizations, what hardware
- Correlates approach with on-chain performance metrics

**Knowledge sources for miner analysis**:
1. **Public miner repos** — some miners open-source their implementations
2. **Axon response patterns** — response times, payload sizes (observable from validator perspective)
3. **Registration patterns** — when top miners register, on which subnets, how long they survive
4. **Hotkey history** — track a successful miner's hotkey across subnets over time

**What this tells us**:
- "The top 3 miners on SN19 all use SDXL Turbo with custom LoRA weights"
- "Miners who respond in <200ms on SN1 get 2x the incentive of those at 500ms"
- "This miner registered on SN32 right after a code update and immediately ranked top 10 — they knew something"

**Limitations**:
- Many miners keep code private (competitive advantage)
- Axon responses aren't publicly logged (only validators see them)
- Correlation ≠ causation — a miner might rank high due to stake, not quality

**Phase**: Include in Phase 2 alongside Discord. Requires Phase 1 metagraph data to identify who to analyze.

---

## Decision 9: Personal Tool First, Public Platform Later

**Context**: Adversarial feedback loops (recommendations changing the market) are a real concern for public tools, but not for personal use.

**Decision**: Build for single-user (personal mining intelligence) first. Defer multi-tenant, public API, and adversarial dynamics to a future phase.

**Implications**:
- Simpler auth (no multi-tenancy)
- No rate limiting on our own API
- Can hardcode preferences and risk tolerance
- Strategy recommendations don't need to account for market impact
- Lower infrastructure costs (no need for high availability)
- Can iterate faster without worrying about breaking others

**When to revisit**: When the system is generating consistent value and we want to either:
- Sell access as a service
- Open-source the data layer
- Build a community around it

---

## Decision 10: Dual Classification — Category + Mining Style

**Context**: Classifying subnets only by what they produce (LLM, Vision, etc.) doesn't answer the strategic question "what do I need to invest to compete here?" A subnet's category tells you what it makes; its mining style tells you what resource you burn to win.

**Decision**: Every subnet gets two classification axes:
1. **Category** (what it produces): LLM_INFERENCE, VISION_IMAGE, TRADING_FINANCIAL, DATA_COLLECTION, COMPUTE, TRAINING, PREDICTION, STORAGE, SCIENTIFIC, OTHER
2. **Mining Style** (key resource consumed): GPU_INFERENCE, GPU_TRAINING, RAW_COMPUTE, KNOWLEDGE_STRATEGY, DATA_COLLECTION, MODEL_QUALITY, LATENCY, CAPITAL

**Rationale**:
- A Vision subnet might be MODEL_QUALITY style (best model wins) or GPU_INFERENCE style (fastest serving wins) — very different strategies
- Enables filtering: "show me all subnets where my A100 gives me an edge" (GPU_INFERENCE + GPU_TRAINING)
- Enables matching: "I have trading expertise but no GPU" → KNOWLEDGE_STRATEGY subnets
- Mining style directly maps to the rent-vs-buy analysis (only GPU styles benefit from renting)

**Implications**:
- Subnet profiles store both fields
- Rankings can be filtered by mining style
- Rental profitability analysis only applies to GPU_INFERENCE, GPU_TRAINING, RAW_COMPUTE styles
- Static site shows mining style as a color-coded badge

---

## Open Architecture Questions

1. ~~**Step Functions vs. custom FSM**~~: RESOLVED — Using SQS/SNS for orchestration with DynamoDB state tracking. Step Functions exceeds free tier; SQS/SNS is free and provides built-in retry/DLQ.

2. ~~**Subnet Researcher deployment**~~: DEFERRED to Phase 2. Will use Container Image Lambda with Bedrock for LLM analysis.

3. **How does the user interact?**: Static site (Jinja2 + Tailwind, dark theme) via CloudFront + Kiro reading from S3/DynamoDB. API Gateway deferred.

4. **Multi-region**: Not needed for Phase 1. Single region (us-east-1). If Finney endpoint is unreliable, can add a fallback endpoint.

---

## Decision 11: Split Profiles as Single Source of Truth (No METRICS#latest)

**Date**: 2026-05-16

**Context**: The original design had a `SUBNET#{netuid}|METRICS#latest` DynamoDB item containing all derived metrics for a subnet. At 1000+ subnets with full per-neuron deregistration risk arrays, winner profiles, and intelligence notes, this single item risks exceeding DynamoDB's 400KB item size limit.

**Decision**: Split profiles (`PROFILE#basic`, `PROFILE#winner`, `PROFILE#validator`, `PROFILE#intelligence`, `PROFILE#composability`) are the **single source of truth** for subnet metrics in DynamoDB. There is no aggregate `METRICS#latest` record.

**Rationale**:
- Each profile stays well under 400KB independently
- Consumers read only the profile they need (one GetItem, not a fat blob)
- Independent update frequency — basic profile rarely changes, winner profile changes daily
- At 1000 subnets × 5 profiles = 5000 items — trivial for DynamoDB
- Derived metrics are also stored in S3 at `derived/metrics/{date}/{netuid}.json` for full history

**Implications**:
- Ranking generation (Finalizer) reads `PROFILE#basic` for each subnet to build the ranking table
- No single "get everything about subnet X" call — consumers make 1-5 targeted reads
- If a "summary" view is needed later, it can be a GSI or a separate lightweight item

---

## Decision 12: Tempo Conversion is the Handler's Responsibility

**Date**: 2026-05-16

**Context**: The Bittensor SDK returns emission values in **alpha tokens per tempo** (where tempo is a subnet-specific hyperparameter, typically 360 blocks). The MetricsEngine needs daily emission values for ROI calculations. The question is: who converts per-tempo to per-day?

**Decision**: The Processor handler reads `tempo` from hyperparameters and multiplies each neuron's emission by `(7200 / tempo)` **before** passing data to MetricsEngine. MetricsEngine functions expect emissions already in daily units.

**Rationale**:
- MetricsEngine stays pure — no dependency on hyperparameters or external context
- Property tests for MetricsEngine work with simple inputs (no need to mock hyperparams)
- The handler is the "wiring" layer that normalizes data between raw storage and pure computation
- Different subnets have different tempos — the handler handles this per-subnet

**Implications**:
- MetricsEngine.compute_roi_estimates() assumes emission values are daily
- Tests for MetricsEngine use pre-converted values
- The Processor handler must always read hyperparameters to get tempo
- If tempo is missing, handler uses default of 360 (most common value)

---

## Decision 13: Taoflow History — Graceful Degradation

**Date**: 2026-05-16

**Context**: `compute_taoflow_health()` requires multi-day stake and emission history (8+ days for death spiral detection). On day 1 of the pipeline, we have no history. Building up history takes time.

**Decision**: Return `TaoflowStatus.HEALTHY` with `consecutive_negative_days=0` when insufficient history exists. Do not attempt to read N days of S3 snapshots — that's expensive and fragile.

**Future path (when needed)**:
- Store running daily totals in DynamoDB: `SUBNET#{netuid}|HISTORY` with last 30 days of {date: stake_total, emission_total}
- Processor appends today's values on each run
- After 8 days of data, Taoflow detection activates naturally

**Rationale**:
- Simplest correct behavior — "I don't have enough data" is not an error
- Avoids N×S3 reads per subnet per cycle (at 128 subnets × 8 days = 1024 reads)
- History accumulates naturally — no backfill needed
- The pipeline is designed to run daily forever; patience is acceptable

**Implications**:
- First 7 days of pipeline operation: all subnets show HEALTHY (no false alarms)
- Churn metrics similarly degrade gracefully (no previous day = zero churn reported)
- Emission trend: no previous day = direction "stable", change_percent 0.0

---

## Decision 14: Per-Subnet FSM as Best-Effort Observability

**Date**: 2026-05-16

**Context**: The pipeline has two tracking mechanisms:
1. **Cycle-level** (`CYCLE#{date}|STATUS`): tracks overall progress, gates the Finalizer
2. **Per-subnet** (`SUBNET#{netuid}|STATE`): tracks individual subnet processing state

The Finalizer only checks cycle-level completion (`subnets_complete >= subnets_total`). Per-subnet state is not on the critical path.

**Decision**: Per-subnet FSM transitions are **best-effort**. The Processor attempts state transitions but does not fail processing if a transition is rejected (e.g., conditional check fails due to stale state).

**Critical path**: `increment_cycle_progress(cycle_id)` — this is what gates the Finalizer.

**Best-effort**: `transition(netuid, "IDLE", "PROCESSING")` and `transition(netuid, "PROCESSING", "COMPLETE")` — useful for debugging but not required for correctness.

**Rationale**:
- Cycle-level counter is atomic (DynamoDB ADD) and reliable
- Per-subnet state can get stale if a previous cycle's error wasn't cleaned up
- Failing processing because of a state transition issue would be worse than skipping the transition
- Per-subnet state is valuable for: identifying stuck subnets, implementing 24h cooldown, dashboard visibility

**Implications**:
- Handler wraps per-subnet transitions in try/except — log warning on failure, continue processing
- Cycle counter increment is NOT wrapped — if it fails, the processing result reflects the error
- Future: add a "state reconciliation" step at cycle start that resets stale per-subnet states

5. ~~**Cost budget**~~: RESOLVED — $0/month. All services within always-free tier. Container Image Lambda solves SDK size. SQS/SNS/CloudFront/Parameter Store all have generous free tiers.

---

## Decision 15: Configurable Collection Frequencies per Data Area

**Date**: 2026-05-17

**Context**: The pipeline evolved from a single daily batch into a multi-source intelligence platform. Different data sources have different freshness requirements. Chain events (registrations, stake movements) benefit from near-real-time detection. Metagraph snapshots are heavy and daily is sufficient. Social data (YouTube, Discord) is daily.

**Decision**: Each collection area has an independently configurable frequency stored in DynamoDB `CONFIG|COLLECTION_FREQUENCIES`:

```json
{
  "metagraph": "60min",
  "chain_events": "15min",
  "prices": "4h",
  "social": "daily",
  "code": "daily"
}
```

Initial deployment frequencies:
- Chain events: every 15 minutes (configurable down to 1 minute)
- Metagraph snapshots: every 60 minutes (spread: 1 subnet/min via reserved concurrency)
- TAO/USD price: every 4 hours
- Social/code: daily

**Implementation**: Each area has its own EventBridge rule. Changing frequency = updating the EventBridge schedule (via console or config update Lambda). No code changes needed to adjust frequency.

**Rationale**:
- 15-minute chain events uses ~3% of Lambda free tier (10,800 invocations/month, ~28,000 GB-seconds)
- Can be tightened to 1 minute (14% requests, 44% compute) without leaving free tier
- Each area is independent — increasing metagraph frequency doesn't affect chain event budget
- Configurable via DynamoDB means no redeployment to change frequencies

**Free tier budget at initial frequencies**:
| Component | Requests/month | GB-seconds/month |
|-----------|---------------|-----------------|
| SubnetCollector (128 subnets, hourly) | 92,160 | ~47,000 |
| ChainEventCollector (every 15min) | 2,880 | ~7,400 |
| Processor (128 subnets, daily) | 3,840 | ~19,000 |
| Finalizer (daily) | 30 | ~150 |
| PriceCollector (every 4h) | 180 | ~90 |
| SocialCollector (daily) | 30 | ~150 |
| **Total** | **~99,120** | **~73,790** |
| **Free tier** | **1,000,000** | **400,000** |
| **Usage** | **~10%** | **~18%** |

---

## Decision 16: Orchestrator + SubnetCollector Split (Eliminate Burst Load)

**Date**: 2026-05-17

**Context**: The monolithic Collector Lambda blasts 128+ subnets in one 15-minute invocation, creating burst load on the Finney endpoint and risking timeout. Each subnet's data is independent.

**Decision**: Split the Collector into:
1. **Orchestrator Lambda** (lightweight, <30s): discovers subnets, claims cycle, publishes one SQS message per subnet to a collection queue, collects global data (TAO/USD price)
2. **SubnetCollector Lambda** (reserved concurrency=2, 60s timeout): collects metagraph + hyperparams + alpha price + reg cost for ONE subnet per invocation

**Data flow**:
```
EventBridge (hourly) → Orchestrator → Collection Queue (SQS)
                                            │
                                            ▼ (1 message per subnet)
                                    SubnetCollector (concurrency=2)
                                            │
                                            ▼
                                    Processing Queue → Processor → Finalizer
```

**Rationale**:
- Eliminates burst: at concurrency=2, subnets process ~2/min = 64 minutes for 128 subnets
- Eliminates timeout risk: each invocation <30s (one subnet = 4-5 RPC calls)
- Eliminates circuit breaker need: SQS retry IS the circuit breaker (3 attempts → DLQ)
- Eliminates graceful shutdown logic: no time management needed
- Same monitoring: trace_id propagated via SQS messages, same instrumentation pattern
- Same cost: more invocations but shorter duration = same GB-seconds

**Implications**:
- Collector handler.py refactored into orchestrator/handler.py + subnet_collector/handler.py
- CDK adds: collection queue + DLQ, SubnetCollector Lambda with reserved concurrency
- Tests refactored to match new split
- Circuit breaker and concurrency semaphore code can be removed (SQS handles both)

---

## Decision 17: Batch Chain Event Processing (No Fargate, $0)

**Date**: 2026-05-17

**Context**: Chain events (NeuronRegistered, StakeAdded, NetworkAdded, etc.) are valuable for near-real-time alerts. The initial assumption was that monitoring events requires an always-on WebSocket subscription (Fargate, ~$5/month).

**Decision**: Process chain events in batches via Lambda. The chain stores events permanently in blocks. A scheduled Lambda queries historical blocks since the last checkpoint, filters for interesting events, and stores them.

**Implementation**:
- DynamoDB stores `CONFIG|LAST_EVENT_BLOCK` (checkpoint)
- EventBridge triggers ChainEventCollector every 15 minutes
- Lambda queries ~75 blocks (15min × 5 blocks/min), filters events, stores to S3
- If Lambda fails, next invocation picks up from the same checkpoint (idempotent)

**Events we monitor**:
- `NeuronRegistered(NetUid, u16, AccountId)` — new miner/validator
- `StakeAdded/Removed(AccountId, AccountId, TaoBalance, AlphaBalance, NetUid)` — whale movements
- `NetworkAdded/Removed(NetUid)` — subnet lifecycle
- `HotkeySwapped(AccountId, AccountId, AccountId)` — wallet migrations
- `LiquidityAdded/Removed(...)` — AMM pool changes
- `BurnSet(NetUid, TaoBalance)` — registration cost changes

**Rationale**:
- $0 (Lambda free tier: 2,880 invocations/month at 15min intervals)
- 15-minute latency is acceptable for intelligence (not trading execution)
- Backfillable: set checkpoint to any historical block to reprocess
- No connection management, no Fargate, no always-on cost
- Can be tightened to 1-minute latency by changing EventBridge schedule (still $0)
