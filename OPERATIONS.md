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
docker run --rm --entrypoint python test-imports -c "from src.discovery.handler import handle; print('OK')"
docker run --rm --entrypoint python test-imports -c "from src.subnet_collector.handler import handle; print('OK')"
docker run --rm --entrypoint python test-imports -c "from src.processor.handler import handle; print('OK')"
docker run --rm --entrypoint python test-imports -c "from src.finalizer.handler import handle; print('OK')"

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
# tao-discovery          (60s timeout)
# tao-subnet-collector   (90s timeout, 1024MB)
# tao-processor          (900s timeout)
# tao-finalizer          (300s timeout)
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
# SQS queues (2: processing queue + DLQ)
aws sqs list-queues --profile tao --region us-east-1 \
  --queue-name-prefix tao --query "QueueUrls | length(@)" --output text
# Expected: 2
```

```bash
# EventBridge rule is ENABLED (hourly Discovery)
aws events list-rules --profile tao --region us-east-1 \
  --name-prefix tao --query "Rules[].{Name:Name,State:State}" --output table
# Expected: tao-hourly-discovery | ENABLED
```

```bash
# CloudWatch alarms are OK (not in ALARM state)
aws cloudwatch describe-alarms --profile tao --region us-east-1 \
  --alarm-name-prefix Tao --query "MetricAlarms[].{Name:AlarmName,State:StateValue}" --output table
# Expected: All alarms in OK state (including TaoPipeline/StaleSubnets)
```

### ✅ CloudFront is accessible

```bash
# Get distribution URL
aws cloudfront list-distributions --profile tao --region us-east-1 \
  --query "DistributionList.Items[0].DomainName" --output text
# Visit https://dkfh19zkgqq18.cloudfront.net
```

## First Pipeline Run

### Manual trigger

```bash
aws lambda invoke --profile tao --region us-east-1 \
  --function-name tao-discovery \
  --payload '{}' \
  /tmp/discovery-response.json && cat /tmp/discovery-response.json
```

### Expected flow

```
tao-discovery (discovers active subnets, checks staleness)
    → creates one-time EventBridge schedule per subnet
        → tao-subnet-collector (collects metagraph for one subnet)
            → stores raw snapshot to S3
            → sends message to tao-process-subnet queue
                → tao-processor (computes metrics)
                    → stores derived metrics to S3
                    → writes profiles to DynamoDB
                    → invokes tao-finalizer (async)
                    → creates next one-time schedule (now + tempo)
                        → loop continues indefinitely
                            → tao-finalizer (recomputes rankings from all profiles)
                                → generates rankings + briefing + HTML site
                                → uploads to site bucket → CloudFront
```

After the first Discovery invocation, subnets become self-scheduling. Each subnet creates its own next schedule after processing. Discovery only re-seeds subnets that stop self-scheduling.

### Monitor execution

```bash
# Watch Discovery logs
aws logs tail /aws/lambda/tao-discovery --profile tao --region us-east-1 --follow

# Watch collector logs (high volume — one invocation per subnet)
aws logs tail /aws/lambda/tao-subnet-collector --profile tao --region us-east-1 --follow

# Watch processor logs
aws logs tail /aws/lambda/tao-processor --profile tao --region us-east-1 --follow

# Watch finalizer logs
aws logs tail /aws/lambda/tao-finalizer --profile tao --region us-east-1 --follow

# Check active EventBridge schedules (self-scheduling loops)
aws scheduler list-schedules --profile tao --region us-east-1 \
  --query "Schedules | length(@)" --output text
# Expected: 100+ (one per actively self-scheduling subnet)
```

### Verify pipeline completed

```bash
# Check S3 for outputs
aws s3 ls --profile tao s3://tao-intelligence-651484323929/derived/ --recursive | tail -5

# Check site was generated
aws s3 ls --profile tao s3://tao-intelligence-site-651484323929/site/

# Check rankings exist
aws s3 cp --profile tao s3://tao-intelligence-site-651484323929/site/data/rankings.json - | python -m json.tool | head -20
```

## System Health Check

Run these commands to verify the autonomous system is operating correctly:

```bash
# 1. How many subnets are self-scheduling?
aws scheduler list-schedules --profile tao --region us-east-1 \
  --query "Schedules | length(@)" --output text
# Expected: 100+ (should match active subnet count)

# 2. Is the staleness alarm OK?
aws cloudwatch describe-alarms --profile tao --region us-east-1 \
  --alarm-names "TaoPipeline/StaleSubnets" \
  --query "MetricAlarms[0].StateValue" --output text
# Expected: OK

# 3. Any messages in DLQ?
aws sqs get-queue-attributes --profile tao --region us-east-1 \
  --queue-url "https://sqs.us-east-1.amazonaws.com/651484323929/tao-process-subnet-dlq" \
  --attribute-names ApproximateNumberOfMessages \
  --query "Attributes.ApproximateNumberOfMessages" --output text
# Expected: 0

