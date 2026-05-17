"""Unit tests for the Finalizer Lambda handler.

Tests cover:
- Cycle not complete → early exit (Req 5.1)
- Cycle complete → generates briefing + rankings (Req 5.1, 6.1)
- Briefing content: new subnets, emission changes >10%, deregistrations (Req 5.2)
- Rankings sorted by attractiveness score descending (Req 6.1, 6.2)
- Rankings stored to S3 and DynamoDB (Req 6.3)
- Cycle marked COMPLETE after finalization
- Error handling: malformed SQS message
"""

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, "lambda")
sys.path.insert(0, "lambda/src")


# ---------------------------------------------------------------------------
# Test Data Factories
# ---------------------------------------------------------------------------


def _make_derived_metrics(netuid: int, date: str, *,
                          net_tao_yield: float = 0.5,
                          days_to_recoup: float = 10.0,
                          competitive_density: float = 0.3,
                          emission_change: float = 0.05,
                          emission_direction: str = "stable") -> dict:
    """Create derived metrics as stored by the Processor."""
    return {
        "metadata": {
            "netuid": netuid,
            "source_snapshot_date": date,
            "computation_timestamp": f"{date}T01:00:00+00:00",
            "schema_version": "1.0.0",
            "pipeline_version": "1.0.0",
        },
        "data": {
            "deregistration_risk": [],
            "competitive_density": competitive_density,
            "emission_trend": {
                "current_total_emission": 10.0,
                "previous_total_emission": 10.0 / (1 + emission_change),
                "change_percent": emission_change,
                "direction": emission_direction,
            },
            "roi_estimate": {
                "net_tao_yield_per_day": net_tao_yield,
                "days_to_recoup": days_to_recoup,
                "thirty_day_projected_tao": net_tao_yield * 30 - 1.0,
                "alpha_tao_rate": 0.05,
                "slippage_estimate_percent": 0.01,
                "hold_vs_swap_recommendation": "SWAP",
                "confidence": "LOW",
            },
            "reward_distribution": {
                "model": "PROPORTIONAL",
                "gini_coefficient": 0.3,
                "top_3_concentration": 0.4,
            },
            "taoflow_health": {
                "status": "HEALTHY",
                "net_staking_flow_tao": 0.0,
                "consecutive_negative_days": 0,
            },
            "churn": {
                "daily_churn_rate": 0.05,
                "new_registrations": 2,
                "deregistrations": 1,
                "average_miner_lifespan_blocks": 50000.0,
                "competition_trend": "STABLE",
            },
            "validator_landscape": {
                "active_validators": 10,
                "total_validator_stake": 50000.0,
                "top_1_stake_share": 0.2,
                "top_3_stake_share": 0.5,
                "concentrated": False,
                "net_tao_yield_per_validator_per_day": 0.1,
            },
        },
    }


def _make_completion_sqs_event(netuid: int = 1, date: str = "2026-05-15",
                               cycle_id: str = "2026-05-15",
                               trace_id: str = "trace-fin-001") -> dict:
    """Create an SQS event matching SNS→SQS forwarded completion message."""
    sns_message = json.dumps({
        "netuid": netuid,
        "date": date,
        "cycle_id": cycle_id,
        "trace_id": trace_id,
        "status": "complete",
    })
    # SNS wraps the message in an envelope when forwarding to SQS
    body = json.dumps({"Message": sns_message})
    return {"Records": [{"messageId": "msg-fin-001", "body": body}]}


# ---------------------------------------------------------------------------
# Inline AWS Resource Helpers
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


def _seed_cycle_complete(table, cycle_id: str = "2026-05-15", subnets_total: int = 3):
    """Seed a cycle record that is complete (subnets_complete >= subnets_total)."""
    table.put_item(Item={
        "PK": f"CYCLE#{cycle_id}", "SK": "STATUS",
        "status": "COLLECTING", "subnets_total": subnets_total,
        "subnets_complete": subnets_total,
        "started_at": f"{cycle_id}T00:00:00+00:00",
    })


def _seed_cycle_incomplete(table, cycle_id: str = "2026-05-15",
                           subnets_total: int = 5, subnets_complete: int = 2):
    """Seed a cycle record that is NOT complete."""
    table.put_item(Item={
        "PK": f"CYCLE#{cycle_id}", "SK": "STATUS",
        "status": "COLLECTING", "subnets_total": subnets_total,
        "subnets_complete": subnets_complete,
        "started_at": f"{cycle_id}T00:00:00+00:00",
    })


