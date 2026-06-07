"""Strategy scoring engine — pure functions for filtering, scoring, and role selection.

No AWS imports. Takes dicts in, returns dicts out. Fully testable without moto.
"""

from typing import Any

# GPU monthly rental costs (USD) — conservative estimates for cloud rental
GPU_MONTHLY_COST_USD: dict[str, float] = {
    "RTX 4090": 250.0,
    "RTX 3090": 150.0,
    "A6000": 500.0,
    "A100": 1000.0,
    "H100": 2000.0,
    "L40": 700.0,
    "RTX 4080": 200.0,
}

# Default scoring weights (overridable via thresholds)
DEFAULT_WEIGHTS = {
    "strategy_weight_yield": 0.40,
    "strategy_weight_risk": 0.25,
    "strategy_weight_accessibility": 0.20,
    "strategy_weight_efficiency": 0.15,
    "strategy_min_fitness_threshold": 0.30,
    "strategy_passive_preference_ratio": 0.80,
}


# Validator server costs (monthly USD)
VALIDATOR_SERVER_MONTHLY_USD: float = 100.0  # Typical VPS with optional GPU for validator
VALIDATOR_COMMISSION_RATE: float = 0.18  # Typical validator commission (18%)
MIN_VIABLE_VALIDATOR_STAKE_TAO: float = 500.0  # Below this, server costs > earnings


def filter_opportunities(
    rankings: list[dict],
    research_profiles: dict[int, dict],
    profile: dict,
) -> tuple[list[dict], dict[str, int]]:
    """Filter subnets by hardware, capital, and risk constraints.

    Returns:
        (surviving_rankings, filter_reasons_summary)
    """
    survivors = []
    reasons: dict[str, int] = {}

    excluded = set(profile.get("excluded_subnets", []))
    risk_tolerance = profile.get("risk_tolerance", "conservative")

    for r in rankings:
        netuid = r["netuid"]

        # Excluded list
        if netuid in excluded:
            reasons["excluded_by_user"] = reasons.get("excluded_by_user", 0) + 1
            continue

        # Self-mining risk
        self_mining = r.get("self_mining_risk", 0.0)
        if self_mining > 0.0 and risk_tolerance != "aggressive":
            reasons["self_mining_risk"] = reasons.get("self_mining_risk", 0) + 1
            continue

        # Concentration risk
        conc = r.get("concentration_risk", {})
        conc_tier = conc.get("tier", "healthy") if isinstance(conc, dict) else "healthy"
        if conc_tier == "critical" and risk_tolerance == "conservative":
            reasons["concentration_risk"] = reasons.get("concentration_risk", 0) + 1
            continue

        survivors.append(r)

    return survivors, reasons


