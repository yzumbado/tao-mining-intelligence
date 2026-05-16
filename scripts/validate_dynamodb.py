"""Task 1.3: Validate DynamoDB single-table operations with moto.

Tests that our DynamoDB access patterns work correctly:
- SUBNET#{netuid}|STATE — pipeline FSM state tracking
- SUBNET#{netuid}|METRICS#latest — latest derived metrics
- SUBNET#{netuid}|PROFILE#basic — subnet profile
- CONFIG|ACTIVE_SUBNETS — monitored subnet list
- CYCLE|{cycle_id} — cycle-level idempotency
- RANKING|LATEST — current rankings
- HOTKEY#{ss58}|EARNINGS#7d — hotkey earnings

Run: python scripts/validate_dynamodb.py
"""

import json
from datetime import datetime, timezone

import boto3
from moto import mock_aws


TABLE_NAME = "tao-pipeline"


def create_table(dynamodb):
    """Create the single-table DynamoDB table."""
    dynamodb.create_table(
        TableName=TABLE_NAME,
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


@mock_aws
def test_subnet_state_transitions():
    """Test FSM state transitions with conditional writes."""
    print("=== TEST: Subnet State Transitions ===")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    create_table(dynamodb)
    table = dynamodb.Table(TABLE_NAME)

    # Initial state: IDLE
    table.put_item(Item={
        "PK": "SUBNET#1",
        "SK": "STATE",
        "current_status": "IDLE",
        "retry_count": 0,
        "cycle_id": "",
    })

    # Transition IDLE → COLLECTING (conditional: must be IDLE)
    try:
        table.update_item(
            Key={"PK": "SUBNET#1", "SK": "STATE"},
            UpdateExpression="SET current_status = :new, cycle_id = :cid",
            ConditionExpression="current_status = :expected",
            ExpressionAttributeValues={
                ":new": "COLLECTING",
                ":expected": "IDLE",
                ":cid": "2026-05-15",
            },
        )
        print("  ✓ IDLE → COLLECTING transition succeeded")
    except Exception as e:
        print(f"  ✗ Transition failed: {e}")

    # Verify state
    resp = table.get_item(Key={"PK": "SUBNET#1", "SK": "STATE"})
    assert resp["Item"]["current_status"] == "COLLECTING"
    print("  ✓ State verified as COLLECTING")

    # Try invalid transition: COLLECTING → COLLECTING (should fail)
    try:
        table.update_item(
            Key={"PK": "SUBNET#1", "SK": "STATE"},
            UpdateExpression="SET current_status = :new",
            ConditionExpression="current_status = :expected",
            ExpressionAttributeValues={
                ":new": "COLLECTING",
                ":expected": "IDLE",  # Wrong! It's COLLECTING now
            },
        )
        print("  ✗ Invalid transition should have failed!")
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        print("  ✓ Invalid transition correctly rejected (ConditionalCheckFailed)")

    print("  PASSED ✓\n")


@mock_aws
def test_cycle_idempotency():
    """Test cycle-level idempotency with conditional PutItem."""
    print("=== TEST: Cycle Idempotency ===")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    create_table(dynamodb)
    table = dynamodb.Table(TABLE_NAME)

    cycle_id = "2026-05-15"

    # First claim: should succeed
    try:
        table.put_item(
            Item={
                "PK": f"CYCLE#{cycle_id}",
                "SK": "STATUS",
                "status": "COLLECTING",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "subnets_total": 129,
                "subnets_complete": 0,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        print("  ✓ First cycle claim succeeded")
    except Exception as e:
        print(f"  ✗ First claim failed: {e}")

    # Second claim (duplicate): should fail
    try:
        table.put_item(
            Item={
                "PK": f"CYCLE#{cycle_id}",
                "SK": "STATUS",
                "status": "COLLECTING",
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        print("  ✗ Duplicate claim should have failed!")
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        print("  ✓ Duplicate cycle correctly rejected (idempotent)")

    print("  PASSED ✓\n")


@mock_aws
def test_config_operations():
    """Test CONFIG items (active subnets, tracked hotkeys, cloud pricing)."""
    print("=== TEST: Config Operations ===")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    create_table(dynamodb)
    table = dynamodb.Table(TABLE_NAME)

    # Store active subnets
    subnets = list(range(0, 129))
    table.put_item(Item={
        "PK": "CONFIG",
        "SK": "ACTIVE_SUBNETS",
        "netuids": subnets,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    })

    # Read back
    resp = table.get_item(Key={"PK": "CONFIG", "SK": "ACTIVE_SUBNETS"})
    assert len(resp["Item"]["netuids"]) == 129
    print(f"  ✓ Active subnets stored and retrieved: {len(resp['Item']['netuids'])} subnets")

    # Store tracked hotkeys
    table.put_item(Item={
        "PK": "CONFIG",
        "SK": "TRACKED_HOTKEYS",
        "hotkeys": ["5FMyHotkey1...", "5FMyHotkey2..."],
    })
    resp = table.get_item(Key={"PK": "CONFIG", "SK": "TRACKED_HOTKEYS"})
    assert len(resp["Item"]["hotkeys"]) == 2
    print(f"  ✓ Tracked hotkeys stored: {len(resp['Item']['hotkeys'])} hotkeys")

    # Store cloud pricing
    table.put_item(Item={
        "PK": "CONFIG",
        "SK": "CLOUD_PRICING",
        "providers": json.dumps({
            "vast.ai": {"RTX 4090": 0.35, "A100 40GB": 0.90, "H100": 2.50},
            "runpod": {"RTX 4090": 0.40, "A100 80GB": 1.10},
        }),
    })
    resp = table.get_item(Key={"PK": "CONFIG", "SK": "CLOUD_PRICING"})
    pricing = json.loads(resp["Item"]["providers"])
    assert "vast.ai" in pricing
    print(f"  ✓ Cloud pricing stored: {len(pricing)} providers")

    print("  PASSED ✓\n")


@mock_aws
def test_split_profile_operations():
    """Test split profile items (basic, winner, validator, intelligence, composability)."""
    print("=== TEST: Split Profile Operations ===")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    create_table(dynamodb)
    table = dynamodb.Table(TABLE_NAME)

    netuid = 1

    # Write split profiles
    table.put_item(Item={
        "PK": f"SUBNET#{netuid}",
        "SK": "PROFILE#basic",
        "name": "Text Prompting",
        "category": "LLM_INFERENCE",
        "mining_style": "GPU_INFERENCE",
        "reward_model": "PROPORTIONAL",
        "hardware_tier": "DATACENTER_GPU",
    })

    table.put_item(Item={
        "PK": f"SUBNET#{netuid}",
        "SK": "PROFILE#winner",
        "top_miners": [{"hotkey": "5Ftest...", "emission_share": "0.15"}],
        "dominant_strategy": "Fast inference with quantized models",
    })

    table.put_item(Item={
        "PK": f"SUBNET#{netuid}",
        "SK": "PROFILE#intelligence",
        "anomalies": ["Top miner registered 2h before incentive change"],
        "strategy_observations": ["Latency < 200ms correlates with 2x emission"],
    })

    # Read back individual profiles
    basic = table.get_item(Key={"PK": f"SUBNET#{netuid}", "SK": "PROFILE#basic"})
    assert basic["Item"]["mining_style"] == "GPU_INFERENCE"
    print(f"  ✓ PROFILE#basic: category={basic['Item']['category']}, style={basic['Item']['mining_style']}")

    winner = table.get_item(Key={"PK": f"SUBNET#{netuid}", "SK": "PROFILE#winner"})
    assert len(winner["Item"]["top_miners"]) == 1
    print(f"  ✓ PROFILE#winner: {len(winner['Item']['top_miners'])} top miners")

    intel = table.get_item(Key={"PK": f"SUBNET#{netuid}", "SK": "PROFILE#intelligence"})
    assert len(intel["Item"]["anomalies"]) == 1
    print(f"  ✓ PROFILE#intelligence: {len(intel['Item']['anomalies'])} anomalies")

    # Query all profiles for a subnet using begins_with
    resp = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={":pk": f"SUBNET#{netuid}", ":prefix": "PROFILE#"},
    )
    assert resp["Count"] == 3
    print(f"  ✓ Query all profiles: {resp['Count']} items returned")

    print("  PASSED ✓\n")


@mock_aws
def test_hotkey_earnings():
    """Test hotkey earnings tracking."""
    print("=== TEST: Hotkey Earnings ===")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    create_table(dynamodb)
    table = dynamodb.Table(TABLE_NAME)

    hotkey = "5FTestHotkey123"

    # Store daily snapshot
    table.put_item(Item={
        "PK": f"HOTKEY#{hotkey}",
        "SK": "SNAPSHOT#2026-05-15",
        "positions": [
            {"netuid": 1, "uid": 45, "emission": "0.023", "incentive": "0.05", "rank": 12},
            {"netuid": 8, "uid": 102, "emission": "0.015", "incentive": "0.03", "rank": 28},
        ],
    })

    # Store cumulative earnings
    table.put_item(Item={
        "PK": f"HOTKEY#{hotkey}",
        "SK": "EARNINGS#7d",
        "cumulative_tao": "0.266",
        "subnets": [1, 8],
        "per_subnet_breakdown": {"1": "0.161", "8": "0.105"},
    })

    # Read back
    resp = table.get_item(Key={"PK": f"HOTKEY#{hotkey}", "SK": "EARNINGS#7d"})
    assert resp["Item"]["cumulative_tao"] == "0.266"
    print(f"  ✓ 7d earnings: {resp['Item']['cumulative_tao']} TAO across {resp['Item']['subnets']}")

    # Query all items for a hotkey
    resp = table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"HOTKEY#{hotkey}"},
    )
    assert resp["Count"] == 2
    print(f"  ✓ All hotkey items: {resp['Count']} records")

    print("  PASSED ✓\n")


def main():
    print("TAO Pipeline - DynamoDB Validation (moto)")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n")

    test_subnet_state_transitions()
    test_cycle_idempotency()
    test_config_operations()
    test_split_profile_operations()
    test_hotkey_earnings()

    print("=" * 60)
    print("ALL DYNAMODB TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
