# Stage 3: STRATEGIZE — Requirements & Design

## Introduction

The Strategizer is a decision engine that takes user-defined resources (hardware, capital, risk tolerance) and pipeline intelligence (rankings, research profiles, market data) and outputs a personalized, actionable allocation plan: which subnets to enter, in what role (mine or validate), with how much capital.

**Primary objective**: Maximize net TAO yield per unit of risk, given the user's specific constraints.

**Non-goals**:
- USD optimization (we optimize for TAO accumulation)
- Automated execution (Stage 6 handles that — this stage only recommends)
- LLM or ML inference (pure deterministic computation)

---

## Glossary

| Term | Definition |
|------|-----------|
| Strategy | A complete allocation plan: which subnets, what roles, how much capital |
| User Profile | Hardware, capital, preferences stored in DynamoDB |
| Opportunity | A specific subnet + role (mine or validate) that the user could enter |
| Fitness Score | How well an opportunity matches the user's constraints (0.0–1.0) |
| Portfolio | The set of allocated opportunities that maximizes yield within constraints |
| Entry Cost | Registration TAO + first-month hardware cost (converted to TAO) |
| Net Yield | Expected daily TAO return minus amortized costs |
| Slippage Budget | Maximum acceptable slippage on entry/exit (from pool liquidity) |

---

## Data Inputs (Already Available)

### From Rankings (Finalizer output — `rankings.json`)
```json
{
  "netuid": 44,
  "attractiveness_score": 0.816,
  "real_apy_percent": 65.0,
  "net_tao_yield": 90.7,
  "days_to_recoup": 0.5,
  "thirty_day_projection": 2721.0,
  "competitive_density": 0.003,
  "emission_trend": -0.000001,
  "alpha_price": 0.35,
  "self_mining_risk": 0.0,
  "concentration_risk": {"risk": 0.0, "tier": "healthy", "active_validators": 10}
}
```

### From Research Profiles (DynamoDB `SUBNET#{netuid}|RESEARCH#latest`)
```json
{
  "netuid": 44,
  "model_type": "llm_inference",
  "gpu_required": true,
  "vram_gb_estimate": 24,
  "open_source_miner": true,
  "difficulty": "trivial",
  "research_confidence": "high"
}
```

### From Market Observer (DynamoDB `CACHE#{netuid}|MARKET_DATA`)
```json
{
  "alpha_price": 0.35,
  "pool_tao": 12500.0,
  "updated_at": "2026-06-07T12:00:00Z"
}
```

### From DynamoDB Profiles (`SUBNET#{netuid}|PROFILE#basic`)
- Registration cost (TAO)
- Tempo
- Name

---

## Requirements

### R1: User Profile

**Story**: As a TAO investor, I define my available resources so the system can recommend opportunities I can actually act on.

1. A user profile SHALL be stored in DynamoDB at `CONFIG|USER_PROFILE`.
2. The profile SHALL include:
   - `hardware`: list of available GPUs (type, vram_gb, count) — may be empty (validator-only user)
   - `tao_available_stake`: TAO available for validator staking
   - `tao_available_registration`: TAO budget for subnet registrations
   - `risk_tolerance`: enum `conservative | moderate | aggressive`
   - `max_positions`: maximum concurrent subnet positions (default: 3)
   - `prefer_passive`: boolean — prefer validating over mining when yields are similar
   - `excluded_subnets`: list of netuids to never recommend (blacklist → exclusion list)
   - `min_pool_liquidity_tao`: minimum pool TAO for entry (slippage guard)
3. The profile SHALL have sensible defaults so the system works without manual configuration.
4. The profile SHALL be editable via AWS DynamoDB Console (no UI needed).

### R2: Opportunity Filtering

**Story**: The system eliminates subnets I cannot enter due to hardware, capital, or risk constraints.

1. A subnet SHALL be filtered out if:
   - Research says `gpu_required=true` with `vram_gb_estimate > max(user.hardware.vram_gb)` AND user has no hardware match → filtered for mining role (can still validate)
   - Registration cost > `tao_available_registration` → filtered entirely
   - `self_mining_risk > 0.0` AND `risk_tolerance != aggressive` → filtered
   - `concentration_risk.tier == "critical"` AND `risk_tolerance == conservative` → filtered
   - Pool liquidity < `min_pool_liquidity_tao` → filtered
   - Subnet in `excluded_subnets` → filtered
   - `research_confidence == "none"` AND `difficulty == "unknown"` → filtered for mining (can validate)