def score_opportunity(
    ranking: dict,
    research: dict,
    profile: dict,
    max_yield: float,
    max_entry_cost: float,
    tao_usd_price: float,
    thresholds: dict,
) -> dict:
    """Score a single subnet across all three roles, return best option.

    Roles: mine, run_validator, delegate.
    Returns dict with: netuid, role, fitness_score, expected_daily_tao, scores, rationale.
    """
    weights = {
        "yield": thresholds.get("strategy_weight_yield", DEFAULT_WEIGHTS["strategy_weight_yield"]),
        "risk": thresholds.get("strategy_weight_risk", DEFAULT_WEIGHTS["strategy_weight_risk"]),
        "accessibility": thresholds.get("strategy_weight_accessibility", DEFAULT_WEIGHTS["strategy_weight_accessibility"]),
        "efficiency": thresholds.get("strategy_weight_efficiency", DEFAULT_WEIGHTS["strategy_weight_efficiency"]),
    }
    passive_ratio = thresholds.get("strategy_passive_preference_ratio", DEFAULT_WEIGHTS["strategy_passive_preference_ratio"])

    # Score dimensions
    yield_score = _score_yield(ranking, max_yield)
    risk_score = _score_risk(ranking)
    accessibility_score = _score_accessibility(research)

    # Estimate yields for all three roles
    mining_yield = _estimate_mining_yield(ranking, research, profile, tao_usd_price)
    validator_yield = _estimate_run_validator_yield(ranking, profile, tao_usd_price)
    delegate_yield = _estimate_delegate_yield(ranking, profile)

    # Pick best role
    yields = {"mine": mining_yield, "run_validator": validator_yield, "delegate": delegate_yield}

    # Prefer passive (delegate) if it's close enough
    if profile.get("prefer_passive", True):
        best_active = max(mining_yield, validator_yield)
        if delegate_yield >= best_active * passive_ratio and delegate_yield > 0:
            role = "delegate"
        elif validator_yield >= mining_yield * passive_ratio and validator_yield > 0:
            role = "run_validator"
        elif mining_yield > 0:
            role = "mine"
        elif validator_yield > 0:
            role = "run_validator"
        else:
            role = "delegate"
    else:
        role = max(yields, key=yields.get)

    expected_daily = yields[role]

    # Efficiency: yield per TAO invested
    entry_cost = _estimate_entry_cost(ranking, research, profile, tao_usd_price, role)
    efficiency_score = min(1.0, (expected_daily / max(entry_cost, 0.01)) / max(max_entry_cost, 0.01)) if max_entry_cost > 0 else 0.5

    # Composite fitness
    fitness = (
        yield_score * weights["yield"]
        + risk_score * weights["risk"]
        + accessibility_score * weights["accessibility"]
        + efficiency_score * weights["efficiency"]
    )

    rationale = _build_rationale(ranking, research, role, expected_daily, risk_score, profile, tao_usd_price)

    return {
        "netuid": ranking["netuid"],
        "role": role,
        "fitness_score": round(fitness, 4),
        "expected_daily_tao": round(expected_daily, 4),
        "expected_monthly_tao": round(expected_daily * 30, 2),
        "entry_cost_tao": round(entry_cost, 4),
        "scores": {
            "yield": round(yield_score, 3),
            "risk": round(risk_score, 3),
            "accessibility": round(accessibility_score, 3),
            "efficiency": round(efficiency_score, 3),
        },
        "rationale": rationale,
        "mining_yield_estimate": round(mining_yield, 4),
        "validator_yield_estimate": round(validator_yield, 4),
        "delegate_yield_estimate": round(delegate_yield, 4),
        "role_details": _role_details(role, ranking, profile, tao_usd_price),
    }


def evaluate_exits(
    active_positions: list[dict],
    rankings: list[dict],
    thresholds: dict,
) -> list[dict]:
    """Evaluate active positions for EXIT signals.

    Returns list of exit recommendations.
    """
    min_fitness = thresholds.get("strategy_min_fitness_threshold", 0.30)
    rankings_by_netuid = {r["netuid"]: r for r in rankings}
    exits = []

    for pos in active_positions:
        netuid = pos["netuid"]
        ranking = rankings_by_netuid.get(netuid)
        if not ranking:
            exits.append({
                "netuid": netuid,
                "role": pos.get("role", "unknown"),
                "urgency": "high",
                "reason": "Subnet no longer in rankings (may be deregistered)",
            })
            continue

        reasons = []
        urgency = "low"

        # Self-mining risk emerged
        if ranking.get("self_mining_risk", 0.0) > 0.0 and pos.get("entry_self_mining_risk", 0.0) == 0.0:
            reasons.append("Self-mining risk emerged since entry")
            urgency = "medium"

        # Attractiveness collapsed
        if ranking.get("attractiveness_score", 0.0) < min_fitness:
            reasons.append(f"Attractiveness score ({ranking['attractiveness_score']:.2f}) below threshold ({min_fitness})")
            urgency = "medium"

        # APY collapsed (>50% drop from entry)
        entry_apy = pos.get("entry_apy_percent", 0.0)
        current_apy = ranking.get("real_apy_percent", 0.0)
        if entry_apy > 0 and current_apy < entry_apy * 0.5:
            reasons.append(f"APY dropped {((entry_apy - current_apy) / entry_apy * 100):.0f}% from entry ({entry_apy:.0f}% → {current_apy:.0f}%)")
            urgency = "high"

        if reasons:
            exits.append({
                "netuid": netuid,
                "role": pos.get("role", "unknown"),
                "urgency": urgency,
                "reason": "; ".join(reasons),
            })

    return exits


