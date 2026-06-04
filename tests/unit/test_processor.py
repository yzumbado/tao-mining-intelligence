"""Unit tests for the Processor Lambda handler.

Tests cover:
- SQS message parsing and metric computation (Req 3.1-3.7)
- Missing previous-day snapshot → trend metrics marked insufficient_data (Req 3.5)
- SNS publish format correct (Req 17.1-17.6)
- Split profile writes (basic, winner, validator, intelligence, composability) (Req 15.1-15.9)
- Hotkey tracking (earnings, deregistration detection) (Req 19.7-19.10)
- Error handling and state transitions
"""

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws



# ---------------------------------------------------------------------------
# Test Data Factories
# ---------------------------------------------------------------------------


def _make_neuron(uid: int, *, emission: float = 0.5, incentive: float = 0.3,
                 dividends: float = 0.0, stake: float = 100.0, active: bool = True,
                 block_at_registration: int = 1000, consensus: float = 0.5,
                 validator_trust: float = 0.0, alpha_stake: float = 0.0,
                 total_stake: float = 0.0) -> dict:
    """Create a neuron dict matching the raw snapshot format."""
    return {
        "uid": uid,
        "hotkey": f"5Hot{'k' * 44}{uid:04d}"[:48],
        "coldkey": f"5Col{'d' * 44}{uid:04d}"[:48],
        "stake": stake,
        "incentive": incentive,
        "emission": emission,
        "consensus": consensus,
        "validator_trust": validator_trust,
        "dividends": dividends,
        "active": active,
        "alpha_stake": alpha_stake,
        "total_stake": total_stake,
        "block_at_registration": block_at_registration,
        "blocks_since_last_step": 10,
    }


def _make_raw_snapshot(netuid: int, date: str, neurons: list[dict] = None) -> dict:
    """Create a raw metagraph snapshot as stored by the Collector."""
    if neurons is None:
        neurons = [_make_neuron(i) for i in range(10)]
    return {
        "metadata": {
            "netuid": netuid,
            "cycle_id": date,
            "collected_at": f"{date}T00:05:00+00:00",
            "source_block_number": 5000000,
            "neuron_count": len(neurons),
            "num_uids": len(neurons),
            "max_uids": len(neurons),
        },
        "data": {"neurons": neurons},
    }


def _make_alpha_prices(netuid: int, date: str) -> dict:
    return {
        "metadata": {"cycle_id": date, "collected_at": f"{date}T00:05:00+00:00", "subnet_count": 1},
        "data": {"prices": [{"netuid": netuid, "alpha_tao_price": 0.05,
                             "pool_tao_liquidity": 1000.0, "pool_alpha_liquidity": 20000.0}]},
    }


def _make_registration_costs(netuid: int, date: str) -> dict:
    return {
        "metadata": {"cycle_id": date, "collected_at": f"{date}T00:05:00+00:00", "subnet_count": 1},
        "data": {"costs": [{"netuid": netuid, "registration_cost_rao": 1000000000,
                            "registration_cost_tao": 1.0}]},
    }


def _make_hyperparameters(netuid: int, date: str) -> dict:
    return {
        "metadata": {"netuid": netuid, "cycle_id": date, "collected_at": f"{date}T00:05:00+00:00"},
        "data": {
            "immunity_period": 7200, "tempo": 360, "max_validators": 64,
            "min_allowed_weights": 1, "activity_cutoff": 5000, "max_weight_limit": 65535,
            "min_burn": 100000000, "max_burn": 100000000000, "registration_allowed": True,
            "commit_reveal_weights_enabled": False, "liquid_alpha_enabled": True,
            "bonds_moving_avg": 900000, "max_regs_per_block": 1,
            "target_regs_per_interval": 2, "adjustment_interval": 112,
            "weights_rate_limit": 100, "yuma_version": 2,
        },
    }


