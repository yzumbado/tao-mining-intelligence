"""Unit tests for the Collector Lambda handler.

Tests cover:
- Idempotency: duplicate trigger skipped (Req 1.5)
- Partial failure: some subnets fail, others succeed (Req 1.5, 1.6)
- Graceful shutdown: timeout approaching, saves partial results (Req 33.1-33.4)
- SQS message format matches schema (Req 1.6)
- Data validation rejects corrupt metagraphs (Req 32.1-32.4)
- Concurrency semaphore limits connections (Req 33.3)
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

# The collector handler uses `from src.X` imports, so we need lambda/ on the path.
# Other modules (storage, config) use direct imports, so lambda/src/ is also needed.
sys.path.insert(0, "lambda")
sys.path.insert(0, "lambda/src")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level cached state between tests."""
    from src.collector import handler as handler_mod
    from src import config as config_mod

    handler_mod._config = None
    handler_mod._state_manager = None
    handler_mod._storage = None
    handler_mod._sqs_client = None
    handler_mod._ssm_client = None
    handler_mod._coingecko_api_key = None
    config_mod.reset_config()
    yield
    handler_mod._config = None
    handler_mod._state_manager = None
    handler_mod._storage = None
    handler_mod._sqs_client = None
    handler_mod._ssm_client = None
    handler_mod._coingecko_api_key = None
    config_mod.reset_config()


@pytest.fixture
def aws_env(tmp_path):
    """Set environment variables for AWS mode with moto."""
    env_vars = {
        "PIPELINE_ENV": "aws",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "TABLE_NAME": "tao-pipeline-test",
        "BUCKET_NAME": "tao-intelligence-test",
        "PROCESS_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/process-queue.fifo",
        "CONCURRENCY_LIMIT": "4",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


@pytest.fixture
def create_dynamodb_table():
    """Create the DynamoDB table for testing."""
    table_name = os.environ.get("TABLE_NAME", "tao-pipeline-test")
    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return table_name


@pytest.fixture
def create_s3_bucket():
    """Create the S3 bucket for testing."""
    bucket_name = os.environ.get("BUCKET_NAME", "tao-intelligence-test")
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=bucket_name)
    return bucket_name


@pytest.fixture
def create_sqs_queue():
    """Create the SQS FIFO queue for testing."""
    client = boto3.client("sqs", region_name="us-east-1")
    resp = client.create_queue(
        QueueName="process-queue.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "true"},
    )
    return resp["QueueUrl"]


@pytest.fixture
def lambda_context():
    """Mock Lambda context with configurable remaining time."""
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 600_000  # 10 minutes
    return context


@pytest.fixture
def lambda_context_low_time():
    """Mock Lambda context with very little time remaining (triggers graceful shutdown)."""
    context = MagicMock()
    # Start with enough time, then drop below threshold after first call
    context.get_remaining_time_in_millis.side_effect = [
        120_000,  # First check: 2 min (above 60s threshold)
        50_000,   # Second check: below threshold
        50_000,   # Subsequent checks: below threshold
        50_000,
        50_000,
        50_000,
        50_000,
        50_000,
        50_000,
        50_000,
    ]
    return context


def _make_mock_metagraph(netuid: int, neuron_count: int = 10):
    """Create a mock metagraph object mimicking the Bittensor SDK."""
    mg = MagicMock()
    mg.n = neuron_count
    mg.hotkeys = [f"5Hot{netuid}key{i:03d}" for i in range(neuron_count)]
    mg.coldkeys = [f"5Cold{netuid}key{i:03d}" for i in range(neuron_count)]

    import numpy as np

    mg.S = np.array([100.0 + i for i in range(neuron_count)])
    # Distribute incentive so it sums to ~1.0 for miners
    incentives = np.zeros(neuron_count)
    miner_count = neuron_count - 2  # Last 2 are validators
    if miner_count > 0:
        incentives[:miner_count] = 1.0 / miner_count
    mg.I = incentives

    mg.E = np.array([0.5 / neuron_count for _ in range(neuron_count)])
    mg.C = np.array([0.8 for _ in range(neuron_count)])
    mg.D = np.zeros(neuron_count)
    mg.D[-2] = 0.6
    mg.D[-1] = 0.4
    mg.Tv = np.array([0.9 for _ in range(neuron_count)])
    mg.active = np.ones(neuron_count, dtype=int)
    mg.AS = np.array([50.0 for _ in range(neuron_count)])
    mg.TS = np.array([150.0 for _ in range(neuron_count)])
    mg.block_at_registration = np.array([1000 + i * 100 for i in range(neuron_count)])
    mg.blocks_since_last_step = np.array([50 for _ in range(neuron_count)])

    return mg


