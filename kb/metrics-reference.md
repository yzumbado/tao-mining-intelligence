# Metrics Reference Guide

> **Living document** — updated whenever a metric is corrected, validated against live data, or its usefulness is proven/disproven.
>
> **Last validated**: 2026-05-18 (first live run: 129 subnets)
>
> **Source of truth**: `lambda/src/processor/metrics.py` (MetricsEngine class)

---

## How to Read This Document

Each metric has:
- **Formula**: The exact calculation
- **Hypothesis**: What we believe this metric represents and why
- **Inputs**: What data feeds it (and where it comes from)
- **Output range**: Valid values
- **Usefulness**: How this metric informs decisions (mining, validating, staking)
- **Status**: `PROVEN` | `HYPOTHESIS` | `NEEDS_VALIDATION` | `DEPRECATED`
- **Corrections log**: Any changes made and why

---

## Metric 1: Deregistration Risk

**Status**: `HYPOTHESIS` — logic is sound but not yet validated against actual deregistration events

**Formula**:
```
IF subnet has empty slots → risk = 0.0 for all
IF miner is immune (blocks_since_registration < immunity_period) → risk = 0.0

For non-immune miners on full subnets:
  queue_pressure = min(recent_registrations_24h / 10, 1.0)

  IF miner in bottom 25% by emission:
    base_risk = 1.0 - (rank_position / bottom_quartile_size)
    risk = base_risk × (0.5 + 0.5 × queue_pressure)
  ELSE (top 75%):
    risk = 0.1 × queue_pressure × (1.0 - rank_position / total_miners)
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| neurons (emission, active, block_at_registration) | Metagraph snapshot | — |
| current_block | Metagraph metadata | block number |
| immunity_period | Subnet hyperparameters | blocks |
| recent_registrations_24h | Derived: count neurons where (current_block - block_at_registration) < 7200 | count |

**Output**: `[0.0, 1.0]` per miner — 0 = safe, 1 = imminent deregistration

**Hypothesis**: On a full subnet, the miner with the lowest emission is the one who gets replaced when a new registrant arrives. Queue pressure (recent registrations) indicates how actively people are trying to enter. The bottom 25% face real risk; the top 75% are safe unless registration pressure is extreme.

**Usefulness**:
- **Mining**: "Should I enter this subnet?" — if churn is high and bottom miners die fast, you need to be competitive immediately after immunity expires
- **Staking**: Indirectly useful — high deregistration risk means the subnet is competitive (good for validators who benefit from miner competition)
- **Risk management**: Track your own miner's risk score over time; exit before deregistration

**Assumptions to validate**:
- [ ] Is the "bottom 25%" threshold correct? Some subnets may deregister more aggressively
- [ ] Does queue_pressure of 10 registrations/day represent "max pressure"? On popular subnets it could be higher
- [ ] Immunity period from hyperparams — is it always respected? (Edge case: subnet owner changes it mid-cycle)

---

## Metric 2: Gini Coefficient

**Status**: `PROVEN` — standard economics formula, correctly implemented, validated with property tests

**Formula**:
```
Given sorted positive emissions [x₁, x₂, ..., xₙ] (ascending):

G = (2 × Σᵢ (i+1)×xᵢ) / (n × Σxᵢ) - (n+1)/n

Edge cases:
  - Empty or all-zero → 0.0
  - Single value → 0.0
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| emissions | Neuron emission values (daily, after tempo conversion) | alpha/day |

**Output**: `[0.0, 1.0]` — 0 = perfect equality, 1 = one miner gets everything

**Hypothesis**: Measures how concentrated rewards are. A Gini of 0.9+ means almost all emission goes to a few miners (Winner-Takes-All). A Gini of 0.3 means rewards are spread relatively evenly.

**Usefulness**:
- **Mining**: High Gini = you need to be in the top few miners or you earn nothing. Low Gini = even mediocre miners earn something.
- **Staking**: Less directly useful, but high Gini subnets tend to have more predictable top performers (stable for validators)
- **Classification**: Primary input to Reward Distribution Model detection

**Corrections log**:
- None — standard formula, no corrections needed

---

## Metric 3: Reward Distribution Model

**Status**: `HYPOTHESIS` — classification thresholds (70% WTA, 0.5 Gini) are educated guesses, not empirically derived

