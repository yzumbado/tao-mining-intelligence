"""Discovery Lambda — hourly safety net for independent subnet refresh.

Responsibilities:
1. Query chain for active subnets (detect new ones)
2. Check each subnet's profile for staleness (processed_at vs now)
3. Create EventBridge schedules for new or stale subnets

This is NOT an orchestrator — it doesn't manage running subnets.
It only seeds loops that haven't started or have died.
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Optional

import boto3

from src.config import PipelineConfig, get_config
from src.instrumentation import init_tracing, instrument
from src.state.state_manager import StateManager

logger = logging.getLogger("tao-pipeline")

_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None


def _init_clients() -> None:
    global _config, _state_manager
    if _config is not None:
        return
    _config = get_config()
    _state_manager = StateManager(_config)


def handle(event: dict, context: Any) -> dict:
    """Lambda entry point. Discovers new/stale subnets and seeds their schedules."""
    _init_clients()
    init_tracing("discovery")

    with instrument("discovery", "handle") as ctx:
        # Get refresh policy
        policy = _state_manager.get_refresh_policy()
        max_staleness_hours = policy["max_staleness_hours"]

        # Discover active subnets from chain
        netuids = asyncio.run(_discover_subnets())
        ctx["active_subnets"] = len(netuids)

        # Update active subnets list
        _state_manager.update_active_subnets(netuids)

        # Check each subnet's freshness
        stale = []
        new = []
        for netuid in netuids:
            profile = _get_profile(netuid)
            if profile is None:
                new.append(netuid)
            elif _is_stale(profile, max_staleness_hours):
                stale.append(netuid)

        # Seed schedules for new and stale subnets
        seeded = 0
        for netuid in new + stale:
            # Stagger to avoid thundering herd (random 0-60s delay)
            delay = random.randint(0, 60)
            if _create_schedule(netuid, delay):
                seeded += 1

        ctx["new_subnets"] = len(new)
        ctx["stale_subnets"] = len(stale)
        ctx["seeded"] = seeded

        return {
            "status": "complete",
            "active_subnets": len(netuids),
            "new_subnets": len(new),
            "stale_subnets": len(stale),
            "seeded": seeded,
        }


async def _discover_subnets() -> list[int]:
    """Query chain for active subnet netuids."""
    try:
        from bittensor import AsyncSubtensor
        async with AsyncSubtensor() as sub:
            netuids = await sub.get_all_subnets_netuid()
            return [int(n) for n in netuids]
    except Exception as e:
        logger.error(f"Subnet discovery failed: {e}")
        # Fall back to stored list
        return _state_manager.get_active_subnets()


def _get_profile(netuid: int) -> Optional[dict]:
    """Read PROFILE#basic for a subnet."""
    try:
        resp = _state_manager._table.get_item(
            Key={"PK": f"SUBNET#{netuid}", "SK": "PROFILE#basic"}
        )
        return resp.get("Item")
    except Exception:
        return None


def _is_stale(profile: dict, max_staleness_hours: float) -> bool:
    """Check if a profile is older than max_staleness_hours."""
    processed_at = profile.get("processed_at") or profile.get("last_updated")
    if not processed_at:
        return True
    try:
        ts = datetime.fromisoformat(str(processed_at))
        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        return age_hours > max_staleness_hours
    except (ValueError, TypeError):
        return True


def _create_schedule(netuid: int, delay_seconds: int = 0) -> bool:
    """Create a one-time EventBridge schedule to invoke SubnetCollector."""
    try:
        scheduler = boto3.client("scheduler", region_name=_config.region)
        collector_arn = os.environ.get("SUBNET_COLLECTOR_ARN", "")
        scheduler_role_arn = os.environ.get("SCHEDULER_ROLE_ARN", "")

        if not collector_arn or not scheduler_role_arn:
            logger.warning("SUBNET_COLLECTOR_ARN or SCHEDULER_ROLE_ARN not set")
            return False

        from datetime import timedelta
        run_time = datetime.now(timezone.utc) + timedelta(seconds=max(60, delay_seconds))

        scheduler.create_schedule(
            Name=f"tao-subnet-{netuid}",
            GroupName="default",
            ScheduleExpression=f"at({run_time.strftime('%Y-%m-%dT%H:%M:%S')})",
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            Target={
                "Arn": collector_arn,
                "RoleArn": scheduler_role_arn,
                "Input": json.dumps({"netuid": netuid}),
            },
            ActionAfterCompletion="DELETE",
        )
        return True
    except Exception as e:
        # Schedule might already exist (subnet loop is running) — that's fine
        if "ConflictException" in str(type(e).__name__) or "Conflict" in str(e):
            return False
        logger.warning(f"Failed to create schedule for SN{netuid}: {e}")
        return False
