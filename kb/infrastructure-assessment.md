# Infrastructure Assessment: Free Tier Architecture

> **Last Updated**: 2026-05-14  
> **Purpose**: Evaluate AWS free tier viability and data access options

---

## 1. Data Access Options (Chain Data)

### Option A: Bittensor Python SDK + Public Finney Endpoint (FREE)

**Endpoint**: `wss://entrypoint-finney.opentensor.ai:443`

**How it works**:
```python
import bittensor as bt

# Connect to public Finney network
sub = bt.Subtensor(network="finney")

# Pull metagraph for any subnet
mg = bt.Metagraph(netuid=1)
mg.sync()  # Syncs to latest block

# Access all miner/validator data
# mg.S (stake), mg.R (rank), mg.I (incentive), mg.E (emission)
# mg.C (consensus), mg.T (trust), mg.hotkeys, mg.coldkeys, etc.
```

**Pros**:
- Completely free
- Direct chain access — authoritative data
- Full metagraph data for any subnet
- Can sync to specific historical blocks
- Python-native — easy to integrate with Lambda

**Cons**:
- Public endpoint may have rate limits (undocumented)
- Cold start time for SDK initialization
- No historical aggregation — you get point-in-time snapshots
- Need to build your own time-series from repeated snapshots
- WebSocket connection management needed

**Risk**: Public endpoint could become unreliable or rate-limited. Mitigation: can switch to own node or paid RPC provider (GetBlock, etc.)

---

### Option B: Taostats API (PAID)

**Pricing**: Requires API key from https://taostats.io/pro/ (pricing not publicly listed)

**Pros**:
- Pre-aggregated historical data
- REST API — simpler than WebSocket
- TypeScript SDK available
- Deepest historical data in ecosystem
- Includes derived metrics

**Cons**:
- Monthly cost (unknown until we check)
- Dependency on third party
- May not have all raw metagraph fields
- Rate limits apply

**Verdict**: Nice-to-have for historical backfill, but not needed for MVP. The SDK gives us everything we need for daily snapshots going forward.

---

### Option C: Run Own Subtensor Node (FREE but infra cost)

**Requirements** (from docs):
- Standard server hardware
- Ports: 9944 (WebSocket), 9933 (RPC), 30333 (P2P)
- Syncs full chain history

**Pros**:
- No rate limits
- Full historical access
- No third-party dependency
- Can subscribe to real-time events

**Cons**:
- Needs always-on server (EC2 cost or home server)
- Sync time for initial setup
- Maintenance burden
- Overkill for daily snapshots

**Verdict**: Phase 3+ consideration. Not needed for MVP.

---

### Option D: Subnet 13 (Data Universe) — Bittensor-native data (INTERESTING)

SN13 is a Bittensor subnet specifically for data collection/storage. Run by Macrocosmos.

**What it offers**:
- Decentralized data scraping network
- 55+ billion scraped posts/comments
- API access (Gravity API)
- Miners scrape data, validators verify quality

**Relevance to us**:
- Could potentially query Bittensor-related data through SN13
- More relevant for social signals (Reddit, Twitter about TAO) than chain data
- Interesting for Phase 2 (sentiment analysis, community signals)

**Verdict**: Not for chain data collection, but potentially useful for social intelligence layer later.

---

### Recommended Approach: Option A (SDK + Public Endpoint)

For Phase 1, the Bittensor Python SDK with the public Finney endpoint gives us everything we need at zero cost. We build our own time-series by taking daily snapshots.

---

## 2. AWS Free Tier Assessment

### Always Free Services (no expiration)

| Service | Free Tier Limit | Our Usage (Daily Pipeline) | Fits? |
|---------|----------------|---------------------------|-------|
| **Lambda** | 1M requests/mo + 400K GB-sec | ~128 invocations/day × 30 = 3,840/mo | ✅ Easily |
| **S3** | 5 GB storage | ~32K records × 30 days × ~1KB = ~1GB/mo | ✅ For months |
| **DynamoDB** | 25 GB storage + 25 RCU/WCU | State tracking + metadata | ✅ Easily |
| **EventBridge** | Free for AWS events | Scheduling triggers | ✅ Free |
| **Step Functions** | 4,000 state transitions/mo | 128 subnets × ~7 states = 896/day... | ⚠️ Tight |
| **SNS** | 1M publishes/mo | Alerts only | ✅ Easily |
| **CloudWatch** | 10 custom metrics, 5GB logs | Monitoring | ✅ Easily |

### Step Functions Concern

4,000 free state transitions/month. If we run 128 subnets daily with ~7 states each:
- 128 × 7 × 30 = 26,880 transitions/month → **Exceeds free tier**

**Alternatives**:
1. **Use EventBridge Scheduler + Lambda directly** (no Step Functions) — simpler, fully free
2. **Batch subnets** — one Lambda processes all 128 subnets in a single invocation
3. **Use Step Functions only for error handling** — happy path is Lambda-to-Lambda via EventBridge