def _seed_derived_metrics(date: str = "2026-05-15", netuids: list[int] = None):
    """Seed S3 with derived metrics for multiple subnets."""
    if netuids is None:
        netuids = [1, 2, 3]
    s3 = boto3.client("s3", region_name="us-east-1")
    bucket = os.environ.get("BUCKET_NAME", "tao-intelligence-test")

    for i, netuid in enumerate(netuids):
        # Vary metrics so rankings are deterministic
        metrics = _make_derived_metrics(
            netuid, date,
            net_tao_yield=1.0 - i * 0.3,  # SN1=1.0, SN2=0.7, SN3=0.4
            days_to_recoup=5.0 + i * 5.0,
            competitive_density=0.2 + i * 0.1,
            emission_change=0.15 if netuid == 2 else 0.03,  # SN2 has >10% change
            emission_direction="increasing" if netuid == 2 else "stable",
        )
        s3.put_object(
            Bucket=bucket,
            Key=f"derived/metrics/{date}/{netuid}.json",
            Body=json.dumps(metrics),
        )


def _seed_active_subnets(table, netuids: list[int] = None):
    """Seed CONFIG|ACTIVE_SUBNETS."""
    if netuids is None:
        netuids = [1, 2, 3]
    table.put_item(Item={
        "PK": "CONFIG", "SK": "ACTIVE_SUBNETS",
        "netuids": netuids, "last_updated": "2026-05-15T00:00:00+00:00",
    })


def _seed_previous_active_subnets(table, netuids: list[int]):
    """Seed previous day's active subnets for new subnet detection."""
    table.put_item(Item={
        "PK": "CONFIG", "SK": "PREVIOUS_ACTIVE_SUBNETS",
        "netuids": netuids, "last_updated": "2026-05-14T00:00:00+00:00",
    })


def _reset_handler():
    """Reset module-level cached state."""
    from src.finalizer import handler as handler_mod
    from src import config as config_mod
    handler_mod._config = None
    handler_mod._state_manager = None
    handler_mod._storage = None
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
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


@pytest.fixture
def lambda_context():
    """Mock Lambda context."""
    ctx = MagicMock()
    ctx.get_remaining_time_in_millis.return_value = 300_000
    return ctx


# ---------------------------------------------------------------------------
# Test: Cycle not complete → early exit
# ---------------------------------------------------------------------------


class TestEarlyExit:
    """Test that Finalizer exits early when cycle is not complete."""

    @mock_aws
    def test_incomplete_cycle_returns_early(self, aws_env, lambda_context):
        """If subnets_complete < subnets_total, return without generating outputs."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_incomplete(table, subnets_complete=2, subnets_total=5)

        from src.finalizer.handler import handle

        result = handle(_make_completion_sqs_event(), lambda_context)

        assert result["status"] == "waiting"
        assert result["cycle_id"] == "2026-05-15"

    @mock_aws
    def test_incomplete_cycle_does_not_write_to_s3(self, aws_env, lambda_context):
        """No rankings or briefings written when cycle is incomplete."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_incomplete(table)

        from src.finalizer.handler import handle

        handle(_make_completion_sqs_event(), lambda_context)

        s3 = boto3.client("s3", region_name="us-east-1")
        resp = s3.list_objects_v2(
            Bucket="tao-intelligence-test", Prefix="derived/rankings/")
        assert resp.get("KeyCount", 0) == 0


# ---------------------------------------------------------------------------
# Test: Cycle complete → generates briefing + rankings
# ---------------------------------------------------------------------------


class TestFinalization:
    """Test full finalization when cycle is complete."""

    @mock_aws
    def test_complete_cycle_generates_rankings(self, aws_env, lambda_context):
        """When all subnets done, rankings JSON is written to S3."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table)
        _seed_derived_metrics()

        from src.finalizer.handler import handle

        result = handle(_make_completion_sqs_event(), lambda_context)

        assert result["status"] == "complete"

        s3 = boto3.client("s3", region_name="us-east-1")
        resp = s3.get_object(Bucket="tao-intelligence-test",
                             Key="derived/rankings/2026-05-15.json")
        rankings = json.loads(resp["Body"].read())
        assert len(rankings) == 3

    @mock_aws
    def test_complete_cycle_generates_briefing(self, aws_env, lambda_context):
        """When all subnets done, briefing JSON is written to S3."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table)
        _seed_derived_metrics()

        from src.finalizer.handler import handle

        handle(_make_completion_sqs_event(), lambda_context)

        s3 = boto3.client("s3", region_name="us-east-1")
        resp = s3.get_object(Bucket="tao-intelligence-test",
                             Key="derived/briefings/2026-05-15.json")
        briefing = json.loads(resp["Body"].read())
        assert "date" in briefing
        assert briefing["date"] == "2026-05-15"
        assert "alerts" in briefing

    @mock_aws
    def test_marks_cycle_complete_in_dynamodb(self, aws_env, lambda_context):
        """After finalization, cycle status is set to COMPLETE."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table)
        _seed_derived_metrics()

        from src.finalizer.handler import handle

        handle(_make_completion_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": "CYCLE#2026-05-15", "SK": "STATUS"})
        assert resp["Item"]["status"] == "COMPLETE"

    @mock_aws
    def test_stores_ranking_latest_in_dynamodb(self, aws_env, lambda_context):
        """Rankings are stored at RANKING|LATEST in DynamoDB."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table)
        _seed_derived_metrics()

        from src.finalizer.handler import handle

        handle(_make_completion_sqs_event(), lambda_context)

        resp = table.get_item(Key={"PK": "RANKING", "SK": "LATEST"})
        assert "Item" in resp
        assert "ranked_subnets" in resp["Item"]


