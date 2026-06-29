# Runbook: Pipeline Pause & Resume

## Status: PAUSED (2026-06-29)

## Why We Paused

A 3-day invocation spike (June 18-21) caused the Lambda free tier GB-seconds overage:
- Normal: 131 collector invocations/day → 32,442 GB-s/month (8% of free tier)
- Spike: 2,000-3,000 collector invocations/day → pushed June total to ~450K GB-s (13% over)
- Root cause: Discovery Lambda re-created per-subnet schedules every hour when staleness check detected subnets as stale (likely Processor failures didn't update `processed_at`)
- Cost impact: ~$0.83 overage. Trivial, but we want to stay within free tier.

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
129 `tao-subnet-*` schedules were still active and self-perpetuating (each collector run creates the next +24h schedule). These were deleted:
```bash
aws scheduler list-schedules --profile tao --region us-east-1 --output json --query 'Schedules[].Name' | \
  python3 -c "import json,sys,subprocess; [subprocess.run(f'aws scheduler delete-schedule --name {n} --profile tao --region us-east-1'.split()) for n in json.load(sys.stdin)]"
```

### Current State
- 0 EventBridge Rules
- 0 EventBridge Scheduler schedules
- All Lambdas remain deployed (can be invoked manually for testing)
- S3 data, DynamoDB state, and CloudFront site remain intact (last data: 2026-06-29 06:00 UTC)

## How to Re-Enable (July 1+)

### Step 1: Uncomment EventBridge Rules in CDK

In `cdk/stacks/pipeline_stack.py`, uncomment the 4 `events.Rule()` blocks:
- `HourlyDiscovery`
- `DailyFinalizer`
- `DailyFinalizerEvening`
- `MarketObserverSchedule`

### Step 2: Deploy

```bash
cd /Users/yvvargas/ai-workspace/coauthor-workspace/Kiro-me/projects/tao-mining-intelligence
source .venv/bin/activate
npx cdk deploy --profile tao --require-approval never
```

### Step 3: Verify Rules Created

```bash
aws events list-rules --name-prefix tao --profile tao --region us-east-1
# Should show 4 rules, all ENABLED
```

### Step 4: Wait for Discovery to Bootstrap

Discovery runs hourly. On first run it will:
1. Query chain for all 129 active subnets
2. Find no existing schedules (all deleted)
3. Create a `tao-subnet-{netuid}` one-time schedule for each subnet
4. Collectors start firing within the hour, self-perpetuating from there

### Step 5: Verify Pipeline Running

```bash
# After ~2 hours, check collector ran
aws logs tail /aws/lambda/tao-subnet-collector --since 2h --profile tao --region us-east-1 | head -5

# After 06:00 or 18:00 UTC, check fresh rankings
curl -s https://dkfh19zkgqq18.cloudfront.net/data/rankings.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} subnets')"
```

### Step 6: Monitor First Week

Watch for spike recurrence:
```bash
# Daily invocation count (should be ~131 for collector)
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Invocations \
  --start-time $(date -u -v-1d +%Y-%m-%dT00:00:00Z) --end-time $(date -u +%Y-%m-%dT00:00:00Z) \
  --period 86400 --statistics Sum \
  --dimensions Name=FunctionName,Value=tao-subnet-collector \
  --profile tao --region us-east-1
```

If collector exceeds 200 invocations/day, the staleness-reschedule bug is recurring. Fix: ensure Processor updates `processed_at` even on partial failure.

## Preventing Future Spikes (Backlog)

The spike root cause is not fully fixed — Discovery will still re-schedule subnets if Processor fails to update `processed_at`. Potential fixes:
- [ ] Add guard in Discovery: skip subnet if schedule already exists for it
- [ ] Update `collected_at` (not just `processed_at`) immediately after collection succeeds, so Discovery doesn't see it as stale
- [ ] Add max-invocations-per-day alarm in CloudWatch to alert on spikes early
