# Phase 5: Static Site, CDK, Deployment & Smoke Test

## Status: ✅ Complete (core items shipped, some descoped to Phase 2+)

## Tasks

### 5.1 Static Site Generator

- [x] 5.1a Create Jinja2 templates with Tailwind CSS dark theme
  - lambda/templates/base.html — Tailwind CDN, dark theme (#0d1117), navigation
  - lambda/templates/index.html — all subnets with badges (category, mining_style, health)
  - lambda/templates/rankings.html — sortable table with mining_style column
  - lambda/templates/briefing.html — daily briefing display
  - DESCOPED: subnet.html, health.html (deferred to Phase 2+)
  - _Requirements: 21.1-21.14, 14.6_

- [x] 5.1b Implement Jinja2SiteGenerator class
  - lambda/src/site_generator/generator.py
  - generate_index(), generate_rankings_page(), generate_briefing_page()
  - Data freshness indicator (warning when >36h old)
  - _Requirements: 21.1-21.14, 34.1-34.3_

- [x] 5.1c Write unit tests for site generator
  - tests/unit/test_site_generator.py (9 tests)
  - _Requirements: 21.2, 21.3, 14.6, 34.2_

### 5.2 CDK Infrastructure Stack

- [x] 5.2a Create CDK app and pipeline stack
- [x] 5.2b Define storage resources (two S3 buckets, DynamoDB)
- [x] 5.2c Define orchestration resources (SQS, SNS, EventBridge)
- [x] 5.2d Define security resources (IAM, CloudFront)
- [x] 5.2e Write CDK assertion tests (11 tests)

### 5.3 Local Development Environment

- DESCOPED: Docker Compose and local scripts deferred to Phase 2+
  - E2E integration test with moto covers the local testing need

### 5.4 Smoke Test

- DESCOPED: scripts/smoke_test.py deferred (E2E integration test covers this)

- [x] 5.4b Create sanity check module
  - lambda/src/sanity_check.py

### 5.5 Integration Test

- [x] 5.5a Write end-to-end integration test
  - tests/integration/test_pipeline_e2e.py (2 tests)
  - Simulates: Processor (3 subnets) → Finalizer
  - Verifies: state transitions, S3 outputs, DynamoDB records, rankings, briefing
  - Verifies: idempotency (duplicate processing safe)

## Checkpoint

After Phase 5: Full pipeline deployed and running. Smoke test passes. Static site accessible via CloudFront. Daily cycles producing data. Run `pytest tests/ -v` — all green (property + unit + integration + CDK).

## Post-Deployment

- [ ] Create OPERATIONS.md runbook
  - How to check pipeline health
  - How to investigate DLQ messages
  - How to manually trigger a cycle
  - How to add/remove tracked hotkeys
  - How to reprocess a day's data
  - How to update cloud pricing / thresholds
  - How to handle circuit breaker trip
  - Troubleshooting decision trees
  - _Requirements: 43.1-43.2_

- [ ] Monitor first 7 days of daily cycles
- [ ] Verify data accumulation in S3
- [ ] Validate ROI estimates against manual calculations
- [ ] Populate subnet classifications for top 10 subnets (manual)
- [ ] Add your own hotkeys to tracked_hotkeys config
