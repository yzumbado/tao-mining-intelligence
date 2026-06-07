"""Portfolio optimizer — greedy allocation within capital constraints.

Pure function. No AWS imports.
"""


def optimize_portfolio(
    scored_opportunities: list[dict],
    profile: dict,
    thresholds: dict,
) -> dict:
    """Allocate capital across top opportunities using greedy strategy.

    Args:
        scored_opportunities: List of scored opportunities (from scoring.score_opportunity),
            pre-sorted by fitness_score descending.
        profile: User profile dict.
        thresholds: Configurable thresholds dict.

    Returns:
        Dict with recommendations list and portfolio_summary.
    """
    max_positions = profile.get("max_positions", 3)
    reg_budget = profile.get("tao_available_registration", 1.0)
    stake_budget = profile.get("tao_available_stake", 0.0)
    min_fitness = thresholds.get("strategy_min_fitness_threshold", 0.30)

    # Filter below minimum fitness
    viable = [o for o in scored_opportunities if o["fitness_score"] >= min_fitness]

    if not viable:
        return {
            "recommendations": [],
            "do_nothing_reason": f"No opportunity exceeds minimum fitness threshold ({min_fitness}). "
                                f"Best available: {scored_opportunities[0]['fitness_score']:.2f} "
                                f"(SN{scored_opportunities[0]['netuid']})" if scored_opportunities else "No data available",
            "portfolio_summary": _empty_summary(),
        }

    # Greedy allocation: take top N within constraints
    recommendations = []
    used_reg = 0.0
    used_stake = 0.0
    total_daily = 0.0

    for opp in viable:
        if len(recommendations) >= max_positions:
            break

        entry_cost = opp["entry_cost_tao"]

        # Registration budget check
        if used_reg + entry_cost > reg_budget and opp["role"] == "mine":
            continue  # Can't afford registration for mining

        # Stake budget check for validators
        allocated_stake = 0.0
        if opp["role"] == "validate":
            per_position_stake = stake_budget / max(1, max_positions)
            if used_stake + per_position_stake > stake_budget:
                continue
            allocated_stake = per_position_stake
            used_stake += allocated_stake

        # Diversification: no single position > 50% of capital (if multiple positions)
        if max_positions > 1 and recommendations:
            total_capital = reg_budget + stake_budget
            position_capital = entry_cost + allocated_stake
            if total_capital > 0 and position_capital / total_capital > 0.5:
                # Cap this position
                allocated_stake = min(allocated_stake, total_capital * 0.5 - entry_cost)
                allocated_stake = max(0.0, allocated_stake)

        used_reg += entry_cost if opp["role"] == "mine" else 0.5  # Validators also register

        rec = {
            "rank": len(recommendations) + 1,
            "netuid": opp["netuid"],
            "role": opp["role"],
            "fitness_score": opp["fitness_score"],
            "expected_daily_tao": opp["expected_daily_tao"],
            "expected_monthly_tao": opp["expected_monthly_tao"],
            "entry_cost_tao": opp["entry_cost_tao"],
            "allocated_stake_tao": round(allocated_stake, 2),
            "rationale": opp["rationale"],
            "scores": opp["scores"],
        }
        recommendations.append(rec)
        total_daily += opp["expected_daily_tao"]

    # Diversification score: 1.0 if evenly spread, lower if concentrated
    if len(recommendations) > 1:
        yields = [r["expected_daily_tao"] for r in recommendations]
        max_share = max(yields) / max(sum(yields), 0.001)
        diversification = 1.0 - max_share
    else:
        diversification = 0.0

    return {
        "recommendations": recommendations,
        "do_nothing_reason": None,
        "portfolio_summary": {
            "total_allocated_registration": round(used_reg, 4),
            "total_allocated_stake": round(used_stake, 2),
            "expected_daily_tao_total": round(total_daily, 4),
            "expected_monthly_tao_total": round(total_daily * 30, 2),
            "diversification_score": round(diversification, 3),
            "positions_count": len(recommendations),
        },
    }


def _empty_summary() -> dict:
    return {
        "total_allocated_registration": 0.0,
        "total_allocated_stake": 0.0,
        "expected_daily_tao_total": 0.0,
        "expected_monthly_tao_total": 0.0,
        "diversification_score": 0.0,
        "positions_count": 0,
    }
