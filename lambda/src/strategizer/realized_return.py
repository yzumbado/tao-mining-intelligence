"""Realized TAO Return — measures actual TAO yield from staking on a subnet.

Unlike alpha APY (which measures alpha token yield), this metric answers:
"If I staked 1 TAO on this subnet N days ago, how many TAO would I have now?"

Formula:
    realized_tao_return = alpha_yield_earned × current_price / entry_price
    
    Simplified (continuous approximation):
    daily_tao_return ≈ alpha_daily_rate + alpha_price_daily_change

Requires: Market Observer price history (HISTORY#{netuid} in DynamoDB).
Minimum: 7 days of data for any statistical confidence.
Ideal: 30+ days.
"""

from typing import Optional


def compute_realized_tao_return(
    price_history: list[dict],
    alpha_apy_percent: float,
    lookback_days: int = 7,
) -> Optional[dict]:
    """Compute realized TAO return from price history.

    Args:
        price_history: List of {timestamp, alpha_price, pool_tao} dicts,
            sorted by timestamp ascending. From Market Observer HISTORY records.
        alpha_apy_percent: Current alpha APY from our metrics engine.
        lookback_days: How many days back to measure (default 7).

    Returns:
        Dict with metrics, or None if insufficient data.
    """
    if len(price_history) < 2:
        return None

    # Get oldest and newest entries within lookback window
    newest = price_history[-1]
    oldest = price_history[0]

    newest_price = float(newest["alpha_price"])
    oldest_price = float(oldest["alpha_price"])

    if oldest_price <= 0 or newest_price <= 0:
        return None

    # Calculate actual time span
    from datetime import datetime
    try:
        t_newest = datetime.fromisoformat(newest["timestamp"])
        t_oldest = datetime.fromisoformat(oldest["timestamp"])
    except (ValueError, KeyError):
        return None

    actual_days = (t_newest - t_oldest).total_seconds() / 86400
    if actual_days < 1:
        return None

    # Price change over period
    price_change_pct = (newest_price - oldest_price) / oldest_price * 100
    daily_price_change = price_change_pct / actual_days

    # Alpha yield component (daily)
    alpha_daily_rate = alpha_apy_percent / 365.0

    # Realized daily TAO return = yield + price appreciation
    daily_tao_return = alpha_daily_rate + daily_price_change

    # Pool TAO trend (growing pool = net inflow = healthy)
    newest_pool = float(newest.get("pool_tao", 0))
    oldest_pool = float(oldest.get("pool_tao", 0))
    pool_change_pct = ((newest_pool - oldest_pool) / oldest_pool * 100) if oldest_pool > 0 else 0

    # Confidence based on data quantity
    if actual_days >= 30:
        confidence = "high"
    elif actual_days >= 7:
        confidence = "medium"
    else:
        confidence = "low"

    # Annualized (simple, not compound — per our project convention)
    annualized_tao_return = daily_tao_return * 365

    return {
        "realized_daily_tao_return_pct": round(daily_tao_return, 4),
        "realized_annualized_tao_return_pct": round(annualized_tao_return, 1),
        "alpha_yield_component_pct": round(alpha_daily_rate, 4),
        "price_change_component_pct": round(daily_price_change, 4),
        "alpha_price_start": oldest_price,
        "alpha_price_end": newest_price,
        "alpha_price_change_pct": round(price_change_pct, 2),
        "pool_tao_change_pct": round(pool_change_pct, 2),
        "data_days": round(actual_days, 1),
        "data_points": len(price_history),
        "confidence": confidence,
        "beats_root": annualized_tao_return > 3.1,  # Root baseline
    }