**Recommendation**: Skip Step Functions for MVP. Use EventBridge Scheduler → Lambda. The FSM logic lives in code (DynamoDB state tracking), not in Step Functions. This keeps us fully in free tier.

---

### 12-Month Free Tier (expires after account creation)

| Service | Free Tier Limit | Relevance |
|---------|----------------|-----------|
| **API Gateway** | 1M API calls/mo for 12 months | Agent-facing API |
| **SQS** | 1M requests/mo | Message queuing between stages |

---

## 3. Recommended Free Tier Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SCHEDULING LAYER                           │
│                                                              │
│  EventBridge Scheduler (cron: daily at 00:00 UTC)           │
│  → Triggers: Collector Lambda (Container Image)             │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    COLLECTION LAYER                           │
│                                                              │
│  Lambda (Container Image): metagraph-collector               │
│  - Iterates all active subnets (AsyncSubtensor concurrent)  │
│  - Pulls metagraph, reg costs, hyperparams, alpha prices    │
│  - Stores raw snapshots to S3                               │
│  - Publishes 1 SQS message per subnet to process queue      │
│  - Updates DynamoDB state (IDLE → COLLECTING)               │
│  - Reads secrets from Parameter Store (cached)              │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATION LAYER                        │
│                                                              │
│  SQS Queue: process-subnet (with DLQ, maxReceiveCount: 3)  │
│  → Triggers: Processor Lambda per subnet                    │
│                                                              │
│  SNS Topic: subnet-processed (completion fan-out)           │
│  → SQS Queue: completion-tracker                            │
│  → Triggers: Finalizer Lambda                               │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    PROCESSING LAYER                           │
│                                                              │
│  Lambda (Container Image): metrics-processor                 │
│  - Reads raw snapshot from S3                               │
│  - Computes all derived metrics                             │
│  - Stores derived metrics to S3 + DynamoDB                  │
│  - Publishes completion to SNS                              │
│                                                              │
│  Lambda (Container Image): finalizer                         │
│  - Checks if all subnets processed (DynamoDB)              │
│  - Generates daily briefing, rankings, static site          │
│  - Generates Pipeline Health page                           │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    STORAGE LAYER                              │
│                                                              │
│  S3: tao-intelligence-{account-id}                          │
│  ├── raw/metagraph/{date}/{subnet-id}.json                  │
│  ├── raw/registration-costs/{date}.json                     │
│  ├── raw/hyperparameters/{date}/{netuid}.json               │
│  ├── raw/alpha-prices/{date}.json                           │
│  ├── raw/tao-price/{date}.json                              │
│  ├── derived/metrics/{date}/{subnet-id}.json                │
│  ├── derived/rankings/{date}.json                           │
│  ├── derived/briefings/{date}.json                          │
│  ├── site/ (Jinja2 + Tailwind CSS HTML)                     │
│  └── config/schemas/                                        │
│                                                              │
│  DynamoDB: tao-pipeline (single-table, PITR enabled)        │
│  ├── SUBNET#{netuid} / STATE                                │
│  ├── SUBNET#{netuid} / METRICS#latest                       │
│  ├── SUBNET#{netuid} / PROFILE#basic|winner|validator|...   │
│  ├── SUBNET#{netuid} / HYPERPARAMS                          │
│  ├── CONFIG / ACTIVE_SUBNETS|TRACKED_HOTKEYS|CLOUD_PRICING  │
│  ├── CYCLE#{cycle_id} / status, counts                      │
│  ├── RANKING / LATEST                                       │
│  └── HOTKEY#{ss58} / EARNINGS#7d|30d|all                    │
│                                                              │
│  CloudFront → S3 (site/ prefix) for HTTPS                  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    QUERY LAYER                                │
│                                                              │
│  - Kiro reads from S3/DynamoDB directly (via AWS CLI/SDK)   │
│  - Static site browsable via CloudFront URL                 │
│  - Daily briefing synced to local workspace                 │
│  - Pipeline Health page shows operational status            │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Lambda Container Image Strategy

**Problem**: Bittensor SDK with substrate-interface is 200-300MB unzipped, exceeding Lambda's 250MB limit.

**Solution**: Container Image Lambda (supports up to 10GB). Same free tier applies.

```dockerfile
FROM public.ecr.aws/lambda/python:3.12
RUN dnf install -y gcc python3-devel libffi-devel openssl-devel && dnf clean all
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ${LAMBDA_TASK_ROOT}/
COPY templates/ ${LAMBDA_TASK_ROOT}/templates/
CMD ["handler.main"]
```

---

## 5. Cost Projection (Staying Free)

### Month 1-12 (Free Tier Active)

