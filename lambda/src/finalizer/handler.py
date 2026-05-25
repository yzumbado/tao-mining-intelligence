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
from src.processor.metrics import MetricsEngine
from src.state.state_manager import StateManager
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
    """Lambda entry point. Recomputes rankings and briefing from current profiles."""
    _init_clients()
    set_trace_id("", "")

    # Parse event — accepts SQS (legacy), direct invoke, or any trigger
    try:
        if "Records" in event:
            record = event["Records"][0]
            body = json.loads(record["body"])
            message = json.loads(body.get("Message", body)) if isinstance(body, dict) else json.loads(body)
            date = message.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            cycle_id = message.get("cycle_id", date)
            trace_id = message.get("trace_id", "")
        else:
            date = event.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            cycle_id = event.get("cycle_id", date)
            trace_id = event.get("trace_id", f"aggregator-{date}")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        logger.error(f"Failed to parse event: {e}")
        return {"status": "error", "error": f"malformed event: {e}"}

    set_trace_id(trace_id, cycle_id)

    with instrument("finalizer", "handle", cycle_id=cycle_id) as ctx:
        # Read all derived metrics from S3 (whatever exists for today)
        active_subnets = _state_manager.get_active_subnets()
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
        _state_manager.store_ranking(date, rankings)

        # Store BRIEFING|{date} in DynamoDB
        _state_manager.store_briefing(date, briefing)

        # Mark cycle complete (best-effort, for observability only)
        try:
            _state_manager.mark_cycle_complete(cycle_id)
        except Exception:
            pass  # Not critical in independent refresh model

        # Upload agent-consumable files to site bucket (AD18)
        _upload_agent_files(rankings, briefing, all_metrics, date)

        # Post-condition verification (Conformance Phase A)
        # Logs findings as structured JSON; does NOT block pipeline.
        _verify_outputs(rankings, briefing, all_metrics, date)

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
    total_emission_all = sum(
        _safe_float(m.get("data", {}).get("emission_trend", {}).get("current_total_emission", 0.0))
        for m in all_metrics.values()
    )

    for netuid, metrics in all_metrics.items():
        data = metrics.get("data", {})
        roi = data.get("roi_estimate", {})

        net_tao_yield = _safe_float(roi.get("net_tao_yield_per_day", 0.0))
        alpha_price = _safe_float(roi.get("alpha_tao_rate", 0.0))

        # Emission share: this subnet's emission / total network emission
        current_emission = _safe_float(
            data.get("emission_trend", {}).get("current_total_emission", 0.0))
        emission_share = (current_emission / total_emission_all
                          if total_emission_all > 0 else 0.0)

        # Pool depth from ROI slippage context (alpha_price × 1000 is a rough proxy
        # when actual pool_tao isn't in derived output — TODO: wire actual pool_tao)
        pool_depth = _safe_float(alpha_price * 10000.0 if alpha_price > 0 else 0.0)

        # Self-mining risk
        sm_risk = _safe_float(
            data.get("self_mining_risk", {}).get("risk_score", 0.0))

        # Net flow EMA (0.0 until stake history accumulates)
        net_flow_ema = 0.0  # TODO: read from DynamoDB stake history once available

        # Risk-adjusted attractiveness score
        score = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=net_tao_yield,
            emission_share=emission_share,
            pool_depth_tao=pool_depth,
            self_mining_risk=sm_risk,
            net_flow_ema=net_flow_ema,
        )

        rankings.append({
            "netuid": netuid,
            "net_tao_yield": net_tao_yield,
            "days_to_recoup": _safe_float(roi.get("days_to_recoup", 0.0), default=9999.0),
            "thirty_day_projection": _safe_float(roi.get("thirty_day_projected_tao", 0.0)),
            "competitive_density": _safe_float(data.get("competitive_density", 1.0)),
            "emission_trend": _safe_float(
                data.get("emission_trend", {}).get("change_percent", 0.0)),
            "alpha_price": alpha_price,
            "attractiveness_score": score,
            "self_mining_risk": sm_risk,
            "real_apy_percent": _safe_float(data.get("real_apy_percent", 0.0)),
        })

    # Sort by attractiveness score descending
    rankings.sort(key=lambda r: r["attractiveness_score"], reverse=True)
    return rankings



