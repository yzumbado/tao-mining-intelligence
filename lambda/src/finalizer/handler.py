"""Finalizer Lambda handler — generates briefing, rankings, and marks cycle complete.

Triggered by SQS (completion-tracker queue, forwarded from SNS subnet-processed).
Each invocation checks if all subnets in the cycle are done. If not, exits early.
If complete, reads all derived metrics, generates aggregate outputs, and marks
the cycle as COMPLETE.

Outputs:
- S3: derived/rankings/{date}.json
- S3: derived/briefings/{date}.json
- DynamoDB: RANKING|LATEST
- DynamoDB: BRIEFING|{date}
- DynamoDB: CYCLE#{cycle_id}|STATUS → COMPLETE
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import boto3

from src.config import PipelineConfig, get_config
from src.instrumentation import set_trace_id, instrument
from src.state.state_manager import StateManager, _float_to_decimal
from src.storage.storage_layer import StorageLayer

logger = logging.getLogger("tao-pipeline")

# Module-level cold-start cache
_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None
_storage: Optional[StorageLayer] = None


def _init_clients() -> None:
    """Initialize AWS clients and config on cold start (cached)."""
    global _config, _state_manager, _storage
    if _config is not None:
        return
    _config = get_config()
    _state_manager = StateManager(_config)
    _storage = StorageLayer(_config)


def handle(event: dict, context: Any) -> dict:
    """Lambda entry point. Checks cycle completeness and generates aggregate outputs."""
    _init_clients()
    set_trace_id("", "")

    # Parse SQS message (SNS envelope)
    try:
        record = event["Records"][0]
        body = json.loads(record["body"])
        # SNS→SQS wraps the message in {"Message": "..."}
        message = json.loads(body["Message"])
        cycle_id = message["cycle_id"]
        date = message["date"]
        trace_id = message.get("trace_id", "")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        logger.error(f"Failed to parse SQS message: {e}")
        return {"status": "error", "error": f"malformed message: {e}"}

    set_trace_id(trace_id, cycle_id)

    with instrument("finalizer", "handle", cycle_id=cycle_id) as ctx:
        # Check if cycle is complete
        if not _state_manager.check_cycle_complete(cycle_id):
            ctx["action"] = "waiting"
            return {"status": "waiting", "cycle_id": cycle_id}

        # Get active subnets
        active_subnets = _state_manager.get_active_subnets()

        # Read all derived metrics from S3
        all_metrics = _read_all_derived_metrics(date, active_subnets)

        # Generate rankings
        rankings = _generate_rankings(all_metrics)

        # Generate briefing
        briefing = _generate_briefing(date, cycle_id, all_metrics, active_subnets)

        # Store rankings to S3
        _storage.store_snapshot(
            _storage.get_date_path("derived/rankings", date),
            rankings)

        # Store briefing to S3
        _storage.store_snapshot(
            _storage.get_date_path("derived/briefings", date),
            briefing)

        # Store RANKING|LATEST in DynamoDB
        _state_manager._table.put_item(Item=_float_to_decimal({
            "PK": "RANKING", "SK": "LATEST",
            "ranked_subnets": rankings,
            "date": date,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }))

        # Store BRIEFING|{date} in DynamoDB
        _state_manager._table.put_item(Item=_float_to_decimal({
            "PK": "BRIEFING", "SK": date,
            "summary": briefing.get("summary", ""),
            "alerts_count": len(briefing.get("alerts", [])),
            "subnets_processed": briefing.get("subnets_processed", 0),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }))

        # Mark cycle complete
        _state_manager.mark_cycle_complete(cycle_id)

        ctx["rankings_count"] = len(rankings)
        ctx["alerts_count"] = len(briefing.get("alerts", []))

        return {
            "status": "complete",
            "cycle_id": cycle_id,
            "rankings_generated": len(rankings),
            "briefing_generated": True,
        }


# ---------------------------------------------------------------------------
# Metrics reading
# ---------------------------------------------------------------------------


def _read_all_derived_metrics(date: str, netuids: list[int]) -> dict[int, dict]:
    """Read derived metrics for all subnets from S3."""
    metrics = {}
    for netuid in netuids:
        path = _storage.get_date_path("derived/metrics", date, netuid)
        data = _storage.read_snapshot(path)
        if data is not None:
            metrics[netuid] = data
    return metrics


# ---------------------------------------------------------------------------
# Ranking generation
# ---------------------------------------------------------------------------


import math


def _safe_float(value, default: float = 0.0) -> float:
    """Sanitize a float value — replace NaN/Inf with default."""
    if value is None:
        return default
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _generate_rankings(all_metrics: dict[int, dict]) -> list[dict]:
    """Generate subnet rankings sorted by attractiveness score."""
    rankings = []

    for netuid, metrics in all_metrics.items():
        data = metrics.get("data", {})
        roi = data.get("roi_estimate", {})
        emission = data.get("emission_trend", {})

        net_tao_yield = _safe_float(roi.get("net_tao_yield_per_day", 0.0))
        days_to_recoup = _safe_float(roi.get("days_to_recoup", 0.0), default=9999.0)
        competitive_density = _safe_float(data.get("competitive_density", 1.0))
        emission_change = _safe_float(emission.get("change_percent", 0.0))
        taoflow = data.get("taoflow_health", {}).get("status", "HEALTHY")

        # Attractiveness score: higher is better
        # Weighted formula: yield dominates, penalize high recoup time and density
        score = _compute_attractiveness_score(
            net_tao_yield, days_to_recoup, competitive_density,
            emission_change, taoflow)

        rankings.append({
            "netuid": netuid,
            "net_tao_yield": net_tao_yield,
            "days_to_recoup": days_to_recoup,
            "thirty_day_projection": _safe_float(roi.get("thirty_day_projected_tao", 0.0)),
            "competitive_density": competitive_density,
            "emission_trend": emission_change,
            "alpha_price": _safe_float(roi.get("alpha_tao_rate", 0.0)),
            "attractiveness_score": score,
        })

    # Sort by attractiveness score descending
    rankings.sort(key=lambda r: r["attractiveness_score"], reverse=True)
    return rankings


def _compute_attractiveness_score(net_tao_yield: float, days_to_recoup: float,
                                  competitive_density: float,
                                  emission_change: float,
                                  taoflow_status: str) -> float:
    """Compute composite attractiveness score.

    Higher is better. Factors:
    - net_tao_yield (weight: 0.4) — primary driver
    - days_to_recoup inverse (weight: 0.25) — faster payback = better
    - competitive_density inverse (weight: 0.15) — less competition = better
    - emission_trend (weight: 0.1) — growing emissions = better
    - taoflow health (weight: 0.1) — healthy = bonus, death spiral = penalty
    """
    # Normalize yield (assume max ~5 TAO/day is excellent)
    yield_score = min(net_tao_yield / 5.0, 1.0)

    # Normalize recoup (7 days = perfect, 365+ = terrible)
    if days_to_recoup <= 0 or days_to_recoup == float("inf"):
        recoup_score = 0.0
    else:
        recoup_score = max(0.0, 1.0 - (days_to_recoup / 365.0))

    # Density inverse (0 = no competition = perfect)
    density_score = 1.0 - min(competitive_density, 1.0)

    # Emission trend (positive = good, capped at ±50%)
    trend_score = 0.5 + min(max(emission_change, -0.5), 0.5)

    # Taoflow bonus/penalty
    taoflow_score = {"HEALTHY": 1.0, "DECLINING": 0.3,
                     "DEATH_SPIRAL_RISK": 0.0}.get(taoflow_status, 0.5)

    return (yield_score * 0.4 + recoup_score * 0.25 + density_score * 0.15 +
            trend_score * 0.1 + taoflow_score * 0.1)


# ---------------------------------------------------------------------------
# Briefing generation
# ---------------------------------------------------------------------------


def _generate_briefing(date: str, cycle_id: str,
                       all_metrics: dict[int, dict],
                       active_subnets: list[int]) -> dict:
    """Generate daily briefing with alerts."""
    alerts = []

    # Detect emission changes > 10%
    for netuid, metrics in all_metrics.items():
        emission = metrics.get("data", {}).get("emission_trend", {})
        change = emission.get("change_percent", 0.0)
        if abs(change) > 0.10:
            alerts.append({
                "netuid": netuid,
                "alert_type": "emission_change",
                "severity": "warning" if abs(change) > 0.25 else "info",
                "message": f"Subnet {netuid} emission changed {change*100:.1f}% day-over-day",
                "metric_value": change,
            })

    # Detect new subnets
    new_subnets = _detect_new_subnets(active_subnets)

    for netuid in new_subnets:
        alerts.append({
            "netuid": netuid,
            "alert_type": "new_subnet",
            "severity": "info",
            "message": f"New subnet {netuid} detected",
        })

    summary = (f"Daily briefing for {date}: "
               f"{len(all_metrics)} subnets processed, "
               f"{len(alerts)} alerts, "
               f"{len(new_subnets)} new subnets.")

    return {
        "date": date,
        "cycle_id": cycle_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "alerts": alerts,
        "new_subnets": new_subnets,
        "removed_subnets": [],
        "top_movers": [],
        "subnets_processed": len(all_metrics),
        "subnets_failed": len(active_subnets) - len(all_metrics),
    }


def _detect_new_subnets(current_subnets: list[int]) -> list[int]:
    """Detect subnets that are new (not in previous active list)."""
    try:
        resp = _state_manager._table.get_item(
            Key={"PK": "CONFIG", "SK": "PREVIOUS_ACTIVE_SUBNETS"})
        item = resp.get("Item")
        if not item:
            return []
        previous = [int(n) for n in item.get("netuids", [])]
        return [n for n in current_subnets if n not in previous]
    except Exception:
        return []
