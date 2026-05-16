"""Pipeline configuration with PIPELINE_ENV switching logic.

Environment switching:
- PIPELINE_ENV=local: Use local filesystem for storage, print for logging,
  DynamoDB Local for state, in-memory queues for messaging.
- PIPELINE_ENV=aws: Use S3, DynamoDB, SQS, SNS, Parameter Store, CloudWatch.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class StorageConfig:
    """Storage layer configuration."""

    bucket_name: str
    local_output_dir: str = "./output"


@dataclass(frozen=True)
class DynamoDBConfig:
    """DynamoDB configuration."""

    table_name: str
    endpoint_url: Optional[str] = None  # Set for DynamoDB Local


@dataclass(frozen=True)
class QueueConfig:
    """SQS/SNS messaging configuration."""

    process_queue_url: str = ""
    completion_queue_url: str = ""
    subnet_processed_topic_arn: str = ""


@dataclass(frozen=True)
class PipelineConfig:
    """Complete pipeline configuration."""

    env: str
    storage: StorageConfig
    dynamodb: DynamoDBConfig
    queue: QueueConfig
    region: str = "us-east-1"
    log_level: str = "INFO"

    @property
    def is_local(self) -> bool:
        return self.env == "local"

    @property
    def is_aws(self) -> bool:
        return self.env == "aws"


def get_pipeline_env() -> str:
    """Read PIPELINE_ENV from environment, defaulting to 'local'."""
    return os.environ.get("PIPELINE_ENV", "local")


def load_config() -> PipelineConfig:
    """Load pipeline configuration based on PIPELINE_ENV.

    When 'local':
      - Storage uses local filesystem (./output/)
      - DynamoDB uses DynamoDB Local (localhost:8000)
      - Queues are disabled (direct function invocation)
      - Logging uses print statements

    When 'aws':
      - Storage uses S3
      - DynamoDB uses real AWS DynamoDB
      - Queues use SQS/SNS
      - Logging uses CloudWatch
    """
    env = get_pipeline_env()

    if env == "local":
        return PipelineConfig(
            env="local",
            storage=StorageConfig(
                bucket_name="local",
                local_output_dir=os.environ.get("LOCAL_OUTPUT_DIR", "./output"),
            ),
            dynamodb=DynamoDBConfig(
                table_name=os.environ.get("TABLE_NAME", "tao-pipeline-local"),
                endpoint_url=os.environ.get("DYNAMODB_ENDPOINT", "http://localhost:8000"),
            ),
            queue=QueueConfig(),
            region=os.environ.get("AWS_REGION", "us-east-1"),
            log_level=os.environ.get("LOG_LEVEL", "DEBUG"),
        )

    # AWS environment
    return PipelineConfig(
        env="aws",
        storage=StorageConfig(
            bucket_name=os.environ.get("BUCKET_NAME", "tao-intelligence"),
        ),
        dynamodb=DynamoDBConfig(
            table_name=os.environ.get("TABLE_NAME", "tao-pipeline"),
        ),
        queue=QueueConfig(
            process_queue_url=os.environ.get("PROCESS_QUEUE_URL", ""),
            completion_queue_url=os.environ.get("COMPLETION_QUEUE_URL", ""),
            subnet_processed_topic_arn=os.environ.get("SUBNET_PROCESSED_TOPIC_ARN", ""),
        ),
        region=os.environ.get("AWS_REGION", "us-east-1"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )


# Module-level singleton — loaded once per Lambda cold start
_config: Optional[PipelineConfig] = None


def get_config() -> PipelineConfig:
    """Get the pipeline configuration singleton.

    Config is loaded once and cached for the lifetime of the Lambda execution
    environment (cold start caching).
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the config singleton. Used in tests."""
    global _config
    _config = None