2. Filtering SHALL produce a log of why each subnet was excluded (for transparency).

### R3: Opportunity Scoring

**Story**: Each surviving opportunity is scored on how well it fits my profile and how much TAO it can produce.

1. Each opportunity SHALL be scored on four dimensions (0.0–1.0 each):
   - **Yield**: normalized `net_tao_yield` relative to the top yielder
   - **Risk**: inverted weighted risk (`1.0 - combined_risk`) where combined = self_mining × 0.3 + concentration × 0.3 + (1.0 - emission stability) × 0.2 + low_liquidity × 0.2
   - **Accessibility**: based on `difficulty` (trivial=1.0, medium=0.6, hard=0.2) and `research_confidence` (high=1.0, medium=0.7, low=0.4)
   - **Efficiency**: `net_tao_yield / entry_cost` normalized (ROI per TAO invested)
2. The composite **fitness score** SHALL be: `yield × 0.4 + risk × 0.25 + accessibility × 0.2 + efficiency × 0.15`
3. Weights SHALL be configurable in DynamoDB thresholds (not hardcoded).
4. Each opportunity SHALL be scored TWICE: once as "mine" role, once as "validate" role, with the better one kept.

### R4: Mine vs Validate Decision

**Story**: For each subnet, the system recommends whether to mine or validate based on which produces more net TAO after costs.

