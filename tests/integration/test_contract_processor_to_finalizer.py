"""Contract smoke test: Processor output → Finalizer consumption.

No hand-crafted mocks between components. Runs the real Processor, captures
its actual S3 output, and feeds it to the real Finalizer ranking/briefing
generators. If any field is renamed, retyped, or removed, this test breaks.

Phase A of the contract test strategy (see kb/backlog.md #9).
"""

import json
import os
from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws


def _setup_infra():
    """Create DynamoDB table and S3 bucket inside mock_aws context."""
    os.environ.update({
        "PIPELINE_ENV": "aws",
        "AWS_DEFAULT_REGION": "us-east-1",
        "TABLE_NAME": "tao-contract-test",
        "BUCKET_NAME": "tao-contract-test",
        "SUBNET_PROCESSED_TOPIC_ARN": "",
        "SUBNET_COLLECTOR_ARN": "",
        "SCHEDULER_ROLE_ARN": "",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
    })
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="tao-contract-test",
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
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="tao-contract-test")


def _seed_raw_data():
    """Seed realistic raw data for Processor to consume."""
    s3 = boto3.client("s3", region_name="us-east-1")
    bucket = "tao-contract-test"
    date = "2026-05-25"
    netuid = 1

    # 10 neurons: 3 earning miners, 2 validators, 5 zero-emission
    neurons = []
    for i in range(3):
        neurons.append({
            "uid": i, "hotkey": f"5HotMiner{i:04d}", "coldkey": f"5ColdMiner{i:04d}",
            "stake": 100.0, "incentive": 0.3, "emission": 0.005 - i * 0.001,
            "consensus": 0.5, "validator_trust": 0.0, "dividends": 0.0,
            "active": True, "alpha_stake": 0.0, "total_stake": 100.0,
            "block_at_registration": 4000000,
        })
    for i in range(2):
        neurons.append({
            "uid": 3 + i, "hotkey": f"5HotVal{i:04d}", "coldkey": f"5ColdVal{i:04d}",
            "stake": 50000.0, "incentive": 0.0, "emission": 0.002,
            "consensus": 0.0, "validator_trust": 0.85, "dividends": 0.3,
            "active": True, "alpha_stake": 50000.0, "total_stake": 50000.0,
            "block_at_registration": 3000000,
        })
    for i in range(5):
        neurons.append({
            "uid": 5 + i, "hotkey": f"5HotZero{i:04d}", "coldkey": f"5ColdZero{i:04d}",
            "stake": 0.0, "incentive": 0.0, "emission": 0.0,
            "consensus": 0.0, "validator_trust": 0.0, "dividends": 0.0,
            "active": True, "alpha_stake": 0.0, "total_stake": 0.0,
            "block_at_registration": 4900000,
        })

    snapshot = {
        "metadata": {
            "netuid": netuid, "cycle_id": date,
            "collected_at": f"{date}T00:05:00+00:00",
            "source_block_number": 8000000,
            "neuron_count": len(neurons),
            "num_uids": len(neurons), "max_uids": len(neurons),
        },
        "data": {"neurons": neurons},
    }
    alpha = {"metadata": {}, "data": {"alpha_tao_price": 0.05, "pool_tao_liquidity": 2000.0}}
    reg = {"metadata": {}, "data": {"registration_cost_tao": 0.5}}
    hyper = {"metadata": {}, "data": {"tempo": 360, "immunity_period": 7200}}

    s3.put_object(Bucket=bucket, Key=f"raw/metagraph/{date}/{netuid}.json", Body=json.dumps(snapshot))
    s3.put_object(Bucket=bucket, Key=f"raw/alpha-prices/{date}/{netuid}.json", Body=json.dumps(alpha))
    s3.put_object(Bucket=bucket, Key=f"raw/registration-costs/{date}/{netuid}.json", Body=json.dumps(reg))
    s3.put_object(Bucket=bucket, Key=f"raw/hyperparameters/{date}/{netuid}.json", Body=json.dumps(hyper))


def _reset_modules():
    """Reset cached module state."""
    from src.processor import handler as proc_mod
    from src.finalizer import handler as fin_mod
    from src import config as config_mod
    proc_mod._config = None
    proc_mod._state_manager = None
    proc_mod._storage = None
    proc_mod._sns_client = None
    fin_mod._config = None
    fin_mod._state_manager = None
    fin_mod._storage = None
    config_mod.reset_config()


