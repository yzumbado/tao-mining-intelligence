"""CDK Stack for TAO Mining Intelligence Pipeline.

All resources designed for AWS free tier ($0/month):
- Lambda: Container Image, 512MB, 15min timeout (1M free requests/month)
- DynamoDB: On-demand, single table (25GB free, 25 WCU/RCU)
- S3: Two buckets (5GB free)
- SQS: Standard + FIFO queues (1M free requests/month)
- SNS: Standard topic (1M free publishes/month)
- EventBridge: Scheduler (free)
- CloudFront: Distribution (1TB free transfer/month)
"""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_events,
    aws_logs as logs,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct


class TaoPipelineStack(Stack):
    """Complete infrastructure for the TAO Mining Intelligence Pipeline."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # =====================================================================
        # Storage: DynamoDB
        # =====================================================================
        table = dynamodb.Table(
            self, "PipelineTable",
            table_name="tao-pipeline",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # =====================================================================
        # Storage: S3 Buckets
        # =====================================================================
        data_bucket = s3.Bucket(
            self, "DataBucket",
            bucket_name=f"tao-intelligence-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="compress-old-raw",
                    prefix="raw/",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        )
                    ],
                )
            ],
        )

        site_bucket = s3.Bucket(
            self, "SiteBucket",
            bucket_name=f"tao-intelligence-site-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # =====================================================================
        # Messaging: SQS + SNS
        # =====================================================================
        process_dlq = sqs.Queue(
            self, "ProcessSubnetDLQ",
            queue_name="tao-process-subnet-dlq",
            retention_period=Duration.days(14),
        )

        process_queue = sqs.Queue(
            self, "ProcessSubnetQueue",
            queue_name="tao-process-subnet",
            visibility_timeout=Duration.minutes(15),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=process_dlq,
            ),
        )

        subnet_processed_topic = sns.Topic(
            self, "SubnetProcessedTopic",
            topic_name="tao-subnet-processed",
        )

        completion_dlq = sqs.Queue(
            self, "CompletionTrackerDLQ",
            queue_name="tao-completion-tracker-dlq",
            retention_period=Duration.days(14),
        )

        completion_queue = sqs.Queue(
            self, "CompletionTrackerQueue",
            queue_name="tao-completion-tracker",
            visibility_timeout=Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=completion_dlq,
            ),
        )

        subnet_processed_topic.add_subscription(
            subs.SqsSubscription(completion_queue)
        )

        # =====================================================================
        # Secrets: Parameter Store
        # =====================================================================
        ssm.StringParameter(
            self, "PriceApiKey",
            parameter_name="/tao-pipeline/coingecko-api-key",
            string_value="placeholder",
            description="CoinGecko API key (set actual value via console)",
        )

        # =====================================================================
        # Compute: Lambda Functions (Container Image)
        # =====================================================================
        import os
        lambda_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "lambda")

        collector_fn = _lambda.DockerImageFunction(
            self, "CollectorLambda",
            function_name="tao-collector",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=lambda_dir,
                cmd=["src.collector.handler.handle"],
            ),
            memory_size=512,
            timeout=Duration.minutes(15),
            environment={
                "PIPELINE_ENV": "aws",
                "TABLE_NAME": table.table_name,
                "BUCKET_NAME": data_bucket.bucket_name,
                "PROCESS_QUEUE_URL": process_queue.queue_url,
                "COINGECKO_API_KEY_PARAM": "/tao-pipeline/coingecko-api-key",
            },
            log_group=logs.LogGroup(self, "CollectorLogs",
                                    retention=logs.RetentionDays.ONE_MONTH),
        )

        processor_fn = _lambda.DockerImageFunction(
            self, "ProcessorLambda",
            function_name="tao-processor",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=lambda_dir,
                cmd=["src.processor.handler.handle"],
            ),
            memory_size=512,
            timeout=Duration.minutes(15),
            environment={
                "PIPELINE_ENV": "aws",
                "TABLE_NAME": table.table_name,
                "BUCKET_NAME": data_bucket.bucket_name,
                "SUBNET_PROCESSED_TOPIC_ARN": subnet_processed_topic.topic_arn,
            },
            log_group=logs.LogGroup(self, "ProcessorLogs",
                                    retention=logs.RetentionDays.ONE_MONTH),
        )

        finalizer_fn = _lambda.DockerImageFunction(
            self, "FinalizerLambda",
            function_name="tao-finalizer",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=lambda_dir,
                cmd=["src.finalizer.handler.handle"],
            ),
            memory_size=512,
            timeout=Duration.minutes(5),
            environment={
                "PIPELINE_ENV": "aws",
                "TABLE_NAME": table.table_name,
                "BUCKET_NAME": data_bucket.bucket_name,
            },
            log_group=logs.LogGroup(self, "FinalizerLogs",
                                    retention=logs.RetentionDays.ONE_MONTH),
        )

        # =====================================================================
        # Event Sources: SQS → Lambda
        # =====================================================================
        processor_fn.add_event_source(
            lambda_events.SqsEventSource(process_queue, batch_size=1)
        )

        finalizer_fn.add_event_source(
            lambda_events.SqsEventSource(completion_queue, batch_size=10)
        )

        # =====================================================================
        # Scheduling: EventBridge
        # =====================================================================
        events.Rule(
            self, "DailyTrigger",
            rule_name="tao-daily-collection",
            schedule=events.Schedule.cron(minute="0", hour="0"),
            targets=[targets.LambdaFunction(collector_fn)],
        )

        # =====================================================================
        # IAM: Least Privilege
        # =====================================================================
        table.grant_read_write_data(collector_fn)
        table.grant_read_write_data(processor_fn)
        table.grant_read_write_data(finalizer_fn)

        data_bucket.grant_read_write(collector_fn)
        data_bucket.grant_read_write(processor_fn)
        data_bucket.grant_read(finalizer_fn)
        data_bucket.grant_put(finalizer_fn)

        site_bucket.grant_put(finalizer_fn)

        process_queue.grant_send_messages(collector_fn)
        subnet_processed_topic.grant_publish(processor_fn)

        # SSM read for Collector (API keys) — scoped to exact parameter
        collector_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/tao-pipeline/coingecko-api-key"],
        ))

        # =====================================================================
        # CDN: CloudFront
        # =====================================================================
        cloudfront.Distribution(
            self, "SiteDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
        )
