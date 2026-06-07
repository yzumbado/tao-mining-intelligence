"""Strategizer Lambda — produces actionable allocation recommendations.

Invoked manually or triggered after Finalizer completes.
Reads: user profile (DynamoDB), rankings (S3), research profiles (DynamoDB),
       market observer cache (DynamoDB).
Writes: strategy/latest.json + strategy/{date}/{timestamp}.json to S3.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import boto3

from src.config import get_config, PipelineConfig
from src.state.state_manager import StateManager
from src.storage.storage_layer import StorageLayer
from src.instrumentation import instrument
from src.strategizer.scoring import (
    filter_opportunities,
    score_opportunity,
    evaluate_exits,
    DEFAULT_WEIGHTS,
)
from src.strategizer.optimizer import optimize_portfolio

logger = logging.getLogger("tao-pipeline")

# Module-level cold-start cache
_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None
_storage: Optional[StorageLayer] = None

# Default user profile (validator-only, conservative)
DEFAULT_USER_PROFILE: dict = {
    "hardware": [],
    "tao_available_stake": 100.0,
    "tao_available_registration": 1.0,
    "risk_tolerance": "conservative",
    "max_positions": 3,
    "prefer_passive": True,
    "excluded_subnets": [],
    "min_pool_liquidity_tao": 500.0,
}

# Default TAO/USD price fallback (used if Market Observer unavailable)
DEFAULT_TAO_USD_PRICE = 260.0


def _init_clients() -> None:
    global _config, _state_manager, _storage
    if _config is not None:
        return
    _config = get_config()
    _state_manager = StateManager(_config)
    _storage = StorageLayer(_config)


def handle(event: dict, context: Any) -> dict:
    """Lambda entry point. Produces strategy from current data."""
    _init_clients()

    with instrument("strategizer", "generate_strategy"):
        now = datetime.now(timezone.utc)

        # 1. Load user profile
        profile = _load_user_profile()
        profile_hash = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:16]

        # 2. Load rankings
        rankings = _load_rankings()
        if not rankings:
            logger.error("No rankings available — cannot generate strategy")
            return {"error": "no_rankings", "generated_at": now.isoformat()}

        # 3. Load research profiles
        research_profiles = _load_research_profiles(rankings)

        # 4. Get TAO/USD price from Market Observer
        tao_usd_price = _get_tao_usd_price()

        # 5. Load thresholds (includes strategy weights)
        thresholds = _state_manager.get_thresholds()
        # Merge strategy-specific defaults
        for k, v in DEFAULT_WEIGHTS.items():
            thresholds.setdefault(k, v)

        # 6. Filter
        survivors, filter_reasons = filter_opportunities(rankings, research_profiles, profile)
        logger.info(f"Filtered {len(rankings)} → {len(survivors)} opportunities. Reasons: {filter_reasons}")

        # 7. Score each survivor
        max_yield = max((r.get("net_tao_yield", 0.0) for r in survivors), default=1.0)
        max_entry_cost = max(1.0, tao_usd_price / 30.0) if tao_usd_price > 0 else 1.0  # Normalize efficiency

        scored = []
        for r in survivors:
            research = research_profiles.get(r["netuid"], {})
            result = score_opportunity(r, research, profile, max_yield, max_entry_cost, tao_usd_price, thresholds)
            scored.append(result)

        # Sort by fitness descending
        scored.sort(key=lambda x: x["fitness_score"], reverse=True)

        # 8. Portfolio optimize
        portfolio = optimize_portfolio(scored, profile, thresholds)

        # 9. Evaluate exits for active positions
        active_positions = _load_active_positions()
        exit_recommendations = evaluate_exits(active_positions, rankings, thresholds) if active_positions else []

        # 10. Build output
        strategy = {
            "generated_at": now.isoformat(),
            "profile_hash": f"sha256:{profile_hash}",
            "rankings_count": len(rankings),
            "total_opportunities_evaluated": len(rankings),
            "total_filtered": len(rankings) - len(survivors),
            "filter_reasons_summary": filter_reasons,
            "tao_usd_price_used": tao_usd_price,
            "recommendations": portfolio["recommendations"],
            "do_nothing_reason": portfolio["do_nothing_reason"],
            "portfolio_summary": portfolio["portfolio_summary"],
            "exit_recommendations": exit_recommendations,
            "user_profile_summary": {
                "hardware_count": len(profile.get("hardware", [])),
                "tao_available_stake": profile.get("tao_available_stake", 0),
                "risk_tolerance": profile.get("risk_tolerance", "conservative"),
                "max_positions": profile.get("max_positions", 3),
                "prefer_passive": profile.get("prefer_passive", True),
            },
        }

        # 11. Store
        _store_strategy(strategy, now)

        logger.info(
            f"Strategy generated: {len(portfolio['recommendations'])} recommendations, "
            f"expected {portfolio['portfolio_summary']['expected_daily_tao_total']:.2f}τ/day"
        )

        return {
            "status": "success",
            "generated_at": now.isoformat(),
            "recommendations_count": len(portfolio["recommendations"]),
            "expected_daily_tao": portfolio["portfolio_summary"]["expected_daily_tao_total"],
        }


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_user_profile() -> dict:
    """Load user profile from DynamoDB, fall back to defaults."""
    try:
        resp = _state_manager._table.get_item(Key={"PK": "CONFIG", "SK": "USER_PROFILE"})
        item = resp.get("Item", {})
        if item:
            # Merge with defaults for any missing keys
            profile = dict(DEFAULT_USER_PROFILE)
            for k in DEFAULT_USER_PROFILE:
                if k in item:
                    profile[k] = item[k]
            # Convert Decimal types
            profile["tao_available_stake"] = float(profile["tao_available_stake"])
            profile["tao_available_registration"] = float(profile["tao_available_registration"])
            profile["min_pool_liquidity_tao"] = float(profile["min_pool_liquidity_tao"])
            profile["max_positions"] = int(profile["max_positions"])
            logger.info("Loaded user profile from DynamoDB")
            return profile
    except Exception as e:
        logger.warning(f"Failed to load user profile: {e}. Using defaults.")

    logger.warning("No user profile found — using defaults (validator-only, conservative)")
    return dict(DEFAULT_USER_PROFILE)


def _load_rankings() -> list[dict]:
    """Load current rankings from S3 (site bucket — always current)."""
    import os
    try:
        s3 = boto3.client("s3", region_name=_config.region)
        site_bucket = os.environ.get("SITE_BUCKET_NAME", "")
        if site_bucket:
            resp = s3.get_object(Bucket=site_bucket, Key="data/rankings.json")
            data = json.loads(resp["Body"].read())
        else:
            # Fallback: read from data bucket (date-keyed)
            data = _storage.read_snapshot("derived/rankings/latest.json")
        if isinstance(data, list):
            return data
        return data.get("rankings", data) if isinstance(data, dict) else []
    except Exception as e:
        logger.error(f"Failed to load rankings: {e}")
        return []


def _load_research_profiles(rankings: list[dict]) -> dict[int, dict]:
    """Load research profiles for all ranked subnets."""
    profiles = {}
    for r in rankings:
        netuid = r["netuid"]
        try:
            profile = _state_manager.get_research_profile(netuid)
            if profile:
                profiles[netuid] = profile
        except Exception:
            pass  # No research data — subnet will be scored with no research context
    return profiles


def _load_active_positions() -> list[dict]:
    """Load active positions from DynamoDB CONFIG|ACTIVE_POSITIONS."""
    try:
        resp = _state_manager._table.get_item(Key={"PK": "CONFIG", "SK": "ACTIVE_POSITIONS"})
        item = resp.get("Item", {})
        return item.get("positions", [])
    except Exception as e:
        logger.debug(f"No active positions found: {e}")
        return []


def _get_tao_usd_price() -> float:
    """Get current TAO/USD price from Market Observer or fallback."""
    try:
        # Market Observer stores TAO price at CACHE|TAO_PRICE
        resp = _state_manager._table.get_item(Key={"PK": "CACHE", "SK": "TAO_PRICE"})
        item = resp.get("Item", {})
        if "price_usd" in item:
            return float(item["price_usd"])
    except Exception:
        pass

    # Fallback: use thresholds or default
    logger.warning(f"TAO/USD price unavailable — using fallback ${DEFAULT_TAO_USD_PRICE}")
    return DEFAULT_TAO_USD_PRICE


def _store_strategy(strategy: dict, now: datetime) -> None:
    """Store strategy to S3 (latest + historical)."""
    date_str = now.strftime("%Y-%m-%d")
    ts_str = now.strftime("%Y-%m-%dT%H-%M-%S")

    # Latest (overwritten each run)
    _storage.store_snapshot("derived/strategy/latest.json", strategy)

    # Historical
    _storage.store_snapshot(f"derived/strategy/{date_str}/{ts_str}.json", strategy)

    logger.info(f"Strategy stored: derived/strategy/latest.json + {date_str}/{ts_str}.json")