# ---------------------------------------------------------------------------
# Private scoring helpers
# ---------------------------------------------------------------------------


def _score_yield(ranking: dict, max_yield: float) -> float:
    """Normalize yield relative to top yielder."""
    if max_yield <= 0:
        return 0.0
    return min(1.0, ranking.get("net_tao_yield", 0.0) / max_yield)


def _score_risk(ranking: dict) -> float:
    """Inverted combined risk score (1.0 = no risk)."""
    self_mining = ranking.get("self_mining_risk", 0.0)
    conc = ranking.get("concentration_risk", {})
    conc_risk = conc.get("risk", 0.0) if isinstance(conc, dict) else 0.0

    # Emission stability: trend near 0 = stable
    emission_trend = abs(ranking.get("emission_trend", 0.0))
    instability = min(1.0, emission_trend * 1000)  # Scale small values to 0-1

    # Liquidity risk (inverse of alpha_price — low price = thin pool)
    alpha_price = ranking.get("alpha_price", 0.0)
    liquidity_risk = 0.0 if alpha_price > 0.1 else (0.5 if alpha_price > 0.01 else 1.0)

    combined = self_mining * 0.3 + conc_risk * 0.3 + instability * 0.2 + liquidity_risk * 0.2
    return max(0.0, 1.0 - combined)


def _score_accessibility(research: dict) -> float:
    """Score based on difficulty and research confidence."""
    if not research:
        return 0.3  # Unknown = low accessibility for mining, ok for validating

    difficulty_map = {"trivial": 1.0, "medium": 0.6, "hard": 0.2, "unknown": 0.3}
    confidence_map = {"high": 1.0, "medium": 0.7, "low": 0.4, "none": 0.2}

    diff = difficulty_map.get(research.get("difficulty", "unknown"), 0.3)
    conf = confidence_map.get(research.get("research_confidence", "none"), 0.2)
    return diff * 0.6 + conf * 0.4


def _estimate_mining_yield(
    ranking: dict, research: dict, profile: dict, tao_usd_price: float
) -> float:
    """Estimate daily TAO from mining. Returns 0 if infeasible."""
    if not research or not research.get("open_source_miner", False):
        return 0.0

    # Hardware check
    if research.get("gpu_required", False):
        if not _hardware_compatible(research, profile):
            return 0.0

    # WTA bifurcation
    difficulty = research.get("difficulty", "unknown")
    competitive_density = ranking.get("competitive_density", 0.0)
    is_wta = competitive_density < 0.01
    if is_wta and difficulty != "trivial":
        return 0.0

    # Base yield: share among miners
    net_yield = ranking.get("net_tao_yield", 0.0)
    estimated_miners = max(1, int(1.0 / max(competitive_density, 0.001)))
    base_yield = net_yield / estimated_miners

    difficulty_multiplier = {"trivial": 1.0, "medium": 0.5, "hard": 0.1, "unknown": 0.2}
    gross_yield = base_yield * difficulty_multiplier.get(difficulty, 0.2)

    # Subtract hardware cost
    if tao_usd_price > 0 and research.get("gpu_required", False):
        gpu_type = _best_compatible_gpu(research, profile)
        monthly_cost = GPU_MONTHLY_COST_USD.get(gpu_type, 300.0)
        daily_cost_tao = (monthly_cost / 30.0) / tao_usd_price
        gross_yield -= daily_cost_tao

    return max(0.0, gross_yield)