1. **Mining yield estimate**:
   - If reward model is WTA AND `difficulty != "trivial"` → mining yield = 0 (can't compete)
   - Otherwise: `net_tao_yield / active_miners * difficulty_multiplier` (trivial=1.0, medium=0.5, hard=0.1)
   - MINUS daily hardware cost converted to TAO (monthly GPU rental / 30 / TAO_USD_price)
2. **Validating yield estimate**: `real_apy_percent / 100 * allocated_stake / 365` (daily TAO from dividends)
   - Only available if `tao_available_stake >= min_validator_stake` (per-subnet, from Collector)
3. The role with higher **net daily TAO** (after costs) SHALL be recommended.
4. If `prefer_passive == true` AND validating yield >= 80% of mining yield → recommend validate.
5. Hardware cost lookup: configurable GPU rental rates (monthly USD) in thresholds. TAO/USD price from Market Observer or fallback to a configurable default.

### R5: Portfolio Optimization

**Story**: The system allocates capital across the top opportunities to maximize total yield while respecting constraints.

1. The portfolio optimizer SHALL select up to `max_positions` opportunities.
2. Total registration cost across all positions SHALL NOT exceed `tao_available_registration`.
3. Total staking across all validator positions SHALL NOT exceed `tao_available_stake`.
4. Diversification constraint: no single subnet SHALL receive more than 50% of total capital (unless `max_positions == 1`).
5. The optimizer SHALL use greedy allocation (sort by fitness, allocate top-down) — NOT linear programming. Keep it simple.
6. Output SHALL include a "do nothing" option with reasoning if no opportunity exceeds a minimum fitness threshold (default: 0.3).

### R6: Strategy Output

**Story**: The strategy output is a structured JSON document consumable by humans and future pipeline stages.

1. The strategy SHALL be stored in S3 at `derived/strategy/latest.json` (overwritten each run).
2. Historical strategies SHALL be stored at `derived/strategy/{date}/{timestamp}.json`.
3. The output format SHALL be:
```json
{
  "generated_at": "2026-06-07T18:30:00Z",
  "profile_hash": "sha256:abc...",
  "rankings_freshness": "2026-06-07T18:25:00Z",
  "total_opportunities_evaluated": 129,
  "total_filtered": 98,
  "filter_reasons_summary": {"no_hardware": 45, "registration_too_expensive": 12, ...},
  "recommendations": [
    {
      "rank": 1,
      "netuid": 44,
      "subnet_name": "SN44",
      "role": "validate",
      "fitness_score": 0.82,
      "expected_daily_tao": 2.5,
      "expected_monthly_tao": 75.0,
      "entry_cost_tao": 0.5,
      "allocated_stake_tao": 500.0,
      "rationale": "High APY (65%), clean risk profile, trivial difficulty, prefer_passive=true",
      "scores": {"yield": 0.9, "risk": 0.95, "accessibility": 1.0, "efficiency": 0.7}
    }
  ],
  "do_nothing_reason": null,
  "portfolio_summary": {
    "total_allocated_registration": 1.5,
    "total_allocated_stake": 800.0,
    "expected_daily_tao_total": 5.2,
    "expected_monthly_tao_total": 156.0,
    "diversification_score": 0.85
  }
}
```

### R7: Invocation Model

**Story**: The strategy updates when data changes or on demand.

1. The Strategizer Lambda SHALL be invokable manually (console, CLI, or API).
2. The Strategizer Lambda MAY be triggered automatically after Finalizer completes (via async invocation) — configurable on/off via DynamoDB threshold `strategy_auto_refresh`.
3. The strategy SHALL NOT run more than once per hour (debounce via last-run timestamp).
4. If no user profile exists, the Strategizer SHALL use default profile and log a warning.

### R8: Transparency and Auditability

**Story**: Every recommendation is traceable back to the data and logic that produced it.

1. Each recommendation SHALL include a human-readable `rationale` field explaining WHY.
2. The filter log SHALL be stored alongside the strategy (which subnets were excluded and why).
3. The scoring breakdown SHALL be visible per-recommendation (not just the composite score).

### R9: Exit Recommendations

**Story**: The system warns me when a currently-held position has degraded below acceptable thresholds.

1. Active positions SHALL be tracked in DynamoDB at `CONFIG|ACTIVE_POSITIONS`.
2. A position record SHALL contain: `netuid`, `role` (mine/validate), `entered_at`, `entry_cost_tao`, `allocated_stake_tao`.
3. The Strategizer SHALL evaluate each active position against current rankings.
4. An EXIT signal SHALL be generated when:
   - `self_mining_risk > 0` AND position was entered when risk was 0
   - `attractiveness_score` dropped below `strategy_min_fitness_threshold`
   - Subnet's `real_apy_percent` fell below 50% of the value at entry time (stored in position record)
5. EXIT recommendations SHALL include rationale and urgency (low/medium/high).
6. Active positions SHALL be manually maintained (user adds/removes via DynamoDB Console) until Stage 6 automates this.

---

## Design

### Architecture

```
                    ┌─────────────────┐
                    │ DynamoDB         │
                    │ CONFIG|USER_PROF │
                    └────────┬────────┘
                             │
    ┌────────────────────────┼────────────────────────┐
    │                        │                        │
    ▼                        ▼                        ▼
┌──────────┐    ┌───────────────────┐    ┌──────────────────┐
│ Rankings │    │ Research Profiles  │    │ Market Observer   │
│ (S3)     │    │ (DynamoDB)         │    │ Cache (DynamoDB)  │
└────┬─────┘    └────────┬──────────┘    └────────┬─────────┘
     │                   │                        │
     └───────────────────┼────────────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │ Strategizer Lambda  │
              │                     │
              │ 1. Load user profile│
              │ 2. Load rankings    │
              │ 3. Load research    │
              │ 4. Filter           │
              │ 5. Score            │
              │ 6. Mine vs Validate │
              │ 7. Optimize         │
              │ 8. Output           │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │ S3: strategy/       │
              │   latest.json       │
              │   {date}/{ts}.json  │
              └─────────────────────┘
```

### Module Layout

```
lambda/src/strategizer/
├── handler.py          # Lambda entry point (wiring, I/O)
├── scoring.py          # Pure functions: filter, score, mine_vs_validate
└── optimizer.py        # Pure function: portfolio allocation
```

### Key Design Decisions

1. **Pure computation** — scoring.py and optimizer.py have zero AWS imports. They take dicts in and return dicts out. Testable without moto.

2. **Greedy optimizer, not LP** — With max 3-5 positions, a greedy top-down allocation is optimal enough and trivially debuggable. Linear programming adds complexity without meaningful improvement at this scale.

3. **Score THEN filter** — Actually, filter FIRST (cheap), then score survivors (expensive). Reversed from typical ML pipelines because our scoring is cheap too, but filtering eliminates 70%+ of subnets immediately.

4. **No caching** — The strategy is recomputed from scratch each time (takes <1s). No stale state to worry about.

5. **Rationale generation** — Each recommendation carries a human-readable explanation. This is critical for trust. If the system says "mine SN44" but can't explain why, it's useless.

6. **Default profile** — The system works out-of-the-box with a conservative default (no hardware, 100 TAO stake, 1 TAO reg budget, conservative risk, prefer passive). This means it produces validator-only recommendations until the user configures hardware.

### Default User Profile

```python
DEFAULT_PROFILE = {
    "hardware": [],  # No GPU → validator-only mode
    "tao_available_stake": 100.0,
    "tao_available_registration": 1.0,
    "risk_tolerance": "conservative",
    "max_positions": 3,
    "prefer_passive": True,
    "excluded_subnets": [],
    "min_pool_liquidity_tao": 500.0,
}
```

### Scoring Weights (Configurable via DynamoDB thresholds)

```python
DEFAULT_SCORING_WEIGHTS = {
    "strategy_weight_yield": 0.40,
    "strategy_weight_risk": 0.25,
    "strategy_weight_accessibility": 0.20,
    "strategy_weight_efficiency": 0.15,
    "strategy_min_fitness_threshold": 0.30,
    "strategy_passive_preference_ratio": 0.80,
    "strategy_auto_refresh": False,
    "strategy_debounce_minutes": 60,
}
```

### Mine vs Validate Logic (Pseudocode)

```python
# GPU rental cost estimates (monthly USD, conservative)
GPU_MONTHLY_COST_USD = {
    "RTX 4090": 250,
    "A100": 1000,
    "H100": 2000,
    "RTX 3090": 150,
    "A6000": 500,
}

def estimate_mining_yield(ranking, research, profile, tao_usd_price) -> float:
    """Estimate daily TAO from mining a subnet."""
    if not research["open_source_miner"]:
        return 0.0  # Can't mine without a miner
    if research["gpu_required"] and not _hardware_compatible(research, profile):
        return 0.0  # Can't mine without compatible hardware

    # WTA bifurcation: if WTA subnet and difficulty != trivial, yield = 0
    reward_model = ranking.get("reward_model", "unknown")
    if reward_model == "wta" and research["difficulty"] != "trivial":
        return 0.0  # Can't compete on WTA without top-tier setup

    # Proportional: equal share among miners, adjusted by difficulty
    base_yield = ranking["net_tao_yield"] / max(1, estimated_miners)
    difficulty_multiplier = {"trivial": 1.0, "medium": 0.5, "hard": 0.1}[research["difficulty"]]
    gross_yield = base_yield * difficulty_multiplier

    # Subtract hardware cost (converted to daily TAO)
    gpu_type = _best_compatible_gpu(research, profile)
    monthly_cost_usd = GPU_MONTHLY_COST_USD.get(gpu_type, 300)
    daily_cost_tao = (monthly_cost_usd / 30) / tao_usd_price
    
    return max(0.0, gross_yield - daily_cost_tao)

def estimate_validating_yield(ranking, profile, min_validator_stake) -> float:
    """Estimate daily TAO from validating on a subnet."""
    if profile["tao_available_stake"] < min_validator_stake:
        return 0.0  # Can't meet minimum stake
    stake = min(profile["tao_available_stake"] / profile["max_positions"], 
                profile["tao_available_stake"])
    daily_rate = ranking["real_apy_percent"] / 100.0 / 365.0
    return stake * daily_rate
```

### Integration with Existing Pipeline

- **Trigger**: Finalizer already invokes async functions (it calls itself for site gen). Adding a conditional async invoke to Strategizer is one line.
- **Storage**: Uses existing `StorageLayer` (S3 writes) and `StateManager` (DynamoDB reads).
- **CDK**: New Lambda function, same container image, new handler CMD.
- **No new infrastructure**: Same DynamoDB table, same S3 buckets, same IAM role (extended with new handler path).

---

## What This Does NOT Cover (Future Stages)

- Automated registration/deployment (Stage 6)
- Backtesting against historical data (Stage 5)
- LLM-powered analysis or reasoning
- Multi-user support (single user profile)
- Real-time alerts when strategy changes materially

---

## Decisions (Resolved 2026-06-07)

1. **Validator minimum stake**: Add to Collector. Query on-chain per-subnet minimum validator stake and store with hyperparameters. Use actual value in strategy.

2. **Mining yield by reward model**: YES — bifurcate. WTA subnets where difficulty != trivial → mining yield = 0 (honest pessimism). Proportional subnets get equal-share estimate.

3. **Hardware cost in TAO**: YES — include estimated monthly GPU rental converted to TAO at current alpha_price from Market Observer. Entry cost = registration + first-month hardware (in TAO). Introduces TAO/USD dependency but makes ROI honest.

4. **Exit recommendations**: YES — strategy output includes EXIT signals for degraded positions. Requires tracking current positions in DynamoDB (`CONFIG|ACTIVE_POSITIONS`). Simple list of {netuid, role, entered_at, entry_cost}.
