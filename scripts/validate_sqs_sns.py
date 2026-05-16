"""Task 1.4: Validate SQS/SNS messaging with moto.

Tests the orchestration pattern:
- Collector publishes to SQS process-subnet queue
- Processor receives from queue, publishes to SNS subnet-processed
- SNS fans out to completion-tracker queue
- Finalizer receives from completion-tracker

Run: python scripts/validate_sqs_sns.py
"""

import json
from datetime import datetime, timezone

import boto3
from moto import mock_aws


@mock_aws
def test_full_orchestration_flow():
    """Test the complete SQS/SNS orchestration pattern."""
    print("=== TEST: Full Orchestration Flow ===")

    region = "us-east-1"
    sqs = boto3.client("sqs", region_name=region)
    sns = boto3.client("sns", region_name=region)

    # 1. Create process-subnet queue + DLQ
    dlq = sqs.create_queue(QueueName="process-subnet-dlq")
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq["QueueUrl"], AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    process_queue = sqs.create_queue(
        QueueName="process-subnet",
        Attributes={
            "VisibilityTimeout": "900",
            "RedrivePolicy": json.dumps({
                "deadLetterTargetArn": dlq_arn,
                "maxReceiveCount": "3",
            }),
        },
    )
    print(f"  ✓ Created process-subnet queue with DLQ (maxReceiveCount=3)")

    # 2. Create SNS topic
    topic = sns.create_topic(Name="subnet-processed")
    topic_arn = topic["TopicArn"]
    print(f"  ✓ Created subnet-processed SNS topic")

    # 3. Create completion-tracker queue subscribed to SNS
    completion_queue = sqs.create_queue(QueueName="completion-tracker")
    completion_arn = sqs.get_queue_attributes(
        QueueUrl=completion_queue["QueueUrl"], AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    sns.subscribe(
        TopicArn=topic_arn,
        Protocol="sqs",
        Endpoint=completion_arn,
    )
    print(f"  ✓ Subscribed completion-tracker queue to SNS topic")

    # 4. Simulate Collector: publish messages to process-subnet queue
    cycle_id = "2026-05-15"
    subnets_to_process = [1, 4, 8, 13, 19]

    for netuid in subnets_to_process:
        sqs.send_message(
            QueueUrl=process_queue["QueueUrl"],
            MessageBody=json.dumps({
                "netuid": netuid,
                "date": cycle_id,
                "cycle_id": cycle_id,
                "action": "process_subnet",
            }),
        )
    print(f"  ✓ Collector published {len(subnets_to_process)} messages to process-subnet queue")

    # 5. Simulate Processor: receive from queue
    messages_received = 0
    for _ in range(len(subnets_to_process)):
        resp = sqs.receive_message(
            QueueUrl=process_queue["QueueUrl"],
            MaxNumberOfMessages=1,
        )
        if "Messages" in resp:
            msg = json.loads(resp["Messages"][0]["Body"])
            messages_received += 1

            # Delete message (acknowledge processing)
            sqs.delete_message(
                QueueUrl=process_queue["QueueUrl"],
                ReceiptHandle=resp["Messages"][0]["ReceiptHandle"],
            )

            # Publish completion to SNS
            sns.publish(
                TopicArn=topic_arn,
                Message=json.dumps({
                    "netuid": msg["netuid"],
                    "cycle_id": msg["cycle_id"],
                    "status": "COMPLETE",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }),
            )

    print(f"  ✓ Processor received and processed {messages_received} messages")
    assert messages_received == len(subnets_to_process)

    # 6. Simulate Finalizer: receive from completion-tracker
    completion_messages = 0
    for _ in range(10):  # Try up to 10 receives
        resp = sqs.receive_message(
            QueueUrl=completion_queue["QueueUrl"],
            MaxNumberOfMessages=10,
        )
        if "Messages" in resp:
            for msg in resp["Messages"]:
                # SNS wraps the message in an envelope
                body = json.loads(msg["Body"])
                if "Message" in body:
                    payload = json.loads(body["Message"])
                else:
                    payload = body
                completion_messages += 1
                sqs.delete_message(
                    QueueUrl=completion_queue["QueueUrl"],
                    ReceiptHandle=msg["ReceiptHandle"],
                )
        else:
            break

    print(f"  ✓ Finalizer received {completion_messages} completion messages")
    assert completion_messages == len(subnets_to_process)

    # 7. Verify DLQ is empty (no failures)
    dlq_attrs = sqs.get_queue_attributes(
        QueueUrl=dlq["QueueUrl"],
        AttributeNames=["ApproximateNumberOfMessages"],
    )
    dlq_count = int(dlq_attrs["Attributes"]["ApproximateNumberOfMessages"])
    assert dlq_count == 0
    print(f"  ✓ DLQ is empty (no failures): {dlq_count} messages")

    print("  PASSED ✓\n")


@mock_aws
def test_message_format():
    """Test that message format matches expected schema."""
    print("=== TEST: Message Format Validation ===")

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue = sqs.create_queue(QueueName="test-queue")

    # Test process-subnet message format
    msg = {
        "netuid": 1,
        "date": "2026-05-15",
        "cycle_id": "2026-05-15",
        "action": "process_subnet",
    }
    sqs.send_message(QueueUrl=queue["QueueUrl"], MessageBody=json.dumps(msg))

    resp = sqs.receive_message(QueueUrl=queue["QueueUrl"], MaxNumberOfMessages=1)
    received = json.loads(resp["Messages"][0]["Body"])

    assert "netuid" in received
    assert "date" in received
    assert "cycle_id" in received
    assert isinstance(received["netuid"], int)
    assert isinstance(received["date"], str)
    print(f"  ✓ Process-subnet message format valid: netuid={received['netuid']}, date={received['date']}")

    # Test completion message format
    completion_msg = {
        "netuid": 1,
        "cycle_id": "2026-05-15",
        "status": "COMPLETE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    sqs.send_message(QueueUrl=queue["QueueUrl"], MessageBody=json.dumps(completion_msg))

    resp = sqs.receive_message(QueueUrl=queue["QueueUrl"], MaxNumberOfMessages=1)
    received = json.loads(resp["Messages"][0]["Body"])

    assert received["status"] == "COMPLETE"
    assert "timestamp" in received
    print(f"  ✓ Completion message format valid: status={received['status']}")

    print("  PASSED ✓\n")


def main():
    print("TAO Pipeline - SQS/SNS Orchestration Validation (moto)")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n")

    test_full_orchestration_flow()
    test_message_format()

    print("=" * 60)
    print("ALL SQS/SNS TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