# ---------------------------------------------------------------------------
# Test: Briefing content
# ---------------------------------------------------------------------------


class TestBriefingContent:
    """Test that briefing includes correct alerts based on thresholds."""

    @mock_aws
    def test_briefing_includes_emission_change_alert(self, aws_env, lambda_context):
        """Subnets with >10% emission change appear in briefing alerts."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table)
        _seed_derived_metrics()  # SN2 has 15% emission change

        from src.finalizer.handler import handle

        handle(_make_completion_sqs_event(), lambda_context)

        s3 = boto3.client("s3", region_name="us-east-1")
        resp = s3.get_object(Bucket="tao-intelligence-test",
                             Key="derived/briefings/2026-05-15.json")
        briefing = json.loads(resp["Body"].read())

        emission_alerts = [a for a in briefing["alerts"]
                           if a["alert_type"] == "emission_change"]
        assert len(emission_alerts) >= 1
        assert any(a["netuid"] == 2 for a in emission_alerts)

    @mock_aws
    def test_briefing_includes_new_subnets(self, aws_env, lambda_context):
        """Newly discovered subnets appear in briefing."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        # Current active: [1, 2, 3], previous: [1, 2] → subnet 3 is new
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table, netuids=[1, 2, 3])
        _seed_previous_active_subnets(table, netuids=[1, 2])
        _seed_derived_metrics()

        from src.finalizer.handler import handle

        handle(_make_completion_sqs_event(), lambda_context)

        s3 = boto3.client("s3", region_name="us-east-1")
        resp = s3.get_object(Bucket="tao-intelligence-test",
                             Key="derived/briefings/2026-05-15.json")
        briefing = json.loads(resp["Body"].read())

        assert 3 in briefing.get("new_subnets", [])


# ---------------------------------------------------------------------------
# Test: Rankings sorted correctly
# ---------------------------------------------------------------------------


class TestRankingSorting:
    """Test that rankings are sorted by attractiveness score descending."""

    @mock_aws
    def test_rankings_sorted_by_attractiveness_descending(self, aws_env, lambda_context):
        """Subnet with highest net_tao_yield ranks first."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table)
        _seed_derived_metrics()  # SN1=1.0, SN2=0.7, SN3=0.4 yield

        from src.finalizer.handler import handle

        handle(_make_completion_sqs_event(), lambda_context)

        s3 = boto3.client("s3", region_name="us-east-1")
        resp = s3.get_object(Bucket="tao-intelligence-test",
                             Key="derived/rankings/2026-05-15.json")
        rankings = json.loads(resp["Body"].read())

        scores = [r["attractiveness_score"] for r in rankings]
        assert scores == sorted(scores, reverse=True)
        assert rankings[0]["netuid"] == 1  # Highest yield

    @mock_aws
    def test_ranking_entries_contain_required_fields(self, aws_env, lambda_context):
        """Each ranking entry has all fields from Req 6.4."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table)
        _seed_derived_metrics()

        from src.finalizer.handler import handle

        handle(_make_completion_sqs_event(), lambda_context)

        s3 = boto3.client("s3", region_name="us-east-1")
        resp = s3.get_object(Bucket="tao-intelligence-test",
                             Key="derived/rankings/2026-05-15.json")
        rankings = json.loads(resp["Body"].read())

        required_fields = {"netuid", "net_tao_yield", "days_to_recoup",
                           "competitive_density", "emission_trend",
                           "attractiveness_score"}
        for entry in rankings:
            assert required_fields.issubset(entry.keys())


# ---------------------------------------------------------------------------
# Test: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test error scenarios."""

    @mock_aws
    def test_malformed_sqs_message_returns_error(self, aws_env, lambda_context):
        """Malformed SQS message returns error without crashing."""
        _create_dynamodb_table()
        _create_s3_bucket()

        from src.finalizer.handler import handle

        event = {"Records": [{"messageId": "bad", "body": "not json!!!"}]}
        result = handle(event, lambda_context)

        assert result["status"] == "error"

    @mock_aws
    def test_missing_derived_metrics_still_completes(self, aws_env, lambda_context):
        """If some subnets have no derived metrics, finalization still completes."""
        table = _create_dynamodb_table()
        _create_s3_bucket()
        _seed_cycle_complete(table, subnets_total=3)
        _seed_active_subnets(table, netuids=[1, 2, 3])
        # Only seed metrics for subnet 1 — 2 and 3 are missing
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.put_object(
            Bucket="tao-intelligence-test",
            Key="derived/metrics/2026-05-15/1.json",
            Body=json.dumps(_make_derived_metrics(1, "2026-05-15")),
        )

        from src.finalizer.handler import handle

        result = handle(_make_completion_sqs_event(), lambda_context)

        assert result["status"] == "complete"
