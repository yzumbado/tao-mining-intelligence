"""Sanity check module — flags obviously wrong pipeline results.

Run after each Processor cycle to catch data quality issues early.
Logs warnings but does not fail the pipeline.
"""

import logging
from typing import Optional

logger = logging.getLogger("tao-pipeline")


def check_derived_metrics(metrics: dict, netuid: int) -> list[str]:
    """Check derived metrics for a subnet for obviously wrong values.

    Args:
        metrics: The derived metrics dict (data section).
        netuid: Subnet ID for logging.

    Returns:
        List of warning messages (empty = all good).
    """
    warnings = []
    data = metrics.get("data", {})

    # ROI sanity
    roi = data.get("roi_estimate", {})
    yield_per_day = roi.get("net_tao_yield_per_day", 0.0)
    days_to_recoup = roi.get("days_to_recoup", 0.0)

    if yield_per_day < 0:
        warnings.append(f"SN{netuid}: negative net_tao_yield_per_day ({yield_per_day})")

    if yield_per_day > 100:
        warnings.append(f"SN{netuid}: unrealistic net_tao_yield_per_day ({yield_per_day} > 100 TAO/day)")

    if 0 < days_to_recoup < 0.01:
        warnings.append(f"SN{netuid}: suspiciously fast recoup ({days_to_recoup} days)")

    # Emission sanity
    emission = data.get("emission_trend", {})
    change = emission.get("change_percent", 0.0)
    if abs(change) > 5.0:
        warnings.append(f"SN{netuid}: extreme emission change ({change*100:.0f}%)")

    # Competitive density
    density = data.get("competitive_density", 0.0)
    if density < 0 or density > 1:
        warnings.append(f"SN{netuid}: competitive_density out of range ({density})")

    # Gini
    reward = data.get("reward_distribution", {})
    gini = reward.get("gini_coefficient", 0.0)
    if gini < 0 or gini > 1:
        warnings.append(f"SN{netuid}: gini_coefficient out of range ({gini})")

    for w in warnings:
        logger.warning(f"SANITY CHECK: {w}")

    return warnings