# ---------------------------------------------------------------------------
# Briefing generation
# ---------------------------------------------------------------------------


def _generate_briefing(date: str, cycle_id: str,
                       all_metrics: dict[int, dict],
                       active_subnets: list[int]) -> dict:
    """Generate daily briefing with alerts."""
    from src.thresholds import DEFAULT_THRESHOLDS
    alerts = []

    emission_threshold = DEFAULT_THRESHOLDS["briefing_emission_change_pct"]

    # Detect emission changes exceeding threshold
    for netuid, metrics in all_metrics.items():
        emission = metrics.get("data", {}).get("emission_trend", {})
        change = emission.get("change_percent", 0.0)
        if abs(change) > emission_threshold:
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


def _generate_staking_rankings(all_metrics: dict[int, dict]) -> list[dict]:
    """Generate staking rankings sorted by net APY.

    Uses validator landscape data from derived metrics to compute
    yield per TAO staked, accounting for entry/exit slippage and
    validator take rate (flat 18% interim estimate).
    """
    from src.processor.metrics import MetricsEngine

    VALIDATOR_TAKE_RATE = 0.18  # Interim flat estimate (real is per-validator)

    staking_ranks = []
    for netuid, metrics in all_metrics.items():
        data = metrics.get("data", {})
        vl = data.get("validator_landscape", {})
        roi = data.get("roi_estimate", {})

        alpha_price = _safe_float(roi.get("alpha_tao_rate", 0.0))
        pool_tao = _safe_float(roi.get("pool_tao_liquidity", 0.0))
        total_stake = _safe_float(vl.get("total_validator_stake", 0.0))
        validators = vl.get("active_validators", 0)
        net_yield = _safe_float(vl.get("net_tao_yield_per_validator_per_day", 0.0))

        if validators == 0 or alpha_price <= 0 or total_stake <= 0:
            continue

        # Total daily validator emission in TAO (after take rate)
        total_daily_tao = net_yield * validators * (1.0 - VALIDATOR_TAKE_RATE)

        # Yield per unit of stake
        yield_per_stake = total_daily_tao / total_stake
        apy = yield_per_stake * 365 * 100

        # Entry slippage for 10 TAO using actual pool liquidity
        entry_slippage = MetricsEngine._estimate_slippage(
            10.0 / alpha_price if alpha_price > 0 else 0,
            alpha_price, pool_tao) if pool_tao > 0 else 0.0

        # Break-even: how much can alpha drop annually before you lose money
        break_even = apy / 100.0

        staking_ranks.append({
            "netuid": netuid,
            "net_apy_percent": round(apy, 2),
            "daily_tao_per_10_staked": round(yield_per_stake * 10, 6),
            "total_validator_stake": round(total_stake, 2),
            "active_validators": validators,
            "alpha_price": alpha_price,
            "concentrated": vl.get("concentrated", False),
            "top_1_stake_share": round(_safe_float(vl.get("top_1_stake_share", 0)), 4),
            "break_even_alpha_depreciation": round(break_even, 4),
            "entry_slippage_10tao": round(entry_slippage, 6),
        })

    staking_ranks.sort(key=lambda r: r["net_apy_percent"], reverse=True)
    return staking_ranks


def _detect_new_subnets(current_subnets: list[int]) -> list[int]:
    """Detect subnets that are new (not in previous active list)."""
    previous = _state_manager.get_previous_active_subnets()
    return [n for n in current_subnets if n not in previous]


# ---------------------------------------------------------------------------
# Agent-consumable files (AD18)
# ---------------------------------------------------------------------------


