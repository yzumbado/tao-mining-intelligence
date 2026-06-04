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

### AD-R6: GitHub PAT Required (POC-Validated)

Unauthenticated rate limit (60/hr) is insufficient — a single research cycle for 30 subnets burns through it. PAT stored in Parameter Store at `/tao-pipeline/github-token` gives 5000/hr.

### AD-R7: URL Validation on Every Run (POC-Validated)

Static repo mappings are 38-56% stale within months. The researcher must HEAD-check URLs before fetching content and handle 404s gracefully (mark as "repo_not_found", not crash).

---

## POC-Validated Findings (2026-06-04)

These findings override earlier assumptions in this design:

| Assumption | POC Result | Design Impact |
|-----------|-----------|--------------|
| min_compute.yml is widely adopted | Only 2-3/16 repos have it (15%) | Heuristics are primary, min_compute.yml is bonus |
| Static repo lists are a good seed | 38-56% dead links | Must validate URLs every run |
| Repo names are stable | Major repos renamed within a year | Need self-healing discovery |
| 60 req/hr is workable | Burns through in one session | GitHub PAT is mandatory |
| README keywords detect model type | 60% accuracy | Multi-signal approach needed |

### Multi-File Scanning Cascade (Priority Order)

```
1. min_compute.yml     → Structured YAML, instant (if exists)
2. Dockerfile          → FROM image reveals GPU (nvidia/cuda), deps
3. docker-compose.yml  → GPU device mapping, service architecture
4. requirements.txt    → torch/cuda/vllm = GPU required
5. pyproject.toml      → Same as above, modern Python
6. go.mod / Cargo.toml → Language detection (not Python = different approach)
7. README.md           → Keywords for model type, hardware mentions
```

For each file, scan in THIS order. Stop GPU detection at first confirmed signal.

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

Scanning cascade — check files in priority order, stop at first confirmed signal:

| Priority | File | GPU Signal | Model Type Signal |
|----------|------|-----------|------------------|
| 1 | `min_compute.yml` | `gpu.required: true`, `gpu.min_vram` | — |
| 2 | `Dockerfile` | `FROM nvidia/cuda`, `--gpus`, runtime flags | Base image (vllm, transformers) |
| 3 | `docker-compose*.yml` | `deploy.resources.reservations.devices` | Service names (miner, validator) |
| 4 | `requirements.txt` | torch, cuda, bitsandbytes, vllm, triton | transformers, diffusers, whisper |
| 5 | `pyproject.toml` | Same as above in `[dependencies]` | Same |
| 6 | `go.mod` / `Cargo.toml` | — (language detection only) | Non-Python = custom build needed |
| 7 | `README.md` | "A100", "GPU", "VRAM", "CUDA" keywords | "LLM", "image", "storage", etc |

**Also check subdirectories** (`neurons/`, `miner/`, `src/`) for deps files — modern repos use workspaces where root has no dependencies.

### Miner Entrypoint Detection

Check for existence of (in order):
- `neurons/miner.py`
- `miner/` directory (with Dockerfile or main.py/main.go)
- `src/miner/`
- `miner.py` at root

### Difficulty Classification

| Signals present | Difficulty |
|----------------|-----------|
| Open-source miner + min_compute.yml + clear README | `trivial` |
| Open-source miner + some docs | `medium` |
| No miner code OR miner requires custom model training | `hard` |
| No repo found | `unknown` |

---

## Subnet Repo Mapping

**POC finding**: Static mappings rot fast (38-56% stale). Must validate on every run.

### Bootstrap Strategy
1. Merge `nanlabs/subnet_links.json` (29 entries) + `awesome-bittensor` links (32 entries)
2. Deduplicate and validate each URL (HEAD request)
3. Store validated mapping in `config/subnet_repos.json` (checked into git as seed)
4. At runtime, Lambda validates URL before fetching. On 404, marks repo as `stale`.

### Self-Healing
- If a known URL returns 404, try GitHub search: `org:{old_org} bittensor subnet {netuid}`
- GitHub redirects renamed repos (301) — follow redirects and update mapping
- DynamoDB caches validated URLs with `last_verified` timestamp
- Monthly: re-verify all URLs, flag any that moved

### Current Coverage (POC-validated, June 2026)
- 13 repos confirmed accessible via GitHub API
- 8/20 top-ranked subnets have known repos
- Top 3 earners (SN44, SN95, SN51) have NO known public repo

---

## GitHub Rate Limiting Strategy

- **Unauthenticated**: 60 requests/hour — **INSUFFICIENT** (POC burned through in one session)
- **With PAT** (stored in Parameter Store at `/tao-pipeline/github-token`): 5000 req/hr ✅
- **Circuit breaker**: If rate limited (403), back off. Discovery re-schedules on next hourly cycle.
- **Caching**: Store raw repo content in S3. Only re-fetch if stale (>7 days).
- **URL validation**: HEAD request before fetching content. Handle 404 gracefully.
- **Requests per subnet**: ~5-8 (root listing + min_compute + Dockerfile + deps + README)

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
