# 7. Technical Roadmap

## Current State: Stage 1 COMPLETE

The data infrastructure is mature. 129 subnets collected autonomously, 17 metrics computed, risk-adjusted rankings served via CloudFront. The architecture is clean, tests are honest, and the pipeline costs $0/month.

## Near-Term (Next 2-4 Sessions)

### Activate Net TAO Flow (June 1, 2026)
- **What**: After 7 days of stake accumulation, enable real flow data in attractiveness score
- **Impact**: The flow component (25% weight) goes from neutral (0.5) to real signal. Subnets gaining stake will score higher; dying subnets will be penalized.
- **Effort**: 30 min — read STAKE_HISTORY from DynamoDB, pass to `compute_net_tao_flow`, wire into Finalizer

### Replace Competitive Density (#14)
- **What**: Replace dead metric with `occupancy_rate = earning_miners / max_miners`
- **Impact**: A metric that actually varies across subnets (0.01 to 1.0 vs current 0.0001 to 0.075)
- **Effort**: 30 min

### EventBridge Retry (#15)
- **What**: Re-raise ThrottlingException in schedule creation so SQS retries
- **Impact**: Prevents silent death of subnet self-perpetuating loops
- **Effort**: 20 min

### Contract Tests Phase B
- **What**: TypedDicts for each boundary, template field validation
- **Impact**: Structural prevention of contract drift (not just smoke detection)
- **Effort**: 1-2 hours

## Medium-Term: Stage 2 — RESEARCH (1-2 weeks)

### What It Does
Uses LLMs to answer: "What does this subnet actually do, and is it worth mining?"

### Architecture Concept

```
Derived Metrics (Stage 1)
        │
        ▼
Subnet Researcher Lambda (LLM-powered)
    ├── Reads: rankings, metagraph, GitHub repos, subnet descriptions
    ├── Classifies: hardware requirements, model type, difficulty
    ├── Assesses: open-source miner availability, competitive landscape
    ├── Produces: structured research report per subnet
    └── Stores: research profiles in DynamoDB + S3
        │
        ▼
Enhanced Rankings (Stage 1 metrics + Stage 2 intelligence)
```

### Key Decisions to Make
1. **Which LLM?** Claude via Bedrock (stays in AWS, no external API calls) vs OpenAI (better at code analysis)
2. **How often?** Research is expensive — weekly per subnet? On-demand for top-20?
3. **What to research?** GitHub activity, subnet description, miner code patterns, hardware requirements
4. **How to validate?** LLM output needs confidence scores and human review triggers

### Prerequisites
- Rental profitability metric needs cloud pricing data (RunPod, Vast.ai APIs)
- Hardware tier classification needs subnet-specific research
- Miner code analysis needs GitHub API access

## Long-Term: Stages 3-7 (Months)

### Stage 3: STRATEGIZE
Given user's resources (TAO balance, hardware, risk tolerance), produce an action plan:
- Mine subnet X with GPU Y for Z TAO/month
- Validate subnet A with B TAO stake for C% APY
- Portfolio allocation across mining + validating

### Stage 4: BUILD
Generate/adapt mining agents:
- Clone open-source miners from GitHub
- Adapt configuration for target subnet
- Package as Docker containers
- Test locally before deployment

### Stage 5: TEST
Simulate against historical data:
- Predict rank position given your hardware
- Estimate yield based on historical emission patterns
- Model deregistration risk over time
- Backtest strategies against past data

### Stage 6: DEPLOY
Register on-chain and deploy:
- Register hotkey on target subnet
- Deploy compute (cloud GPU or local)
- Monitor performance vs predictions
- Auto-deregister if underperforming (capital preservation)

### Stage 7: OPTIMIZE
Self-improving feedback loop:
- Compare actual vs predicted performance
- Reallocate across subnets based on results
- Compound TAO earnings into new positions
- Discover new opportunities as subnets launch

## Architecture Evolution Principles

1. **Each stage builds on the previous** — Stage 2 consumes Stage 1 output, Stage 3 consumes both
2. **Human role shifts over time** — from operator (Stage 1-2) to investor (Stage 6-7)
3. **Cost scales with value** — Stages 1-3 are free, Stages 4-7 cost money but earn TAO
4. **LLMs where they add value, scripts elsewhere** — don't use an LLM to compute Gini
5. **Validate before automating** — each stage must prove value manually before being automated
6. **Reversibility at every step** — can always deregister, unstake, or stop mining

## Cost Projection

| Stage | Monthly Cost | Monthly TAO Earned (estimate) |
|-------|-------------|-------------------------------|
| 1 (COLLECT) | $0 | $0 (intelligence only) |
| 2 (RESEARCH) | $0-5 (LLM API) | $0 (intelligence only) |
| 3 (STRATEGIZE) | $0 | $0 (plan only) |
| 4-5 (BUILD/TEST) | $5-20 (compute) | $0 (testing only) |
| 6-7 (DEPLOY/OPTIMIZE) | $50-500 (GPU) | 10-100+ TAO/month |

Break-even: When mining/validating revenue exceeds compute costs. At current TAO prices (~$280), even 1 TAO/month = $280 revenue vs $50-500 cost.
