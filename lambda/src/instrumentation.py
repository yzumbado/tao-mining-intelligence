"""Instrumentation module for distributed tracing and structured logging.

Provides:
- Trace ID generation and propagation across Lambda functions
- Context manager for timing and logging operations
- Error classification (retryable vs fatal)
- Structured JSON log format compatible with CloudWatch Insights

Usage:
    from instrumentation import init_tracing, instrument

    trace_id = init_tracing("2026-05-15")

    with instrument("collector", "collect_metagraph", netuid=1) as ctx:
        mg = await sub.metagraph(netuid=1)
        ctx["data_size_bytes"] = len(mg.hotkeys) * 200
"""

import json
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Generator, Optional

logger = logging.getLogger("tao-pipeline")
logger.setLevel(logging.INFO)

# Module-level trace state
_trace_id: Optional[str] = None
_cycle_id: Optional[str] = None


def init_tracing(cycle_id: str) -> str:
    """Initialize tracing for a new cycle (called by Collector).

    Generates a unique trace_id that will be propagated through SQS messages
    to Processor and Finalizer Lambdas.

    Args:
        cycle_id: The cycle identifier (typically ISO date string).

    Returns:
        The generated trace_id (format: cycle-{date}-{8_hex_chars}).
    """
    global _trace_id, _cycle_id
    _cycle_id = cycle_id
    _trace_id = f"cycle-{cycle_id}-{uuid.uuid4().hex[:8]}"
    logger.info(json.dumps({
        "trace_id": _trace_id,
        "cycle_id": _cycle_id,
        "component": "system",
        "operation": "init_tracing",
        "status": "success",
    }))
    return _trace_id


def set_trace_id(trace_id: str, cycle_id: str) -> None:
    """Set trace_id from an incoming SQS message (used by Processor/Finalizer).

    Args:
        trace_id: The trace_id from the SQS message.
        cycle_id: The cycle_id from the SQS message.
    """
    global _trace_id, _cycle_id
    _trace_id = trace_id
    _cycle_id = cycle_id


def get_trace_id() -> Optional[str]:
    """Get the current trace_id."""
    return _trace_id


def get_cycle_id() -> Optional[str]:
    """Get the current cycle_id."""
    return _cycle_id


@contextmanager
def instrument(
    component: str,
    operation: str,
    netuid: Optional[int] = None,
    **extra: Any,
) -> Generator[dict[str, Any], None, None]:
    """Context manager for instrumenting operations with timing and structured logging.

    Logs a structured JSON entry on both start and completion (success or error).
    The yielded dict can be updated by the caller to add context (e.g., data_size_bytes).

    Args:
        component: Which Lambda/module (collector, processor, finalizer, state_manager, storage).
        operation: What operation (collect_metagraph, compute_risk, store_snapshot, etc.).
        netuid: Optional subnet ID for subnet-specific operations.
        **extra: Additional key-value pairs to include in the log entry.

    Yields:
        A mutable dict that becomes the log entry. Caller can add fields.

    Example:
        with instrument("collector", "collect_metagraph", netuid=1) as ctx:
            mg = await sub.metagraph(netuid=1)
            ctx["data_size_bytes"] = 51200
            ctx["neuron_count"] = mg.n
    """
    start = time.time()
    log_data: dict[str, Any] = {
        "trace_id": _trace_id,
        "cycle_id": _cycle_id,
        "component": component,
        "operation": operation,
        "netuid": netuid,
        **{k: v for k, v in extra.items() if v is not None},
    }

    try:
        yield log_data
        log_data["status"] = "success"
    except Exception as e:
        log_data["status"] = "error"
        log_data["error"] = f"{type(e).__name__}: {str(e)[:500]}"
        log_data["retryable"] = is_retryable(e)
        raise
    finally:
        log_data["duration_ms"] = int((time.time() - start) * 1000)
        # Remove None values for cleaner logs
        clean_data = {k: v for k, v in log_data.items() if v is not None}
        logger.info(json.dumps(clean_data, default=str))


def is_retryable(error: Exception) -> bool:
    """Classify whether an error is retryable.

    Retryable errors are transient (network issues, timeouts, throttling).
    Non-retryable errors are permanent (invalid data, auth failures, bugs).

    Args:
        error: The exception to classify.

    Returns:
        True if the error is likely transient and worth retrying.
    """
    retryable_types = (
        TimeoutError,
        ConnectionError,
        ConnectionResetError,
        OSError,
    )

    if isinstance(error, retryable_types):
        return True

    retryable_messages = (
        "timeout",
        "connection reset",
        "throttl",
        "rate limit",
        "too many requests",
        "service unavailable",
        "internal server error",
        "websocket",
    )

    msg = str(error).lower()
    return any(r in msg for r in retryable_messages)


def truncate_coldkey(coldkey: str) -> str:
    """Truncate a coldkey address for safe logging (first 12 chars only).

    Args:
        coldkey: Full SS58 coldkey address.

    Returns:
        Truncated address with "..." suffix.
    """
    if len(coldkey) <= 12:
        return coldkey
    return f"{coldkey[:12]}..."