def _run_processor() -> dict:
    """Run the real Processor and return its derived output from S3."""
    from src.processor.handler import handle

    event = {"Records": [{"body": json.dumps({
        "netuid": 1, "date": "2026-05-25",
        "cycle_id": "2026-05-25", "trace_id": "contract-test",
    })}]}
    result = handle(event, None)
    assert result["status"] == "complete", f"Processor failed: {result}"

    s3 = boto3.client("s3", region_name="us-east-1")
    obj = s3.get_object(Bucket="tao-contract-test", Key="derived/metrics/2026-05-25/1.json")
    return json.loads(obj["Body"].read())


class TestProcessorToFinalizerContract:
    """Processor output must be directly consumable by Finalizer without errors."""

    @mock_aws
    def test_processor_output_feeds_generate_rankings(self):
        """_generate_rankings must consume Processor output without exceptions."""
        _setup_infra()
        _seed_raw_data()
        _reset_modules()

        derived = _run_processor()

        # Feed real Processor output to real Finalizer ranking generator
        _reset_modules()  # Reset so Finalizer gets fresh config
        from src.finalizer.handler import _generate_rankings

        all_metrics = {1: derived}
        rankings = _generate_rankings(all_metrics)

        # Contract assertions
        assert len(rankings) == 1
        entry = rankings[0]
        assert entry["netuid"] == 1
        assert isinstance(entry["attractiveness_score"], float)
        assert 0.0 <= entry["attractiveness_score"] <= 1.0
        assert isinstance(entry["self_mining_risk"], float)
        assert isinstance(entry["real_apy_percent"], float)
        assert isinstance(entry["net_tao_yield"], float)
        assert entry["net_tao_yield"] >= 0

    @mock_aws
    def test_processor_output_feeds_generate_staking_rankings(self):
        """_generate_staking_rankings must consume Processor output without exceptions."""
        _setup_infra()
        _seed_raw_data()
        _reset_modules()

        derived = _run_processor()

        _reset_modules()
        from src.finalizer.handler import _generate_staking_rankings

        all_metrics = {1: derived}
        staking = _generate_staking_rankings(all_metrics)

        # Contract assertions — should produce a result (validators exist in our data)
        assert len(staking) == 1
        entry = staking[0]
        assert entry["netuid"] == 1
        assert isinstance(entry["net_apy_percent"], float)
        assert entry["net_apy_percent"] >= 0
        assert isinstance(entry["entry_slippage_10tao"], float)

    @mock_aws
    def test_processor_output_feeds_generate_briefing(self):
        """_generate_briefing must consume Processor output without exceptions."""
        _setup_infra()
        _seed_raw_data()
        _reset_modules()

        derived = _run_processor()

        _reset_modules()
        from src.finalizer.handler import _generate_briefing, _init_clients
        _init_clients()

        all_metrics = {1: derived}
        briefing = _generate_briefing("2026-05-25", "2026-05-25", all_metrics, [1])

        # Contract assertions
        assert "alerts" in briefing
        assert "date" in briefing
        assert briefing["date"] == "2026-05-25"
        assert isinstance(briefing["alerts"], list)

    @mock_aws
    def test_derived_output_has_all_expected_fields(self):
        """Processor derived output must contain all fields that Finalizer reads."""
        _setup_infra()
        _seed_raw_data()
        _reset_modules()

        derived = _run_processor()
        data = derived["data"]
        metadata = derived["metadata"]

        # Fields the Finalizer reads from metadata
        assert "source_block_number" in metadata
        assert "processed_at" in metadata

        # Fields the Finalizer reads from data
        assert "roi_estimate" in data
        assert "emission_trend" in data
        assert "self_mining_risk" in data
        assert "concentration_risk" in data
        assert "real_apy_percent" in data
        assert "validator_landscape" in data
        assert "competitive_density" in data

        # ROI sub-fields the Finalizer reads
        roi = data["roi_estimate"]
        assert "net_tao_yield_per_day" in roi
        assert "alpha_tao_rate" in roi
        assert "pool_tao_liquidity" in roi
        assert "days_to_recoup" in roi
        assert "thirty_day_projected_tao" in roi

        # Self-mining risk sub-fields
        sm = data["self_mining_risk"]
        assert "risk_score" in sm
        assert isinstance(sm["risk_score"], float)

        # Concentration risk sub-fields
        cr = data["concentration_risk"]
        assert "risk" in cr
        assert "tier" in cr

        # Emission trend sub-fields
        et = data["emission_trend"]
        assert "change_percent" in et
        assert "current_total_emission" in et

        # Validator landscape sub-fields
        vl = data["validator_landscape"]
        assert "active_validators" in vl
        assert "total_validator_stake" in vl
        assert "top_1_stake_share" in vl
        assert "avg_vtrust" in vl
        assert "min_vtrust" in vl
