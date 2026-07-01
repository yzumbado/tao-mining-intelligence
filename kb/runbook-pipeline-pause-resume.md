# Runbook: Pipeline Pause & Resume

## Status: PAUSED (2026-06-29)

## Why We Paused

A 3-day invocation spike (June 18-21) caused the Lambda free tier GB-seconds overage:
- Normal: 131 collector invocations/day → 32,442 GB-s/month (8% of free tier)
- Spike: 2,000-3,000 collector invocations/day → pushed June total to ~450K GB-s (13% over)
- Root cause: Discovery Lambda re-created per-subnet schedules every hour when staleness check detected subnets as stale (Processor failures didn't update `processed_at` before next Discovery run)
- Cost impact: ~$0.83 overage. Trivial, but we want to stay within free tier.
- Fix applied: commit `d023f63` — Collector writes `collected_at` before SQS, Discovery checks it

Since the pipeline is not being actively consumed (Stage 3 STRATEGIZE not built yet), we paused to avoid unnecessary spend until July free tier reset.

## What Was Disabled

### 1. EventBridge Rules (removed via CDK deploy)
Commit `0177f16` commented out 4 rules in `cdk/stacks/pipeline_stack.py`:
- `tao-hourly-discovery` — Discovery Lambda (hourly)
- `tao-daily-finalizer` — Finalizer at 06:00 UTC
- `tao-daily-finalizer-evening` — Finalizer at 18:00 UTC
- `tao-market-observer-hourly` — Market Observer (hourly)

Deployed via `npx cdk deploy --profile tao --require-approval never` on 2026-06-29.

### 2. EventBridge Scheduler One-Time Schedules (deleted manually)
129 `tao-subnet-*` schedules were deleted:
```bash
aws scheduler list-schedules --profile tao --region us-east-1 --output json --query 'Schedules[].Name' | \
  python3 -c "import json,sys,subprocess; [subprocess.run(f'aws scheduler delete-schedule --name {n} --profile tao --region us-east-1'.split()) for n in json.load(sys.stdin)]"
```

### Current State (as of pause)
- 0 EventBridge Rules
- 0 EventBridge Scheduler schedules
- All Lambdas deployed but at **June 22 code** (spike fix NOT yet deployed)
- DLQ contains ~11,097 stale messages from spike period (14-day retention, expiring by Jul 5)
- S3 data, DynamoDB state, and CloudFront site intact (last data: 2026-06-29 06:00 UTC)

---

## How to Re-Enable (SOP)

### Pre-Flight Checks (MUST DO BEFORE ENABLING)

#### Check 1: Purge the Dead Letter Queue

The DLQ contains ~11K stale messages from the June spike. These MUST be purged before re-enabling to prevent:
- Accidental redrive flooding Processor with old data
- Confusion about DLQ alarm state

```bash
# Verify DLQ message count
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/651484323929/tao-process-subnet-dlq \
  --attribute-names ApproximateNumberOfMessages \
  --profile tao --region us-east-1

# Purge all messages
aws sqs purge-queue \
  --queue-url https://sqs.us-east-1.amazonaws.com/651484323929/tao-process-subnet-dlq \
  --profile tao --region us-east-1

# Verify empty (wait 60s for consistency)
sleep 60 && aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/651484323929/tao-process-subnet-dlq \
  --attribute-names ApproximateNumberOfMessages \
  --profile tao --region us-east-1
# Expected: "ApproximateNumberOfMessages": "0"
```

#### Check 2: Verify main queue is empty

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/651484323929/tao-process-subnet \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --profile tao --region us-east-1
# Expected: both "0"
```

#### Check 3: Verify no lingering schedules

```bash
aws scheduler list-schedules --profile tao --region us-east-1 --query 'Schedules | length(@)'
# Expected: 0

aws events list-rules --name-prefix tao --profile tao --region us-east-1 --query 'Rules | length(@)'
# Expected: 0
```

#### Check 4: Run tests

```bash
cd /Users/yvvargas/ai-workspace/coauthor-workspace/Kiro-me/projects/tao-mining-intelligence
source .venv/bin/activate
.venv/bin/pytest tests/ -q
# Expected: 264 passed
```

---

### Step 1: Uncomment EventBridge Rules in CDK

In `cdk/stacks/pipeline_stack.py`, uncomment the 4 `events.Rule()` blocks:
- `HourlyDiscovery` (~line 276)
- `DailyFinalizer` (~line 285)
- `DailyFinalizerEvening` (~line 293)
- `MarketObserverSchedule` (~line 370)

### Step 2: Update CDK test

In `tests/cdk/test_pipeline_stack.py`, change `TestEventBridge` to assert rules EXIST:
```python
def test_hourly_discovery_schedule(self):
    template = _get_template()
    template.has_resource_properties("AWS::Events::Rule", {
        "ScheduleExpression": "rate(1 hour)",
    })
```

### Step 3: Run tests again

```bash
.venv/bin/pytest tests/ -q
# Must pass with the CDK test now asserting rules exist
```

### Step 4: Deploy

This deploys BOTH the spike fix (new container images) AND the EventBridge rules:

```bash
npx cdk deploy --profile tao --require-approval never
```

Expected output: creates 4 EventBridge Rules, rebuilds Lambda container images.

### Step 5: Verify deployment

```bash
# Rules exist
aws events list-rules --name-prefix tao --profile tao --region us-east-1
# Expected: 4 rules, all ENABLED

# Lambda code was updated (LastModified should be today)
aws lambda get-function --function-name tao-subnet-collector --profile tao --region us-east-1 \
  --query 'Configuration.LastModified'
aws lambda get-function --function-name tao-discovery --profile tao --region us-east-1 \
  --query 'Configuration.LastModified'
# Expected: today's date (confirms spike fix is deployed)
```

### Step 6: Wait for Discovery to bootstrap

Discovery runs hourly. On first run it will:
1. Query chain for all active subnets (~129)
2. Find no existing schedules (all deleted)
3. Create a `tao-subnet-{netuid}` one-time schedule for each
4. Collectors start firing within the hour, self-perpetuating from there

```bash
# After ~1 hour, verify schedules were created
aws scheduler list-schedules --name-prefix tao-subnet --profile tao --region us-east-1 \
  --query 'Schedules | length(@)'
# Expected: ~129
```

### Step 7: Verify first collection cycle

```bash
# After ~2 hours, check collector ran (use CDK log group name)
aws logs filter-log-events \
  --log-group-name "TaoPipeline-SubnetCollectorLogsB887CE49-ik3z09VrOeW7" \
  --start-time $(python3 -c "import time; print(int((time.time()-7200)*1000))") \
  --filter-pattern "complete" --limit 5 \
  --profile tao --region us-east-1

# Check DLQ is still empty (no new failures)
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/651484323929/tao-process-subnet-dlq \
  --attribute-names ApproximateNumberOfMessages \
  --profile tao --region us-east-1
# Expected: "0"
```

### Step 8: Verify rankings refresh (after 06:00 or 18:00 UTC)

```bash
curl -s https://dkfh19zkgqq18.cloudfront.net/data/briefing.json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Briefing date: {d[\"generated_at\"]}')"
# Expected: today's date
```

### Step 9: Monitor first week

```bash
# Daily check: collector invocations (should be ~131/day)
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Invocations \
  --start-time $(date -u -v-1d +%Y-%m-%dT00:00:00Z) --end-time $(date -u +%Y-%m-%dT00:00:00Z) \
  --period 86400 --statistics Sum \
  --dimensions Name=FunctionName,Value=tao-subnet-collector \
  --profile tao --region us-east-1
# Expected: 129-135 (129 subnets + 2-3 retries at most)

# Daily check: GB-seconds consumption
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Duration \
  --start-time $(date -u -v-1d +%Y-%m-%dT00:00:00Z) --end-time $(date -u +%Y-%m-%dT00:00:00Z) \
  --period 86400 --statistics Sum \
  --profile tao --region us-east-1
# Expected: <2000 seconds total (~1081 GB-s/day budget)
```

**ALERT THRESHOLD**: If collector exceeds 200 invocations/day, the spike is recurring. Immediately disable Discovery rule:
```bash
aws events disable-rule --name tao-hourly-discovery --profile tao --region us-east-1
```

---

## Preventing Future Spikes

The spike root cause is now fixed (commit `d023f63`):
- [x] Collector writes `collected_at` to DynamoDB before SQS publish
- [x] Discovery checks `collected_at` + `processed_at` + `last_updated` (most recent wins)

Remaining backlog items:
- [ ] Add CloudWatch alarm for >200 collector invocations/day (automatic alerting)
- [ ] Add CloudWatch alarm for DLQ depth > 0 (detect Processor failures early)

---

## How to Pause Again (if needed)

### Quick pause (disable rules, keep Lambda code deployed):
```bash
aws events disable-rule --name tao-hourly-discovery --profile tao --region us-east-1
aws events disable-rule --name tao-daily-finalizer --profile tao --region us-east-1
aws events disable-rule --name tao-daily-finalizer-evening --profile tao --region us-east-1
aws events disable-rule --name tao-market-observer-hourly --profile tao --region us-east-1
```

### Full pause (also kill self-perpetuating subnet schedules):
```bash
# Disable rules first (stops Discovery from creating new schedules)
# Then delete all existing one-time schedules:
aws scheduler list-schedules --name-prefix tao-subnet --profile tao --region us-east-1 \
  --output json --query 'Schedules[].Name' | \
  python3 -c "import json,sys,subprocess; [subprocess.run(f'aws scheduler delete-schedule --name {n} --profile tao --region us-east-1'.split()) for n in json.load(sys.stdin)]"
```

Note: Quick pause leaves the per-subnet schedules running (they'll fire once more each, then die because Discovery won't re-seed them). Full pause stops everything immediately.