| Service | Usage | Cost |
|---------|-------|------|
| Lambda | ~260 invocations/day (1 collector + 128 processor + 128 SNS + 1 finalizer), ~100K GB-sec | $0 |
| S3 | ~2-3 GB stored | $0 (5GB free) |
| DynamoDB | ~500 MB, low throughput, PITR enabled | $0 (25GB free) |
| EventBridge | 30 scheduled events | $0 |
| SQS | ~8K messages/month (128 subnets × 2 queues × 30 days) | $0 (1M free) |
| SNS | ~4K publishes/month | $0 (1M free) |
| CloudFront | <1GB transfer/month | $0 (1TB free) |
| Parameter Store | 2-3 parameters | $0 (standard free) |
| CloudWatch | Basic monitoring + 5 alarms | $0 (10 alarms free) |
| ECR | ~500MB image storage | $0 (500MB free) |
| **Total** | | **$0/month** |

### After Month 12 (Core services remain always-free)

Lambda, S3 (first 5GB), DynamoDB (25GB + 25 RCU/WCU), SQS (1M requests), SNS (1M publishes), and CloudWatch (10 alarms) are **always free** — not 12-month limited.

CloudFront (1TB/month) and ECR (500MB) are also always-free tier.

API Gateway (if added later) would cost after 12 months: ~$3.50/million requests.

### When Costs Start

Costs appear when:
- S3 exceeds 5GB (after ~5-6 months of daily snapshots for all 128 subnets)
- ECR image exceeds 500MB (unlikely with single image)
- We add LLM calls for code analysis (Bedrock/external API costs)
- We need more DynamoDB throughput (unlikely at personal scale)

**Mitigation for S3 growth**: 
- Compress snapshots (gzip JSON → ~80% reduction)
- Use S3 Intelligent-Tiering for older data
- Archive data older than 90 days to S3 Glacier

---

## 6. Paid Options Assessment (When Free Tier Isn't Enough)

| Need | Paid Option | Cost | When to Consider |
|------|-------------|------|-----------------|
| Historical backfill | Taostats API | ~$50-200/mo? | When we need pre-2026 data |
| Faster queries | DynamoDB on-demand | ~$1-5/mo | If 25 RCU/WCU isn't enough |
| More storage | S3 Standard | $0.023/GB/mo | After 5GB (~6 months) |
| Code analysis | Bedrock (Claude) | ~$0.01-0.05/analysis | Phase 2 (Subnet Researcher) |
| Reliable RPC | GetBlock/own node | $50-100/mo | If public endpoint fails |
| Real-time events | WebSocket on EC2 | ~$10-30/mo | If daily isn't frequent enough |
| REST API | API Gateway | $3.50/M requests | After 12-month free tier |

**Key insight**: The expensive part isn't data collection — it's the LLM-powered analysis (Subnet Researcher, Strategy layer). That's where we'll eventually spend money. The pipeline itself can run nearly free for a long time.

---

## 7. Kiro as Agent Interface

Since you're using Kiro as your agent layer, the "consumer" of this data is Kiro itself. This simplifies things:

**How Kiro consumes the data**:
1. Kiro can read files directly from the workspace (local JSON/markdown)
2. Kiro can execute AWS CLI commands to query S3/DynamoDB
3. Kiro can run Python scripts that pull from the data layer

**Implication**: We don't need a REST API for Phase 1. We can:
- Store daily summaries as markdown/JSON in this workspace
- Have a "refresh" script that pulls latest data from S3
- Kiro reads the local files and reasons over them

**Future**: When we want other agents or automation to consume the data, we add API Gateway.

---

## 8. Deployment Strategy

**Infrastructure as Code**: Terraform or AWS CDK (Python)

**Recommended**: AWS CDK (Python) because:
- Same language as the Bittensor SDK
- Type-safe infrastructure definitions
- Easy to version control
- Kiro can help write and modify it

**Deployment pipeline**:
1. CDK defines all infrastructure (Lambda, S3, DynamoDB, EventBridge)
2. Lambda code lives in this repo
3. `cdk deploy` creates everything
4. EventBridge starts triggering daily collection

---

## Summary: Phase 1 Architecture Decision

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Data source | Bittensor SDK + public Finney endpoint | Free, authoritative, sufficient |
| Scheduling | EventBridge Scheduler | Free, simple cron |
| Compute | Lambda (Container Image, Python 3.12) | Free tier, serverless, supports large SDK |
| Orchestration | SQS + SNS | Free tier, reliable delivery, DLQ, completion detection |
| Storage (raw) | S3 (JSON, gzipped) | Free 5GB, cheap after |
| Storage (state) | DynamoDB (single-table, PITR) | Free 25GB, fast lookups, backup |
| Static site | Jinja2 + Tailwind CSS → S3 + CloudFront | Free, HTTPS, no build tools in Lambda |
| Secrets | Parameter Store | Free, cached at cold start |
| Agent interface | Local files + AWS CLI + static site | Kiro reads directly, no API needed yet |
| IaC | AWS CDK (Python) | Same language, type-safe |
| Monitoring | CloudWatch Alarms + Pipeline Health page | Free tier (10 alarms), no dashboard cost |
| Backup | DynamoDB PITR + S3 deny-delete policy | Free, append-only is inherent backup |