def _estimate_run_validator_yield(ranking: dict, profile: dict, tao_usd_price: float) -> float:
    """Estimate daily TAO from running your own validator.

    Requires: server 24/7, subnet validator software, minimum viable stake.
    Same alpha risk as delegation — yield is in alpha tokens, not TAO.
    """
    stake_available = profile.get("tao_available_stake", 0.0)
    max_positions = profile.get("max_positions", 3)
    if stake_available <= 0:
        return 0.0

    per_subnet_stake = stake_available / max(1, max_positions)

    # Below minimum viable stake, server cost exceeds earnings — not worth it
    if per_subnet_stake < MIN_VIABLE_VALIDATOR_STAKE_TAO:
        return 0.0

    # Gross yield from staking
    apy = ranking.get("real_apy_percent", 0.0)
    daily_rate = apy / 100.0 / 365.0
    gross_daily = per_subnet_stake * daily_rate

    # Alpha risk discount (same as delegate)
    if apy <= 20:
        alpha_discount = 0.90
    elif apy <= 100:
        alpha_discount = 0.70
    elif apy <= 300:
        alpha_discount = 0.50
    else:
        alpha_discount = 0.30

    risk_adjusted = gross_daily * alpha_discount

    # Subtract server cost (converted to TAO)
    if tao_usd_price > 0:
        daily_server_cost_tao = (VALIDATOR_SERVER_MONTHLY_USD / 30.0) / tao_usd_price
        net_daily = risk_adjusted - daily_server_cost_tao
    else:
        net_daily = risk_adjusted

    return max(0.0, net_daily)


def _estimate_delegate_yield(ranking: dict, profile: dict) -> float:
    """Estimate daily TAO from delegating to an existing validator.

    Truly passive: no software, no server, just stake.
    Yield = APY * stake * (1 - commission) * alpha_risk_discount.

    IMPORTANT: Subnet APY is denominated in alpha tokens, not TAO.
    Alpha price can depreciate, wiping out yield. We apply a discount:
    - Low APY (<20%): likely stable, 90% confidence
    - Medium APY (20-100%): moderate risk, 70% confidence
    - High APY (>100%): high alpha risk, 50% confidence
    - Extreme APY (>300%): very high risk, 30% confidence
    Root (SN0) at ~3% is the TAO-native baseline — everything above carries alpha risk.
    """
    stake_available = profile.get("tao_available_stake", 0.0)
    max_positions = profile.get("max_positions", 3)
    if stake_available <= 0:
        return 0.0

    per_subnet_stake = stake_available / max(1, max_positions)
    apy = ranking.get("real_apy_percent", 0.0)
    daily_rate = apy / 100.0 / 365.0
    gross_daily = per_subnet_stake * daily_rate

    # Deduct validator commission
    after_commission = gross_daily * (1.0 - VALIDATOR_COMMISSION_RATE)

    # Alpha risk discount (higher APY = less likely to sustain)
    if apy <= 20:
        alpha_discount = 0.90
    elif apy <= 100:
        alpha_discount = 0.70
    elif apy <= 300:
        alpha_discount = 0.50
    else:
        alpha_discount = 0.30

    return max(0.0, after_commission * alpha_discount)


def _estimate_entry_cost(
    ranking: dict, research: dict, profile: dict, tao_usd_price: float, role: str
) -> float:
    """Estimate total entry cost in TAO."""
    reg_cost = 0.5  # Typical registration

    if role == "mine" and tao_usd_price > 0 and research.get("gpu_required", False):
        gpu_type = _best_compatible_gpu(research, profile)
        monthly_cost = GPU_MONTHLY_COST_USD.get(gpu_type, 300.0)
        hardware_tao = monthly_cost / tao_usd_price
        return reg_cost + hardware_tao

    if role == "run_validator" and tao_usd_price > 0:
        server_tao = VALIDATOR_SERVER_MONTHLY_USD / tao_usd_price
        return reg_cost + server_tao

    if role == "delegate":
        return 0.0  # No registration needed for delegation

    return reg_cost


def _hardware_compatible(research: dict, profile: dict) -> bool:
    """Check if user has GPU compatible with subnet requirements."""
    hardware = profile.get("hardware", [])
    if not hardware:
        return False
    required_vram = research.get("vram_gb_estimate") or 0
    return any(gpu.get("vram_gb", 0) >= required_vram for gpu in hardware)


