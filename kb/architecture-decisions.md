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

5. ~~**Cost budget**~~: RESOLVED — $0/month. All services within always-free tier. Container Image Lambda solves SDK size. SQS/SNS/CloudFront/Parameter Store all have generous free tiers.
