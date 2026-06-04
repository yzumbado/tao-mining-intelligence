# Stage 2: RESEARCH — Design & Implementation Plan

**Status**: Designed, ready to build
**Decided**: 2026-06-04
**Dependencies**: Stage 1 complete ✅

---

## Goal

For each subnet, answer: "What does it take to win here?" — without spending money.

## Architecture Decisions

### AD-R1: No LLM in Core Path (Free Tier)

Deterministic parsing of GitHub repos (README, requirements.txt, Dockerfile) extracts 90% of what we need. No Bedrock, no paid APIs. Zero cost.

LLM enrichment is an **optional async upgrade** via S3 drop box to a local home server. Core pipeline never waits for it, never fails because of it.

### AD-R2: Same Patterns as Stage 1 (Self-Scheduling + Discovery Safety Net)

- One Lambda per subnet invocation (SubnetResearcher)
- Self-scheduling: creates next EventBridge schedule 7 days out
- Discovery Lambda checks research staleness (>7 days) as safety net
- Circuit breaker for GitHub rate limits (60/hr unauth, 5000/hr with token)

### AD-R3: S3 Drop Box for Local LLM Enrichment

```
Researcher Lambda → S3 (enrichment/requests/{netuid}.json)
Home server polls S3 → Local LLM processes → S3 (enrichment/results/{netuid}.json)
Finalizer reads enrichment on next cycle (opportunistic)
```

- No inbound connectivity needed (home server pulls)
- Resilient: server off → requests accumulate → processes backlog on return
- No new infrastructure (same S3 bucket)
- Decoupled: core pipeline never depends on enrichment existing

### AD-R4: DynamoDB for Profiles, S3 for Artifacts

- `PK: SUBNET#{netuid} | SK: RESEARCH#latest` — structured research profile
- S3 `raw/research/{date}/{netuid}.json` — full README, requirements, Dockerfile content

### AD-R5: Rank-Change Trigger for Priority Research

