# Conformance System — Build Plan

**Status**: READY TO BUILD
**Created**: 2026-05-19
**Proofs completed**: 2, 3, 4 (all validated — concept works)

---

## Phase A: Inline Post-Conditions (30 min, zero new infra)

Add `_verify_outputs()` to Finalizer after output generation. Checks:

1. Rankings count == metrics count
2. No NaN/None in critical ranking fields
3. Rankings sorted descending by score
4. Briefing date matches today
5. source_block > 0 for at least some subnets

On failure: log structured JSON + emit CloudWatch metric. Does NOT block pipeline.

## Phase B: Auditor Lambda (1-2 sessions)

Separate Lambda, hourly trigger, picks 2-3 random checks per run:

| Check | Type | Source |
|-------|------|--------|
| `never_fires` | runtime | Proof 3 — dead emission threshold |
| `field_range` | runtime | Proof 3 — test values outside live range |
| `link_integrity` | runtime | Bug 1 — broken nav link |
| `source_block` | runtime | Bug 2 — field not propagated |
| `orphaned_functions` | code | Proof 2 — 4 dead features found |
| `feat_without_test` | git | Proof 2 — predicted 2/3 of bugs |
| `dead_modules` | code | Proof 2 — orchestrator/collector never imported |
| `schema_drift` | spec | Proof 2 — 3 design doc metrics missing |

Output: `/data/audit_report.json` (CloudFront) + DynamoDB `AUDIT_FINDING#{id}`

## Phase C+: Advanced (future)

- Requirements parser (extract SHALL → verifiable assertions)
- Live data → test fixture pipeline (auto-generate edge case fixtures)
- Agent-driven resolution (agent reads findings, proposes fixes)

---

## Key Design Decisions (from proofs)

- Findings are self-contained (agent can fix from finding alone)
- Detection is agent work; decisions are human work
- Cheap probes > exhaustive checks (randomized coverage over time)
- Track "never-fires" for every conditional output path
- Flag feat-without-test commits as bug predictors
- Operate on live data, not just code

## References

- `kb/conformance-findings-schema.md` — Finding data model (18 required fields)
- `kb/conformance-proof2-commit-history.md` — Git analysis patterns
- `kb/conformance-proof3-test-vs-production.md` — Value range comparison
- `kb/conformance-concept-index.md` — Full concept map + design rules
- `kb/design-principle-agent-native-conformance.md` — Philosophy + collaboration model