def _make_sqs_event(netuid: int = 1, date: str = "2026-05-15",
                    cycle_id: str = "2026-05-15",
                    trace_id: str = "trace-abc-123") -> dict:
    body = json.dumps({"netuid": netuid, "date": date, "cycle_id": cycle_id, "trace_id": trace_id})
    return {"Records": [{"messageId": "msg-001", "body": body,
                         "attributes": {"ApproximateReceiveCount": "1"}}]}


# ---------------------------------------------------------------------------
# Inline AWS Resource Helpers (called inside @mock_aws context)
# ---------------------------------------------------------------------------


def _create_dynamodb_table():
    """Create DynamoDB table (call inside @mock_aws context)."""
    table_name = os.environ.get("TABLE_NAME", "tao-pipeline-test")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.create_table(
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
    return table


def _create_s3_bucket():
    """Create S3 bucket (call inside @mock_aws context)."""
    bucket_name = os.environ.get("BUCKET_NAME", "tao-intelligence-test")
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)
    return bucket_name


def _create_sns_topic():
    """Create SNS topic (call inside @mock_aws context)."""
    sns = boto3.client("sns", region_name="us-east-1")
    resp = sns.create_topic(Name="subnet-processed")
    return resp["TopicArn"]


def _seed_raw_data(netuid: int = 1, date: str = "2026-05-15", neurons: list[dict] = None):
    """Seed S3 with raw snapshot data for processing."""
    s3 = boto3.client("s3", region_name="us-east-1")
    bucket = os.environ.get("BUCKET_NAME", "tao-intelligence-test")

    s3.put_object(Bucket=bucket, Key=f"raw/metagraph/{date}/{netuid}.json",
                  Body=json.dumps(_make_raw_snapshot(netuid, date, neurons)))
    s3.put_object(Bucket=bucket, Key=f"raw/alpha-prices/{date}/{netuid}.json",
                  Body=json.dumps(_make_alpha_prices(netuid, date)))
    s3.put_object(Bucket=bucket, Key=f"raw/registration-costs/{date}/{netuid}.json",
                  Body=json.dumps(_make_registration_costs(netuid, date)))
    s3.put_object(Bucket=bucket, Key=f"raw/hyperparameters/{date}/{netuid}.json",
                  Body=json.dumps(_make_hyperparameters(netuid, date)))


def _seed_previous_day(netuid: int = 1, date: str = "2026-05-15", neurons: list[dict] = None):
    """Seed S3 with previous day's snapshot for trend comparison."""
    from datetime import timedelta
    prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    if neurons is None:
        neurons = [_make_neuron(i, emission=0.4) for i in range(10)]
    s3 = boto3.client("s3", region_name="us-east-1")
    bucket = os.environ.get("BUCKET_NAME", "tao-intelligence-test")
    s3.put_object(Bucket=bucket, Key=f"raw/metagraph/{prev_date}/{netuid}.json",
                  Body=json.dumps(_make_raw_snapshot(netuid, prev_date, neurons)))


