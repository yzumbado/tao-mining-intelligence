# Bittensor Mining Intelligence - Research Knowledge Base

> **Status**: Initial research — needs validation and expansion  
> **Last Updated**: 2026-05-14  
> **Purpose**: Shared source of truth for building the Bittensor Mining Intelligence Platform

---

## 1. Bittensor Architecture Overview

### Core Components
- **Subtensor**: The Bittensor blockchain (Polkadot parachain with EVM compatibility)
- **Subnets**: Specialized decentralized networks (~128 active as of mid-2025). Each focuses on a specific AI task (LLM inference, image generation, financial signals, protein folding, etc.)
- **Miners**: Produce digital commodities (AI model outputs, compute, storage, etc.)
- **Validators**: Evaluate miners' work quality and assign scores (weights)
- **TAO Token**: Native token, 21M max supply (mirrors Bitcoin's supply curve)

### Network Scale (as of early 2026)
- ~128 subnets active
- 256 UID slots per subnet (max 64 validators, 192 miners)
- ~$2.75B market cap
- TAO price ~$287
- ~3,600 TAO (~$960k) distributed daily across all subnets
- 70% of tokens staked
- December 2025 halving cut emissions by 50%

Sources: [Bittensor Docs](https://docs.bittensor.com), [Taostats](https://taostats.io), [SubnetRadar](https://subnetradar.com)

---

## 2. Emission Mechanism (Critical for Mining Strategy)

### Evolution of Emissions
1. **Pre-dTAO (before Feb 2025)**: Root network validators decided emission allocation to subnets
2. **dTAO (Feb 2025)**: Market-driven model — each subnet has its own Alpha token + AMM pool. Staking into a subnet increases its emissions.
3. **Taoflow (Nov 2025)**: Flow-based model — emissions based on **net TAO inflows** (staking activity), not token prices. Subnets with negative net staking flow receive **zero emissions**.

### Current Emission Split (per subnet)
- Validators: 41%
- Miners: 41%
- Subnet Owners: 18%

### Alpha Tokens
- Every subnet has its own alpha token since Feb 2025
- Alpha tokens trade against TAO on Constant Product AMMs
- Market decides which subnets get most daily TAO emissions
- Subnet Zero: stake TAO there to get a cut from all subnets automatically

### Key Insight for Mining Strategy
- Subnets must maintain positive net staking inflow or they get zero emissions
- Top 10 subnets control ~56% of emissions
- This creates a "ship or die" dynamic — subnets must deliver value to attract stakers

Sources: [Bittensor dTAO Whitepaper](https://bittensor.com/dtao-whitepaper), [Taostats Docs](https://docs.taostats.io)

---

## 3. Mining Mechanics

### How Mining Works
1. Miner registers a hotkey on a subnet (costs TAO — dynamic burn price)
2. Miner runs inference/compute tasks defined by the subnet's incentive mechanism
3. Validators send requests to miner's Axon (IP:PORT endpoint)
4. Validators score miner responses according to subnet-specific criteria
5. Scores (weights) are submitted to chain
6. Yuma Consensus processes weights → determines emission distribution
7. Miner receives proportional TAO/Alpha emissions

### Registration
- Dynamic cost: decays over time, increases with each registration
- Controlled by: `BurnHalfLife`, `BurnIncreaseMult`, `MinBurn`, `MaxBurn`
- Sunk cost — cannot be recovered
- One hotkey can hold UIDs across multiple subnets
- Within one subnet, each UID must have a unique hotkey

### Deregistration Risk
- Lowest-emission neuron (outside immunity period) gets replaced by new registrant each tempo
- Immunity period: typically 4096 blocks (~13.7 hours)
- Formula: `is_immune = (current_block - registered_at) < immunity_period`
- Subnet owner's hotkey has permanent immunity
- Deregistration only occurs when all 256 slots are occupied

### Key Miner Metrics (from Metagraph)
| Metric | Description |
|--------|-------------|
| **RANK** | Absolute ranking according to validators |
| **TRUST** | Proportion of validators that have scored this miner positively |
| **CONSENSUS** | Agreement between validators on miner's quality |
| **INCENTIVE** | Distribution of miner emissions (adds to 1 for all miners in subnet) |
| **EMISSION** | Actual emission received (in RAO) |
| **ACTIVE** | Whether the UID is considered active |
| **UPDATED** | Blocks since the neuron last set weights |
| **STAKE** | Amount of stake in the wallet |

### Mining Types by Subnet Category

| Category | Example Subnets | What Miners Do | Hardware Needed |
|----------|----------------|----------------|-----------------|
| **LLM Inference** | SN1, SN33 (Converserse) | Serve language model responses | GPU (A100/H100), 40-80GB VRAM |
| **Vision/Image** | SN19 | Generate/process images | GPU, 24-80GB VRAM |
| **Trading/Financial** | SN8 (Vanta) | Maintain profitable trading strategies | CPU/GPU, low latency |
| **Data Collection** | SN13 (Data Universe) | Scrape and store web data | CPU, high bandwidth, storage |
| **Compute** | SN110 (Green Compute) | Provide GPU inference capacity | GPU (RTX 4090/5090+) |
| **Training** | Various | Contribute to distributed model training | Multi-GPU, high bandwidth |
| **Prediction** | SN8, time-series subnets | Generate predictions/forecasts | CPU/GPU, data access |
| **Storage** | Various | Provide decentralized storage | Large disk, bandwidth |
| **Scientific** | SN25 (Protein Folding) | Run scientific computations | Specialized GPU |

### Mining Style (Key Resource Consumed to Compete)

This is a distinct classification from category. Category = what the subnet produces. Mining style = what resource you burn to win.

| Mining Style | Key Resource | What Determines Winners | Strategic Implication |
|-------------|-------------|------------------------|---------------------|
| **GPU_INFERENCE** | GPU VRAM + compute | Fastest/cheapest inference serving | Hardware-bound; rent-vs-buy analysis applies |
| **GPU_TRAINING** | GPU + time + data | Best training contributions | Long-running; needs sustained compute |
| **RAW_COMPUTE** | CPU/GPU cycles | Most cycles delivered | Commodity; cheapest hardware wins |
| **KNOWLEDGE_STRATEGY** | Human expertise + data | Best predictions/signals/strategies | Intellectual edge; hardware is secondary |
| **DATA_COLLECTION** | Bandwidth + storage | Most/best data scraped | I/O-bound; cheap hardware, expensive bandwidth |
| **MODEL_QUALITY** | ML expertise + experimentation | Best model (SDXL vs competitors) | R&D-bound; one-time investment in model quality |
| **LATENCY** | Network proximity + optimization | Fastest response time | Infrastructure-bound; location matters |
| **CAPITAL** | TAO stake | Most stake committed | Capital-bound; no hardware needed (validation) |

**Key insight**: A subnet can be "Vision/Image" (category) but its mining style is "MODEL_QUALITY" — the winners have better models, not faster GPUs. This distinction is critical for strategy: if you have a great GPU but a mediocre model, you'll lose on MODEL_QUALITY subnets but win on GPU_INFERENCE subnets.

### Reward Distribution Models

Subnets use different reward distribution approaches:

1. **Winner-Takes-All (WTA)**: The top-performing miner(s) receive disproportionately large share of emissions. Extreme competition — if you're not #1, you earn almost nothing. High risk, high reward.

2. **Proportional**: Emissions distributed proportionally to scores. More miners can be profitable, but top performers still earn more. Lower risk, more predictable.

3. **Hybrid/Tiered**: Some subnets use tiered approaches where top N miners get a bonus, but remaining miners still earn proportionally.

4. **Multiple Incentive Mechanisms**: Some subnets support multiple incentive mechanisms within a single subnet (sub-subnets), each with its own bond pool and emission allocation.

**Key insight for strategy**: The reward distribution model fundamentally changes whether a subnet is worth mining. On a WTA subnet, you need to be top 5 or don't bother. On a proportional subnet, being top 50 might still be profitable.

### Competitive Strategies

- **Quality Optimization**: Run the best model/hardware to score highest
- **Latency Optimization**: Some subnets reward faster responses
- **Cost Arbitrage**: Use cheaper inference (e.g., SN33 miners using free Venice AI API instead of running own GPU)
- **Multi-Subnet Diversification**: Mine multiple subnets to reduce risk
- **Timing**: Register when costs are low, exit when emissions decline
- **Subnet Hopping**: Move to new/underserved subnets before competition arrives

Sources: [Bittensor Mining Docs](https://docs.bittensor.com/miners/), [Taostats Metagraph Docs](https://docs.taostats.io/docs/metagraph), [Coldint Incentive Landscape](https://coldint.io/the-optimal-incentive-landscape/)

---

## 4. Yuma Consensus

- Runs on-chain within Subtensor
- Computes validator and miner emissions from validators' weight submissions
- Stake-weighted: validators with more stake have more influence on consensus
- Penalizes validators who deviate from consensus (lower dividends)
- Resistant to collusion up to 50% of network weight
- **YC3** (latest version): designed to make scoring more fair

### How It Affects Miners
- A miner's reward depends not just on one validator's score, but on the **consensus** of all validators
- High trust = many validators agree you're performing well
- High consensus = strong agreement on your quality relative to others

Sources: [Yuma Consensus Docs](https://docs.bittensor.com/learn/yuma-consensus), [Incentive Mechanism Docs](https://docs.bittensor.com/learn/anatomy-of-incentive-mechanism)

---

## 5. Data Sources & APIs

### Primary Data Sources

| Source | Type | Notes |
|--------|------|-------|
| **Bittensor Python SDK (v10)** | Direct chain access | `import bittensor as bt; mg = bt.Metagraph(netuid=1)` |
| **Taostats API** | REST API | Requires API key, deepest historical data, TS SDK available |
| **Subtensor RPC** | WebSocket/HTTP | Direct blockchain queries |
| **TAO.app** | Web UI | Subnet listings and browsing |
| **TaoRevenue.com** | Web dashboard | Subnet profitability & health metrics |
| **SubnetRadar.com** | Web dashboard | Health scores, analytics, power rankings |
| **SubnetStats.app** | Web dashboard | Holders, trading activity, liquidity metrics |
| **DynamicTaoMarketCap.com** | Web dashboard | Subnet exploration |

### Bittensor Python SDK - Metagraph Fields (VALIDATED v10.3.2)
```python
import bittensor as bt

# Connect async
async with bt.AsyncSubtensor(network="finney") as sub:
    mg = await sub.metagraph(netuid=1)
    
    # Discover all subnets
    netuids = await sub.get_all_subnets_netuid()  # Returns ~129 netuids
    
    # Get alpha price
    price = await sub.get_subnet_price(netuid=1)  # Returns Balance (e.g., τ0.010118548)
    
    # Get hyperparameters
    hp = await sub.get_subnet_hyperparameters(netuid=1)

# Available metagraph fields (SDK v10.3.2):
# mg.S  - Stake (TAO)
# mg.I  - Incentive [0,1]
# mg.E  - Emission (TAO per tempo)
# mg.C  - Consensus [0,1]
# mg.Tv - Validator Trust [0,1]
# mg.D  - Dividends [0,1]
# mg.B  - Bonds
# mg.W  - Weights
# mg.AS  - Alpha Stake
# mg.TS  - Total Stake (TAO + alpha)
# mg.hotkeys - Hotkey addresses
# mg.coldkeys - Coldkey addresses
# mg.active - Active status
# mg.block_at_registration
# mg.blocks_since_last_step
# mg.n  - Total neuron count
#
# REMOVED in v10 (no longer available):
# mg.R  - Rank (use incentive ordering instead)
# mg.T  - Trust (no longer directly exposed)
```

### Validated Performance (Live Finney Endpoint)
- Single metagraph retrieval: ~2 seconds
- 3 concurrent metagraphs: 1.4 seconds total
- Extrapolated 128 subnets: ~60 seconds (fits 15-min Lambda)
- No rate limiting observed on concurrent connections
- Current block: ~8.19M (as of May 2026)
- Active subnets: 129

### Emission Units (CRITICAL for ROI)
- **Emission field (mg.E) is in alpha tokens PER TEMPO** (not per day, not per block)
- Tempo varies per subnet (SN1: 99 blocks ≈ 19.8 minutes)
- Daily conversion: `daily_alpha = emission_per_tempo × (7200 / tempo)`
- Blocks per day: 7200 (at 12s/block)
- Tempos per day on SN1: 7200/99 ≈ 72.7
- Total emission per tempo on SN1: ~82 alpha (41 miners + 41 validators)
- Incentive sums to 1.0 across all miners (proportional share)
- Dividends sums to 1.0 across all validators

### SN1 Live Data Example (May 2026)
- Only 4 out of 247 miners have non-zero emission (extreme WTA)
- Top miner: 36.6 alpha/tempo × 72.7 tempos/day = ~2,662 alpha/day
- At α/τ price 0.0101: top miner earns ~26.9 TAO/day
- Average miner emission is misleading on WTA subnets (most earn 0)
- Registration cost: 0.0005 TAO (very cheap for SN1)

### Validated Hyperparameter Fields (SN1 example)
```
immunity_period: 7200 blocks (~24 hours, NOT 4096 as some docs say)
tempo: 99 blocks (~20 minutes)
max_validators: 128 (NOT 64)
min_burn: 500000 RAO (0.0005 TAO)
max_burn: 100000000000 RAO (100 TAO)
yuma_version: 2 (YC2, not YC3)
registration_allowed: true
max_regs_per_block: 1
```

### Pool Reserve Access (for slippage calculation)
```python
# Direct storage queries for AMM pool data:
tao_reserve = await sub.substrate.query(
    module='SubtensorModule', storage_function='SubnetTAO', params=[netuid])
alpha_reserve = await sub.substrate.query(
    module='SubtensorModule', storage_function='SubnetAlphaIn', params=[netuid])
# SN1: ~28,265 TAO in pool, ~2.79M alpha tokens
```

### Taostats API & SDK
- TypeScript SDK: `@taostats/sdk` (npm, requires Node.js v22.3.0+)
- Python: via REST API calls
- Requires API key from https://taostats.io/pro/
- Provides: subnet data, metagraph, staking info, historical data
- Full RPC access to Bittensor chain included
- Env vars: `TAOSTATS_API_KEY`, `RPC_URL` (optional custom)

Sources: [Bittensor SDK Docs](https://docs.bittensor.com/python-api/), [Taostats API Docs](https://docs.taostats.io)

---

## 6. Existing Ecosystem Tools & Gaps

### What Exists
- **Taostats**: Block explorer, staking, portfolio tracking, validator analytics, API
- **TaoRevenue**: Subnet profitability tracking (inflow/outflow, 24H/7D/30D)
- **SubnetRadar**: Health scores (avg 56/100), power rankings, alerts
- **Taoculator**: Monte Carlo price simulation tool
- **TAO.app**: Subnet browsing and discovery
- **SubnetStats.app**: Holder analytics, trading activity, liquidity

### Gaps for Mining-Specific Intelligence (Our Opportunity)
1. **No automated daily data collection pipeline** — existing tools are dashboards, not data feeds for agents
2. **No agent-consumable format** — everything is human-facing UI
3. **No cross-subnet mining strategy optimization** — which subnet to mine, when to switch
4. **No registration cost forecasting** — predicting optimal registration timing
5. **No deregistration risk scoring** — predicting when a miner might get kicked
6. **No historical performance correlation** — linking hardware/model quality to emission outcomes
7. **No subnet lifecycle analysis** — identifying subnets trending toward zero emissions (Taoflow death spiral)
8. **No competitive density analysis** — how crowded is a subnet, what's the marginal miner earning

---

## 7. Key Decision Points for Mining Agents

An AI agent deciding mining strategy needs to answer:

1. **Which subnet to mine?** (emission rate, competition, hardware match, task type)
2. **When to register?** (registration cost trend, immunity period timing)
3. **When to deregister/switch?** (emission declining, deregistration risk rising)
4. **What hardware to allocate?** (GPU requirements per subnet, cost/reward ratio)
5. **How to optimize performance?** (model quality, response latency, uptime)
6. **When is a subnet dying?** (negative staking flow, declining emissions under Taoflow)
7. **What's the ROI timeline?** (registration cost vs. expected emissions over time)

---

## 8. Architecture Considerations

### Data Collection Layer
- **Option A**: Bittensor Python SDK direct chain queries (free, but may need public endpoint or own node)
- **Option B**: Taostats API (paid, comprehensive, historical data, reliable)
- **Option C**: Hybrid — SDK for real-time metagraph snapshots, Taostats for historical/enriched data

### Data Volume Estimate
- Daily snapshots of all subnet metagraphs: ~128 subnets × 256 UIDs = ~32K neuron records per snapshot
- If capturing every tempo: depends on subnet tempo settings (varies)
- Historical backfill: dTAO data from Feb 2025, Taoflow from Nov 2025

### AWS Architecture Options
- **Lambda**: Scheduled collection jobs (daily/hourly)
- **S3**: Raw data lake (JSON/Parquet snapshots)
- **DynamoDB**: Fast lookups for agent queries
- **Timestream**: Time-series analytics
- **EventBridge**: Scheduling and event routing
- **API Gateway + Lambda**: Agent-facing REST API

### Web3 Architecture Options
- Run own Subtensor node for direct chain access
- Subscribe to chain events via WebSocket
- Index historical data from chain

### Agent Interface Requirements
- Structured JSON/API format for agent consumption
- Pre-computed derived metrics (ROI estimates, risk scores, trend indicators)
- Event-driven alerts (registration cost drops, emission spikes, deregistration warnings)
- Queryable by: subnet, time range, metric type, miner hotkey

---

## 9. Open Questions (Need Your Input)

1. **Scope**: All 128 subnets or focus on a subset (e.g., top 20 by emission)?
2. **Update frequency**: Daily sufficient, or do we need intra-day (every tempo)?
3. **Historical depth**: How far back do we need data? (dTAO launched Feb 2025, Taoflow Nov 2025)
4. **Agent interface**: REST API? S3 data lake? Both?
5. **Are you currently mining?** If so, which subnets? This would help prioritize.
6. **Budget constraints**: Taostats API has costs; running our own subtensor node is an option but more infra.
7. **Multi-agent or single agent consumer?** Different strategies might need different data views.
8. **Latency requirements**: Is "yesterday's data" good enough, or do agents need near-real-time?
9. **AWS budget**: What monthly spend are we designing for? Affects storage/compute choices.
10. **MVP interface**: CLI? API? Web UI? What do the consuming agents look like today?

## 10. Architectural Decisions Made

See `kb/architecture-decisions.md` for full details. Summary:

- **Assembly line / FSM model** over agent swarm — predictable, debuggable, scalable
- **LLM only where it adds value** — code analysis and strategy, not data collection
- **Subnet Researcher** is a first-class pipeline component with classification taxonomy
- **Discord deferred to Phase 2** — need code analysis context first
- **Append-only knowledge** — never delete, always version, history is the moat
- **Subnet lifecycle FSM** — DISCOVERED → ANALYZED → MONITORED → ARCHIVED
- **Design for subnet churn** — handle renames, deregistrations, forks gracefully

---

## 10. Research Still Needed

### Validated Through Implementation (Task 1.2)
- [✅] AsyncSubtensor connects to Finney endpoint — confirmed working
- [✅] Metagraph retrieval — 2s per subnet, all fields accessible (except rank/trust removed)
- [✅] Concurrent collection — 128 subnets in ~60s, no rate limiting
- [✅] Alpha token price — `get_subnet_price()` returns Balance object
- [✅] Pool reserves — accessible via direct storage query (SubnetTAO, SubnetAlphaIn)
- [✅] Registration cost — queryable via storage query (in RAO, divide by 1e9 for TAO)
- [✅] Hyperparameters — `get_subnet_hyperparameters()` works, field names differ from docs
- [✅] Subnet discovery — `get_all_subnets_netuid()` returns 129 subnets

### Corrected Assumptions (from live validation)
- [⚠️] `rank` and `trust` fields REMOVED in SDK v10 — not available in metagraph
- [⚠️] `max_validators` = 128 on SN1 (not 64 as some docs suggest)
- [⚠️] `immunity_period` = 7200 blocks on SN1 (~24h, not 4096/~13.7h)
- [⚠️] `burn_half_life` and `burn_increase_mult` NOT exposed by SDK — track empirically
- [⚠️] Registration cost in RAO (500000 = 0.0005 TAO for SN1) — need unit conversion
- [⚠️] `yuma_version` = 2 (YC2, not YC3 as we assumed)
- [⚠️] `blocks_since_last_step` is a plain int scalar (value=87 on SN1), NOT an ndarray
- [⚠️] `mg.n` is numpy ndarray scalar — `int(mg.n)` required for range() and JSON
- [⚠️] `mg.block` is numpy ndarray scalar — this is the current chain block (8200740 observed)
- [⚠️] `mg.block_at_registration[0]` is UID 0's registration block, NOT the current block
- [⚠️] `mg.hotkeys[i]` returns plain Python `str` — no cast needed
- [⚠️] No NaN/Inf observed in emission arrays on SN1 (but guard against it in validation)

### Still Open (Phase 1 - needed for implementation)
- [ ] CoinGecko/Binance free API limits for TAO/USD price
- [ ] Cloud GPU pricing (Vast.ai, RunPod) — current rates for RTX 4090, A100, H100

### Still Open (Phase 2 - deferred)
- [ ] Specific subnet incentive mechanisms (per-subnet deep dives)
- [ ] Hardware requirements per subnet (GPU types, VRAM, bandwidth)
- [ ] Taostats API pricing and rate limits
- [ ] Existing open-source mining bots or strategy tools
- [ ] Subnet-specific repositories and their miner templates
- [ ] Tempo duration per subnet and how it affects emission timing
- [ ] YC3 specifics — what changed from YC2 and how it affects miner scoring
- [ ] Mining style classification for top 20 subnets (manual research needed)
- [ ] Cross-subnet service dependencies mapping (which subnets serve which)
