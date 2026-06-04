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
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_ecr_assets as ecr_assets,
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
        collection_dlq = sqs.Queue(
            self, "CollectionDLQ",
            queue_name="tao-collection-dlq",
            retention_period=Duration.days(14),
        )

        collection_queue = sqs.Queue(
            self, "CollectionQueue",
            queue_name="tao-collection",
            visibility_timeout=Duration.seconds(120),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=collection_dlq,
            ),
        )

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

        # Orchestrator REMOVED — replaced by Discovery Lambda (AD18)

        subnet_collector_fn = _lambda.DockerImageFunction(
            self, "SubnetCollectorLambda",
            function_name="tao-subnet-collector",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=lambda_dir,
                cmd=["src.subnet_collector.handler.handle"],
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=_lambda.Architecture.ARM_64,
            memory_size=1024,
            timeout=Duration.seconds(90),
            reserved_concurrent_executions=2,
            environment={
                "PIPELINE_ENV": "aws",
                "HOME": "/tmp",
                "TABLE_NAME": table.table_name,
                "BUCKET_NAME": data_bucket.bucket_name,
                "PROCESS_QUEUE_URL": process_queue.queue_url,
            },
            log_group=logs.LogGroup(self, "SubnetCollectorLogs",
                                    retention=logs.RetentionDays.ONE_MONTH),
        )

        processor_fn = _lambda.DockerImageFunction(
            self, "ProcessorLambda",
            function_name="tao-processor",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=lambda_dir,
                cmd=["src.processor.handler.handle"],
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=_lambda.Architecture.ARM_64,
            memory_size=512,
            timeout=Duration.minutes(15),
            environment={
                "PIPELINE_ENV": "aws",
                "HOME": "/tmp",
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
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=_lambda.Architecture.ARM_64,
            memory_size=512,
            timeout=Duration.minutes(5),
            environment={
                "PIPELINE_ENV": "aws",
                "HOME": "/tmp",
                "TABLE_NAME": table.table_name,
                "BUCKET_NAME": data_bucket.bucket_name,
                "SITE_BUCKET_NAME": site_bucket.bucket_name,
            },
            log_group=logs.LogGroup(self, "FinalizerLogs",
                                    retention=logs.RetentionDays.ONE_MONTH),
        )

        # =====================================================================
        # Event Sources: SQS → Lambda
        # =====================================================================
        # SubnetCollector: invoked directly by EventBridge Scheduler (AD18)
        # Collection queue event source REMOVED — no longer needed

        processor_fn.add_event_source(
            lambda_events.SqsEventSource(process_queue, batch_size=1)
        )

        # Finalizer/Aggregator: invoked directly by Processor (AD18)
        # Completion queue event source REMOVED — no longer needed

        # =====================================================================
        # Scheduling: EventBridge
        # =====================================================================
        # Scheduling: EventBridge + Scheduler Role
        # =====================================================================
        # EventBridge Scheduler: role for invoking SubnetCollector
        scheduler_role = iam.Role(
            self, "SchedulerExecutionRole",
            role_name="tao-scheduler-execution",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            inline_policies={
                "InvokeCollector": iam.PolicyDocument(statements=[
                    iam.PolicyStatement(
                        actions=["lambda:InvokeFunction"],
                        resources=[subnet_collector_fn.function_arn],
                    )
                ])
            },
        )

        # DailyTrigger REMOVED — replaced by hourly Discovery Lambda (AD18)

        # Discovery Lambda: hourly safety net for independent refresh (AD18)
        discovery_fn = _lambda.DockerImageFunction(
            self, "DiscoveryLambda",
            function_name="tao-discovery",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=lambda_dir,
                cmd=["src.discovery.handler.handle"],
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=_lambda.Architecture.ARM_64,
            memory_size=256,
            timeout=Duration.seconds(60),
            environment={
                "PIPELINE_ENV": "aws",
                "HOME": "/tmp",
                "TABLE_NAME": table.table_name,
                "SUBNET_COLLECTOR_ARN": subnet_collector_fn.function_arn,
                "SCHEDULER_ROLE_ARN": scheduler_role.role_arn,
            },
            log_group=logs.LogGroup(self, "DiscoveryLogs",
                                    retention=logs.RetentionDays.ONE_MONTH),
        )
        table.grant_read_write_data(discovery_fn)
        discovery_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["scheduler:CreateSchedule", "scheduler:GetSchedule"],
            resources=[f"arn:aws:scheduler:{self.region}:{self.account}:schedule/default/tao-subnet-*",
                       f"arn:aws:scheduler:{self.region}:{self.account}:schedule/default/tao-research-*"],
        ))
        discovery_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[scheduler_role.role_arn],
        ))

        events.Rule(
            self, "HourlyDiscovery",
            rule_name="tao-hourly-discovery",
            schedule=events.Schedule.rate(Duration.hours(1)),
            targets=[targets.LambdaFunction(discovery_fn)],
        )

        # =====================================================================
        # Researcher Lambda (Stage 2 — subnet repo analysis)
        # =====================================================================
        researcher_fn = _lambda.DockerImageFunction(
            self, "ResearcherLambda",
            function_name="tao-researcher",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=lambda_dir,
                cmd=["src.researcher.handler.handle"],
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=_lambda.Architecture.ARM_64,
            memory_size=256,
            timeout=Duration.seconds(60),
            environment={
                "PIPELINE_ENV": "aws",
                "HOME": "/tmp",
                "TABLE_NAME": table.table_name,
                "BUCKET_NAME": data_bucket.bucket_name,
            },
            log_group=logs.LogGroup(self, "ResearcherLogs",
                                    retention=logs.RetentionDays.ONE_MONTH),
        )
        table.grant_read_write_data(researcher_fn)
        data_bucket.grant_read_write(researcher_fn)
        researcher_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/tao-pipeline/github-token"],
        ))

        # Discovery needs to schedule researcher invocations
        discovery_fn.add_environment("RESEARCHER_ARN", researcher_fn.function_arn)

        # Scheduler role needs to invoke researcher
        scheduler_role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[researcher_fn.function_arn],
        ))

        # =====================================================================
        # IAM: Least Privilege
        # =====================================================================
        table.grant_read_write_data(subnet_collector_fn)
        table.grant_read_write_data(processor_fn)
        table.grant_read_write_data(finalizer_fn)

        data_bucket.grant_read_write(subnet_collector_fn)
        data_bucket.grant_read_write(processor_fn)
        data_bucket.grant_read(finalizer_fn)
        data_bucket.grant_put(finalizer_fn)

        site_bucket.grant_put(finalizer_fn)

        process_queue.grant_send_messages(subnet_collector_fn)
        subnet_processed_topic.grant_publish(processor_fn)

        # Processor needs to create/delete schedules
        processor_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["scheduler:CreateSchedule", "scheduler:DeleteSchedule",
                     "scheduler:GetSchedule"],
            resources=[f"arn:aws:scheduler:{self.region}:{self.account}:schedule/default/tao-subnet-*"],
        ))
        processor_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[scheduler_role.role_arn],
        ))

        # Add env vars for self-scheduling
        processor_fn.add_environment("SUBNET_COLLECTOR_ARN", subnet_collector_fn.function_arn)
        processor_fn.add_environment("SCHEDULER_ROLE_ARN", scheduler_role.role_arn)
        processor_fn.add_environment("AGGREGATOR_ARN", finalizer_fn.function_arn)

        # Processor invokes Aggregator (async) after each subnet
        finalizer_fn.grant_invoke(processor_fn)

        # =====================================================================
        # Monitoring: DLQ Alarms + Staleness
        # =====================================================================
        for dlq, name in [
            (collection_dlq, "Collection"),
            (process_dlq, "Process"),
            (completion_dlq, "Completion"),
        ]:
            cloudwatch.Alarm(
                self, f"{name}DLQAlarm",
                alarm_name=f"tao-{name.lower()}-dlq-not-empty",
                metric=dlq.metric_approximate_number_of_messages_visible(),
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )

        # Staleness alarm: fires if Discovery Lambda reports stale subnets
        alert_topic = sns.Topic(self, "AlertTopic", topic_name="tao-pipeline-alerts")
        alert_topic.add_subscription(
            subs.EmailSubscription("yzumbado@gmail.com")
        )

        staleness_alarm = cloudwatch.Alarm(
            self, "StalenessAlarm",
            alarm_name="tao-subnets-stale",
            metric=cloudwatch.Metric(
                namespace="TaoPipeline",
                metric_name="StaleSubnets",
                statistic="Maximum",
                period=Duration.hours(1),
            ),
            threshold=10,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        staleness_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(alert_topic)
        )

        # Discovery Lambda needs cloudwatch:PutMetricData + scheduler:ListSchedules
        discovery_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "TaoPipeline"}},
        ))
        discovery_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["scheduler:ListSchedules"],
            resources=["*"],
        ))

        # Lambda error rate alarms (fires if > 5 errors in 15 min)
        for fn, name in [
            (subnet_collector_fn, "Collector"),
            (processor_fn, "Processor"),
            (finalizer_fn, "Finalizer"),
            (discovery_fn, "Discovery"),
        ]:
            cloudwatch.Alarm(
                self, f"{name}ErrorAlarm",
                alarm_name=f"tao-{name.lower()}-errors",
                metric=fn.metric_errors(period=Duration.minutes(15)),
                threshold=5,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )

        # Active schedules alarm (fires if loops are dying)
        cloudwatch.Alarm(
            self, "ScheduleCountAlarm",
            alarm_name="tao-schedules-low",
            metric=cloudwatch.Metric(
                namespace="TaoPipeline",
                metric_name="ActiveSchedules",
                statistic="Minimum",
                period=Duration.hours(1),
            ),
            threshold=50,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )

        # =====================================================================
        # Budget: Hard cost limit ($1/month)
        # =====================================================================
        from aws_cdk import aws_budgets as budgets

        budgets.CfnBudget(
            self, "CostBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=1.0,
                    unit="USD",
                ),
                budget_name="tao-pipeline-monthly-limit",
            ),
        )

        # =====================================================================
        # CDN: CloudFront
        # =====================================================================
        distribution = cloudfront.Distribution(
            self, "SiteDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
        )

        # Pass distribution ID to Finalizer for cache invalidation
        finalizer_fn.add_environment(
            "CLOUDFRONT_DISTRIBUTION_ID", distribution.distribution_id)

        # Grant Finalizer permission to create invalidations
        distribution.grant_create_invalidation(finalizer_fn)
