# 4. Metrics Engine

## Design Philosophy

- **Pure functions**: Zero side effects, no AWS calls, no I/O
- **Simple types for testing**: Hypothesis property tests generate inputs easily
- **Pydantic at boundaries**: Models validate at storage/API edges, not inside computation
- **Configurable thresholds**: Never hardcode — read from DynamoDB via `get_thresholds()`
- **Status tracking**: Each metric has PROVEN/HYPOTHESIS/NEEDS_VALIDATION status

## Algorithm Inventory

### PROVEN (validated against live data or mathematically sound)

| Algorithm | Inputs | Output | Validation |
|-----------|--------|--------|------------|
| **Gini Coefficient** | emissions: list[float] | float [0,1] | Standard economics formula, O(n log n) |
| **Emission Trend** | current_emission, previous_emission | {change_percent, direction} | Confirmed: 127/129 subnets show <0.2% daily change (expected) |
| **Real 1D APY** | total_emission, total_stake, alpha_price | float (percent) | Matches taostats methodology (actual returns extrapolated) |
| **Net TAO Flow (EMA)** | stake_history: list[float] | {net_flow, ema_flow} | 30-day half-life EMA, matches Bittensor protocol's own smoothing |
| **Validator Concentration Risk** | active_validators, top_1_share | {risk, tier} | Calibrated against live data: 47% of subnets are "concentrated" by old binary flag |

### HYPOTHESIS (reasonable but not empirically validated)

| Algorithm | Key Assumption | Risk If Wrong |
|-----------|---------------|---------------|
| **Deregistration Risk** | Bottom 25% threshold, queue pressure cap of 10/day | Miners may be deregistered without warning |
| **Reward Distribution Model** | 70% WTA threshold, Gini < 0.5 for PROPORTIONAL | Misclassification → wrong strategy recommendation |
| **ROI Estimate** | Average earning miner yield is achievable | WTA subnets: most miners earn 0, average is misleading |
| **Miner Churn** | 5% net change = INCREASING/DECREASING | Threshold may be too sensitive or too conservative |
| **Validator Opportunity** | Bottom 10% stake = minimum viable | May be too low for some subnets |
| **Competitive Density** | earning_miners / (earning + emission) | Mixes units, never differentiates (max 0.075) — REPLACE |
| **Staking Yield** | Dividends proportional to stake share | Validated on SN95/SN1, but may not hold everywhere |
| **Attractiveness Score** | yield×0.30 + flow×0.25 + emission×0.25 + depth×0.20 | Weights are educated guesses from Taoculator |
| **Self-Mining Risk** | 4 signals with weights (0.35, 0.25, 0.25, 0.15) | May flag legitimate bootstrap subnets |
| **Validator Landscape** | top_1 > 50% = concentrated | 47% of network triggers this — too broad |

### NEEDS_VALIDATION (dormant or known broken)

| Algorithm | Issue | Activation Condition |
|-----------|-------|---------------------|
| **Taoflow Health** | Always returns HEALTHY (empty history passed) | 7 days of stake accumulation (started 2026-05-25) |
| **Competitive Density** | Mixes units, max 0.075, never differentiates | Replace with occupancy rate (backlog #14) |

### NOT CALLED IN PRODUCTION

| Algorithm | Why | When to Activate |
|-----------|-----|-----------------|
| **Rental Profitability** | Needs hardware_tier from Stage 2 + cloud pricing APIs | Stage 2 (RESEARCH) |

## Attractiveness Score Formula (Current)

```python
yield_score = min(net_tao_yield / 200, 1.0)           # 200 TAO/day = ceiling
flow_score = sigmoid(net_flow_ema / 500)              # Centered at 0, scaled by 500
emission_score = min(emission_share / 0.02, 1.0)      # 2% of network = max
depth_score = min(pool_depth_tao / 20000, 1.0)        # 20k TAO = deep enough

raw = yield×0.30 + flow×0.25 + emission×0.25 + depth×0.20
score = raw × (1.0 - self_mining_risk)                # Multiplicative penalty
```

**Why multiplicative**: Additive weights failed — all factors were near 1.0, producing no differentiation. Multiplicative penalty means risk=1.0 → score=0.0 regardless of yield.

**Why these weights**: Inspired by Taoculator's Subnet Health Score. Yield is most important for TAO accumulation, but flow (momentum) and emission share (protocol allocation) are equally critical signals.

## Self-Mining Risk Signals

| Signal | Weight | What It Detects |
|--------|--------|-----------------|
| `single_or_no_earning_miner` | 0.35 | No competition — one entity captures all emission |
| `single_validator` | 0.25 | No independent validation |
| `coldkey_overlap` | 0.25 | Owner validates their own miner |
| `low_neuron_diversity` | 0.15 | < 30% unique coldkeys (sybil or abandoned) |

SN104 scores 1.0 (all 4 signals). Legitimate subnets with 10+ miners and 5+ validators score 0.0.
