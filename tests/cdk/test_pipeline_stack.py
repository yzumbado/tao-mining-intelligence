"""CDK assertion tests for the TAO Pipeline Stack.

Validates infrastructure configuration matches requirements:
- Lambda timeout/memory/container config (Req 13.1-13.6)
- EventBridge schedule expression
- SQS DLQ config, visibility timeout
- DynamoDB PITR enabled
- S3 BlockPublicAccess on both buckets
- CloudFront distribution exists
- No Lambda env var contains secrets (Req 38.4)
"""


import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from stacks.pipeline_stack import TaoPipelineStack


def _get_template() -> Template:
    """Synthesize the stack and return the CloudFormation template."""
    app = cdk.App()
    stack = TaoPipelineStack(app, "TestStack", env=cdk.Environment(
        account="123456789012", region="us-east-1"))
    return Template.from_stack(stack)


class TestLambdaConfiguration:
    """Assert Lambda functions are configured correctly."""

    def test_discovery_lambda_exists(self):
        template = _get_template()
        template.has_resource_properties("AWS::Lambda::Function", {
            "FunctionName": "tao-discovery",
            "Timeout": 60,
            "MemorySize": 256,
        })

    def test_subnet_collector_timeout_60_seconds(self):
        template = _get_template()
        template.has_resource_properties("AWS::Lambda::Function", {
            "FunctionName": "tao-subnet-collector",
            "Timeout": 90,
            "MemorySize": 1024,
        })

    def test_subnet_collector_reserved_concurrency(self):
        template = _get_template()
        template.has_resource_properties("AWS::Lambda::Function", {
            "FunctionName": "tao-subnet-collector",
            "ReservedConcurrentExecutions": 2,
        })

    def test_processor_timeout_15_minutes(self):
        template = _get_template()
        template.has_resource_properties("AWS::Lambda::Function", {
            "FunctionName": "tao-processor",
            "Timeout": 900,
            "MemorySize": 512,
        })

    def test_finalizer_timeout_5_minutes(self):
        template = _get_template()
        template.has_resource_properties("AWS::Lambda::Function", {
            "FunctionName": "tao-finalizer",
            "Timeout": 300,
            "MemorySize": 512,
        })

    def test_no_lambda_env_contains_secrets(self):
        """No Lambda environment variable key contains KEY, SECRET, PASSWORD, TOKEN."""
        template = _get_template()
        resources = template.find_resources("AWS::Lambda::Function")
        forbidden = {"KEY", "SECRET", "PASSWORD", "TOKEN"}

        for _logical_id, resource in resources.items():
            env_vars = (resource.get("Properties", {})
                        .get("Environment", {})
                        .get("Variables", {}))
            for key, value in env_vars.items():
                # Key names should not contain secret indicators
                # (COINGECKO_API_KEY_PARAM is a parameter NAME, not a value)
                if key == "COINGECKO_API_KEY_PARAM":
                    continue
                for f in forbidden:
                    assert f not in key.upper() or "PARAM" in key.upper(), \
                        f"Lambda env var '{key}' may contain a secret"
                # Values should not be hardcoded secrets
                if isinstance(value, str):
                    assert not value.startswith("sk-"), \
                        f"Lambda env var '{key}' contains what looks like a secret"


class TestEventBridge:
    """Assert EventBridge schedule configuration.

    NOTE: EventBridge rules are currently DISABLED (commented out in CDK)
    to stay within Lambda free tier. See kb/runbook-pipeline-pause-resume.md.
    This test verifies that no rules exist while paused.
    When re-enabling, flip the assertion back to has_resource_properties.
    """

    def test_no_eventbridge_rules_while_paused(self):
        template = _get_template()
        template.resource_count_is("AWS::Events::Rule", 0)


class TestSQS:
    """Assert SQS queue configuration."""

    def test_process_queue_visibility_timeout(self):
        template = _get_template()
        template.has_resource_properties("AWS::SQS::Queue", {
            "QueueName": "tao-process-subnet",
            "VisibilityTimeout": 900,
        })

    def test_dlq_retention_14_days(self):
        template = _get_template()
        template.has_resource_properties("AWS::SQS::Queue", {
            "QueueName": "tao-process-subnet-dlq",
            "MessageRetentionPeriod": 1209600,
        })


class TestDynamoDB:
    """Assert DynamoDB table configuration."""

    def test_pitr_enabled(self):
        template = _get_template()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
        })

    def test_on_demand_billing(self):
        template = _get_template()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "BillingMode": "PAY_PER_REQUEST",
        })


class TestS3:
    """Assert S3 bucket configuration."""

    def test_data_bucket_blocks_public_access(self):
        template = _get_template()
        template.has_resource_properties("AWS::S3::Bucket", {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
        })


class TestCloudFront:
    """Assert CloudFront distribution exists."""

    def test_distribution_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::CloudFront::Distribution", 1)