When Finalizer detects a subnet jumped 10+ positions, it flags it in DynamoDB. Discovery schedules immediate research for flagged subnets (don't wait 7 days).

---

## Data Flow

```
Discovery Lambda (hourly — existing, add 10 lines)
    └── Check RESEARCH#latest.last_researched > 7 days → schedule researcher

EventBridge Scheduler (one-time, per subnet, self-perpetuating)
                │
                ▼
SubnetResearcher Lambda (one subnet per invocation)
    ├── Read repo_url from PROFILE#basic (or static mapping)
    ├── Fetch README.md, requirements.txt, Dockerfile from GitHub API
    ├── Parse deterministically:
    │   ├── GPU required? (torch/cuda in requirements)
    │   ├── Model type? (keyword matching in README)
    │   ├── VRAM estimate? (model name → lookup table)
    │   ├── Open-source miner? (neurons/miner.py exists?)
    │   └── Difficulty? (has miner + docs = trivial, no miner = hard)
    ├── Compute net profit: yield_from_stage1 - estimated_compute_cost
    ├── Store RESEARCH#latest to DynamoDB
    ├── Store raw artifacts to S3
    ├── [Optional] Write enrichment request to S3 (for local LLM)
    └── Schedule next research (7 days, self-perpetuating)
                │
                ▼
[Optional] Home Server (polls S3 every 5 min)
    ├── Reads enrichment/requests/{netuid}.json
    ├── Runs local LLM: strategy analysis, scoring reverse-engineering
    ├── Writes enrichment/results/{netuid}.json
    └── Deletes request (marks processed)
                │
                ▼
Finalizer (existing, on next run)
    └── Reads enrichment/results/ if available → upgrades profile confidence
```

---

## v1 Output Schema

```json
{
  "netuid": 4,
  "repo_url": "https://github.com/manifold-inc/targon",
  "model_type": "llm_inference",
  "gpu_required": true,
  "vram_gb_estimate": 24,
  "open_source_miner": true,
  "miner_entrypoint": "neurons/miner.py",
  "difficulty": "trivial",
  "estimated_monthly_cost_usd": 150,
  "net_tao_profit_per_day": 2.3,
  "last_researched": "2026-06-04T12:00:00Z",
  "research_confidence": "medium"
}
```

With LLM enrichment (upgrade):
```json
{
  ...all above...,
  "research_confidence": "high",
  "llm_analysis": {
    "winning_strategy": "Run Llama-3-70B with vLLM, optimize for latency",
    "validator_scoring": "Scores based on response quality + speed, min 0.6 to earn",
    "key_risks": ["Requires latest model weights updated weekly", "Top miner uses custom fine-tune"],
    "analyzed_at": "2026-06-04T13:00:00Z"
  }
}
```

---

## Detection Heuristics (No LLM)

| Signal | Detection Method |
|--------|-----------------|
| GPU required | `torch`, `cuda`, `bitsandbytes`, `triton` in requirements.txt |
| Model type | README keywords → category mapping (LLM, image, audio, storage, compute) |
| VRAM estimate | Model name (llama-70b → 40GB, stable-diffusion → 8GB) lookup table |
| Open-source miner | File exists: `neurons/miner.py`, `miner/`, `src/miner` |
| Difficulty | Has runnable miner + clear docs = trivial. Needs custom model = hard. |
| Compute cost | GPU tier × hourly rate from known pricing table |

---

## Subnet Repo Mapping

Many subnets don't have `repo_url` in their profile yet. Bootstrap with:
1. Static JSON mapping file (`config/subnet_repos.json`) seeded from community knowledge
2. On-chain metadata query (some subnets publish repo URL)
3. Organic updates as we discover repos

Start with top 30 by attractiveness score (highest value to research first).

---

## GitHub Rate Limiting Strategy

- **Unauthenticated**: 60 requests/hour (covers ~20 subnets/hour at 3 req each)
- **With token** (stored in Parameter Store): 5000 requests/hour (covers all 129 instantly)
- **Circuit breaker**: If rate limited, back off. Discovery re-schedules on next hourly cycle.
- **Caching**: Store raw repo content in S3. Only re-fetch if `Last-Modified` changed.

---

## Cost: $0/month

| Resource | Usage | Cost |
|----------|-------|------|
| Lambda | 129 invocations/week, <3s each | Free tier |
| DynamoDB | 129 writes/week | Free tier |
| S3 | ~1KB per subnet per week | Free tier |
| GitHub API | Free (public repos, optional token) | $0 |
| EventBridge | 129 one-time schedules | Free tier |

---

## Implementation Tasks

### Phase 1: Core Researcher (1-2 days)
- [ ] Create `config/subnet_repos.json` — seed top 30 subnet repo URLs
- [ ] Create `lambda/src/researcher/handler.py` — single Lambda handler
- [ ] Implement GitHub fetching (README, requirements.txt, Dockerfile)
- [ ] Implement deterministic parsing heuristics
- [ ] Implement compute cost estimation (GPU tier × pricing table)
- [ ] Store RESEARCH#latest to DynamoDB
- [ ] Store raw artifacts to S3
- [ ] Self-schedule next run (7 days)
- [ ] Add CDK: Lambda function, IAM permissions, EventBridge schedule
- [ ] Write tests (property: output schema valid, unit: parsing heuristics)

### Phase 2: Discovery Integration (half day)
- [ ] Add research staleness check to existing Discovery Lambda
- [ ] Add rank-change flag detection in Finalizer
- [ ] Discovery schedules researcher for stale/flagged subnets

### Phase 3: LLM Enrichment Drop Box (half day)
- [ ] Add S3 PUT for enrichment request at end of Researcher Lambda
- [ ] Add S3 GET for enrichment result in Finalizer profile loading
- [ ] Create standalone home-server script (`scripts/local_llm_worker.py`)
- [ ] Document home server setup in runbook

### Phase 4: Surface in Rankings (half day)
- [ ] Add research fields to rankings.json output (difficulty, cost, net_profit)
- [ ] Add research column to rankings.html table
- [ ] Update llms.txt with new endpoint

---

## Success Criteria

- 80%+ of top-30 subnets have a research profile within first week
- Research profiles are accurate enough to make mine-vs-validate decisions
- Pipeline self-recovers from GitHub downtime without intervention
- Zero additional monthly cost