def _best_compatible_gpu(research: dict, profile: dict) -> str:
    """Find the best compatible GPU from user's hardware."""
    hardware = profile.get("hardware", [])
    required_vram = research.get("vram_gb_estimate") or 0
    compatible = [g for g in hardware if g.get("vram_gb", 0) >= required_vram]
    if compatible:
        # Return cheapest compatible
        return min(compatible, key=lambda g: GPU_MONTHLY_COST_USD.get(g.get("type", ""), 9999)).get("type", "RTX 4090")
    return "RTX 4090"  # Fallback


def _build_rationale(ranking: dict, research: dict, role: str, daily_tao: float, risk_score: float, profile: dict, tao_usd_price: float) -> str:
    """Build human-readable rationale for recommendation."""
    parts = []
    apy = ranking.get("real_apy_percent", 0.0)
    parts.append(f"APY {apy:.0f}%")

    if risk_score > 0.8:
        parts.append("clean risk profile")
    elif risk_score > 0.5:
        parts.append("moderate risk")
    else:
        parts.append("elevated risk")

    if role == "delegate":
        apy = ranking.get("real_apy_percent", 0.0)
        if apy > 300:
            parts.append("⚠️ EXTREME alpha risk (APY>300% rarely sustains)")
        elif apy > 100:
            parts.append("⚠️ HIGH alpha risk (yield in volatile alpha tokens)")
        elif apy > 20:
            parts.append("moderate alpha risk")
        else:
            parts.append("low alpha risk (near TAO-native yield)")
        parts.append("PASSIVE — just delegate, no software needed")
        parts.append(f"~{VALIDATOR_COMMISSION_RATE*100:.0f}% commission to validator")
    elif role == "run_validator":
        parts.append("ACTIVE — requires 24/7 server + validator software")
        parts.append(f"server ~${VALIDATOR_SERVER_MONTHLY_USD}/mo")
    elif role == "mine":
        if research:
            diff = research.get("difficulty", "unknown")
            parts.append(f"difficulty={diff}")
            if research.get("open_source_miner"):
                parts.append("open-source miner")

    parts.append(f"~{daily_tao:.3f}τ/day")
    return "; ".join(parts)


def _role_details(role: str, ranking: dict, profile: dict, tao_usd_price: float) -> dict:
    """Provide transparency about what each role actually requires."""
    max_positions = profile.get("max_positions", 3)
    per_stake = profile.get("tao_available_stake", 0.0) / max(1, max_positions)

    if role == "delegate":
        return {
            "type": "passive",
            "requirements": "TAO to stake (no hardware, no software, no registration)",
            "what_you_do": "Delegate TAO to an existing validator via btcli or Bittensor dashboard",
            "risks": "Validator can change commission; validator could go offline (you'd stop earning)",
            "stake_per_subnet": round(per_stake, 1),
            "commission_percent": VALIDATOR_COMMISSION_RATE * 100,
            "server_cost_monthly_usd": 0,
        }
    elif role == "run_validator":
        return {
            "type": "active",
            "requirements": "Server 24/7 ($100/mo), subnet validator code running, registration (0.5τ), minimum ~500τ stake",
            "what_you_do": "Rent a VPS, clone subnet repo, run validator process, set weights on-chain every tempo",
            "risks": "Server downtime → vtrust drops → deregistration; subnet code updates require maintenance",
            "stake_per_subnet": round(per_stake, 1),
            "commission_percent": 0,
            "server_cost_monthly_usd": VALIDATOR_SERVER_MONTHLY_USD,
            "min_viable_stake": MIN_VIABLE_VALIDATOR_STAKE_TAO,
        }
    else:  # mine
        return {
            "type": "active",
            "requirements": "GPU compute 24/7, subnet miner code running, registration (0.5τ)",
            "what_you_do": "Rent GPU, clone subnet repo, run miner, compete for incentive score",
            "risks": "Deregistration if performance below peers; hardware costs are fixed regardless of earnings",
            "stake_per_subnet": 0,
            "server_cost_monthly_usd": 0,
        }