# 4. When was the site last updated?
aws s3api head-object --profile tao --region us-east-1 \
  --bucket tao-intelligence-site-651484323929 --key site/index.html \
  --query "LastModified" --output text
# Expected: within last 4 hours

# 5. Recent Discovery Lambda invocations (should be hourly)
aws logs filter-log-events --profile tao --region us-east-1 \
  --log-group-name /aws/lambda/tao-discovery \
  --start-time $(date -v-6H +%s000) \
  --filter-pattern "subnets_seeded" \
  --query "events[].message" --output text | tail -5
```

## Daily Operations

The pipeline is **fully autonomous**. No manual intervention needed.

- **Discovery Lambda** runs hourly, detects new subnets and re-seeds stale loops
- **Self-scheduling loops** keep each subnet refreshing at its tempo cadence (20-240 min)
- **Finalizer** recomputes rankings after each subnet update (~780 times/day)
- **Staleness alarm** fires if any subnet exceeds `max_staleness_hours` (default: 4h)

**When to intervene**:
1. **Staleness alarm fires** → Check if Discovery is running, check DLQ, check Lambda errors
2. **DLQ has messages** → Inspect messages, fix root cause, redrive
3. **Site not updating** → Check Finalizer logs, verify profiles exist in DynamoDB

## Troubleshooting

### Subnet loop died (not self-scheduling)

1. Check if the subnet's schedule exists:
   ```bash
   aws scheduler list-schedules --profile tao --region us-east-1 \
     --query "Schedules[?contains(Name, 'subnet-<NETUID>')].{Name:Name,State:State}" --output table
   ```
2. If missing, Discovery will re-seed it within 1 hour. To force immediately:
   ```bash
   aws lambda invoke --profile tao --region us-east-1 \
     --function-name tao-discovery --payload '{}' /tmp/out.json
   ```
3. Check Processor logs for the subnet — the schedule creation may have failed:
   ```bash
   aws logs filter-log-events --profile tao --region us-east-1 \
     --log-group-name /aws/lambda/tao-processor \
     --filter-pattern "netuid=<NETUID> schedule" \
     --start-time $(date -v-4H +%s000)
   ```

### Staleness alarm in ALARM state

```bash
# Check which subnets are stale
aws s3 cp --profile tao s3://tao-intelligence-site-651484323929/site/data/metadata.json - \
  | python -c "import json,sys; d=json.load(sys.stdin); [print(f'SN{k}: {v[\"processed_at\"]}') for k,v in d.items() if 'processed_at' in v]" \
  | sort -t: -k2 | head -10
```

### Messages in DLQ

```bash
# Check DLQ message count
aws sqs get-queue-attributes --profile tao --region us-east-1 \
  --queue-url "https://sqs.us-east-1.amazonaws.com/651484323929/tao-process-subnet-dlq" \
  --attribute-names ApproximateNumberOfMessages \
  --query "Attributes.ApproximateNumberOfMessages" --output text

# Redrive DLQ messages back to main queue
aws sqs start-message-move-task --profile tao --region us-east-1 \
  --source-arn "arn:aws:sqs:us-east-1:651484323929:tao-process-subnet-dlq" \
  --destination-arn "arn:aws:sqs:us-east-1:651484323929:tao-process-subnet"
```

### Lambda timeout

- Discovery (60s): Chain query slow — check circuit breaker logs
- SubnetCollector (90s): Single subnet metagraph fetch — usually 3-5s, check chain health
- Processor (15min): Should complete in <30s per subnet — if timing out, check S3 read errors
- Finalizer (5min): Site generation — check if DynamoDB scan is slow (many profiles)

### Pipeline not producing output

1. Check Discovery is running: `aws logs tail /aws/lambda/tao-discovery --since 2h`
2. Check schedules exist: `aws scheduler list-schedules --query "Schedules | length(@)"`
3. Check processing queue: `aws sqs get-queue-attributes` on `tao-process-subnet`
4. Check Finalizer invocations: `aws logs tail /aws/lambda/tao-finalizer --since 2h`

## Cost

All resources are within AWS free tier:
- Lambda: ~1000 invocations/day (free: 1M/month)
- DynamoDB: ~500 writes/day (free: 25 WCU)
- S3: ~50MB/month growth (free: 5GB)
- SQS: ~500 messages/day (free: 1M/month)
- EventBridge Scheduler: ~23K schedules/month ($0.02/month)
- CloudFront: ~100 requests/day (free: 10M/month)
- CloudWatch: 2 alarms (free: 10)

**Expected monthly cost: $0.00** (EventBridge Scheduler rounds to $0)

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

### Adjust refresh policy

```bash
aws dynamodb put-item --profile tao --region us-east-1 \
  --table-name tao-pipeline \
  --item '{"PK":{"S":"CONFIG"},"SK":{"S":"REFRESH_POLICY"},"max_staleness_hours":{"N":"4"},"min_refresh_interval_minutes":{"N":"15"},"discovery_cadence_minutes":{"N":"60"}}'
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
11. **Self-scheduling is self-healing** — if a loop dies, Discovery re-seeds it within 1 hour; no manual intervention needed
