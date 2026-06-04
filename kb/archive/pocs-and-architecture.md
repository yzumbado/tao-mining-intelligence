# POCs & Architecture Vision

> **Last Updated**: 2026-05-14  
> **Purpose**: Define proof-of-concepts and the multi-agent architecture

---

## POC 1: Live Metagraph Snapshot (Foundation)

**Goal**: Pull a live metagraph for 3-5 subnets, understand the actual data shape, store it.

**What we learn**:
- Real data structure and volume
- SDK reliability and performance
- What derived metrics we can compute from raw data
- Baseline for "what does a healthy miner look like"

**Implementation**:
```python
import bittensor as bt
import json
from datetime import datetime

# Pull metagraph for top subnets
for netuid in [1, 8, 19, 25, 32]:
    mg = bt.Metagraph(netuid=netuid)
    # Extract miner-relevant data
    # Store as JSON snapshot with timestamp
```

**Success criteria**: We have a repeatable script that produces a structured JSON snapshot of miner metrics across multiple subnets, and we understand what each field means in practice.

---

## POC 2: Subnet Code Analyzer Agent

**Goal**: Given a subnet's GitHub repo URL, produce a structured "subnet spec" document.

**What we learn**:
- What's consistent across subnet codebases
- What the incentive mechanism code looks like in practice
- How to extract hardware requirements, scoring functions, task types
- How much variation exists between subnets

**Schema for output** (the "Subnet Intelligence Card"):
```json
{
  "subnet_id": 19,
  "name": "Vision/Image",
  "repo_url": "https://github.com/...",
  "last_analyzed_commit": "abc123",
  "last_analyzed_date": "2026-05-14",
  "incentive_mechanism": {
    "task_type": "image_generation",
    "scoring_method": "human_preference_model",
    "scoring_function_location": "neurons/validator.py:L45-L120",
    "key_parameters": {}
  },
  "hardware_requirements": {
    "gpu_type": "A100/H100",
    "vram_min_gb": 40,
    "bandwidth_min_mbps": 100,
    "storage_min_gb": 500
  },
  "miner_template": {
    "entry_point": "neurons/miner.py",
    "dependencies": ["torch", "diffusers", "..."],
    "model_requirements": "Stable Diffusion XL or better"
  },
  "competitive_landscape": {
    "max_miners": 192,
    "current_miners": null,  // filled from metagraph
    "entry_barrier": "high"  // derived from hardware + model requirements
  },
  "gameability_assessment": {
    "risk_level": "medium",
    "notes": "Scoring relies on CLIP similarity — could be gamed with adversarial optimization"
  },
  "change_frequency": "weekly",  // how often the repo gets meaningful updates
  "value_proposition": "Decentralized image generation marketplace"
}
```

**Success criteria**: We can run this against 3 different subnet repos and get useful, structured output that a strategy agent could consume.

---

## POC 3: Registration Cost Tracker & Predictor

**Goal**: Track registration costs across subnets over time, build a simple prediction model.

**What we learn**:
- How volatile registration costs are
- Whether there are patterns (time of day, day of week, after deregistration events)
- Whether we can predict "cheap windows" for registration

**Implementation**: 
- Poll `btcli subnets show --netuid <N>` or SDK equivalent every hour
- Store time series
- After 1-2 weeks, analyze patterns

**Success criteria**: We can tell an agent "subnet X registration cost is likely to drop below Y TAO in the next Z hours" with some confidence.

---

## POC 4: Discord Intelligence Pipeline

**Goal**: Connect to 3-5 subnet Discord channels, filter for actionable signals.

**What we learn**:
- What the actual signal types are (announcements, config changes, outages)
- How to filter noise from value
- Latency between Discord announcement and on-chain change

**Signal categories to detect**:
1. **Incentive mechanism changes** ("we're updating the scoring to...")
2. **Validator configuration changes** ("updating weights to...")
3. **Miner troubleshooting** ("anyone else getting low scores since...")
4. **Registration/deregistration events** ("just got deregistered from...")
5. **Hardware discussions** ("you need at least X to compete on this subnet")
6. **Subnet health signals** ("emissions dropping because...")

**Architecture**:
- Discord bot or webhook listener
- LLM-based classifier for signal vs. noise
- Structured event extraction
- Store in event log with subnet_id, event_type, timestamp, raw_text, extracted_data

**Success criteria**: Over 1 week, we capture at least 10 actionable signals that would have informed a mining decision.

---

## POC 5: YouTube Research Agent

**Goal**: Process top Bittensor mining YouTube content to extract practical knowledge.

**What we learn**:
- What experienced miners actually care about (vs. what docs say)
- Real-world profitability numbers and experiences
- Common pitfalls and strategies
- Hardware setups that work in practice

