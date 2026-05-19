"""Configurable thresholds for the TAO Mining Intelligence Pipeline.

All tunable parameters are defined here with defaults. In production,
values are read from DynamoDB (CONFIG|THRESHOLDS) and override these defaults.
Edit via AWS DynamoDB Console without code changes.

To add a new threshold:
1. Add it to DEFAULT_THRESHOLDS with a sensible default
2. Add validation in validate_thresholds() if needed
3. Use it in code via: thresholds = state_manager.get_thresholds()
"""

from typing import Any


# All tunable parameters with their default values
DEFAULT_THRESHOLDS: dict[str, float | int] = {
    # Reward distribution model detection
    "wta_top3_concentration": 0.70,  # Top-3 miners > this % → WTA
    "proportional_gini_max": 0.50,  # Gini < this → PROPORTIONAL

    # Daily briefing alert thresholds
    "briefing_emission_change_pct": 0.01,  # >1% emission change → alert
    "briefing_reg_cost_change_pct": 0.20,  # >20% reg cost change → alert
    "briefing_rank_change_positions": 50,  # >50 rank positions → alert

    # Pipeline reliability
    "max_retries": 3,  # Max retries before ERROR_FATAL
    "error_cooldown_hours": 24,  # Hours before retrying ERROR_FATAL subnet
    "circuit_breaker_threshold": 5,  # Consecutive failures before tripping
    "poison_pill_cycle_threshold": 5,  # Consecutive cycle failures → auto-archive

    # Timeouts (seconds)
    "metagraph_timeout_seconds": 30,  # Per-subnet metagraph fetch timeout
    "query_timeout_seconds": 10,  # Per-query timeout (reg cost, hyperparams)
    "price_api_timeout_seconds": 10,  # External price API timeout
    "collection_timeout_buffer_seconds": 60,  # Stop collecting when this much time remains

    # Concurrency
    "concurrent_collection_limit": 32,  # Max simultaneous WebSocket connections

    # Taoflow health detection
    "death_spiral_consecutive_days": 7,  # Days of negative flow → death spiral check
    "death_spiral_emission_decline": 0.25,  # >25% emission decline → death spiral risk

    # Liquidity
    "low_liquidity_tao_threshold": 100,  # Pool < 100 TAO → low liquidity warning

    # Data freshness
    "data_staleness_warning_hours": 36,  # Show warning if data older than this
}


def validate_thresholds(thresholds: dict[str, Any]) -> dict[str, str]:
    """Validate threshold values at load time.

    Checks that percentages are between 0 and 1, integers are positive,
    and timeouts are reasonable.

    Args:
        thresholds: Dict of threshold name → value to validate.

    Returns:
        Dict of invalid_key → error_message. Empty dict means all valid.
    """
    errors: dict[str, str] = {}

    # Percentage fields (must be 0.0 to 1.0)
    pct_fields = [
        "wta_top3_concentration",
        "proportional_gini_max",
        "briefing_emission_change_pct",
        "briefing_reg_cost_change_pct",
        "death_spiral_emission_decline",
    ]
    for field in pct_fields:
        if field in thresholds:
            val = thresholds[field]
            if not (0.0 <= val <= 1.0):
                errors[field] = f"Must be between 0.0 and 1.0, got {val}"

    # Positive integer fields
    int_fields = [
        "max_retries",
        "circuit_breaker_threshold",
        "poison_pill_cycle_threshold",
        "briefing_rank_change_positions",
        "concurrent_collection_limit",
        "death_spiral_consecutive_days",
    ]
    for field in int_fields:
        if field in thresholds:
            val = thresholds[field]
            if not (isinstance(val, (int, float)) and val > 0):
                errors[field] = f"Must be a positive number, got {val}"

    # Timeout fields (must be positive, reasonable range)
    timeout_fields = [
        "metagraph_timeout_seconds",
        "query_timeout_seconds",
        "price_api_timeout_seconds",
        "collection_timeout_buffer_seconds",
        "error_cooldown_hours",
        "data_staleness_warning_hours",
    ]
    for field in timeout_fields:
        if field in thresholds:
            val = thresholds[field]
            if not (isinstance(val, (int, float)) and val > 0):
                errors[field] = f"Must be a positive number, got {val}"

    # Liquidity threshold (must be non-negative)
    if "low_liquidity_tao_threshold" in thresholds:
        val = thresholds["low_liquidity_tao_threshold"]
        if not (isinstance(val, (int, float)) and val >= 0):
            errors["low_liquidity_tao_threshold"] = f"Must be non-negative, got {val}"

    return errors
