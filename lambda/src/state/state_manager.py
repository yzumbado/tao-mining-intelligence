"""State Manager — DynamoDB state tracking for pipeline FSM.

Implements single-table design with conditional writes for safe state transitions.
Supports PIPELINE_ENV switching between DynamoDB Local and AWS DynamoDB.

DynamoDB PK/SK patterns:
- SUBNET#{netuid} | STATE — pipeline FSM state per subnet
- CONFIG | ACTIVE_SUBNETS — monitored subnet list
- CONFIG | TRACKED_HOTKEYS — hotkey watchlist
- CYCLE#{cycle_id} | STATUS — cycle-level idempotency
- HOTKEY#{ss58} | EARNINGS#{period} — hotkey earnings
- HOTKEY#{ss58} | SNAPSHOT#{date} — daily hotkey position snapshot
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from src.config import PipelineConfig, get_config

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class SubnetState:
    """Current pipeline FSM state for a subnet."""

    netuid: int
    current_status: str = "IDLE"
    cycle_id: str = ""
    retry_count: int = 0
    last_updated: Optional[str] = None
    metadata: dict = field(default_factory=dict)


# =============================================================================
# Decimal Conversion Helpers
# =============================================================================


def _float_to_decimal(obj: Any) -> Any:
    """Recursively convert Python floats to Decimal for DynamoDB writes.

    DynamoDB does not accept Python float types — must use Decimal.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(item) for item in obj]
    return obj


def _decimal_to_float(obj: Any) -> Any:
    """Recursively convert Decimal back to Python float for reads."""
    if isinstance(obj, Decimal):
        # Return int if it's a whole number, else float
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(item) for item in obj]
    return obj


# =============================================================================
# StateManager
# =============================================================================