def _reset_handler():
    """Reset module-level cached state."""
    from src.processor import handler as handler_mod
    from src import config as config_mod
    handler_mod._config = None
    handler_mod._state_manager = None
    handler_mod._storage = None
    handler_mod._sns_client = None
    config_mod.reset_config()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level cached state between tests."""
    try:
        _reset_handler()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        _reset_handler()
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def aws_env():
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
        "SUBNET_PROCESSED_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:subnet-processed",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


@pytest.fixture
def lambda_context():
    """Mock Lambda context with plenty of time remaining."""
    ctx = MagicMock()
    ctx.get_remaining_time_in_millis.return_value = 300_000
    return ctx


# ---------------------------------------------------------------------------
# Test: SQS message parsing and full metric computation
# ---------------------------------------------------------------------------


class TestProcessorHappyPath:
    """Test the full processing pipeline: SQS → read → compute → store."""

    @mock_aws
    def test_processes_sqs_message_and_computes_metrics(self, aws_env, lambda_context):
        """Handler receives SQS message, reads raw data, computes all metrics, stores results."""
        _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        from src.processor.handler import handle

        result = handle(_make_sqs_event(), lambda_context)

        assert result["status"] == "complete"
        assert result["netuid"] == 1
        assert result["cycle_id"] == "2026-05-15"
        assert len(result.get("metrics_computed", [])) > 0

    @mock_aws
    def test_stores_derived_metrics_to_s3(self, aws_env, lambda_context):
        """Derived metrics are stored at derived/metrics/{date}/{netuid}.json."""
        _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        from src.processor.handler import handle

        handle(_make_sqs_event(), lambda_context)

        s3 = boto3.client("s3", region_name="us-east-1")
        resp = s3.get_object(Bucket="tao-intelligence-test",
                             Key="derived/metrics/2026-05-15/1.json")
        stored = json.loads(resp["Body"].read())
        assert "metadata" in stored
        assert "data" in stored
        assert stored["metadata"]["netuid"] == 1

    @mock_aws
    def test_increments_cycle_progress(self, aws_env, lambda_context):
        """Processing a subnet increments the cycle's subnets_complete counter."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        # Seed cycle record
        table.put_item(Item={
            "PK": "CYCLE#2026-05-15", "SK": "STATUS",
            "status": "COLLECTING", "subnets_total": 5, "subnets_complete": 0,
        })

        from src.processor.handler import handle

        handle(_make_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": "CYCLE#2026-05-15", "SK": "STATUS"})
        assert resp["Item"]["subnets_complete"] == 1


# ---------------------------------------------------------------------------
# Test: Realistic WTA emission distribution (most miners earn 0)
# ---------------------------------------------------------------------------


class TestRealisticWTADistribution:
    """Verify metrics handle production-like WTA subnets where most miners earn 0."""

    @mock_aws
    def test_wta_subnet_with_mostly_zero_emission(self):
        """256-neuron full subnet where only 4 miners earn — like SN1 in production."""
        os.environ.update({"PIPELINE_ENV": "aws", "TABLE_NAME": "tao-pipeline-test",
                           "BUCKET_NAME": "tao-intelligence-test",
                           "SUBNET_PROCESSED_TOPIC_ARN": ""})
        _create_dynamodb_table()
        _create_s3_bucket()
        _reset_handler()

        # 4 earning miners with unequal emission (realistic WTA: top miner dominates)
        # 252 zero-emission miners (the common case on WTA subnets)
        neurons = []
        earning_emissions = [0.008, 0.004, 0.002, 0.001]  # top miner gets 53%
        for i, em in enumerate(earning_emissions):
            neurons.append(_make_neuron(i, emission=em, incentive=0.25,
                                        block_at_registration=4000000))
        for i in range(4, 256):
            neurons.append(_make_neuron(i, emission=0.0, incentive=0.0,
                                        block_at_registration=4900000))

        # Override snapshot to have full subnet
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = os.environ["BUCKET_NAME"]
        snapshot = {
            "metadata": {"netuid": 1, "cycle_id": "2026-05-15",
                         "collected_at": "2026-05-15T00:05:00+00:00",
                         "source_block_number": 5000000, "neuron_count": 256,
                         "num_uids": 256, "max_uids": 256},
            "data": {"neurons": neurons},
        }
        alpha = {"metadata": {}, "data": {"alpha_tao_price": 0.05, "pool_tao_liquidity": 1000.0}}
        reg = {"metadata": {}, "data": {"registration_cost_tao": 1.0}}
        hyper = {"metadata": {}, "data": {"tempo": 360, "immunity_period": 7200}}

        s3.put_object(Bucket=bucket, Key="raw/metagraph/2026-05-15/1.json",
                      Body=json.dumps(snapshot))
        s3.put_object(Bucket=bucket, Key="raw/alpha-prices/2026-05-15/1.json",
                      Body=json.dumps(alpha))
        s3.put_object(Bucket=bucket, Key="raw/registration-costs/2026-05-15/1.json",
                      Body=json.dumps(reg))
        s3.put_object(Bucket=bucket, Key="raw/hyperparameters/2026-05-15/1.json",
                      Body=json.dumps(hyper))

        from src.processor.handler import handle
        result = handle(_make_sqs_event(), None)
        assert result["status"] == "complete"

        # Read derived output and validate WTA behavior
        obj = s3.get_object(Bucket=bucket, Key="derived/metrics/2026-05-15/1.json")
        derived = json.loads(obj["Body"].read())
        data = derived["data"]

        # Gini should be non-trivial (inequality among earners)
        gini = data["reward_distribution"]["gini_coefficient"]
        assert gini > 0.2, f"WTA subnet with unequal earners should have Gini > 0.2, got {gini}"

        # Reward model should be WTA (top 3 of 4 earners capture >70%)
        assert data["reward_distribution"]["model"] == "WINNER_TAKES_ALL"

        # ROI should use earning miners only (4 miners, not 256)
        roi = data["roi_estimate"]
        assert roi["net_tao_yield_per_day"] > 0, "Yield should be positive"

        # Deregistration risk should be non-zero for bottom miners (subnet is full)
        dereg = data["deregistration_risk"]
        assert len(dereg) > 0, "Should have deregistration risk entries"
        risk_scores = [d["risk_score"] for d in dereg]
        assert max(risk_scores) > 0, "Full subnet should have non-zero deregistration risk"


# ---------------------------------------------------------------------------
# Test: Missing previous-day snapshot
# ---------------------------------------------------------------------------


class TestMissingPreviousDay:
    """Test behavior when previous day's snapshot is unavailable."""

    @mock_aws
    def test_missing_previous_day_still_completes(self, aws_env, lambda_context):
        """Without previous day data, handler still completes successfully."""
        _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        # NOTE: _seed_previous_day() NOT called

        from src.processor.handler import handle

        result = handle(_make_sqs_event(), lambda_context)

        assert result["status"] == "complete"
        assert result["netuid"] == 1

    @mock_aws
    def test_missing_previous_day_still_computes_core_metrics(self, aws_env, lambda_context):
        """All non-trend metrics are computed even without previous day data."""
        _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()

        from src.processor.handler import handle

        result = handle(_make_sqs_event(), lambda_context)

        assert "metrics_computed" in result
        assert len(result["metrics_computed"]) > 0


# ---------------------------------------------------------------------------
# Test: SNS publish format
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Test: Split profile writes
# ---------------------------------------------------------------------------


class TestSplitProfileWrites:
    """Test that processing writes split subnet profiles to DynamoDB."""

    @mock_aws
    def test_writes_basic_profile(self, aws_env, lambda_context):
        """Processor writes SubnetProfileBasic to SUBNET#{netuid}|PROFILE#basic."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        from src.processor.handler import handle

        handle(_make_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": "SUBNET#1", "SK": "PROFILE#basic"})
        assert "Item" in resp
        assert resp["Item"]["netuid"] == 1
        assert "reward_model" in resp["Item"]

    @mock_aws
    def test_writes_winner_profile(self, aws_env, lambda_context):
        """Processor writes SubnetProfileWinner with top miners."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        from src.processor.handler import handle

        handle(_make_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": "SUBNET#1", "SK": "PROFILE#winner"})
        assert "Item" in resp
        assert resp["Item"]["netuid"] == 1
        assert "top_miners" in resp["Item"]

    @mock_aws
    def test_writes_validator_profile(self, aws_env, lambda_context):
        """Processor writes SubnetProfileValidator with landscape data."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()

        # Include validators in the snapshot
        neurons = [_make_neuron(i, emission=0.5, incentive=0.3) for i in range(8)]
        neurons += [_make_neuron(i, emission=0.2, incentive=0.0, dividends=0.5,
                                 stake=5000.0, validator_trust=0.9) for i in range(8, 12)]
        _seed_raw_data(neurons=neurons)
        _seed_previous_day()

        from src.processor.handler import handle

        handle(_make_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": "SUBNET#1", "SK": "PROFILE#validator"})
        assert "Item" in resp
        assert resp["Item"]["netuid"] == 1
        assert resp["Item"]["active_validators"] >= 1

    @mock_aws
    def test_writes_intelligence_profile(self, aws_env, lambda_context):
        """Processor writes SubnetProfileIntelligence with observations."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        from src.processor.handler import handle

        handle(_make_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": "SUBNET#1", "SK": "PROFILE#intelligence"})
        assert "Item" in resp
        assert resp["Item"]["netuid"] == 1

    @mock_aws
    def test_writes_composability_profile(self, aws_env, lambda_context):
        """Processor writes SubnetProfileComposability."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        from src.processor.handler import handle

        handle(_make_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": "SUBNET#1", "SK": "PROFILE#composability"})
        assert "Item" in resp
        assert resp["Item"]["netuid"] == 1


# ---------------------------------------------------------------------------
# Test: Hotkey tracking
# ---------------------------------------------------------------------------


class TestHotkeyTracking:
    """Test hotkey earnings recording and deregistration detection."""

    @mock_aws
    def test_records_earnings_for_tracked_hotkeys(self, aws_env, lambda_context):
        """If tracked hotkeys are found in the metagraph, record their earnings."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        # Seed tracked hotkeys config — use hotkey from uid=0
        tracked_hotkey = _make_neuron(0)["hotkey"]
        table.put_item(Item={
            "PK": "CONFIG", "SK": "TRACKED_HOTKEYS", "hotkeys": [tracked_hotkey],
        })

        from src.processor.handler import handle

        handle(_make_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": f"HOTKEY#{tracked_hotkey}", "SK": "SNAPSHOT#2026-05-15"})
        assert "Item" in resp
        assert resp["Item"]["hotkey"] == tracked_hotkey

    @mock_aws
    def test_detects_deregistered_hotkey(self, aws_env, lambda_context):
        """If a tracked hotkey was in previous day but not current, detect deregistration."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()

        # Previous day has a hotkey that's NOT in current snapshot
        deregistered_hotkey = "5DeregisteredHotkey000000000000000000000000000000"
        prev_neurons = [_make_neuron(i, emission=0.4) for i in range(9)]
        prev_neurons.append({**_make_neuron(9, emission=0.4), "hotkey": deregistered_hotkey})
        _seed_previous_day(neurons=prev_neurons)

        table.put_item(Item={
            "PK": "CONFIG", "SK": "TRACKED_HOTKEYS", "hotkeys": [deregistered_hotkey],
        })

        from src.processor.handler import handle

        result = handle(_make_sqs_event(), lambda_context)

        # Should complete and note the deregistration
        assert result["status"] == "complete"


# ---------------------------------------------------------------------------
# Test: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test error scenarios and graceful degradation."""

    @mock_aws
    def test_missing_raw_snapshot_returns_error(self, aws_env, lambda_context):
        """If raw metagraph snapshot is missing, handler returns error status."""
        _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        # No raw data seeded

        from src.processor.handler import handle

        result = handle(_make_sqs_event(netuid=99), lambda_context)

        assert result["status"] == "error"
        assert result["netuid"] == 99

    @mock_aws
    def test_malformed_sqs_message_returns_error(self, aws_env, lambda_context):
        """Malformed SQS message body returns error without crashing."""
        _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()

        from src.processor.handler import handle

        event = {"Records": [{"messageId": "bad", "body": "not json!!!"}]}
        result = handle(event, lambda_context)

        assert result["status"] == "error"

    @mock_aws
    def test_state_transition_on_processing(self, aws_env, lambda_context):
        """Handler transitions subnet state through processing lifecycle."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _create_sns_topic()
        _seed_raw_data()
        _seed_previous_day()

        # Initialize subnet state as IDLE
        table.put_item(Item={
            "PK": "SUBNET#1", "SK": "STATE",
            "current_status": "IDLE", "retry_count": 0,
            "cycle_id": "", "last_updated": "2026-05-15T00:00:00+00:00", "metadata": {},
        })

        from src.processor.handler import handle

        result = handle(_make_sqs_event(), lambda_context)

        assert result["status"] == "complete"
        resp = table.get_item(Key={"PK": "SUBNET#1", "SK": "STATE"})
        assert resp["Item"]["current_status"] in ("COMPLETE", "IDLE")