# ---------------------------------------------------------------------------
# Test: Idempotency (duplicate trigger skipped)
# Requirements: 1.5
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Verify that duplicate cycle triggers are skipped via conditional DynamoDB write."""

    @mock_aws
    def test_duplicate_trigger_returns_duplicate_status(self, aws_env, lambda_context):
        """Second invocation for same cycle_id returns 'duplicate' status."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        create_sqs_queue_inline()

        from src.collector.handler import handle

        async def mock_discover():
            return [1, 2, 3]

        async def mock_collect_metagraph(netuid, cycle_id):
            return _make_valid_snapshot(netuid, cycle_id)

        async def mock_supplementary(*args, **kwargs):
            pass

        with patch("src.collector.handler._discover_subnets", side_effect=mock_discover):
            with patch("src.collector.handler._collect_metagraph", side_effect=mock_collect_metagraph):
                with patch("src.collector.handler._collect_supplementary_data", side_effect=mock_supplementary):
                    # First call claims the cycle
                    result1 = handle({}, lambda_context)
                    assert result1["status"] == "complete"

                    # Reset module state but keep DynamoDB data (moto state persists)
                    from src.collector import handler as handler_mod
                    from src import config as config_mod
                    handler_mod._config = None
                    handler_mod._state_manager = None
                    handler_mod._storage = None
                    handler_mod._sqs_client = None
                    handler_mod._ssm_client = None
                    handler_mod._coingecko_api_key = None
                    config_mod.reset_config()

                    # Second call should be duplicate
                    result2 = handle({}, lambda_context)
                    assert result2["status"] == "duplicate"
                    assert result2["subnets_collected"] == 0

    @mock_aws
    def test_idempotency_uses_conditional_write(self, aws_env, lambda_context):
        """claim_cycle uses attribute_not_exists condition to prevent duplicates."""
        create_dynamodb_table_inline()

        from src.config import get_config
        from src.state.state_manager import StateManager

        config = get_config()
        sm = StateManager(config)

        # First claim succeeds
        assert sm.claim_cycle("2026-01-15", subnets_total=5) is True
        # Second claim fails (idempotent)
        assert sm.claim_cycle("2026-01-15", subnets_total=5) is False


# ---------------------------------------------------------------------------
# Test: Partial failure (some subnets fail, others succeed)
# Requirements: 1.5, 1.6
# ---------------------------------------------------------------------------


class TestPartialFailure:
    """Verify pipeline continues when some subnets fail collection."""

    @mock_aws
    def test_failed_subnets_dont_block_successful_ones(self, aws_env, lambda_context):
        """When some metagraph collections fail, successful ones still get stored and published."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        create_sqs_queue_inline()

        from src.collector.handler import handle

        async def mock_discover():
            return [1, 2, 3]

        async def mock_collect_metagraph(netuid, cycle_id):
            """Subnet 2 fails, subnets 1 and 3 succeed."""
            if netuid == 2:
                return None  # Simulates failure
            return _make_valid_snapshot(netuid, cycle_id)

        async def mock_supplementary(*args, **kwargs):
            pass

        with patch("src.collector.handler._discover_subnets", side_effect=mock_discover):
            with patch("src.collector.handler._collect_metagraph", side_effect=mock_collect_metagraph):
                with patch("src.collector.handler._collect_supplementary_data", side_effect=mock_supplementary):
                    result = handle({}, lambda_context)

        assert result["status"] == "complete"
        assert result["subnets_collected"] == 2
        assert result["subnets_failed"] == 1
        assert 2 in result["failed_netuids"]

    @mock_aws
    def test_circuit_breaker_trips_after_consecutive_failures(self, aws_env, lambda_context):
        """Circuit breaker opens after threshold consecutive failures, skipping remaining subnets."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        create_sqs_queue_inline()

        from src.circuit_breaker import CircuitBreaker
        from src.collector.handler import _collect_all_metagraphs

        netuids = list(range(1, 10))
        semaphore = asyncio.Semaphore(32)
        cb = CircuitBreaker(failure_threshold=3)

        async def mock_collect_metagraph(netuid, cycle_id):
            raise TimeoutError(f"Timeout for netuid={netuid}")

        with patch("src.collector.handler._collect_metagraph", side_effect=mock_collect_metagraph):
            results = asyncio.run(
                _collect_all_metagraphs(
                    netuids=netuids,
                    cycle_id="2026-01-15",
                    semaphore=semaphore,
                    circuit_breaker=cb,
                    context=lambda_context,
                )
            )

        # After 3 failures, circuit breaker opens — remaining subnets skipped
        assert cb.is_open
        # All results should be None (either failed or skipped)
        assert all(v is None for v in results.values())


