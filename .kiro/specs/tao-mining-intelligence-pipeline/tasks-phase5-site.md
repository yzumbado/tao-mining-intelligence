# Phase 5: Static Site, CDK, Deployment & Smoke Test

## Status: Not Started

## Tasks

### 5.1 Static Site Generator

- [ ] 5.1a Create Jinja2 templates with Tailwind CSS dark theme
  - lambda/templates/base.html — Tailwind CDN, dark theme (#0d1117), navigation
  - lambda/templates/index.html — all subnets with badges (category, mining_style, health)
  - lambda/templates/subnet.html — full intelligence card
  - lambda/templates/rankings.html — sortable table with mining_style column
  - lambda/templates/briefing.html — daily briefing display
  - lambda/templates/health.html — Pipeline Health page (last run, failures, DLQ, storage)
  - _Requirements: 21.1-21.14, 14.6_

- [ ] 5.1b Implement Jinja2SiteGenerator class
  - lambda/src/site_generator/generator.py
  - generate_index(), generate_subnet_page(), generate_rankings_page()
  - generate_briefing_page(), generate_health_page()
  - write_site_to_s3() — uploads to site bucket
  - Incremental regeneration (only changed pages)
  - Data freshness indicator (warning when >36h old)
  - _Requirements: 21.1-21.14, 34.1-34.3_

- [ ] 5.1c Write unit tests for site generator
  - tests/unit/test_site_generator.py
  - Test: generated HTML contains expected sections
  - Test: Pipeline Health page shows operational metrics
  - Test: mining_style badges render correctly
  - Test: data staleness warning appears when data >36h old
  - _Requirements: 21.2, 21.3, 14.6, 34.2_

### 5.2 CDK Infrastructure Stack

- [ ] 5.2a Create CDK app and pipeline stack
  - cdk/app.py, cdk/stacks/pipeline_stack.py
  - ECR image asset from lambda/Dockerfile
  - Three Lambda functions (Collector, Processor, Finalizer) as DockerImageFunction
  - Environment variables: PIPELINE_ENV, TABLE_NAME, BUCKET_NAME, queue URLs, topic ARNs
  - _Requirements: 13.1-13.6_

- [ ] 5.2b Define storage resources (two S3 buckets, DynamoDB)
  - Private data bucket: BlockPublicAccess=ALL, deny-delete policy, lifecycle rules
  - Site bucket: BlockPublicAccess=ALL (CloudFront OAC only)
  - DynamoDB table: on-demand, PITR enabled, single-table schema
  - Parameter Store: /tao-pipeline/price-api-key
  - _Requirements: 13.5, 35.1-35.4_

- [ ] 5.2c Define orchestration resources (SQS, SNS, EventBridge)
  - SQS process-subnet queue (visibility 900s, DLQ maxReceiveCount=3)
  - SQS DLQ (14-day retention)
  - SNS subnet-processed topic
  - SQS completion-tracker queue (subscribed to SNS)
  - EventBridge Scheduler: cron(0 0 * * ? *) with 15-min flexible window
  - SQS queue policy: restrict SendMessage to Collector role only
  - _Requirements: 13.3, 13.4, 36.5_

- [ ] 5.2d Define security resources (IAM, CloudFront)
  - Per-Lambda IAM roles with least privilege (no wildcards, no delete)
  - CloudFront distribution with OAC for site bucket
  - CloudWatch Alarms: missed cycle, DLQ depth, Lambda errors, S3 storage
  - SNS alert topic
  - CloudWatch log groups (30-day retention)
  - _Requirements: 14.5, 35.3, 36.1-36.4_

- [ ] 5.2e Write CDK assertion tests
  - tests/cdk/test_pipeline_stack.py
  - Assert: Lambda timeout/memory/container config
  - Assert: EventBridge schedule expression
  - Assert: SQS DLQ config, visibility timeout
  - Assert: DynamoDB PITR enabled
  - Assert: S3 BlockPublicAccess on both buckets
  - Assert: CloudFront distribution exists
  - Assert: No Lambda env var contains KEY/SECRET/PASSWORD/TOKEN
  - _Requirements: 13.1-13.6, 35.1-35.4, 36.1-36.5, 38.4_

### 5.3 Local Development Environment

- [ ] 5.3a Create Docker Compose and local scripts
  - docker-compose.yml with DynamoDB Local
  - scripts/run_local.py — full pipeline locally (PIPELINE_ENV=local)
  - scripts/seed_config.py — seed DynamoDB Local with CONFIG items
  - scripts/inspect_output.py — pretty-print local outputs
  - _Requirements: (operational)_

### 5.4 Smoke Test

- [ ] 5.4a Create deployment smoke test
  - scripts/smoke_test.py
  - Triggers one cycle for 3 subnets (SN1, SN4, SN8)
  - Verifies: raw snapshots exist in S3, derived metrics computed, rankings generated
  - Validates: metrics are reasonable (non-negative, within expected ranges)
  - Checks: no ERROR_FATAL states in DynamoDB
  - Checks: site HTML generated and accessible via CloudFront
  - _Requirements: (operational validation)_

- [ ] 5.4b Create sanity check module
  - lambda/src/sanity_check.py
  - Flags obviously wrong results: ROI > 1000 days on high-emission subnet, negative yields, emission sum > 1000 TAO/tempo
  - Runs after each Processor cycle, logs warnings
  - _Requirements: (data quality)_

### 5.5 Integration Test

- [ ] 5.5a Write end-to-end integration test
  - tests/integration/test_pipeline_e2e.py
  - Uses moto for all AWS services
  - Simulates: EventBridge trigger → Collector → SQS → Processor → SNS → Finalizer
  - Verifies: state transitions, S3 outputs, DynamoDB records, site generation
  - Verifies: idempotency (duplicate trigger skipped)
  - Verifies: partial failure handling (one subnet fails, others succeed)
  - _Requirements: 7.3-7.7, 9.1, 10.2_

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