def _enrich_rankings_for_site(rankings: list[dict], all_metrics: dict[int, dict]) -> list[dict]:
    """Enrich ranking entries with profile fields needed by index.html template.

    Adds name, category, mining_style, taoflow_status from DynamoDB profiles
    and derived metrics. Missing fields default to empty string (template handles gracefully).
    """
    # Build lookup of taoflow_status from derived metrics
    taoflow_map = {}
    for netuid, metrics in all_metrics.items():
        status = metrics.get("data", {}).get("taoflow_health", {}).get("status", "")
        taoflow_map[netuid] = status

    # Batch-read profiles from DynamoDB
    profiles = _state_manager.scan_basic_profiles()

    enriched = []
    for r in rankings:
        entry = dict(r)
        netuid = r["netuid"]
        profile = profiles.get(netuid, {})
        entry["name"] = profile.get("name", "")
        entry["category"] = profile.get("category", "")
        entry["mining_style"] = profile.get("mining_style", "")
        entry["taoflow_status"] = taoflow_map.get(netuid, "")
        enriched.append(entry)
    return enriched


# ---------------------------------------------------------------------------
# Conformance Phase A: Inline Post-Conditions
# ---------------------------------------------------------------------------


def _verify_outputs(rankings: list, briefing: dict,
                    all_metrics: dict, date: str) -> None:
    """Verify output quality after generation. Logs findings, never blocks.

    Checks:
    1. Rankings count matches metrics count
    2. No NaN/None in critical ranking fields
    3. Rankings sorted descending by score
    4. Briefing date matches expected date
    5. At least some subnets have source_block > 0
    """
    import math
    findings: list[dict] = []

    # Check 1: Rankings count == metrics count
    if len(rankings) != len(all_metrics):
        findings.append({
            "check": "rankings_count_mismatch",
            "severity": "warning",
            "expected": len(all_metrics),
            "actual": len(rankings),
            "message": f"Rankings has {len(rankings)} entries but {len(all_metrics)} subnets have metrics",
        })

    # Check 2: No NaN/None in critical fields
    critical_fields = ["netuid", "attractiveness_score", "net_tao_yield"]
    for i, entry in enumerate(rankings):
        for field in critical_fields:
            val = entry.get(field)
            if val is None:
                findings.append({
                    "check": "null_critical_field",
                    "severity": "error",
                    "field": field, "rank_position": i,
                    "message": f"Rank #{i} has None for {field}",
                })
            elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                findings.append({
                    "check": "nan_critical_field",
                    "severity": "error",
                    "field": field, "rank_position": i,
                    "message": f"Rank #{i} has {val} for {field}",
                })

    # Check 3: Rankings sorted descending
    for i in range(1, len(rankings)):
        if rankings[i].get("attractiveness_score", 0) > rankings[i - 1].get("attractiveness_score", 0):
            findings.append({
                "check": "rankings_not_sorted",
                "severity": "error",
                "position": i,
                "message": f"Rank #{i} score {rankings[i]['attractiveness_score']:.4f} > "
                           f"rank #{i-1} score {rankings[i-1]['attractiveness_score']:.4f}",
            })
            break  # One violation is enough

    # Check 4: Briefing date matches
    briefing_date = briefing.get("date", "")
    if briefing_date != date:
        findings.append({
            "check": "briefing_date_mismatch",
            "severity": "warning",
            "expected": date, "actual": briefing_date,
            "message": f"Briefing date '{briefing_date}' != expected '{date}'",
        })

    # Check 5: At least some subnets have source_block > 0
    blocks_found = sum(
        1 for m in all_metrics.values()
        if m.get("metadata", {}).get("source_block_number", 0) > 0
    )
    if blocks_found == 0 and len(all_metrics) > 0:
        findings.append({
            "check": "no_source_blocks",
            "severity": "warning",
            "message": "No subnets have source_block_number > 0 in metadata",
        })

    # Log findings as structured JSON
    if findings:
        logger.warning(json.dumps({
            "conformance": "post_condition_check",
            "date": date,
            "findings_count": len(findings),
            "findings": findings,
        }))
    else:
        logger.info(json.dumps({
            "conformance": "post_condition_check",
            "date": date,
            "status": "all_passed",
            "rankings_count": len(rankings),
        }))


