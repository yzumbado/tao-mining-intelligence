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
    min_liquidity = profile.get("min_pool_liquidity_tao", 500.0)
    reg_budget = profile.get("tao_available_registration", 1.0)

    for r in rankings:
        netuid = r["netuid"]
        research = research_profiles.get(netuid, {})

        # Excluded list
        if netuid in excluded:
            reasons["excluded_by_user"] = reasons.get("excluded_by_user", 0) + 1
            continue

        # Registration cost check (use days_to_recoup as proxy — if 0, reg is free/trivial)
        # We don't have reg_cost in rankings directly, skip if we can't afford
        # For now pass through — optimizer handles capital constraint

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

        # Research confidence — no data at all? Skip for mining, but keep for validation
        confidence = research.get("research_confidence", "none")
        difficulty = research.get("difficulty", "unknown")
        if confidence == "none" and difficulty == "unknown" and not research:
            # No research at all — still valid for validation, keep it
            pass

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
    """Score a single subnet as both mine and validate, return best option.

    Returns dict with: netuid, role, fitness_score, expected_daily_tao, scores breakdown, rationale.
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
    mining_yield = _estimate_mining_yield(ranking, research, profile, tao_usd_price)
    validating_yield = _estimate_validating_yield(ranking, profile)

    # Determine role
    prefer_passive = profile.get("prefer_passive", True)
    if prefer_passive and validating_yield >= mining_yield * passive_ratio:
        role = "validate"
        expected_daily = validating_yield
    elif mining_yield > validating_yield:
        role = "mine"
        expected_daily = mining_yield
    else:
        role = "validate"
        expected_daily = validating_yield

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

    rationale = _build_rationale(ranking, research, role, expected_daily, risk_score)

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
        "validating_yield_estimate": round(validating_yield, 4),
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
    # Check reward model — we infer WTA from competitive_density
    # competitive_density < 0.01 suggests extreme WTA
    competitive_density = ranking.get("competitive_density", 0.0)
    is_wta = competitive_density < 0.01
    if is_wta and difficulty != "trivial":
        return 0.0

    # Base yield: share among miners
    net_yield = ranking.get("net_tao_yield", 0.0)
    # Use 1/competitive_density as proxy for miner count (density = 1/miners for uniform)
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


def _estimate_validating_yield(ranking: dict, profile: dict) -> float:
    """Estimate daily TAO from validating."""
    stake_available = profile.get("tao_available_stake", 0.0)
    max_positions = profile.get("max_positions", 3)
    if stake_available <= 0:
        return 0.0

    # Allocate stake evenly across max_positions
    per_subnet_stake = stake_available / max(1, max_positions)
    daily_rate = ranking.get("real_apy_percent", 0.0) / 100.0 / 365.0
    return per_subnet_stake * daily_rate


def _estimate_entry_cost(
    ranking: dict, research: dict, profile: dict, tao_usd_price: float, role: str
) -> float:
    """Estimate total entry cost in TAO (registration + first month hardware if mining)."""
    # Registration cost — use days_to_recoup * net_yield as proxy if available
    # Fallback: assume 0.5 TAO typical registration
    reg_cost = 0.5  # TODO: use actual reg cost when Collector exposes it in rankings

    if role == "mine" and tao_usd_price > 0 and research.get("gpu_required", False):
        gpu_type = _best_compatible_gpu(research, profile)
        monthly_cost = GPU_MONTHLY_COST_USD.get(gpu_type, 300.0)
        hardware_tao = monthly_cost / tao_usd_price
        return reg_cost + hardware_tao

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


def _build_rationale(ranking: dict, research: dict, role: str, daily_tao: float, risk_score: float) -> str:
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

    if research:
        diff = research.get("difficulty", "unknown")
        if diff != "unknown":
            parts.append(f"difficulty={diff}")
        if research.get("open_source_miner"):
            parts.append("open-source miner available")

    parts.append(f"role={role}")
    parts.append(f"~{daily_tao:.2f}τ/day")

    return "; ".join(parts)
