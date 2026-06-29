# TAO Mining Intelligence — Product Vision & Roadmap

## End Goal

An **autonomous TAO accumulation machine** that continuously discovers, evaluates,
deploys, and optimizes mining and validating positions across the Bittensor network.
The system self-improves by learning from its own performance, reallocating resources
to maximize net TAO yield with minimal human intervention.

## Design Principles

- **Autonomous by default**: Every stage should run without human intervention once configured
- **Self-improving**: Results feed back into strategy, improving decisions over time
- **Free tier first**: Maximize AWS free tier; only spend money on actual mining compute
- **Pipeline architecture**: Each stage has clear inputs/outputs, independently testable
- **Deterministic where possible**: LLM reserved for research/analysis, not core logic
- **TAO accumulation, not USD**: All decisions optimize for net TAO, not fiat conversion

## The Seven Stages

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS TAO MACHINE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Stage 1: COLLECT ✅ (DONE)                                      │
│  │  On-chain data, metrics, rankings                             │
│  │  Once daily per subnet, rankings twice daily                  │
│  ▼                                                               │
│  Stage 2: RESEARCH ✅ (DONE)                                     │
│  │  Subnet requirements, model types, hardware needs             │
│  │  GitHub scraping, deterministic parsing, 7-day refresh        │
│  ▼                                                               │
│  Stage 3: STRATEGIZE (NEXT)                                      │
│  │  Given my resources, where to deploy?                         │
│  │  Mine vs validate, portfolio optimization                     │
│  ▼                                                               │
│  Stage 4: BUILD                                                  │
│  │  Generate/adapt mining agents for target subnets              │
│  │  Package as deployable containers                             │
│  ▼                                                               │
│  Stage 5: TEST                                                   │
│  │  Simulate against historical data                             │
│  │  Predict rank, yield, deregistration risk                     │
│  ▼                                                               │
│  Stage 6: DEPLOY                                                 │
│  │  Register on-chain, deploy compute, monitor                   │
│  │  Auto-deregister if underperforming                           │
│  ▼                                                               │
│  Stage 7: OPTIMIZE                                               │
│     Compare actual vs predicted, reallocate, self-improve        │
│     Feed learnings back to Stage 3                               │
│                                                                   │
│  ◄──────── Continuous feedback loop ────────►                    │
└─────────────────────────────────────────────────────────────────┘
```

## Stage Details

### Stage 1: COLLECT ✅ Complete

**Status**: Deployed, autonomous, 129 subnets self-scheduling (currently paused — resume July 1)

**What it produces**:
- Per-subnet metrics: ROI, yield, competition, churn, risk, taoflow health, price trends
- Rankings sorted by attractiveness (20 fields, generated twice daily)
- Agent-consumable endpoints (llms.txt, rankings.json, metadata.json)
- Historical snapshots (append-only S3, full time-series)

**Infrastructure**: Lambda (7 functions), DynamoDB, S3, EventBridge Scheduler, CloudFront
**Cost**: ~$0/month (8% of free tier at steady state)

---

### Stage 2: RESEARCH (Next)

**Goal**: For each subnet, answer "what does it take to win here?"

**Inputs**: Rankings from Stage 1, subnet GitHub repos, documentation

**Outputs** (per subnet):
```json
{
  "netuid": 4,
  "subnet_name": "Multi-Modality",
  "model_type": "multi-modal generation",
  "hardware_minimum": {"gpu": "A100", "vram_gb": 40, "cpu_cores": 8},
  "open_source_miner": "https://github.com/...",
  "miner_difficulty": "medium",
  "validator_minimum_stake": 50000,
  "estimated_monthly_cost_usd": 200,
  "net_profit_tao_per_day": 43.2,
  "entry_recommendation": "MINE",
  "last_researched": "2026-05-18T00:00:00Z"
}
```

**How it works**:
1. Scrape subnet's GitHub repo (most are public)
2. Analyze miner code: detect model type, dependencies, GPU requirements
3. Check if open-source miner exists (can you just run it?)
4. Estimate hardware cost from cloud GPU pricing
5. Compare cost vs yield from Stage 1 → net profit
6. Classify difficulty: trivial (run open-source), medium (adapt), hard (build custom)

**Infrastructure**: Lambda + S3 + GitHub API (free for public repos)
**LLM usage**: Code analysis (classify model type, extract requirements)
**Refresh cadence**: Weekly per subnet (requirements don't change daily)
**Cost**: ~$0 (GitHub API free, LLM via Bedrock free tier or local)

---

### Stage 3: STRATEGIZE

**Goal**: Given my specific resources, produce an action plan

**Inputs**: Research from Stage 2 + user profile (hardware, capital, skills)

**User profile** (stored in DynamoDB):
```json
{
  "available_hardware": [{"type": "RTX 4090", "vram_gb": 24, "count": 1}],
  "available_tao_for_staking": 1000,
  "available_tao_for_registration": 10,
  "risk_tolerance": "medium",
  "max_subnets": 3,
  "prefer_passive": true
}
```

**Outputs**:
- Ranked list of actionable opportunities
- For each: mine or validate, expected yield, required investment, risk level
- Portfolio allocation recommendation (diversification)
- "Do nothing" option with reasoning (if no good opportunities exist)

**Infrastructure**: Lambda (pure computation)
**Cost**: $0

---

### Stage 4: BUILD

**Goal**: Produce a deployable mining agent for a target subnet

**Inputs**: Strategy decision + subnet miner code from Research

**What it does**:
1. Fork/clone the subnet's open-source miner
2. Configure for user's hardware (model size, batch size, etc.)
3. Package as Docker container with all dependencies
4. Generate deployment scripts (EC2 user-data, docker-compose)
5. For custom models: fine-tune or select best available checkpoint

**Infrastructure**: Lambda for orchestration, CodeBuild for Docker builds
**Cost**: CodeBuild free tier (100 min/month). GPU compute is the real cost.

**Key constraint**: Start with subnets that have open-source miners and don't
require custom model training. These are "run and earn" opportunities.

---

### Stage 5: TEST

**Goal**: Validate strategy before spending TAO on registration

**Inputs**: Built agent + historical metagraph data from Stage 1

**What it does**:
1. Replay last 7 days of metagraph data
2. Simulate: "if my agent produced output X, where would I rank?"
3. Estimate emission share based on historical validator scoring patterns
4. Calculate: would I have been deregistered? When?
5. Produce confidence interval: "70% chance of earning 2-5 TAO/day"

**Infrastructure**: Lambda + S3 (historical data already stored)
**Cost**: $0

---

### Stage 6: DEPLOY

**Goal**: Go live on-chain with minimal risk

**Inputs**: Tested agent + registration decision

**What it does**:
1. Register hotkey on target subnet (automated via SDK)
2. Deploy miner container to compute (EC2 spot instance)
3. Monitor first 24h (immunity period — can't be deregistered)
4. Track emission rank vs prediction from Stage 5
5. Auto-deregister if performance is below break-even threshold
6. Alert if approaching deregistration risk

**Infrastructure**: Lambda (orchestration), EC2 spot (mining compute)
**Cost**: EC2 spot varies ($0.30-$3/hr for GPU instances)

---

### Stage 7: OPTIMIZE

**Goal**: Continuously improve returns across all positions

**Inputs**: Live performance data + Stage 1 continuous monitoring

**What it does**:
1. Compare actual yield vs predicted yield (calibrate Stage 5 model)
2. Detect declining subnets early (emission trend, new competitors)
3. Recommend reallocation: "move from SN8 (declining) to SN4 (growing)"
4. Auto-reallocate validator stake between subnets
5. A/B test mining strategies (run two models, keep the winner)
6. Feed learnings back to Stage 3 (improve strategy model over time)

**Infrastructure**: Lambda + DynamoDB (lightweight optimization logic)
**Cost**: $0 for the optimization logic; mining compute is separate

---

## Implementation Priority

| Stage | Effort | Value | Dependencies | Target |
|-------|--------|-------|--------------|--------|
| 1. COLLECT | ✅ Done | Foundation | None | Done |
| 2. RESEARCH | 1-2 weeks | Unlocks strategy | Stage 1 | Next |
| 3. STRATEGIZE | 3-5 days | Unlocks action | Stage 2 | After Research |
| 4. BUILD | 1-2 weeks | First real miner | Stage 3 | Month 2 |
| 5. TEST | 3-5 days | Risk reduction | Stage 4 + historical data | Month 2 |
| 6. DEPLOY | 1 week | First TAO earned | Stage 5 | Month 2 |
| 7. OPTIMIZE | Ongoing | Compound returns | Stage 6 running | Month 3+ |

## Cost Model

| Stage | Monthly Cost |
|-------|-------------|
| 1-3 (Intelligence) | $0 (free tier) |
| 4-5 (Build + Test) | $0-5 (CodeBuild, occasional GPU test) |
| 6-7 (Deploy + Optimize) | $50-500 (GPU compute for mining) |

The intelligence pipeline is free. You only spend money when you actually deploy
a miner — and by then, you have high confidence it will be profitable.

## Success Metrics

- **Stage 1**: All 129 subnets refreshing within 4h staleness ✅
- **Stage 2**: 80%+ of subnets have research profiles
- **Stage 3**: Strategy produces actionable recommendations weekly
- **Stage 4**: First miner deployed from automated pipeline
- **Stage 5**: Prediction accuracy > 70% (actual yield within 30% of predicted)
- **Stage 6**: First TAO earned autonomously
- **Stage 7**: Month-over-month TAO yield increasing without manual intervention

## Long-Term Vision

The system becomes a **TAO compounding engine**:
- Earned TAO funds more validator stake → more passive income
- Earned TAO funds more registrations → more mining positions
- Better data → better strategy → higher yield → more capital → repeat

The human's role shifts from "operator" to "investor" — setting risk parameters
and capital allocation, while the machine handles discovery, execution, and optimization.

---

## Backlog (High Priority Ideas)

### TAO Flow Visualization

**Idea**: Create a real-time visualization of TAO flowing through the Bittensor network — showing how emission moves from subnets to miners/validators, how stake flows between subnets, and where the money is going.

**Why**: The raw numbers (TAO/day, stake amounts) are hard to intuit. A flow visualization (Sankey diagram, animated graph, or heatmap) would make the network's economics immediately legible — both for human decision-making and for communicating opportunities.

**Research needed**:
- What visualization libraries work for flow data? (D3.js Sankey, Observable, Grafana)
- Can we generate it statically (S3 + CloudFront) or need a backend?
- What data do we already have vs what we'd need to collect?
- How to show time dimension (flows changing over days/weeks)?

**Data we already have**: Per-subnet emission, stake, alpha prices, validator dividends, miner incentives. All refreshing once daily with 7-day price history from Market Observer.

**Priority**: HIGH — unlocks intuitive understanding of where TAO is accumulating.

### Validator Scoring Reverse Engineering

**Idea**: Analyze validator code to understand exactly HOW miners are scored. The validator's scoring logic determines who earns and who gets deregistered — understanding it is the key to building a winning miner.

**Why this matters**: On-chain data tells us WHO is winning (incentive distribution), but not WHY. The "why" lives in the validator code — their reward function, evaluation criteria, quality thresholds. If you understand the scoring, you can optimize directly for it.

**What to analyze per subnet**:
- Validator repo (usually public on GitHub)
- Reward function: what inputs, what outputs, how is quality measured?
- Evaluation frequency: how often are miners scored?
- Penalty conditions: what gets you zero score?
- Gaming detection: do validators check for cheating/shortcuts?

**Relationship to Stage 2 (Research)**: This IS part of Research but deserves its own focus. Stage 2 answers "what model type do I need?" — this answers "what specific behavior does the validator reward?" It's the difference between "you need an LLM" and "you need an LLM that scores > 0.8 on the validator's custom benchmark with latency < 2s."

**Approach**: LLM-powered code analysis of validator repos. Extract the reward function, summarize scoring criteria in structured format, identify the minimum quality bar to earn.

**Priority**: HIGH — directly determines mining success. A miner optimized for the validator's actual scoring function will outperform one that just "runs a good model."

### TAO Flow — Follow the Money (Wallet Map)

**Idea**: Build a pipeline stage that maps the flow of TAO through the network — who earns, who sells, who accumulates, which wallets are linked. Create a transparency layer that exposes extractive subnets vs productive ones.

**What it produces**:
- Wallet graph: which coldkeys control which subnets, miners, validators
- Flow analysis: where does earned TAO go? (held, sold on exchange, re-staked)
- Extraction score: per-subnet metric of "TAO out vs value produced"
- Ponzi detector: flag subnets where returns come from new stakers, not value creation
- Historical tracking: is a subnet becoming more or less extractive over time?

**Data sources**:
- On-chain: emission events, stake/unstake, transfers, registration events
- Exchange deposits: known exchange wallet addresses (public)
- Our existing metagraph data: who earns what, monopoly detection

**Why this matters**: Most TAO stakers have no visibility into whether their subnet is productive or extractive. This data creates an information advantage — and a product.

**Priority**: HIGH — directly enables the "Smart Validator" idea below.

---

### Smart Validator — Stake Only on Real Projects

**Idea**: Run a public validator that ONLY stakes on subnets producing real AI commodities. Market it as "the anti-extraction validator" — stakers delegate to us because we do the research they can't.

**The pitch to stakers**: "We analyze every subnet. We only stake where real work is happening. Your TAO earns yield from productive subnets, not Ponzi schemes. We publish our research openly."

**How it works**:
1. Pipeline Stage 1 (COLLECT) provides real-time subnet metrics ✅
2. TAO Flow analysis identifies extractive vs productive subnets
3. Stage 2 (RESEARCH) classifies each subnet's actual output
4. Our validator auto-allocates stake to top productive subnets
5. Stakers delegate to us → we earn validator commission
6. We publish transparency reports (builds trust, attracts more stakers)

**Revenue model**:
- Validator commission: typically 10-18% of staker earnings
- If we attract 100K TAO in delegated stake across productive subnets
- At ~5% APY on productive subnets = 5,000 TAO/year to stakers
- Our commission (10%): 500 TAO/year (~$130K at current prices)
- Scales linearly with delegated stake

**Why it could work**:
- No one else is doing data-driven subnet selection publicly
- Stakers WANT to avoid Ponzi subnets but can't analyze 129 subnets themselves
- Transparency builds trust in an opaque ecosystem
- The pipeline we already built IS the competitive moat
- Aligns incentives: we earn more when productive subnets earn more

**What we need**:
- TAO Flow analysis (wallet mapping, extraction scoring)
- Public dashboard showing our methodology
- Validator infrastructure (can run on a VPS, ~$50/month)
- Marketing/community presence (Discord, Twitter)
- Enough initial stake to be a credible validator (~1,000+ TAO)

**Priority**: HIGH — this is potentially the business model for the entire project. The pipeline pays for itself by attracting delegated stake.


---

## Immediate Action Plan (Path to 1,000 TAO)

**Starting capital**: 50 TAO + $50K USD (~242 TAO total)
**Target**: 1,000 TAO (enough to run a credible Smart Validator)
**Timeline**: 5-8 months

### Phase A: Passive Income (This Week)
- [ ] Stake 100 TAO on Root (SN0) as validator → passive yield
- [ ] Monitor earnings via pipeline

### Phase B: Research (Weeks 1-2)
- [ ] Build Stage 2 (Subnet Researcher) — identify which subnets are winnable
- [ ] Classify subnets: what hardware, what model, what difficulty
- [ ] Identify 2-3 target subnets for mining with rented GPU
- [ ] Estimate cost vs yield for each target

### Phase C: Deploy First Miner (Month 2)
- [ ] Rent GPU compute (~$30K budget = 3 months A100 spot)
- [ ] Deploy miner on highest-confidence target subnet
- [ ] Monitor for 7 days (immunity period)
- [ ] If earning: continue. If not: pivot to next target.

### Phase D: Compound & Scale (Months 3-6)
- [ ] All earned TAO → re-stake on Root (compound)
- [ ] Expand to 2nd subnet if first is profitable
- [ ] Build TAO Flow analysis (wallet mapping, extraction scoring)
- [ ] Publish transparency reports (build reputation)

### Phase E: Launch Smart Validator (Month 6-8)
- [ ] Reach 1,000 TAO threshold
- [ ] Launch public validator with "only productive subnets" thesis
- [ ] Publish methodology + live dashboard
- [ ] Attract delegators through transparency and track record

### Budget Allocation
| Use | Amount | Purpose |
|-----|--------|---------|
| Root validation | 100 TAO | Passive income, zero risk |
| Mining registration | 1 TAO | Subnet entry (multiple attempts) |
| GPU compute | $30K | 3 months of mining operations |
| Reserve | $20K + 141 TAO | Opportunities, emergencies, additional staking |
