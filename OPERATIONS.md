# TAO Mining Intelligence — Operations Manual

## Prerequisites

| Tool | Install | Verify |
|------|---------|--------|
| Python 3.12+ | `brew install python@3.12` | `python3.12 --version` |
| AWS CLI | `brew install awscli` | `aws --version` |
| CDK CLI | `npm install -g aws-cdk` | `cdk --version` |
| Docker (colima) | `brew install docker colima && colima start` | `docker --version` |
| Node.js (for CDK) | `brew install node` | `node --version` |

## AWS Account Setup

### 1. Create IAM user (if needed)

- AWS Console → IAM → Users → Create user
- Name: `<your-name>-admin`
- Attach policy: `AdministratorAccess`
- Create access key: Security credentials → Create access key → CLI

### 2. Configure profile

```bash
aws configure --profile tao
# Access Key ID: <from step 1>
# Secret Access Key: <from step 1>
# Region: us-east-1
# Output: json
```

### 3. Verify access

```bash
aws sts get-caller-identity --profile tao
# Should return your account ID and user ARN
```

## Deployment

### First-time deployment

```bash
cd /path/to/tao-mining-intelligence
source .venv/bin/activate

# 1. Run tests (must all pass)
pytest tests/ -q

# 2. Verify Docker image builds and imports resolve
docker build -t test-imports lambda/
docker run --rm --entrypoint python test-imports -c "from src.orchestrator.handler import handle; print('OK')"
docker run --rm --entrypoint python test-imports -c "from src.processor.handler import handle; print('OK')"
docker run --rm --entrypoint python test-imports -c "from src.finalizer.handler import handle; print('OK')"
docker run --rm --entrypoint python test-imports -c "from src.subnet_collector.handler import handle; print('OK')"

# 3. Bootstrap CDK (one-time per account/region)
AWS_PROFILE=tao cdk bootstrap aws://<ACCOUNT_ID>/us-east-1

# 4. Deploy
AWS_PROFILE=tao cdk deploy TaoPipeline --require-approval never
```

### Subsequent deployments (code changes)

```bash
pytest tests/ -q                    # Tests pass
docker build -t test-imports lambda/ # Docker builds
AWS_PROFILE=tao cdk deploy TaoPipeline --require-approval never
```

### Teardown (removes everything except DynamoDB and data bucket)

```bash
AWS_PROFILE=tao cdk destroy TaoPipeline
# DynamoDB table and data bucket have RemovalPolicy.RETAIN — delete manually if needed
```

## Deployment Verification Checklist

After `cdk deploy` succeeds, verify these signals:

### ✅ All resources exist

```bash
# Lambdas (4 functions, all Image type)
aws lambda list-functions --profile tao --region us-east-1 \
  --query "Functions[?starts_with(FunctionName, 'tao-')].{Name:FunctionName,Timeout:Timeout}" \
  --output table

# Expected:
# tao-orchestrator      (60s timeout)
# tao-subnet-collector  (90s timeout, 1024MB)
# tao-processor         (900s timeout)
# tao-finalizer         (300s timeout)
```

```bash
# DynamoDB table is ACTIVE
aws dynamodb describe-table --profile tao --region us-east-1 \
  --table-name tao-pipeline --query "Table.TableStatus" --output text
# Expected: ACTIVE
```

```bash
# S3 buckets exist
aws s3 ls --profile tao | grep tao-intelligence
# Expected: tao-intelligence-<account-id> and tao-intelligence-site-<account-id>
```

```bash
# SQS queues (6: 3 main + 3 DLQ)
aws sqs list-queues --profile tao --region us-east-1 \
  --queue-name-prefix tao --query "QueueUrls | length(@)" --output text
# Expected: 6
```

```bash
# EventBridge rule is ENABLED
aws events list-rules --profile tao --region us-east-1 \
  --name-prefix tao --query "Rules[].{Name:Name,State:State}" --output table
# Expected: tao-daily-collection | ENABLED
```

```bash
# CloudWatch alarms are OK (not in ALARM state)
aws cloudwatch describe-alarms --profile tao --region us-east-1 \
  --alarm-name-prefix tao --query "MetricAlarms[].{Name:AlarmName,State:StateValue}" --output table
# Expected: All 3 alarms in OK state
```

### ✅ CloudFront is accessible

```bash
# Get distribution URL
aws cloudfront list-distributions --profile tao --region us-east-1 \
  --query "DistributionList.Items[0].DomainName" --output text
# Visit https://<domain> — will show 403 until first pipeline run generates site
```

## First Pipeline Run

### Manual trigger

```bash
aws lambda invoke --profile tao --region us-east-1 \
  --function-name tao-orchestrator \
  --payload '{}' \
  /tmp/orchestrator-response.json && cat /tmp/orchestrator-response.json
```

### Expected flow

```
tao-orchestrator (discovers active subnets)
    → sends 1 SQS message per subnet to tao-collection queue
        → tao-subnet-collector (collects metagraph for each subnet)
            → stores raw snapshot to S3
            → sends message to tao-process-subnet queue
                → tao-processor (computes metrics)
                    → stores derived metrics to S3
                    → writes profiles to DynamoDB
                    → publishes to SNS topic
                        → tao-completion-tracker queue
                            → tao-finalizer (when all subnets complete)
                                → generates rankings + briefing
                                → generates HTML site
                                → uploads to site bucket
```

### Monitor execution

