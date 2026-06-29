# TAO Pipeline — Validation & Deploy Runbook

## What This System Does

The pipeline collects data from the Bittensor blockchain once daily per subnet, computes metrics (yield, APY, risk), and publishes rankings twice daily to CloudFront. Before deploying code changes, we validate that our output matches the chain's ground truth.

---

## Deploy Flow (`./scripts/deploy.sh`)

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1/5: Unit Tests (pytest)                               │
│   • 264 tests — structural correctness                      │
│   • If FAIL → deploy blocked                                │
├─────────────────────────────────────────────────────────────┤
│ Step 2/5: Chain Validation Gate (HARD — blocks deploy)      │
│   ├── Fast pre-check (2s): Raw RPC price query              │
│   │   • Checks alpha_price for 3 subnets via Substrate RPC  │
│   │   • If >5% deviation → FAIL FAST (data is stale)        │
│   └── Full check (30s): SDK metagraph pulls                 │
│       • Compares 4 metrics × 5 subnets vs live chain        │
│       • Tolerances: price ±2%, yield ±30%, APY ±40%         │
│       • If ANY metric exceeds tolerance → deploy blocked    │
├─────────────────────────────────────────────────────────────┤
│ Step 3/5: Provider Spot Check (SOFT — warns only)           │
│   • Independent RPC call (different code path than our SDK) │
│   • Catches: SDK bugs, field interpretation errors          │
│   • If FAIL → warning logged, deploy continues             │
├─────────────────────────────────────────────────────────────┤
│ Step 4/5: CDK Deploy                                        │
│   • Pushes Lambda container + infra to AWS                  │
├─────────────────────────────────────────────────────────────┤
│ Step 5/5: Post-Deploy Spot Check (30s wait + RPC)           │
│   • Quick confirmation the pipeline is producing output     │
│   • Same RPC price check as step 3                          │
└─────────────────────────────────────────────────────────────┘
```

---

## How to Run a Deploy

```bash
source .venv/bin/activate
./scripts/deploy.sh
```

If everything is healthy, expect ~2 min total for validation steps.

---

## Emergency Deploy (validation gate down or chain unreachable)

```bash
./scripts/deploy.sh --skip-validation
```

⚠️ This skips step 2 entirely. Use ONLY when Finney endpoint is unresponsive and you need to push a critical fix. Step 3 and 5 still run (soft checks).

---

## How to Investigate a Validation Failure

**Step 2 fails with "FAST FAIL: price deviation >5%":**
- Our rankings.json is stale (pipeline hasn't refreshed recently)
- Check CloudWatch for Lambda errors
- Check `https://dkfh19zkgqq18.cloudfront.net/data/metadata.json` — look at `processed_at` timestamps
- If pipeline is healthy but slow, wait and re-run

**Step 2 fails on specific metric (e.g., "SN44 real_apy_percent: 45% > 40%"):**
- Formula may have diverged from expected
- Check if you changed `MetricsEngine.compute_real_apy` recently
- Run `python scripts/validate_all_metrics.py` standalone to see full table
- Compare against chain manually if needed

**Step 3 warns but deploy continues:**
- Not blocking, but investigate if persistent
- Usually means our SDK is interpreting a field slightly differently than the raw RPC
- Check `scripts/validate_against_providers.py` output

---

## Drift Detection (Proactive Monitoring)

Every time `validate_all_metrics.py` runs, it appends results to `data/validation_history.jsonl`. To check for gradual drift:

```bash
python scripts/check_drift.py
```

**What it detects:**
- Deviation trending UP for 5+ consecutive runs (something is slowly diverging)
- Average deviation exceeding 50% of failure threshold over 7 runs (approaching failure)

Run this weekly or before a deploy if you suspect data quality issues.

---

## Key Files

| File | Purpose | Run frequency |
|------|---------|---------------|
| `scripts/deploy.sh` | Full deploy with gates | Every deploy |
| `scripts/validate_all_metrics.py` | Hard gate (chain comparison) | Every deploy |
| `scripts/validate_against_providers.py` | Soft check (independent RPC) | Every deploy |
| `scripts/check_drift.py` | Drift analysis | Weekly / ad-hoc |
| `data/validation_history.jsonl` | Run history (local, gitignored) | Auto-appended |

---

## What Each Check Catches

| Check | Catches | Doesn't catch |
|-------|---------|---------------|
| Unit tests | Logic bugs, schema violations, edge cases | Value correctness (formula producing wrong numbers) |
| Chain validation (hard gate) | Stale data, broken pipeline, metric divergence | SDK bugs that affect both our code AND the validation |
| RPC spot check (soft) | SDK interpretation bugs, wrong field mapping | Anything not reflected in alpha_price |
| Drift detection | Gradual degradation over time | Sudden one-time failures |

---

## Prerequisites (must be running before deploy)

1. **Docker (Colima)**: `colima start` — CDK builds Lambda container images
2. **AWS credentials**: Profile `tao` in `~/.aws/credentials` (account 651484323929, us-east-1)
3. **Python venv**: `source .venv/bin/activate` (Python 3.12 required)
4. **Node.js**: npx must be available (for CDK CLI)

Verify prerequisites:
```bash
docker info >/dev/null 2>&1 && echo "Docker: OK" || echo "Docker: MISSING — run 'colima start'"
aws sts get-caller-identity --profile tao >/dev/null 2>&1 && echo "AWS: OK" || echo "AWS: MISSING"
.venv/bin/python --version 2>&1 | grep -q "3.12" && echo "Python: OK" || echo "Python: MISSING"
which npx >/dev/null 2>&1 && echo "Node/npx: OK" || echo "Node: MISSING"
```

---

## When to Use --skip-validation

The `--skip-validation` flag is for TWO scenarios:

1. **Chain endpoint down** — Finney RPC is unresponsive, you need to deploy urgently
2. **Deploying a formula fix** — The validation compares live output against chain. If live output is wrong BECAUSE of the bug you're fixing, it will always fail pre-deploy. Use `--skip-validation` and verify post-deploy manually.

After deploying with `--skip-validation`, manually verify within 30 minutes:
```bash
# Wait for at least one subnet to refresh with new code, then:
python scripts/validate_all_metrics.py
```

---

## Post-Deploy: How Long Until Data Converges

Subnets refresh independently on a fixed 24h cadence:
- **All subnets**: once per day (self-scheduling via EventBridge Scheduler)
- **Rankings**: regenerated twice daily at 06:00 + 18:00 UTC
- **Max staleness**: 26h (Discovery re-seeds if exceeded)

To monitor convergence:
```bash
# Count how many subnets have refreshed since deploy
curl -s https://dkfh19zkgqq18.cloudfront.net/data/metadata.json | python3 -c "
import json, sys
from datetime import datetime, timezone
data = json.load(sys.stdin)
deploy = datetime.fromisoformat('REPLACE_WITH_DEPLOY_TIME')
refreshed = sum(1 for s in data['subnets'].values()
                if datetime.fromisoformat(s['processed_at']) > deploy)
print(f'{refreshed}/129 subnets refreshed post-deploy')
"
```