**Approach**:
- Identify top 10-15 Bittensor mining YouTubers
- Process transcripts (YouTube API or whisper)
- Extract structured knowledge: strategies mentioned, subnets discussed, hardware used, profitability reported
- Cross-reference with our metagraph data

**Success criteria**: We extract at least 5 validated insights that aren't in official docs.

---

## Multi-Agent Architecture Vision

### The "Company" Structure

```
┌─────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE LAYER (S3/DB)                    │
│  Subnet Intelligence Cards │ Metagraph Snapshots │ Events    │
│  Strategy Playbooks │ Historical Performance │ Agent Logs    │
└─────────────────────────────────────────────────────────────┘
        ▲ write                              ▲ write
        │                                    │
┌───────┴────────┐  ┌──────────────┐  ┌─────┴──────────┐
│ CODE ANALYST   │  │ DATA COLLECTOR│  │ DISCORD MONITOR │
│ AGENTS (per    │  │ AGENT        │  │ AGENT           │
│ subnet)        │  │              │  │                 │
│                │  │ - Metagraph  │  │ - Signal filter │
│ - Parse repos  │  │   snapshots  │  │ - Event extract │
│ - Detect changes│ │ - Reg costs  │  │ - Alert routing │
│ - Update specs │  │ - Emissions  │  │                 │
└────────────────┘  └──────────────┘  └─────────────────┘
        ▲ trigger                            ▲ trigger
        │                                    │
┌───────┴────────────────────────────────────┴──────────┐
│              ORCHESTRATOR / SCHEDULER                   │
│  - Daily collection runs                               │
│  - Repo change detection (GitHub webhooks)             │
│  - Discord event routing                               │
│  - Agent health monitoring                             │
└───────────────────────────────────────────────────────┘
        │ read
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    STRATEGY LAYER                             │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ SUBNET       │  │ RISK         │  │ PORTFOLIO    │      │
│  │ RECOMMENDER  │  │ ASSESSOR     │  │ OPTIMIZER    │      │
│  │              │  │              │  │              │      │
│  │ "Mine here"  │  │ "Watch out"  │  │ "Rebalance"  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
        │ recommendations
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    CONSUMER LAYER                             │
│  - REST API for external agents                              │
│  - Alerts/notifications                                      │
│  - Human dashboard (optional, secondary)                     │
│  - Strategy execution interface                              │
└─────────────────────────────────────────────────────────────┘
```

### Agent Roles Defined

| Agent | Responsibility | Trigger | Output |
|-------|---------------|---------|--------|
| **Data Collector** | Pull metagraph snapshots, registration costs, emissions | Scheduled (daily/hourly) | Structured snapshots in knowledge layer |
| **Code Analyst** (×N) | Parse subnet repos, extract incentive mechanisms, detect changes | GitHub webhook / scheduled | Subnet Intelligence Cards |
| **Discord Monitor** | Listen to subnet Discords, filter signals, extract events | Real-time stream | Structured events + alerts |
| **YouTube Researcher** | Process new mining content, extract insights | Weekly or on new video | Knowledge entries, strategy notes |
| **Subnet Recommender** | Given current state, recommend which subnets to mine | On-demand / daily | Ranked subnet list with rationale |
| **Risk Assessor** | Monitor deregistration risk, subnet health, emission trends | Continuous | Risk scores, alerts |
| **Portfolio Optimizer** | Multi-subnet allocation strategy | On-demand / weekly | Allocation recommendations |

### Shared Knowledge Model

All agents read from and write to a common knowledge layer. Key entities:

1. **Subnet Intelligence Card** — structured understanding of each subnet (from code analysis)
2. **Metagraph Snapshot** — point-in-time state of all neurons in a subnet
3. **Event Log** — timestamped events from Discord, chain, repos
4. **Strategy Playbook** — accumulated mining strategies and their historical performance
5. **Research Notes** — unstructured findings from YouTube, docs, community

### Key Design Principles

1. **Append-only knowledge**: Never delete, always version. Historical context is the moat.
2. **Schema-first**: Define the data contracts between agents before building them.
3. **Eventual consistency**: Agents don't need real-time sync. Daily is fine for most.
4. **Graceful degradation**: If one agent fails, others continue with stale data.
5. **Human-in-the-loop for strategy**: Agents recommend, humans (or a master agent) decide.
6. **Audit trail**: Every recommendation should be traceable to the data that informed it.

---

## What's Missing From This Vision (Honest Assessment)

### Technical Gaps
1. **LLM cost for code analysis at scale**: Analyzing 128 repos regularly with an LLM isn't free. Need to be smart about diff-based analysis (only re-analyze what changed).
2. **Discord API limitations**: Rate limits, bot permissions, some channels may be private.
3. **YouTube transcript quality**: Auto-generated captions are noisy. May need Whisper for accuracy.
4. **Subnet repo discovery**: Not all subnets have public repos. Some are closed-source.

