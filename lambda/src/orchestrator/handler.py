"""Orchestrator Lambda — lightweight dispatcher for subnet collection.

Triggered by EventBridge (configurable frequency, default hourly).
Discovers active subnets, claims the cycle, and publishes one SQS message
per subnet to the collection queue. Each message triggers a SubnetCollector.

This Lambda is fast (<30s): no metagraph fetching, no heavy SDK calls.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from bittensor import AsyncSubtensor

from src.config import PipelineConfig, get_config
from src.instrumentation import init_tracing, instrument
from src.state.state_manager import StateManager
from src.storage.storage_layer import StorageLayer

logger = logging.getLogger("tao-pipeline")

_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None
_storage: Optional[StorageLayer] = None
_sqs_client: Optional[Any] = None


def _init_clients() -> None:
    global _config, _state_manager, _storage, _sqs_client
    if _config is not None:
        return
    _config = get_config()
    _state_manager = StateManager(_config)
    _storage = StorageLayer(_config)
    if _config.is_aws:
        _sqs_client = boto3.client("sqs", region_name=_config.region)


def handle(event: dict, context: Any) -> dict:
    """Lambda entry point. Discovers subnets and dispatches collection messages."""
    return asyncio.run(_async_handle(event, context))


async def _async_handle(event: dict, context: Any) -> dict:
    _init_clients()

    cycle_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trace_id = init_tracing(cycle_id)

    with instrument("orchestrator", "handle", cycle_id=cycle_id) as ctx:
        # Discover active subnets
        netuids = await _discover_subnets()
        if not netuids:
            return {"cycle_id": cycle_id, "status": "no_subnets", "subnets_dispatched": 0}

        # Claim cycle (idempotency)
        claimed = _state_manager.claim_cycle(cycle_id, subnets_total=len(netuids))
        if not claimed:
            return {"cycle_id": cycle_id, "status": "duplicate", "subnets_dispatched": 0}

        # Update active subnets list
        _state_manager.update_active_subnets(netuids)

        # Publish one collection message per subnet
        published = _publish_collection_messages(netuids, cycle_id, trace_id)

        ctx["subnets_total"] = len(netuids)
        ctx["messages_published"] = published

        return {
            "cycle_id": cycle_id,
            "trace_id": trace_id,
            "status": "dispatched",
            "subnets_total": len(netuids),
            "subnets_dispatched": published,
        }


async def _discover_subnets() -> list[int]:
    """Discover all active subnets from the Bittensor network."""
    with instrument("orchestrator", "discover_subnets") as ctx:
        async with AsyncSubtensor() as sub:
            netuids = await sub.get_all_subnets_netuid()
        ctx["subnet_count"] = len(netuids)
        return sorted(netuids)


def _publish_collection_messages(netuids: list[int], cycle_id: str, trace_id: str) -> int:
    """Publish one SQS message per subnet to the collection queue."""
    queue_url = os.environ.get("COLLECTION_QUEUE_URL", "")
    if not queue_url or not _sqs_client:
        logger.info("No collection queue URL — skipping dispatch")
        return 0

    published = 0
    date = cycle_id  # cycle_id is the ISO date

    for netuid in netuids:
        message = {
            "netuid": netuid,
            "date": date,
            "cycle_id": cycle_id,
            "trace_id": trace_id,
        }
        try:
            _sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message),
            )
            published += 1
        except Exception as e:
            logger.error(f"Failed to publish collection message for netuid={netuid}: {e}")

    return published
