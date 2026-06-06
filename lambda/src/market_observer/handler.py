"""Market Observer Lambda — high-frequency cache + time-series writer.

Runs every 10 minutes via EventBridge. For each active subnet:
1. Queries chain via raw Substrate RPC (no SDK needed)
2. Writes latest market data to DynamoDB cache (CACHE#{netuid}|MARKET_DATA)
3. Appends observation to DynamoDB history (HISTORY#{netuid}|{timestamp})

The cache serves other Lambdas needing current price/pool data.
The history enables observed APY calculation (vs single-point extrapolation).
"""

import json
import logging
import struct
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import boto3

from src.config import get_config, PipelineConfig
from src.state.state_manager import StateManager
from src.instrumentation import instrument

logger = logging.getLogger("tao-pipeline")

RPC_ENDPOINT = "https://entrypoint-finney.opentensor.ai"

_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None
_cw_client = None


def _init_clients() -> None:
    global _config, _state_manager, _cw_client
    if _config is not None:
        return
    _config = get_config()
    _state_manager = StateManager(_config)
    if _config.is_aws:
        _cw_client = boto3.client("cloudwatch", region_name=_config.region)


def handle(event: dict, context: Any) -> dict:
    """Lambda entry point. Observes market data for all active subnets."""
    _init_clients()

    with instrument("market_observer", "handle") as ctx:
        active_subnets = _state_manager.get_active_subnets()
        if not active_subnets:
            return {"status": "no_subnets"}

        block = _get_current_block()
        if not block:
            return {"status": "error", "error": "cannot reach chain"}

        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        ttl_epoch = int(now.timestamp()) + (30 * 86400)  # 30 days

        observed = 0
        errors = 0

        for netuid in active_subnets:
            try:
                price = _get_alpha_price(netuid)
                pool_tao = _get_pool_tao(netuid)

                if price is None or pool_tao is None:
                    errors += 1
                    if observed < 3:  # Log first few failures for diagnostics
                        logger.info(f"SN{netuid}: price={price}, pool_tao={pool_tao}")
                    continue

                pool_alpha = pool_tao / price if price > 0 else 0.0

                # Write cache (latest — overwritten each run)
                _state_manager.write_market_cache(netuid, {
                    "alpha_price": price,
                    "pool_tao": pool_tao,
                    "pool_alpha": pool_alpha,
                    "block": block,
                    "cached_at": timestamp,
                })

                # Append history (time-series — new item per observation)
                _state_manager.append_market_history(netuid, timestamp, {
                    "alpha_price": price,
                    "pool_tao": pool_tao,
                    "pool_alpha": pool_alpha,
                    "block": block,
                }, ttl_epoch)

                observed += 1

            except Exception as e:
                logger.warning(f"SN{netuid} observation failed: {str(e)[:100]}")
                errors += 1

            # Small delay to avoid overwhelming the public RPC endpoint
            time.sleep(0.2)

        # Publish CloudWatch metric
        _publish_metric(observed)

        ctx["observed"] = observed
        ctx["errors"] = errors
        ctx["block"] = block

        return {
            "status": "complete",
            "observed": observed,
            "errors": errors,
            "block": block,
        }


# ---------------------------------------------------------------------------
# RPC Calls (raw Substrate, no SDK)
# ---------------------------------------------------------------------------


def _rpc_call(method: str, params: list = None) -> Optional[dict]:
    """Make a raw Substrate JSON-RPC call."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": method, "params": params or []
    }).encode()
    req = urllib.request.Request(
        RPC_ENDPOINT, data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError):
        return None


def _get_current_block() -> Optional[int]:
    """Get current block number."""
    result = _rpc_call("chain_getHeader")
    if result and "result" in result:
        return int(result["result"]["number"], 16)
    return None


def _get_alpha_price(netuid: int) -> Optional[float]:
    """Get alpha price via SwapRuntimeApi."""
    params_hex = struct.pack("<H", netuid).hex()
    result = _rpc_call("state_call", ["SwapRuntimeApi_current_alpha_price", "0x" + params_hex])
    if result and result.get("result"):
        raw = result["result"]
        if raw and raw != "0x":
            data = bytes.fromhex(raw[2:])
            if len(data) >= 8:
                return int.from_bytes(data[:8], "little") / 1e9
    return None


def _get_pool_tao(netuid: int) -> Optional[float]:
    """Get pool TAO liquidity via SubnetTAO storage query."""
    try:
        import xxhash

        def twox_128(data: bytes) -> bytes:
            return (xxhash.xxh64(data, seed=0).intdigest().to_bytes(8, "little") +
                    xxhash.xxh64(data, seed=1).intdigest().to_bytes(8, "little"))

        netuid_bytes = struct.pack("<H", netuid)
        # SubnetTAO uses Identity hasher (raw key bytes, no hashing)
        storage_key = "0x" + (
            twox_128(b"SubtensorModule") +
            twox_128(b"SubnetTAO") +
            netuid_bytes
        ).hex()

        result = _rpc_call("state_getStorage", [storage_key])
        if result and result.get("result"):
            raw = result["result"]
            if raw and raw != "0x":
                data = bytes.fromhex(raw[2:])
                return int.from_bytes(data, "little") / 1e9
    except ImportError:
        pass
    return None


# ---------------------------------------------------------------------------
# CloudWatch
# ---------------------------------------------------------------------------


def _publish_metric(observed: int) -> None:
    """Publish SubnetsObserved metric for staleness alarming."""
    if not _cw_client:
        return
    try:
        _cw_client.put_metric_data(
            Namespace="TaoPipeline",
            MetricData=[{
                "MetricName": "MarketObserverSubnetsObserved",
                "Value": observed,
                "Unit": "Count",
            }],
        )
    except Exception:
        pass
