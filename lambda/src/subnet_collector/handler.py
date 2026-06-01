"""SubnetCollector Lambda — collects all data for ONE subnet per invocation.

Triggered by SQS (collection queue). Collects metagraph, hyperparameters,
alpha price, and registration cost for a single subnet. Stores raw snapshots
to S3 and publishes a processing message to the processing queue.

Design: No circuit breaker needed — SQS retry (3 attempts → DLQ) handles failures.
No timeout management — each invocation takes <30s for one subnet.
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
from src.instrumentation import set_trace_id, instrument
from src.state.state_manager import StateManager
from src.storage.storage_layer import StorageLayer
from src.validation import validate_metagraph

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
    """Lambda entry point. Collects data for one subnet."""
    return asyncio.run(_async_handle(event, context))


async def _async_handle(event: dict, context: Any) -> dict:
    _init_clients()
    set_trace_id("", "")

    # Parse event — supports both SQS trigger and direct Lambda invoke
    try:
        if "Records" in event:
            # SQS trigger (legacy orchestrator path)
            record = event["Records"][0]
            body = json.loads(record["body"])
        else:
            # Direct invoke (EventBridge Scheduler path)
            body = event
        netuid = body["netuid"]
        date = body.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        cycle_id = body.get("cycle_id", date)
        trace_id = body.get("trace_id", f"subnet-{netuid}-{date}")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse event: {e}")
        return {"status": "error", "error": f"malformed event: {e}"}

    set_trace_id(trace_id, cycle_id)

    with instrument("subnet_collector", "handle", netuid=netuid, cycle_id=cycle_id) as ctx:
        async with AsyncSubtensor() as sub:
            # Collect metagraph
            snapshot = await _collect_metagraph(sub, netuid, date)
            if snapshot is None:
                return {"status": "error", "netuid": netuid, "error": "metagraph collection failed"}

            # Collect supplementary data
            await _collect_hyperparameters(sub, netuid, date)
            await _collect_alpha_price(sub, netuid, date)
            await _collect_registration_cost(sub, netuid, date)

        # Publish processing message
        _publish_processing_message(netuid, date, cycle_id, trace_id)

        ctx["status"] = "complete"
        return {"status": "complete", "netuid": netuid, "cycle_id": cycle_id}


async def _collect_metagraph(sub, netuid: int, date: str) -> Optional[dict]:
    """Collect and store metagraph for one subnet."""
    with instrument("subnet_collector", "collect_metagraph", netuid=netuid):
        try:
            mg = await sub.metagraph(netuid=netuid)
        except Exception as e:
            logger.error(f"Metagraph fetch failed for netuid={netuid}: {e}")
            return None

        neurons = []
        for i in range(int(mg.n)):
            neurons.append({
                "uid": i,
                "hotkey": mg.hotkeys[i],
                "coldkey": mg.coldkeys[i],
                "stake": float(mg.S[i]),
                "incentive": float(mg.I[i]),
                "emission": float(mg.E[i]),
                "consensus": float(mg.C[i]),
                "dividends": float(mg.D[i]),
                "validator_trust": float(mg.Tv[i]),
                "active": bool(mg.active[i]),
                "alpha_stake": float(mg.AS[i]),
                "total_stake": float(mg.TS[i]),
                "block_at_registration": int(mg.block_at_registration[i]),
                "validator_permit": bool(mg.validator_permit[i]),
            })

        snapshot = {
            "metadata": {
                "netuid": netuid,
                "cycle_id": date,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "source_block_number": int(mg.block),
                "neuron_count": int(mg.n),
                "num_uids": int(mg.num_uids),
                "max_uids": int(mg.max_uids),
                "blocks_since_last_step": int(mg.blocks_since_last_step),
            },
            "data": {"neurons": neurons},
        }

        is_valid, errors = validate_metagraph(snapshot)
        if not is_valid:
            # Hard reject only for truly corrupt data (NaN/Inf, empty)
            hard_errors = [e for e in errors if "NaN/Inf" in e or "Empty" in e]
            if hard_errors:
                logger.error(f"Corrupt data for netuid={netuid}: {hard_errors}")
                return None
            # Soft warnings — data is usable but non-standard
            logger.warning(f"Validation warnings for netuid={netuid}: {errors}")
            snapshot["metadata"]["data_quality"] = "degraded"
            snapshot["metadata"]["quality_warnings"] = errors
        else:
            snapshot["metadata"]["data_quality"] = "ok"

        path = _storage.get_date_path("raw/metagraph", date, netuid)
        _storage.store_snapshot(path, snapshot)
        return snapshot


async def _collect_hyperparameters(sub, netuid: int, date: str) -> None:
    """Collect and store hyperparameters for one subnet."""
    try:
        hp = await sub.get_subnet_hyperparameters(netuid=netuid)
        hp_dict = {attr: getattr(hp, attr) for attr in dir(hp)
                   if not attr.startswith("_") and not callable(getattr(hp, attr))}
        data = {
            "metadata": {"netuid": netuid, "cycle_id": date,
                         "collected_at": datetime.now(timezone.utc).isoformat()},
            "data": hp_dict,
        }
        _storage.store_snapshot(_storage.get_date_path("raw/hyperparameters", date, netuid), data)
    except Exception as e:
        logger.warning(f"Hyperparameters failed for netuid={netuid}: {e}")


async def _collect_alpha_price(sub, netuid: int, date: str) -> None:
    """Collect and store alpha price, pool liquidity, and root proportion inputs."""
    try:
        alpha_price = float(await sub.get_subnet_price(netuid=netuid))
        pool_tao_rao = await sub.substrate.query(
            module="SubtensorModule", storage_function="SubnetTAO", params=[netuid])
        pool_alpha_rao = await sub.substrate.query(
            module="SubtensorModule", storage_function="SubnetAlphaIn", params=[netuid])
        alpha_out_rao = await sub.substrate.query(
            module="SubtensorModule", storage_function="SubnetAlphaOut", params=[netuid])
        tao_weight_raw = await sub.substrate.query(
            module="SubtensorModule", storage_function="TaoWeight", params=[])
        tao_root_rao = await sub.substrate.query(
            module="SubtensorModule", storage_function="SubnetTAO", params=[0])

        tao_weight = int(tao_weight_raw) / 18446744073709551615
        alpha_supply = (int(pool_alpha_rao) + int(alpha_out_rao)) / 1e9
        tao_root = int(tao_root_rao) / 1e9
        root_proportion = ((tao_root * tao_weight) /
                           (tao_root * tao_weight + alpha_supply)) if alpha_supply > 0 else 1.0

        data = {
            "metadata": {"netuid": netuid, "cycle_id": date,
                         "collected_at": datetime.now(timezone.utc).isoformat()},
            "data": {
                "netuid": netuid,
                "alpha_tao_price": alpha_price,
                "pool_tao_liquidity": int(pool_tao_rao) / 1e9,
                "pool_alpha_liquidity": int(pool_alpha_rao) / 1e9,
                "alpha_out": int(alpha_out_rao) / 1e9,
                "alpha_supply": alpha_supply,
                "tao_weight": tao_weight,
                "root_proportion": root_proportion,
            },
        }
        _storage.store_snapshot(_storage.get_date_path("raw/alpha-prices", date, netuid), data)
    except Exception as e:
        logger.warning(f"Alpha price failed for netuid={netuid}: {e}")


async def _collect_registration_cost(sub, netuid: int, date: str) -> None:
    """Collect and store registration cost for one subnet."""
    try:
        burn_rao = await sub.substrate.query(
            module="SubtensorModule", storage_function="Burn", params=[netuid])
        data = {
            "metadata": {"netuid": netuid, "cycle_id": date,
                         "collected_at": datetime.now(timezone.utc).isoformat()},
            "data": {
                "netuid": netuid,
                "registration_cost_rao": int(burn_rao),
                "registration_cost_tao": int(burn_rao) / 1e9,
            },
        }
        _storage.store_snapshot(_storage.get_date_path("raw/registration-costs", date, netuid), data)
    except Exception as e:
        logger.warning(f"Registration cost failed for netuid={netuid}: {e}")


def _publish_processing_message(netuid: int, date: str, cycle_id: str, trace_id: str) -> None:
    """Publish message to processing queue for the Processor Lambda."""
    queue_url = os.environ.get("PROCESS_QUEUE_URL", "")
    if not queue_url or not _sqs_client:
        return
    try:
        _sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "netuid": netuid, "date": date,
                "cycle_id": cycle_id, "trace_id": trace_id,
            }),
        )
    except Exception as e:
        logger.error(f"Failed to publish processing message for netuid={netuid}: {e}")