**Formula**:
```
active_emissions = [e for e in emissions if e > 0]
top_3_share = sum(top 3 emissions) / sum(all emissions)
gini = compute_gini_coefficient(active_emissions)

IF top_3_share > 0.70 → WINNER_TAKES_ALL
ELIF gini < 0.5 → PROPORTIONAL
ELIF has_tiered_pattern(sorted_desc) → TIERED
ELSE → UNKNOWN

has_tiered_pattern: count gaps where emission[i]/emission[i-1] < 0.5
  → True if 1-3 such gaps exist (indicating 2-4 distinct reward tiers)
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| emissions | All neuron emissions (positive only) | alpha/day |

**Output**: Enum `{WINNER_TAKES_ALL, PROPORTIONAL, TIERED, UNKNOWN}` + gini + top_3_concentration

**Hypothesis**: Subnets fall into distinct reward patterns:
- **WTA**: Validator scoring is binary/competitive — only the best response wins. Top 3 miners capture >70% of emission.
- **PROPORTIONAL**: Validator scoring is continuous — all miners earn proportionally to quality. Gini < 0.5.
- **TIERED**: Validators have quality thresholds — miners above each threshold earn a fixed share. Distinct step-function in emission distribution.

**Usefulness**:
- **Mining**: Critical for strategy. On WTA subnets, you must be top-3 or you earn nothing. On PROPORTIONAL, even a mediocre miner earns. On TIERED, you need to clear a quality threshold.
- **Staking**: WTA subnets have more predictable top performers → more stable validator returns
- **Stage 2 (Research)**: Determines what "winning" means on each subnet

**Assumptions to validate**:
- [ ] Is 70% the right WTA threshold? Could be 60% or 80% depending on subnet
- [ ] Is Gini < 0.5 the right PROPORTIONAL threshold?
- [ ] Does the tiered pattern detection work on real data? (gap detection is heuristic)
- [ ] First live run showed 4/247 miners earn on SN1 — confirms WTA classification works

---

## Metric 4: ROI Estimation (Net TAO Yield)

**Status**: `HYPOTHESIS` — formula is correct but uses average emission which may be misleading on WTA subnets

**Formula**:
```
# CRITICAL: Emissions are converted to daily BEFORE this calculation
# Conversion: emission_daily = emission_per_tempo × (7200 / tempo)

miner_emissions = [n.emission for n in neurons if n.incentive > 0]
avg_daily_alpha = sum(miner_emissions) / len(miner_emissions)

net_tao_yield_per_day = avg_daily_alpha × alpha_tao_price
days_to_recoup = registration_cost_tao / net_tao_yield_per_day
thirty_day_projection = (net_tao_yield_per_day × 30) - registration_cost_tao
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| neuron emissions | Metagraph (tempo-converted to daily) | alpha/day |
| registration_cost_tao | Chain query (RAO ÷ 1e9) | TAO |
| alpha_tao_price | Chain query (subnet pool) | TAO per alpha |
| pool_tao_liquidity | Chain query (AMM pool) | TAO |

**Output**:
| Field | Unit | Meaning |
|-------|------|---------|
| net_tao_yield_per_day | TAO/day | Expected daily earnings converted to TAO |
| days_to_recoup | days | Time to recover registration cost |
| thirty_day_projected_tao | TAO | Net earnings after 30 days minus reg cost |
| slippage_estimate_percent | [0,1] | Expected slippage when selling alpha for TAO |
| hold_vs_swap | HOLD/SWAP | Whether to hold alpha or convert to TAO immediately |

**Hypothesis**: If you register on this subnet and perform at the average miner level, this is what you'd earn. The alpha→TAO conversion via the AMM pool determines your real return.

**Usefulness**:
- **Mining**: Primary decision metric — "is this subnet worth entering?"
- **Staking**: The `net_tao_yield_per_validator_per_day` variant (see Metric 8) is the staking equivalent
- **Comparison**: Enables apples-to-apples comparison across subnets with different tokens

