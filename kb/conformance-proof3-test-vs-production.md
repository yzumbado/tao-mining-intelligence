# Proof 3: Test Data vs Production Data

**Date**: 2026-05-19
**Question**: How badly are our tests lying about production reality?
**Answer**: Significantly. 2 fields have test values outside production range entirely. Most numeric fields have test values in the wrong order of magnitude.

---

## Results Summary

| Field | Live Range | Test Values | Verdict |
|-------|-----------|-------------|---------|
| `net_tao_yield` | 0.05 — 104.7 | 0.5, 1.0 | ⚠️ Tests in bottom 13% of range |
| `days_to_recoup` | 0.000005 — 44.5 | 5.0, 15.0 | ⚠️ Tests miss 95% of subnets (near-zero) |
| `competitive_density` | 0.0002 — 0.074 | 0.2, 0.4 | ❌ Test values 3-5x above max real value |
| `emission_trend` | -0.0009 — 0.0014 | 0.05, -0.02 | ❌ Test values 100x larger than reality |
| `attractiveness_score` | 0.52 — 0.95 | 0.55, 0.85 | ✅ Reasonable |
| `alpha_price` | 0.003 — 1.0 | 0.05, 0.03 | ✅ Within range |
| `thirty_day_projection` | -10.3 — 3142.4 | 14.0, 4.0 | ⚠️ Tests miss the 100-3000 range |

**Field sets match** — no missing or extra fields between test and production.

---

## Critical Findings

### 1. `competitive_density` test values are physically impossible

- **Live max**: 0.074 (all 129 subnets are below 0.075)
- **Test uses**: 0.2 and 0.4
- **Why**: Formula is `earning_miners / (earning_miners + total_emission)`. With real emissions (10-100+ TAO/day), the denominator dominates. You'd need total_emission < 1 TAO/day to get density > 0.2.
- **Impact**: The attractiveness score's density penalty (`1.0 - min(competitive_density, 1.0)`) is always ~1.0 in production. The test exercises a penalty of 0.8 and 0.6 which never happens.
- **Implication**: The density component of the attractiveness score is effectively dead weight in production — it never differentiates subnets.

### 2. `emission_trend` test values are 100x too large

- **Live range**: ±0.001 (max absolute value: 0.0014)
- **Test uses**: 0.05 and -0.02
- **Why**: Bittensor emissions change very slowly day-to-day. The 10% alert threshold in the briefing is never triggered because real changes are < 0.2%.
- **Impact**: The briefing's emission alert logic is correct but the threshold (10%) is calibrated for a world that doesn't exist. Real meaningful changes might be 0.5-1%.
- **Implication**: Either lower the alert threshold or accept that emission alerts will never fire.

### 3. `days_to_recoup` — tests miss the dominant pattern

- **82/129 subnets** have recoup < 0.001 days (< 1.4 minutes)
- **Tests use**: 5.0 and 15.0 days
- **Why**: Most subnets have minimum burn registration (0.0005 TAO). With yields of 10-100 TAO/day, recoup is microseconds.
- **Impact**: The "days to recoup" display shows "0d" for 82 subnets. Not a bug, but the metric is uninformative for the majority of subnets.
- **Implication**: Consider showing "< 1 min" or removing recoup from the primary display when it's negligible. The real decision factor for these subnets isn't registration cost — it's hardware/skill requirements.

### 4. `net_tao_yield` — tests are in the bottom tail

- **72/129 subnets** yield 10-100 TAO/day
- **Tests use**: 0.5 and 1.0
- **Impact**: Tests never exercise the display formatting for large yields (104.337 TAO/day). The "%.3f" format works but shows "104.337" which is fine.
- **Implication**: Low risk, but tests should include at least one high-yield value.

---

## What This Proves

1. **Test values are hand-crafted idealizations** — they were chosen for "nice" numbers (0.5, 1.0, 5.0) not for realism.

2. **Two fields have test values outside the physically possible range** — `competitive_density` and `emission_trend` tests exercise code paths that production never hits.

3. **The dominant production pattern (near-zero recoup, near-zero trend) is untested** — 82/129 subnets live in a regime no test covers.

4. **Threshold calibration is wrong** — the 10% emission alert threshold was set without knowing that real changes are < 0.2%. The threshold should be ~1% or the feature is dead.

---

## Actionable Outcomes

### Immediate (fix thresholds):
- Lower emission alert threshold from 10% to 1% (or make it configurable via DynamoDB thresholds)
- This will make the briefing actually generate alerts

### Short-term (ground test fixtures):
- Save today's live rankings.json as `tests/fixtures/live/rankings_2026-05-19.json`
- Add a test that loads real data and verifies rendering/formatting
- Update test factories to use realistic value ranges

### Medium-term (the conformance auditor does this automatically):
- Dimension 5 (Live Data → Test Fixtures) samples production weekly
- Flags when test values are outside production range
- Auto-generates fixture files from live samples

### Design question surfaced:
- **Is `competitive_density` a useful metric?** It never differentiates subnets in practice. The formula mixes units (count + TAO). Consider replacing with `earning_miners / total_miners` (occupancy rate) which would actually vary.