class StateManager:
    """DynamoDB state tracking for the TAO Mining Intelligence Pipeline.

    Uses single-table design with conditional writes for FSM transitions.
    Supports local (DynamoDB Local) and AWS environments via config.
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """Initialize StateManager with DynamoDB resource.

        Args:
            config: Pipeline configuration. If None, loads from environment.
        """
        self._config = config or get_config()
        self._table_name = self._config.dynamodb.table_name
        self._table = self._get_table()

    def _get_table(self):
        """Create DynamoDB Table resource based on environment config."""
        kwargs = {"region_name": self._config.region}
        if self._config.is_local and self._config.dynamodb.endpoint_url:
            kwargs["endpoint_url"] = self._config.dynamodb.endpoint_url

        dynamodb = boto3.resource("dynamodb", **kwargs)
        return dynamodb.Table(self._table_name)

    # =========================================================================
    # Subnet State Operations
    # =========================================================================

    def get_subnet_state(self, netuid: int) -> SubnetState:
        """Get current pipeline state for a subnet.

        Returns SubnetState with defaults if no state record exists.
        """
        try:
            resp = self._table.get_item(
                Key={"PK": f"SUBNET#{netuid}", "SK": "STATE"}
            )
        except ClientError as e:
            logger.error(f"Failed to get subnet state for netuid={netuid}: {e}")
            return SubnetState(netuid=netuid)

        item = resp.get("Item")
        if not item:
            return SubnetState(netuid=netuid)

        item = _decimal_to_float(item)
        return SubnetState(
            netuid=netuid,
            current_status=item.get("current_status", "IDLE"),
            cycle_id=item.get("cycle_id", ""),
            retry_count=item.get("retry_count", 0),
            last_updated=item.get("last_updated"),
            metadata=item.get("metadata", {}),
        )

    def transition(
        self, netuid: int, from_state: str, to_state: str, metadata: dict = None
    ) -> bool:
        """Atomic state transition with conditional write.

        Uses DynamoDB ConditionExpression to ensure the current state matches
        `from_state` before transitioning to `to_state`. Prevents race conditions.

        Args:
            netuid: Subnet network UID.
            from_state: Expected current state (condition check).
            to_state: Target state to transition to.
            metadata: Optional metadata to store with the state.

        Returns:
            True if transition succeeded, False if conditional check failed.
        """
        now = datetime.now(timezone.utc).isoformat()
        update_expr = "SET current_status = :new_state, last_updated = :ts"
        expr_values: dict[str, Any] = {
            ":new_state": to_state,
            ":expected": from_state,
            ":ts": now,
        }

        if metadata:
            update_expr += ", metadata = :meta"
            expr_values[":meta"] = _float_to_decimal(metadata)

        # If transitioning from IDLE, also set cycle_id from metadata
        if metadata and "cycle_id" in metadata:
            update_expr += ", cycle_id = :cid"
            expr_values[":cid"] = metadata["cycle_id"]

        # Handle retry count
        if to_state == "ERROR_RETRYABLE":
            update_expr += " ADD retry_count :inc"
            expr_values[":inc"] = 1
        elif from_state == "ERROR_RETRYABLE" and to_state in ("COLLECTING", "PROCESSING"):
            # Keep retry_count as-is on retry
            pass
        elif to_state == "IDLE":
            update_expr += ", retry_count = :zero, cycle_id = :empty"
            expr_values[":zero"] = 0
            expr_values[":empty"] = ""

        try:
            self._table.update_item(
                Key={"PK": f"SUBNET#{netuid}", "SK": "STATE"},
                UpdateExpression=update_expr,
                ConditionExpression="current_status = :expected",
                ExpressionAttributeValues=expr_values,
            )
            logger.info(
                f"Subnet {netuid}: {from_state} → {to_state}"
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(
                    f"Subnet {netuid}: transition {from_state} → {to_state} "
                    f"rejected (conditional check failed)"
                )
                return False
            # Throttling, internal errors, etc. — raise so caller can retry
            raise

    def initialize_subnet_state(self, netuid: int) -> None:
        """Initialize a subnet state record if it doesn't exist.

        Creates the initial IDLE state for a subnet. Safe to call multiple times.
        """
        try:
            self._table.put_item(
                Item={
                    "PK": f"SUBNET#{netuid}",
                    "SK": "STATE",
                    "current_status": "IDLE",
                    "retry_count": 0,
                    "cycle_id": "",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "metadata": {},
                },
                ConditionExpression="attribute_not_exists(PK)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                pass  # Already exists, that's fine
            else:
                raise

    # =========================================================================
    # Config Operations
    # =========================================================================

    def get_active_subnets(self) -> list[int]:
        """Get list of monitored subnets from DynamoDB config."""
        try:
            resp = self._table.get_item(
                Key={"PK": "CONFIG", "SK": "ACTIVE_SUBNETS"}
            )
        except ClientError as e:
            logger.error(f"Failed to get active subnets: {e}")
            return []

        item = resp.get("Item")
        if not item:
            return []

        netuids = item.get("netuids", [])
        return [int(n) for n in netuids]

    def update_active_subnets(self, netuids: list[int]) -> None:
        """Update the monitored subnet list in DynamoDB."""
        self._table.put_item(
            Item={
                "PK": "CONFIG",
                "SK": "ACTIVE_SUBNETS",
                "netuids": netuids,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info(f"Updated active subnets: {len(netuids)} subnets")

    def get_tracked_hotkeys(self) -> list[str]:
        """Get watchlist of tracked hotkeys from DynamoDB config."""
        try:
            resp = self._table.get_item(
                Key={"PK": "CONFIG", "SK": "TRACKED_HOTKEYS"}
            )
        except ClientError as e:
            logger.error(f"Failed to get tracked hotkeys: {e}")
            return []

        item = resp.get("Item")
        if not item:
            return []

        return item.get("hotkeys", [])

    def update_tracked_hotkeys(self, hotkeys: list[str]) -> None:
        """Update the tracked hotkeys watchlist."""
        self._table.put_item(
            Item={
                "PK": "CONFIG",
                "SK": "TRACKED_HOTKEYS",
                "hotkeys": hotkeys,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info(f"Updated tracked hotkeys: {len(hotkeys)} hotkeys")

    def get_thresholds(self) -> dict:
        """Read configurable thresholds from DynamoDB CONFIG|THRESHOLDS.

        Falls back to DEFAULT_THRESHOLDS for any missing keys.
        Validates values at load time (percentages 0-1, integers positive).

        Returns:
            Dict of threshold name → value, with defaults for missing keys.
        """
        from src.thresholds import DEFAULT_THRESHOLDS, validate_thresholds

        try:
            resp = self._table.get_item(
                Key={"PK": "CONFIG", "SK": "THRESHOLDS"}
            )
        except ClientError as e:
            logger.warning(f"Failed to read thresholds from DynamoDB: {e}. Using defaults.")
            return dict(DEFAULT_THRESHOLDS)

        item = resp.get("Item", {})
        item = _decimal_to_float(item)

        # Merge with defaults (DynamoDB values override defaults)
        thresholds = dict(DEFAULT_THRESHOLDS)
        for key in DEFAULT_THRESHOLDS:
            if key in item:
                thresholds[key] = item[key]

        # Validate
        errors = validate_thresholds(thresholds)
        if errors:
            logger.warning(f"Invalid threshold values (using defaults for those): {errors}")
            for key in errors:
                thresholds[key] = DEFAULT_THRESHOLDS[key]

        return thresholds

    def get_refresh_policy(self) -> dict:
        """Read configurable refresh policy from DynamoDB CONFIG|REFRESH_POLICY.

        Controls per-subnet refresh cadence for the independent scheduling model.
        Falls back to defaults for any missing keys.

        Returns:
            Dict with keys: max_staleness_hours, min_refresh_interval_minutes,
            discovery_cadence_minutes.
        """
        defaults = {
            "max_staleness_hours": 26,
            "min_refresh_interval_minutes": 15,
            "discovery_cadence_minutes": 60,
        }

        try:
            resp = self._table.get_item(
                Key={"PK": "CONFIG", "SK": "REFRESH_POLICY"}
            )
        except ClientError as e:
            logger.warning(f"Failed to read refresh policy: {e}. Using defaults.")
            return defaults

        item = resp.get("Item", {})
        item = _decimal_to_float(item)

        policy = dict(defaults)
        for key in defaults:
            if key in item:
                policy[key] = item[key]

        return policy

    # =========================================================================
    # Hotkey Earnings
    # =========================================================================

    def record_hotkey_earnings(
        self, hotkey: str, netuid: int, earnings: dict
    ) -> None:
        """Record per-cycle earnings for a tracked hotkey.

        Args:
            hotkey: SS58 hotkey address.
            netuid: Subnet network UID.
            earnings: Earnings data dict (period, cumulative_tao, per_subnet_breakdown, etc.)
        """
        period = earnings.get("period", "7d")
        item = {
            "PK": f"HOTKEY#{hotkey}",
            "SK": f"EARNINGS#{period}",
            "hotkey": hotkey,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        # Merge earnings data into item, converting floats to Decimal
        for key, value in earnings.items():
            if key not in ("PK", "SK"):
                item[key] = _float_to_decimal(value)

        self._table.put_item(Item=item)
        logger.info(f"Recorded earnings for hotkey={hotkey[:12]}... period={period}")

    def record_hotkey_snapshot(
        self, hotkey: str, date: str, positions: list[dict]
    ) -> None:
        """Record a daily position snapshot for a tracked hotkey.

        Args:
            hotkey: SS58 hotkey address.
            date: ISO date string (YYYY-MM-DD).
            positions: List of position dicts with netuid, uid, emission, etc.
        """
        self._table.put_item(
            Item={
                "PK": f"HOTKEY#{hotkey}",
                "SK": f"SNAPSHOT#{date}",
                "hotkey": hotkey,
                "date": date,
                "positions": _float_to_decimal(positions),
            }
        )

    # =========================================================================
    # Cycle Idempotency
    # =========================================================================

    def claim_cycle(self, cycle_id: str, subnets_total: int) -> bool:
        """Claim a pipeline cycle with conditional PutItem.

        Uses attribute_not_exists(PK) to ensure only one invocation can claim
        a given cycle. Provides at-most-once semantics for cycle execution.

        Args:
            cycle_id: Unique cycle identifier (typically ISO date string).
            subnets_total: Total number of subnets to process in this cycle.

        Returns:
            True if this invocation successfully claimed the cycle.
            False if the cycle was already claimed (duplicate/retry).
        """
        try:
            self._table.put_item(
                Item={
                    "PK": f"CYCLE#{cycle_id}",
                    "SK": "STATUS",
                    "status": "COLLECTING",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "subnets_total": subnets_total,
                    "subnets_complete": 0,
                },
                ConditionExpression="attribute_not_exists(PK)",
            )
            logger.info(f"Claimed cycle {cycle_id} with {subnets_total} subnets")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.info(f"Cycle {cycle_id} already claimed (idempotent skip)")
                return False
            # Throttling, internal errors — raise so Lambda retries
            raise

    def check_cycle_complete(self, cycle_id: str) -> bool:
        """Check if all subnets in a cycle have COMPLETE state.

        Reads the cycle status record and compares subnets_complete to subnets_total.

        Args:
            cycle_id: Unique cycle identifier.

        Returns:
            True if subnets_complete >= subnets_total.
        """
        try:
            resp = self._table.get_item(
                Key={"PK": f"CYCLE#{cycle_id}", "SK": "STATUS"}
            )
        except ClientError as e:
            logger.error(f"Failed to check cycle {cycle_id}: {e}")
            return False

        item = resp.get("Item")
        if not item:
            return False

        item = _decimal_to_float(item)
        status = item.get("status", "")
        if status == "COMPLETE":
            return True

        subnets_total = item.get("subnets_total", 0)
        subnets_complete = item.get("subnets_complete", 0)
        return subnets_complete >= subnets_total and subnets_total > 0

    def mark_cycle_complete(self, cycle_id: str) -> None:
        """Mark a cycle as COMPLETE.

        Args:
            cycle_id: Unique cycle identifier.
        """
        self._table.update_item(
            Key={"PK": f"CYCLE#{cycle_id}", "SK": "STATUS"},
            UpdateExpression="SET #s = :status, completed_at = :ts",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "COMPLETE",
                ":ts": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info(f"Cycle {cycle_id} marked COMPLETE")

    def increment_cycle_progress(self, cycle_id: str) -> int:
        """Atomically increment the subnets_complete counter for a cycle.

        Uses DynamoDB ADD expression for atomic increment.

        Args:
            cycle_id: Unique cycle identifier.

        Returns:
            The new value of subnets_complete after increment.

        Raises:
            ClientError: On DynamoDB errors (throttling, internal). Let SQS retry.
        """
        resp = self._table.update_item(
            Key={"PK": f"CYCLE#{cycle_id}", "SK": "STATUS"},
            UpdateExpression="ADD subnets_complete :inc",
            ExpressionAttributeValues={":inc": 1},
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(resp["Attributes"]["subnets_complete"])
        logger.debug(f"Cycle {cycle_id}: subnets_complete = {new_count}")
        return new_count

    # =========================================================================
    # Ranking & Briefing Storage
    # =========================================================================

    def store_ranking(self, date: str, rankings: list[dict]) -> None:
        """Store ranked subnets to RANKING|LATEST."""
        self._table.put_item(Item=_float_to_decimal({
            "PK": "RANKING", "SK": "LATEST",
            "ranked_subnets": rankings,
            "date": date,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }))

    def store_briefing(self, date: str, briefing: dict) -> None:
        """Store daily briefing summary to BRIEFING|{date}."""
        self._table.put_item(Item=_float_to_decimal({
            "PK": "BRIEFING", "SK": date,
            "summary": briefing.get("summary", ""),
            "alerts_count": len(briefing.get("alerts", [])),
            "subnets_processed": briefing.get("subnets_processed", 0),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }))

    def get_previous_active_subnets(self) -> list[int]:
        """Get the previous cycle's active subnet list from CONFIG."""
        try:
            resp = self._table.get_item(
                Key={"PK": "CONFIG", "SK": "PREVIOUS_ACTIVE_SUBNETS"})
            item = resp.get("Item")
            if not item:
                return []
            return [int(n) for n in item.get("netuids", [])]
        except Exception as e:
            logger.warning(f"DynamoDB read failed (returning empty): {e}")
            return []

    def set_previous_active_subnets(self, netuids: list[int]) -> None:
        """Store current active subnets for next briefing's new-subnet detection."""
        try:
            self._table.put_item(Item={
                "PK": "CONFIG",
                "SK": "PREVIOUS_ACTIVE_SUBNETS",
                "netuids": netuids,
            })
        except Exception as e:
            logger.warning(f"Failed to store previous active subnets: {e}")

    def get_research_profile(self, netuid: int) -> Optional[dict]:
        """Get research profile for a subnet."""
        try:
            resp = self._table.get_item(
                Key={"PK": f"SUBNET#{netuid}", "SK": "RESEARCH#latest"})
            return resp.get("Item")
        except Exception as e:
            logger.warning(f"DynamoDB read failed (returning None): {e}")
            return None

    def store_research_profile(self, netuid: int, profile: dict) -> None:
        """Store subnet research profile at SUBNET#{netuid}|RESEARCH#latest."""
        from decimal import Decimal
        try:
            item = {
                "PK": f"SUBNET#{netuid}",
                "SK": "RESEARCH#latest",
                **{k: v for k, v in profile.items()
                   if v is not None and k != "gpu_signals"},
            }
            # DynamoDB can't store float — convert
            if profile.get("vram_gb_estimate") is not None:
                item["vram_gb_estimate"] = Decimal(str(profile["vram_gb_estimate"]))
            # Store signals as string list
            if profile.get("gpu_signals"):
                item["gpu_signals"] = profile["gpu_signals"]
            self._table.put_item(Item=item)
        except Exception as e:
            logger.warning(f"Failed to store research profile for SN{netuid}: {e}")

    # =========================================================================
    # Market Observer: Cache + History
    # =========================================================================

    def write_market_cache(self, netuid: int, data: dict) -> None:
        """Write latest market data to cache (overwritten each observation)."""
        from decimal import Decimal
        try:
            self._table.put_item(Item={
                "PK": f"CACHE#{netuid}",
                "SK": "MARKET_DATA",
                "alpha_price": Decimal(str(data["alpha_price"])),
                "pool_tao": Decimal(str(data["pool_tao"])),
                "block": data["block"],
                "cached_at": data["cached_at"],
            })
        except Exception as e:
            logger.warning(f"Cache write failed SN{netuid}: {e}")

    def append_market_history(self, netuid: int, timestamp: str,
                              data: dict, ttl_epoch: int) -> None:
        """Append market observation to time-series history."""
        from decimal import Decimal
        try:
            self._table.put_item(Item={
                "PK": f"HISTORY#{netuid}",
                "SK": timestamp,
                "alpha_price": Decimal(str(data["alpha_price"])),
                "pool_tao": Decimal(str(data["pool_tao"])),
                "block": data["block"],
                "ttl": ttl_epoch,
            })
        except Exception as e:
            logger.warning(f"History append failed SN{netuid}: {e}")

    def get_market_cache(self, netuid: int) -> Optional[dict]:
        """Read latest cached market data for a subnet."""
        try:
            resp = self._table.get_item(
                Key={"PK": f"CACHE#{netuid}", "SK": "MARKET_DATA"})
            return resp.get("Item")
        except Exception as e:
            logger.warning(f"DynamoDB read failed (returning None): {e}")
            return None

    def query_market_history(self, netuid: int, since_iso: str) -> list[dict]:
        """Query market history observations since a given timestamp.

        NOTE: No current consumer (June 2026). Kept for future use:
        - Price volatility calculation
        - Net TAO flow taoflow metric
        - Trend detection for alerts
        """
        try:
            resp = self._table.query(
                KeyConditionExpression="PK = :pk AND SK >= :since",
                ExpressionAttributeValues={
                    ":pk": f"HISTORY#{netuid}",
                    ":since": since_iso,
                },
            )
            return resp.get("Items", [])
        except Exception as e:
            logger.warning(f"DynamoDB read failed (returning empty): {e}")
            return []

    def scan_basic_profiles(self) -> dict[int, dict]:
        """Scan all PROFILE#basic items. Returns {netuid: profile_dict}."""
        profiles: dict[int, dict] = {}
        try:
            resp = self._table.scan(
                FilterExpression="SK = :sk",
                ExpressionAttributeValues={":sk": "PROFILE#basic"},
                ProjectionExpression="PK, netuid, #n, category, mining_style",
                ExpressionAttributeNames={"#n": "name"},
            )
            for item in resp.get("Items", []):
                nid = int(item.get("netuid", 0))
                profiles[nid] = item
        except Exception as e:
            logger.warning(f"scan_basic_profiles failed: {e}")
        return profiles

    # =========================================================================
    # Subnet Profile Writes (Processor)
    # =========================================================================

    def write_subnet_profiles(self, netuid: int, profiles: dict[str, dict]) -> None:
        """Write split profiles to DynamoDB.

        Args:
            netuid: Subnet ID.
            profiles: Dict mapping profile SK suffix to item data.
                      e.g. {"basic": {...}, "winner": {...}, ...}
        """
        for suffix, data in profiles.items():
            item = {"PK": f"SUBNET#{netuid}", "SK": f"PROFILE#{suffix}", **data}
            self._table.put_item(Item=_float_to_decimal(item))

    def store_daily_stake(self, netuid: int, date: str, total_stake: float) -> None:
        """Store daily stake total for Net TAO Flow computation."""
        self._table.put_item(Item=_float_to_decimal({
            "PK": f"STAKE_HISTORY#{netuid}",
            "SK": date,
            "total_stake": total_stake,
            "netuid": netuid,
        }))

    def store_daily_emission(self, netuid: int, date: str, total_emission: float) -> None:
        """Store daily emission total for taoflow_health computation."""
        self._table.put_item(Item=_float_to_decimal({
            "PK": f"EMISSION_HISTORY#{netuid}",
            "SK": date,
            "total_emission": total_emission,
            "netuid": netuid,
        }))

    def get_stake_history(self, netuid: int, days: int = 8) -> list[dict]:
        """Get recent daily stake totals for a subnet (sorted ascending by date)."""
        from boto3.dynamodb.conditions import Key as DDBKey
        try:
            resp = self._table.query(
                KeyConditionExpression=DDBKey("PK").eq(f"STAKE_HISTORY#{netuid}"),
                ScanIndexForward=True,
                Limit=days,
            )
            return resp.get("Items", [])
        except Exception as e:
            logger.warning(f"DynamoDB read failed (returning empty): {e}")
            return []

    def get_basic_profile(self, netuid: int) -> Optional[dict]:
        """Get a single subnet's basic profile."""
        try:
            resp = self._table.get_item(
                Key={"PK": f"SUBNET#{netuid}", "SK": "PROFILE#basic"})
            return resp.get("Item")
        except Exception as e:
            logger.warning(f"DynamoDB read failed (returning None): {e}")
            return None


    def mark_subnet_collected(self, netuid: int, date: str) -> None:
        """Write collected_at timestamp to the basic profile.

        Called by SubnetCollector immediately after successful S3 storage,
        BEFORE publishing the SQS message to Processor. This prevents
        Discovery from re-scheduling subnets that are awaiting processing.

        Uses UpdateItem so it works even if the profile doesn't exist yet
        (first-ever collection of a new subnet).
        """
        now = datetime.now(timezone.utc).isoformat()
        self._table.update_item(
            Key={"PK": f"SUBNET#{netuid}", "SK": "PROFILE#basic"},
            UpdateExpression="SET collected_at = :ts, last_collection_date = :d",
            ExpressionAttributeValues={
                ":ts": now,
                ":d": date,
            },
        )