**Known issues**:
- Average emission is misleading on WTA subnets (most miners earn 0, average is pulled up by top earners)
- No adjustment for your likely rank position — assumes you'd be "average"
- Slippage estimate is conservative upper bound (doesn't account for concentrated liquidity)

**Assumptions to validate**:
- [ ] Does averaging across earning miners (emission > 0) give a realistic estimate?
- [ ] Should we use median instead of mean for WTA subnets?
- [ ] Is the constant-product AMM slippage model accurate for Bittensor pools?
- [ ] Alpha price trend (hold vs swap) — is 5% over 7 days the right threshold?

---

## Metric 4a: AMM Slippage Estimation

**Status**: `HYPOTHESIS` — conservative upper bound, real slippage may be lower

**Formula**:
```
# Constant product AMM: x × y = k
pool_alpha = pool_tao / alpha_price
k = pool_tao × pool_alpha

new_pool_alpha = pool_alpha + sell_amount_alpha
new_pool_tao = k / new_pool_alpha
actual_tao_received = pool_tao - new_pool_tao

expected_tao = sell_amount_alpha × alpha_price
slippage = 1 - (actual_tao_received / expected_tao)
```

**Hypothesis**: When you sell alpha tokens for TAO, the AMM pool moves against you. Larger sells relative to pool size = more slippage. This is a CONSERVATIVE UPPER BOUND because Bittensor also supports concentrated liquidity (Uniswap V3-style) which adds depth at specific price ranges.

**Usefulness**:
- **Mining**: "Can I actually realize this yield?" — high slippage means your paper yield is higher than real yield
- **Staking**: Same concern — validator dividends in alpha need to be converted to TAO
- **Liquidity assessment**: Subnets with thin pools are risky even if yield looks good

---

## Metric 5: Taoflow Health

**Status**: `NEEDS_VALIDATION` — currently returns HEALTHY for all subnets because we don't have stake history yet

**Formula**:
```
daily_flows = [stake[i] - stake[i-1] for i in range(1, len(stake_history))]

consecutive_negative = count of consecutive negative flows from most recent day backward

IF consecutive_negative >= 7 AND emission declined > 25% over same period:
  → DEATH_SPIRAL_RISK
ELIF consecutive_negative >= 3:
  → DECLINING
ELSE:
  → HEALTHY
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| stake_history | Daily total stake snapshots (NOT YET COLLECTED) | TAO |
| emission_history | Daily total emission snapshots (NOT YET COLLECTED) | alpha/day |

**Output**: Enum `{HEALTHY, DECLINING, DEATH_SPIRAL_RISK}` + net_staking_flow + consecutive_negative_days

**Hypothesis**: Under Bittensor's Taoflow model, subnets compete for stake. When stakers leave (negative flow), the subnet's emission share decreases, causing more stakers to leave → death spiral. 3+ consecutive negative days = warning. 7+ days with >25% emission decline = critical.

**Usefulness**:
- **Mining**: Don't enter a dying subnet — your registration cost is wasted if emission drops to zero
- **Staking**: CRITICAL — this is the primary risk signal for validators. A death spiral means your staked TAO earns less and less
- **Timing**: Detect declining subnets early → exit before the crowd

**Current limitation**: We pass empty lists `([], [])` because we don't accumulate daily stake/emission history yet. This metric is **dormant** — always returns HEALTHY.

**To activate**:
- [ ] Accumulate daily `total_validator_stake` per subnet in DynamoDB or S3
- [ ] Accumulate daily `total_emission` per subnet
- [ ] Need 7+ days of history before this metric becomes meaningful

---

## Metric 6: Rental Profitability

**Status**: `HYPOTHESIS` — formula is correct but cloud_pricing data is not populated (no live pricing source)

**Formula**:
```
daily_rental_cost = cheapest_viable_gpu_hourly_rate × 24
daily_tao_value_usd = net_tao_yield_per_day × tao_usd_price
daily_profit_usd = daily_tao_value_usd - daily_rental_cost

rent_vs_buy_multiplier = net_tao_yield_per_day / (daily_rental_cost / tao_usd_price)
  → "Do I earn more TAO by mining than I could buy with the rental money?"

break_even_tao_price = daily_rental_cost / net_tao_yield_per_day
  → "What TAO price makes mining break-even vs just buying?"
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| net_tao_yield_per_day | From Metric 4 | TAO/day |
| tao_usd_price | External (CoinGecko API) | USD |
| hardware_tier | From Stage 2 Research (NOT YET BUILT) | enum |
| cloud_pricing | External pricing APIs (NOT YET INTEGRATED) | USD/hour |

**Output**: `rental_profitable: bool` + cost breakdown

**Hypothesis**: Mining is only worth it if `rent_vs_buy_multiplier > 1.0` — meaning you earn more TAO by mining than you could buy with the same money. This accounts for the "opportunity cost" of renting GPUs.

**Usefulness**:
- **Mining**: THE decision metric for "should I rent a GPU to mine this subnet?"
- **Staking**: Not directly relevant (validators don't need GPUs)
- **Capital allocation**: Compares mining ROI vs simply buying TAO

**Current limitation**: Not called in production — requires hardware_tier from Stage 2 and cloud_pricing from external APIs.

---

## Metric 7: Miner Churn

**Status**: `HYPOTHESIS` — formula works but requires previous-day snapshot for comparison

**Formula**:
```
new_miners = current_hotkeys - previous_hotkeys
departed_miners = previous_hotkeys - current_hotkeys

churn_rate = (|new_miners| + |departed_miners|) / |current_hotkeys|
avg_lifespan = mean(current_block - block_at_registration) for active miners

net_change_pct = (|new_miners| - |departed_miners|) / |current_hotkeys|
IF net_change_pct > 0.05 → INCREASING competition
ELIF net_change_pct < -0.05 → DECREASING competition
ELSE → STABLE
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| current_hotkeys | Today's metagraph | set of SS58 strings |
| previous_hotkeys | Yesterday's metagraph snapshot | set of SS58 strings |
| block_at_registration | Per-neuron metagraph field | block number |
| current_block | Metagraph metadata | block number |

**Output**:
| Field | Unit | Meaning |
|-------|------|---------|
| daily_churn_rate | [0,1] | Fraction of miners replaced per day |
| new_registrations | count | Miners who appeared since yesterday |
| deregistrations | count | Miners who disappeared since yesterday |
| average_miner_lifespan_blocks | blocks | How long active miners have survived |
| competition_trend | INCREASING/STABLE/DECREASING | Net direction of competition |

**Hypothesis**: High churn = competitive subnet where weak miners get replaced quickly. Low churn = stable subnet where incumbents are entrenched. The trend tells you if competition is heating up or cooling down.

**Usefulness**:
- **Mining**: High churn + INCREASING = dangerous to enter (you'll be deregistered fast). Low churn + STABLE = incumbents are safe.
- **Staking**: High churn means more registration fees burned → good for the subnet's economics
- **Timing**: DECREASING competition = opportunity window to enter

---

## Metric 8: Validator Opportunity Assessment

**Status**: `HYPOTHESIS` — formula is correct but needs validation against actual validator earnings

**Formula**:
```
validators = [n for n in neurons if n.dividends > 0]

avg_emission = sum(v.emission for v in validators) / len(validators)
net_tao_yield = avg_emission × alpha_tao_price

# Minimum stake to be a viable validator (bottom 10% threshold)
validators_by_dividends = sorted(validators, key=dividends)
min_effective_stake = validators_by_dividends[10th percentile].stake

# Daily ROI on staked capital
daily_roi = net_tao_yield / avg_stake

# Slot availability
slots_available = max_allowed_validators - len(validators)

# Concentration
top_1_share = max(v.stake) / total_stake
concentrated = top_1_share > 0.5
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| neurons (dividends, emission, stake) | Metagraph | various |
| alpha_tao_price | Chain query | TAO per alpha |
| max_allowed_validators | Subnet hyperparameters | count |

**Output**:
| Field | Unit | Meaning |
|-------|------|---------|
| viable | bool | Is validation possible on this subnet? |
| net_tao_yield | TAO/day | Average daily earnings per validator |
| min_effective_stake | TAO | Minimum stake to earn dividends |
| daily_roi_percent | % | Daily return on staked capital |
| slots_available | count | Open validator slots |
| concentrated | bool | Is >50% of stake held by one validator? |

**Hypothesis**: Validators earn dividends proportional to their stake share. The minimum effective stake tells you "how much TAO do I need to stake to earn anything?" The daily ROI tells you the return rate on your capital.

**Usefulness**:
- **Staking**: PRIMARY metric for "where should I stake my TAO?" — directly answers the question
- **Mining**: Indirectly useful — concentrated validator subnets may have biased scoring
- **Capital allocation**: Compare daily_roi across subnets to optimize stake distribution

**THIS IS THE KEY METRIC FOR YOUR 60 TAO STAKING POSITION.**

**Assumptions to validate**:
- [ ] Does avg_emission × alpha_price accurately predict validator earnings?
- [ ] Is the bottom 10% threshold the right "minimum viable stake"?
- [ ] Does stake concentration affect individual validator returns linearly?
- [ ] Are there subnets where small validators earn disproportionately more/less?

---

## Metric 9: Validator Landscape

**Status**: `HYPOTHESIS` — computed but not yet used for decision-making

**Formula**:
```
validators = [n for n in neurons if n.dividends > 0]

active_validators = len(validators)
total_validator_stake = sum(v.stake for v in validators)
top_1_stake_share = max(v.stake) / total_validator_stake
top_3_stake_share = sum(top 3 stakes) / total_validator_stake
concentrated = top_1_stake_share > 0.5

avg_emission = sum(v.emission for v in validators) / len(validators)
net_tao_yield_per_validator_per_day = avg_emission × alpha_tao_price
```

**Inputs**: Same as Metric 8

**Output**: Structural analysis of the validator set — count, stake distribution, concentration, yield

**Hypothesis**: The validator landscape determines how competitive staking is. A concentrated subnet (one whale validator) means your small stake earns proportionally less. A distributed subnet means more equal opportunity.

**Usefulness**:
- **Staking**: Avoid concentrated subnets where one whale dominates dividends
- **Mining**: Concentrated validators may have biased scoring (single point of failure)
- **Risk**: If the dominant validator leaves, the subnet's scoring could change dramatically

---

## Metric 10: Competitive Density

**Status**: `NEEDS_VALIDATION` — formula is unusual and may not be the best measure

**Formula**:
```
miners = [n for n in neurons if n.incentive > 0 or not n.is_validator]
active_miners = count(m for m in miners if m.active)
total_emission = sum(m.emission for m in miners)

density = active_miners / (active_miners + total_emission)
```

**Output**: `[0.0, 1.0]` — higher = more competition for the same emission pool

**Hypothesis**: More miners competing for the same emission pool = harder to earn. This ratio captures "miners per unit of emission" in a normalized way.

**Usefulness**:
- **Mining**: High density = crowded, hard to stand out. Low density = less competition.
- **Ranking**: Used as a penalty factor in the attractiveness score (weight: 0.15)

**Known issues**:
- The formula `active_miners / (active_miners + total_emission)` mixes units (count + alpha/day). This is a normalization hack, not a principled metric.
- A subnet with 100 miners and 100 alpha/day emission has the same density as one with 10 miners and 10 alpha/day — but the competitive dynamics are very different.

**Potential improvement**:
- Consider `active_miners / max_slots` (occupancy rate) as a simpler alternative
- Or `emission_per_miner` as an absolute measure of opportunity

---

## Metric 11: Emission Trend

**Status**: `PROVEN` — simple day-over-day comparison, works correctly

**Formula**:
```
change_percent = (current_total_emission - previous_total_emission) / previous_total_emission

IF change_percent > 0.01 → "increasing"
ELIF change_percent < -0.01 → "declining"
ELSE → "stable"

# Optional 7-day trend (when history available):
seven_day_trend = (emission_day7 - emission_day1) / emission_day1
```

**Inputs**:
| Input | Source | Unit |
|-------|--------|------|
| current_total_emission | Sum of all neuron emissions today | alpha/day |
| previous_total_emission | Sum of all neuron emissions yesterday | alpha/day |

**Output**: direction + change_percent + optional seven_day_trend

**Hypothesis**: Emission trends indicate subnet health. Increasing emission = subnet is gaining stake (Taoflow model allocates more emission to subnets with more stake). Declining = stakers are leaving.

**Usefulness**:
- **Mining**: Enter subnets with increasing emission (growing pie). Avoid declining ones.
- **Staking**: Same logic — increasing emission means your stake earns more over time
- **Ranking**: Used in attractiveness score (weight: 0.10)

---

## Metric 12: Attractiveness Score (Composite)

**Status**: `HYPOTHESIS` — weights are educated guesses, not empirically optimized

**Formula**:
```
yield_score = min(net_tao_yield / 5.0, 1.0)                    # weight: 0.40
recoup_score = max(0, 1.0 - days_to_recoup / 365.0)            # weight: 0.25
density_score = 1.0 - min(competitive_density, 1.0)             # weight: 0.15
trend_score = 0.5 + min(max(emission_change, -0.5), 0.5)       # weight: 0.10
taoflow_score = {HEALTHY: 1.0, DECLINING: 0.3, DEATH_SPIRAL: 0.0}  # weight: 0.10

attractiveness = yield×0.4 + recoup×0.25 + density×0.15 + trend×0.10 + taoflow×0.10
```

**Hypothesis**: A single score that answers "how attractive is this subnet for mining?" Higher = better opportunity. Yield dominates (40%) because that's what you're optimizing for. Payback time matters (25%) because capital is limited. Competition, trend, and health are secondary signals.

**Usefulness**:
- **Mining**: Sort subnets by this score → top ones are your best opportunities
- **Staking**: NOT directly useful — this is mining-focused. Need a separate "staking attractiveness" score.

**Known issues**:
- `5.0 TAO/day` as "excellent" yield normalization — is this the right ceiling?
- `365 days` as "terrible" recoup — should it be shorter?
- Weights are arbitrary — should be tuned based on actual mining outcomes
- **Missing: No staking-specific composite score exists yet**

**Assumptions to validate**:
- [ ] Do subnets ranked highly by this score actually produce good mining returns?
- [ ] Are the weights correct? Should yield be even more dominant?
- [ ] Should there be a separate "staking attractiveness" score with different weights?

---

## Metrics NOT Yet Implemented (Needed)

### Validator Yield Per TAO Staked (NEEDED FOR STAKING INTELLIGENCE)

**Proposed formula**:
```
# For a given subnet:
total_validator_emission_daily = sum(v.emission for v in validators) × (7200/tempo)
total_validator_stake = sum(v.stake for v in validators)

yield_per_tao_staked = (total_validator_emission_daily × alpha_tao_price) / total_validator_stake

# For YOUR specific stake:
your_expected_daily_tao = your_stake × yield_per_tao_staked
```

**Why needed**: Directly answers "if I stake X TAO on subnet Y, how much do I earn per day?"

### Alpha Price Momentum (NEEDED FOR HOLD VS SWAP)

**Proposed formula**:
```
# 7-day simple moving average trend
alpha_momentum = (price_today - price_7d_ago) / price_7d_ago

# Volatility (standard deviation of daily returns)
daily_returns = [(price[i] - price[i-1]) / price[i-1] for i in range(1, 7)]
alpha_volatility = std(daily_returns)
```

**Why needed**: Alpha tokens that are appreciating should be held, not swapped. Currently we only have a binary hold/swap recommendation.

### Stake Dilution Risk (NEEDED FOR STAKING INTELLIGENCE)

**Proposed formula**:
```
# How much would a new whale staker dilute your returns?
your_share = your_stake / total_validator_stake
diluted_share = your_stake / (total_validator_stake + hypothetical_whale_stake)
dilution_risk = 1 - (diluted_share / your_share)
```

**Why needed**: Small stakers on subnets with low total stake are vulnerable to whale dilution.

---

## Corrections Log

| Date | Metric | Change | Reason |
|------|--------|--------|--------|
| 2026-05-17 | ROI (Metric 4) | Fixed alpha_price = 0 for all subnets | SubnetCollector wasn't storing per-subnet alpha prices; Processor couldn't find them |
| 2026-05-17 | All metrics | Relaxed validation (27 subnets recovered) | Incentive sum != 1.0 on some subnets is normal, not an error |
| 2026-05-17 | Emission conversion | Confirmed: emission × (7200/tempo) for daily | Validated against live SN1 data |
| 2026-05-17 | Taoflow Health | Returns HEALTHY always (no history) | Intentional — needs 7+ days of accumulated data |

---

## Decision Framework: When to Trust a Metric

| Confidence Level | Criteria | Action |
|-----------------|----------|--------|
| **PROVEN** | Validated against live outcomes, formula is standard (e.g., Gini) | Use for automated decisions |
| **HYPOTHESIS** | Logic is sound, formula implemented, but not validated against outcomes | Use for recommendations, flag uncertainty |
| **NEEDS_VALIDATION** | Implemented but known limitations (missing data, untested assumptions) | Display but don't act on |
| **DEPRECATED** | Replaced by better metric or found to be misleading | Remove from rankings, keep in history |

---

## How This Document Evolves

1. **When a metric is validated**: Move status to PROVEN, document the evidence
2. **When a metric is wrong**: Add to Corrections Log, explain what was wrong and why
3. **When a new metric is added**: Add full entry with HYPOTHESIS status
4. **When a metric proves useless**: Move to DEPRECATED with explanation
5. **When weights are tuned**: Update the Attractiveness Score section with new weights and reasoning