### Strategic Gaps
1. **Validation loop**: How do we know our analysis is correct? We need a feedback mechanism — ideally, actually mining based on recommendations and measuring outcomes.
2. **Adversarial dynamics**: If our system recommends a subnet, and many agents follow that recommendation, it increases competition and reduces profitability. The system's own recommendations change the landscape.
3. **Legal/ToS considerations**: Some subnets may have terms about automated analysis or bot participation.
4. **Alpha token economics**: Mining profitability isn't just about TAO emissions — it's also about the alpha token price. A subnet with high emissions but a crashing alpha token may not be profitable.

### Organizational Gaps
1. **Who validates the code analyst's output?** Initially, us. But at scale, we need automated validation (e.g., "does the extracted scoring function match observed on-chain behavior?")
2. **Priority ordering**: We can't build all agents at once. What's the MVP that delivers value fastest?

---

## Suggested Build Order (MVP → Full Vision)

### Phase 1: Foundation (Weeks 1-2)
- POC 1: Metagraph snapshot pipeline
- POC 3: Registration cost tracker
- Basic S3 storage + simple API
- **Value delivered**: Raw data collection working, we understand the data

### Phase 2: Intelligence (Weeks 3-4)
- POC 2: Subnet code analyzer (start with 5 subnets)
- Define Subnet Intelligence Card schema
- Basic derived metrics (deregistration risk score, emission trend)
- **Value delivered**: Structured understanding of top subnets

### Phase 3: Signals (Weeks 5-6)
- POC 4: Discord monitor (3-5 channels)
- POC 5: YouTube research (batch process existing content)
- Event log and alert system
- **Value delivered**: Real-time awareness of ecosystem changes

### Phase 4: Strategy (Weeks 7-8)
- Subnet recommender agent
- Risk assessor
- Portfolio optimizer
- **Value delivered**: Actionable mining recommendations

### Phase 5: Scale (Ongoing)
- Expand to all 128 subnets
- Automated feedback loop (mine → measure → improve)
- Multi-agent coordination refinement
- External API for third-party agents

---

## POC 6: Miner Submission / Top Miner Analysis

**Goal**: Identify top-performing miners on 3 subnets, find their public code/patterns, correlate with performance.

**What we learn**:
- What winning miners actually do (ground truth)
- Whether top miner code is publicly available or mostly private
- Response time / quality patterns that correlate with high incentive
- Whether hotkey tracking reveals strategic behavior (subnet hopping, timing)

**Approach**:
1. From metagraph snapshots, identify top 5 miners per subnet (by incentive score)
2. Look up their hotkeys — any public repos linked?
3. Track their registration history across subnets
4. Analyze patterns: when did they register, how fast did they climb, did they switch subnets?

**Success criteria**: For at least 2 subnets, we can describe "what a winning miner looks like" with specific, actionable detail.

---

## Revised Build Order

### Phase 1: Foundation (Weeks 1-3)
- POC 1: Metagraph snapshot pipeline (all subnets, daily)
- POC 3: Registration cost tracker
- Basic S3 storage + DynamoDB state
- Step Functions FSM for pipeline orchestration
- **Deliverable**: Working daily data collection, queryable snapshots

### Phase 2: Intelligence (Weeks 4-6)
- POC 2: Subnet Code Analyzer / Researcher (start with 5 subnets)
- POC 6: Top Miner Analysis (3 subnets)
- Subnet Intelligence Card schema + first cards
- Alpha token price tracking
- **Deliverable**: Structured understanding of top subnets + what winners do

### Phase 3: Strategy (Weeks 7-9)
- Derived metrics engine (deregistration risk, ROI estimates, trend scores)
- Simple recommendation logic ("based on your hardware, mine here")
- Registration cost prediction model
- **Deliverable**: Actionable daily recommendations for personal mining

### Phase 4: Signals & Scale (Weeks 10+)
- POC 4: Discord monitor
- POC 5: YouTube research batch
- Expand Subnet Researcher to all active subnets
- Feedback loop: track actual mining results vs. recommendations
- **Deliverable**: Full intelligence platform with real-time signals

---

## YouTube Research Targets (To Investigate)

- [ ] Search for: "Bittensor mining tutorial 2025"
- [ ] Search for: "TAO subnet mining profitability"
- [ ] Search for: "Bittensor miner setup guide"
- [ ] Search for: "dTAO mining strategy"
- [ ] Search for: "Bittensor subnet analysis"
- [ ] Identify top creators in the space
- [ ] Extract hardware recommendations
- [ ] Extract profitability reports and compare with on-chain data