```bash
# Watch orchestrator logs
aws logs tail /aws/lambda/tao-orchestrator --profile tao --region us-east-1 --follow

# Watch collector logs
aws logs tail /aws/lambda/tao-subnet-collector --profile tao --region us-east-1 --follow

# Watch processor logs
aws logs tail /aws/lambda/tao-processor --profile tao --region us-east-1 --follow

# Watch finalizer logs
aws logs tail /aws/lambda/tao-finalizer --profile tao --region us-east-1 --follow
```

### Verify pipeline completed

```bash
# Check DynamoDB for cycle status
aws dynamodb get-item --profile tao --region us-east-1 \
  --table-name tao-pipeline \
  --key '{"PK": {"S": "CYCLE#2026-05-17"}, "SK": {"S": "STATUS"}}' \
  --query "Item.{status:status.S,complete:subnets_complete.N,total:subnets_total.N}" \
  --output table

# Check S3 for outputs
aws s3 ls --profile tao s3://tao-intelligence-651484323929/derived/ --recursive

# Check site was generated
aws s3 ls --profile tao s3://tao-intelligence-site-651484323929/site/
```

## Troubleshooting

### Pipeline didn't run

1. Check EventBridge rule is ENABLED
2. Check orchestrator CloudWatch logs for errors
3. Verify DynamoDB table has no stale cycle record blocking idempotency

### Messages in DLQ

```bash
# Check DLQ message count
for q in tao-collection-dlq tao-process-subnet-dlq tao-completion-tracker-dlq; do
  echo -n "$q: "
  aws sqs get-queue-attributes --profile tao --region us-east-1 \
    --queue-url "https://sqs.us-east-1.amazonaws.com/651484323929/$q" \
    --attribute-names ApproximateNumberOfMessages \
    --query "Attributes.ApproximateNumberOfMessages" --output text
done
```

### Lambda timeout

- Orchestrator (60s): Bittensor chain may be slow — check circuit breaker logs
- SubnetCollector (60s): Single subnet metagraph fetch — usually 3-5s
- Processor (15min): Should complete in <30s per subnet — if timing out, check S3 read errors
- Finalizer (5min): Site generation — check if all subnets completed

### Redrive DLQ messages

```bash
# Move messages from DLQ back to main queue for retry
aws sqs start-message-move-task --profile tao --region us-east-1 \
  --source-arn "arn:aws:sqs:us-east-1:651484323929:tao-process-subnet-dlq" \
  --destination-arn "arn:aws:sqs:us-east-1:651484323929:tao-process-subnet"
```

### Reset a stuck cycle

```bash
# Delete the cycle record to allow re-run
aws dynamodb delete-item --profile tao --region us-east-1 \
  --table-name tao-pipeline \
  --key '{"PK": {"S": "CYCLE#2026-05-17"}, "SK": {"S": "STATUS"}}'
# Then re-invoke orchestrator
```

## Daily Operations

The pipeline runs automatically at 00:00 UTC daily via EventBridge. No manual intervention needed unless:

1. **DLQ alarm fires** → Check logs, redrive or fix
2. **Site not updated** → Check finalizer logs, verify cycle completed
3. **Data looks wrong** → Check raw snapshots in S3, compare with `python scripts/validate_fields.py`

## Cost

All resources are within AWS free tier:
- Lambda: ~30 invocations/day × 4 functions = ~120 requests (free: 1M/month)
- DynamoDB: ~100 writes/day (free: 25 WCU)
- S3: ~50MB/month growth (free: 5GB)
- SQS: ~300 messages/day (free: 1M/month)
- CloudFront: ~10 requests/day (free: 10M/month)
- CloudWatch: 3 alarms (free: 10)

**Expected monthly cost: $0.00**

## Key Configuration

### Update CoinGecko API key (optional, for TAO/USD price)

```bash
aws ssm put-parameter --profile tao --region us-east-1 \
  --name "/tao-pipeline/coingecko-api-key" \
  --value "your-actual-key" \
  --type String --overwrite
```

### Add tracked hotkeys

```bash
aws dynamodb put-item --profile tao --region us-east-1 \
  --table-name tao-pipeline \
  --item '{"PK":{"S":"CONFIG"},"SK":{"S":"TRACKED_HOTKEYS"},"hotkeys":{"L":[{"S":"5YourHotkeyHere..."}]}}'
```

## Deployment Lessons Learned

1. **Always run Docker import smoke test before deploying** — `pytest` passing doesn't guarantee Lambda can find handlers
2. **`cdk.json` is required** — without it, `cdk deploy` fails with `--app is required`
3. **Colima must be running** for CDK to build Docker images — `colima start`
4. **First deploy takes ~4 minutes** (CloudFront distribution creation is slow)
5. **The account was clean** — if deploying to an account with existing resources, verify no name collisions on S3 buckets (they're globally unique)
6. **`requests` version must satisfy bittensor SDK** — check `pip install` output during Docker build
7. **ARM64 architecture required** — Apple Silicon builds ARM64 images; Lambda must be configured with `architecture=ARM_64`
8. **HOME=/tmp is mandatory** — Bittensor SDK tries to create `~/.bittensor/wallets/` on import; Lambda's default HOME is read-only
9. **lambda_patch.py must load before bittensor** — patches multiprocessing.Queue (needs /dev/shm which Lambda lacks); loaded via `src/__init__.py` when `PIPELINE_ENV=aws`
10. **Validation must be relaxed for real-world data** — 27/129 subnets have non-standard incentive distributions; hard rejection blocks the entire pipeline