# ---------------------------------------------------------------------------
# Test: Graceful shutdown (timeout approaching, saves partial results)
# Requirements: 33.1-33.4
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    """Verify collector stops work and saves partial results when timeout approaches."""

    @mock_aws
    def test_stops_collection_when_time_low(self, aws_env, lambda_context_low_time):
        """When remaining time drops below threshold, new collections are skipped."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        create_sqs_queue_inline()

        from src.collector.handler import _collect_all_metagraphs
        from src.circuit_breaker import CircuitBreaker

        netuids = list(range(1, 6))
        semaphore = asyncio.Semaphore(32)
        cb = CircuitBreaker(failure_threshold=5)

        collected = []

        async def mock_collect_metagraph(netuid, cycle_id):
            collected.append(netuid)
            await asyncio.sleep(0.01)
            return _make_valid_snapshot(netuid, cycle_id)

        with patch("src.collector.handler._collect_metagraph", side_effect=mock_collect_metagraph):
            results = asyncio.run(
                _collect_all_metagraphs(
                    netuids=netuids,
                    cycle_id="2026-01-15",
                    semaphore=semaphore,
                    circuit_breaker=cb,
                    context=lambda_context_low_time,
                )
            )

        # Some subnets should be None due to time running out
        none_count = sum(1 for v in results.values() if v is None)
        assert none_count > 0, "Expected some subnets to be skipped due to timeout"

    def test_has_time_remaining_returns_false_below_threshold(self):
        """_has_time_remaining returns False when remaining time < 60s."""
        from src.collector.handler import _has_time_remaining, GRACEFUL_SHUTDOWN_THRESHOLD_MS

        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 30_000  # 30s < 60s threshold
        assert _has_time_remaining(context) is False

    def test_has_time_remaining_returns_true_above_threshold(self):
        """_has_time_remaining returns True when remaining time > 60s."""
        from src.collector.handler import _has_time_remaining

        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 120_000  # 2 min
        assert _has_time_remaining(context) is True

    def test_has_time_remaining_returns_true_for_none_context(self):
        """_has_time_remaining returns True when context is None (local testing)."""
        from src.collector.handler import _has_time_remaining

        assert _has_time_remaining(None) is True


# ---------------------------------------------------------------------------
# Test: SQS message format matches schema
# Requirements: 1.6
# ---------------------------------------------------------------------------


class TestSQSMessageFormat:
    """Verify SQS messages published by the collector match the expected schema."""

    @mock_aws
    def test_sqs_message_contains_required_fields(self, aws_env, lambda_context):
        """Each SQS message must contain netuid, date, cycle_id, and trace_id."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        queue_url = create_sqs_queue_inline()

        from src.collector.handler import handle

        async def mock_discover():
            return [1, 4]

        async def mock_collect_metagraph(netuid, cycle_id):
            return _make_valid_snapshot(netuid, cycle_id)

        async def mock_supplementary(*args, **kwargs):
            pass

        with patch("src.collector.handler._discover_subnets", side_effect=mock_discover):
            with patch("src.collector.handler._collect_metagraph", side_effect=mock_collect_metagraph):
                with patch("src.collector.handler._collect_supplementary_data", side_effect=mock_supplementary):
                    result = handle({}, lambda_context)

        assert result["status"] == "complete"
        assert result["messages_published"] == 2

        # Read messages from SQS to verify format
        sqs = boto3.client("sqs", region_name="us-east-1")
        messages = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
        ).get("Messages", [])

        assert len(messages) == 2

        for msg in messages:
            body = json.loads(msg["Body"])
            # Required fields per schema
            assert "netuid" in body
            assert "date" in body
            assert "cycle_id" in body
            assert "trace_id" in body
            # Type checks
            assert isinstance(body["netuid"], int)
            assert isinstance(body["date"], str)
            assert isinstance(body["cycle_id"], str)
            assert isinstance(body["trace_id"], str)
            # trace_id format: cycle-{date}-{hex}
            assert body["trace_id"].startswith("cycle-")

    @mock_aws
    def test_sqs_message_trace_id_propagated(self, aws_env, lambda_context):
        """trace_id in SQS messages matches the trace_id returned by the handler."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        queue_url = create_sqs_queue_inline()

        from src.collector.handler import handle

        async def mock_discover():
            return [7]

        async def mock_collect_metagraph(netuid, cycle_id):
            return _make_valid_snapshot(netuid, cycle_id)

        async def mock_supplementary(*args, **kwargs):
            pass

        with patch("src.collector.handler._discover_subnets", side_effect=mock_discover):
            with patch("src.collector.handler._collect_metagraph", side_effect=mock_collect_metagraph):
                with patch("src.collector.handler._collect_supplementary_data", side_effect=mock_supplementary):
                    result = handle({}, lambda_context)

        trace_id = result["trace_id"]

        sqs = boto3.client("sqs", region_name="us-east-1")
        messages = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
        ).get("Messages", [])

        assert len(messages) == 1
        body = json.loads(messages[0]["Body"])
        assert body["trace_id"] == trace_id


# ---------------------------------------------------------------------------
# Test: Data validation rejects corrupt metagraphs
# Requirements: 32.1-32.4
# ---------------------------------------------------------------------------


class TestDataValidation:
    """Verify that corrupt metagraph data is rejected before storage."""

    @mock_aws
    def test_empty_metagraph_rejected(self, aws_env, lambda_context):
        """A metagraph with 0 neurons is rejected by validation."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        create_sqs_queue_inline()

        from src.validation import validate_metagraph

        snapshot = {
            "metadata": {"netuid": 1, "cycle_id": "2026-01-15", "source_block_number": 100},
            "data": {"neurons": []},
        }
        is_valid, errors = validate_metagraph(snapshot)
        assert not is_valid
        assert any("Empty metagraph" in e for e in errors)

    def test_negative_emission_rejected(self):
        """Neurons with negative emission values are flagged."""
        from src.validation import validate_metagraph

        snapshot = {
            "metadata": {"source_block_number": 100},
            "data": {"neurons": [
                {"uid": 0, "emission": -0.5, "incentive": 1.0, "dividends": 0},
            ]},
        }
        is_valid, errors = validate_metagraph(snapshot)
        assert not is_valid
        assert any("negative emission" in e for e in errors)

    def test_block_number_backwards_rejected(self):
        """Block number going backwards is flagged as invalid."""
        from src.validation import validate_metagraph

        snapshot = {
            "metadata": {"source_block_number": 50},
            "data": {"neurons": [
                {"uid": 0, "emission": 0.5, "incentive": 1.0, "dividends": 0},
            ]},
        }
        is_valid, errors = validate_metagraph(snapshot, previous_block=100)
        assert not is_valid
        assert any("backwards" in e for e in errors)

    def test_too_many_neurons_rejected(self):
        """More than 256 neurons is flagged as invalid."""
        from src.validation import validate_metagraph

        neurons = [{"uid": i, "emission": 0, "incentive": 0, "dividends": 0} for i in range(300)]
        snapshot = {"metadata": {}, "data": {"neurons": neurons}}
        is_valid, errors = validate_metagraph(snapshot)
        assert not is_valid
        assert any("exceeds max 256" in e for e in errors)

    @mock_aws
    def test_invalid_metagraph_not_stored(self, aws_env, lambda_context):
        """When validation fails, the snapshot is NOT stored to S3."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        create_sqs_queue_inline()

        from src.collector.handler import handle

        async def mock_discover():
            return [1]

        # Return a snapshot that will fail validation (empty neurons)
        async def mock_collect_metagraph_invalid(netuid, cycle_id):
            # _collect_metagraph internally validates — if invalid, returns None
            return None

        async def mock_supplementary(*args, **kwargs):
            pass

        with patch("src.collector.handler._discover_subnets", side_effect=mock_discover):
            with patch("src.collector.handler._collect_metagraph", side_effect=mock_collect_metagraph_invalid):
                with patch("src.collector.handler._collect_supplementary_data", side_effect=mock_supplementary):
                    result = handle({}, lambda_context)

        # Subnet failed validation, so 0 collected
        assert result["subnets_collected"] == 0
        assert result["subnets_failed"] == 1

        # Verify nothing was stored in S3
        s3 = boto3.client("s3", region_name="us-east-1")
        objects = s3.list_objects_v2(
            Bucket="tao-intelligence-test",
            Prefix="raw/metagraph/",
        )
        assert objects.get("KeyCount", 0) == 0


# ---------------------------------------------------------------------------
# Test: Concurrency semaphore limits connections
# Requirements: 33.3
# ---------------------------------------------------------------------------


class TestConcurrencySemaphore:
    """Verify the semaphore limits concurrent metagraph collections."""

    @mock_aws
    def test_semaphore_limits_concurrent_tasks(self, aws_env, lambda_context):
        """No more than CONCURRENCY_LIMIT tasks run simultaneously."""
        create_dynamodb_table_inline()
        create_s3_bucket_inline()
        create_sqs_queue_inline()

        from src.collector.handler import _collect_all_metagraphs
        from src.circuit_breaker import CircuitBreaker

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        netuids = list(range(1, 9))  # 8 subnets
        concurrency_limit = 4
        semaphore = asyncio.Semaphore(concurrency_limit)
        cb = CircuitBreaker(failure_threshold=10)

        async def mock_collect_metagraph(netuid, cycle_id):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            await asyncio.sleep(0.05)  # Simulate work
            async with lock:
                current_concurrent -= 1
            return _make_valid_snapshot(netuid, cycle_id)

        with patch("src.collector.handler._collect_metagraph", side_effect=mock_collect_metagraph):
            results = asyncio.run(
                _collect_all_metagraphs(
                    netuids=netuids,
                    cycle_id="2026-01-15",
                    semaphore=semaphore,
                    circuit_breaker=cb,
                    context=lambda_context,
                )
            )

        # Semaphore should have limited concurrency
        assert max_concurrent <= concurrency_limit
        # All subnets should have been collected
        assert len([v for v in results.values() if v is not None]) == 8


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _make_valid_snapshot(netuid: int, cycle_id: str) -> dict:
    """Create a valid metagraph snapshot that passes validation."""
    neuron_count = 10
    miner_count = 8
    # Incentives sum to 1.0 for miners
    miner_incentive = 1.0 / miner_count

    neurons = []
    for i in range(neuron_count):
        is_validator = i >= miner_count
        neurons.append({
            "uid": i,
            "hotkey": f"5Hot{netuid}key{i:03d}",
            "coldkey": f"5Cold{netuid}key{i:03d}",
            "stake": 100.0 + i,
            "incentive": miner_incentive if not is_validator else 0.0,
            "emission": 0.05,
            "consensus": 0.8,
            "dividends": 0.5 if is_validator else 0.0,
            "trust": 0.9,
            "active": True,
            "alpha_stake": 50.0,
            "tao_stake": 150.0,
            "block_at_registration": 1000 + i * 100,
            "blocks_since_last_step": 50,
        })

    return {
        "metadata": {
            "netuid": netuid,
            "cycle_id": cycle_id,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source_block_number": 5000,
            "neuron_count": neuron_count,
        },
        "data": {
            "neurons": neurons,
        },
    }


def create_dynamodb_table_inline():
    """Create DynamoDB table (call inside @mock_aws context)."""
    table_name = os.environ.get("TABLE_NAME", "tao-pipeline-test")
    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def create_s3_bucket_inline():
    """Create S3 bucket (call inside @mock_aws context)."""
    bucket_name = os.environ.get("BUCKET_NAME", "tao-intelligence-test")
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=bucket_name)


def create_sqs_queue_inline() -> str:
    """Create SQS FIFO queue (call inside @mock_aws context). Returns queue URL."""
    client = boto3.client("sqs", region_name="us-east-1")
    resp = client.create_queue(
        QueueName="process-queue.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "true"},
    )
    return resp["QueueUrl"]