def _upload_agent_files(rankings: list, briefing: dict,
                        all_metrics: dict, date: str) -> None:
    """Upload llms.txt, metadata.json, rankings.json, and HTML site to site bucket."""
    if not _config.is_aws:
        return

    site_bucket = os.environ.get("SITE_BUCKET_NAME", "")
    if not site_bucket:
        return

    try:
        s3 = boto3.client("s3", region_name=_config.region)
        now = datetime.now(timezone.utc).isoformat()

        # llms.txt — machine-readable index for AI agents
        llms_txt = (
            "# TAO Mining Intelligence\n"
            "> Bittensor subnet mining/validating metrics.\n"
            "> Data refreshes per-subnet every 20-240 minutes (tempo-based).\n"
            "> No subnet older than 4 hours.\n\n"
            "## Endpoints\n"
            "- /data/rankings.json — Subnet rankings sorted by attractiveness\n"
            "- /data/briefing.json — Latest daily briefing and alerts\n"
            "- /data/metadata.json — Per-subnet freshness timestamps\n"
            "- /index.html — Human-readable dashboard\n"
            "- /rankings.html — Sortable rankings table\n"
            "- /briefing.html — Daily briefing page\n"
        )
        s3.put_object(Bucket=site_bucket, Key="llms.txt",
                      Body=llms_txt.encode(), ContentType="text/plain")

        # metadata.json — per-subnet freshness
        subnet_freshness = {}
        for netuid, metrics in all_metrics.items():
            meta = metrics.get("metadata", {})
            subnet_freshness[str(netuid)] = {
                "processed_at": meta.get("processed_at", meta.get("computation_timestamp", "")),
                "source_block": meta.get("source_block_number", 0),
            }

        metadata = {
            "generated_at": now,
            "subnets_count": len(all_metrics),
            "subnets": subnet_freshness,
        }
        s3.put_object(Bucket=site_bucket, Key="data/metadata.json",
                      Body=json.dumps(metadata).encode(), ContentType="application/json")

        # rankings.json — current rankings
        s3.put_object(Bucket=site_bucket, Key="data/rankings.json",
                      Body=json.dumps(rankings).encode(), ContentType="application/json")

        # briefing.json — latest briefing
        s3.put_object(Bucket=site_bucket, Key="data/briefing.json",
                      Body=json.dumps(briefing).encode(), ContentType="application/json")

        # HTML site generation
        try:
            from src.site_generator.generator import SiteGenerator
            gen = SiteGenerator()
            enriched = _enrich_rankings_for_site(rankings, all_metrics)
            index_html = gen.generate_index(enriched, last_updated=now)
            rankings_html = gen.generate_rankings_page(rankings)
            briefing_html = gen.generate_briefing_page(briefing)

            s3.put_object(Bucket=site_bucket, Key="index.html",
                          Body=index_html.encode(), ContentType="text/html")
            s3.put_object(Bucket=site_bucket, Key="rankings.html",
                          Body=rankings_html.encode(), ContentType="text/html")
            s3.put_object(Bucket=site_bucket, Key="briefing.html",
                          Body=briefing_html.encode(), ContentType="text/html")
        except Exception as e:
            logger.warning(f"HTML site generation failed (non-critical): {e}")

        # Staking rankings
        try:
            staking_rankings = _generate_staking_rankings(all_metrics)
            s3.put_object(Bucket=site_bucket, Key="data/staking_rankings.json",
                          Body=json.dumps(staking_rankings).encode(),
                          ContentType="application/json")
        except Exception as e:
            logger.warning(f"Staking rankings generation failed (non-critical): {e}")

    except Exception as e:
        logger.warning(f"Failed to upload agent files to site bucket: {e}")
