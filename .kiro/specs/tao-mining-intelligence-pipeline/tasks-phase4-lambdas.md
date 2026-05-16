# Phase 4: Lambda Handlers

## Status: Not Started

## Approach

Each Lambda handler wires together the core components (StateManager, StorageLayer, MetricsEngine, Instrumentation). Tests use moto to mock AWS services.

## Tasks

### 4.1 Collector Lambda

- [ ] 4.1a Write unit tests for Collector
  - tests/unit/test_collector.py
  - Test: idempotency (duplicate trigger skipped)
  - Test: partial failure (some subnets fail, others succeed, pipeline continues)
  - Test: graceful shutdown (timeout approaching, saves partial results)
  - Test: SQS message format matches schema
  - Test: data validation rejects corrupt metagraphs
  - Test: concurrency semaphore limits connections
  - _Requirements: 1.5, 1.6, 32.1-32.4, 33.1-33.4_

- [ ] 4.1b Implement CollectorHandler
  - lambda/src/collector/handler.py
  - handle() entry point: read config once, check idempotency, collect all subnets
  - collect_metagraph() with AsyncSubtensor
  - collect_registration_costs(), collect_hyperparameters(), collect_alpha_prices(), collect_tao_price()
  - discover_subnets() for lifecycle detection
  - publish_processing_messages() to SQS
  - Graceful shutdown with context.get_remaining_time_in_millis()
  - Concurrency semaphore (configurable limit)
  - Data validation before storage
  - Full instrumentation (every operation wrapped in instrument())
  - _Requirements: 1.1-1.6, 2.1-2.3, 8.1-8.4, 22.1-22.3, 23.1-23.2, 24.1-24.2, 31.1-31.5, 32.1-32.4, 33.1-33.4_

- [ ] 4.1c Run tests — all must pass

### 4.2 Processor Lambda

- [ ] 4.2a Write unit tests for Processor
  - tests/unit/test_processor.py
  - Test: receives SQS message, reads raw data, computes metrics, stores results
  - Test: missing previous-day snapshot → trend metrics marked insufficient_data
  - Test: SNS publish format correct
  - Test: split profile writes (basic, winner, validator, intelligence, composability)
  - Test: hotkey tracking (earnings, deregistration detection)
  - _Requirements: 3.1-3.7, 17.1-17.6_

- [ ] 4.2b Implement ProcessorHandler
  - lambda/src/processor/handler.py
  - handle() entry point: parse SQS message, set trace_id, process subnet
  - Wire MetricsEngine for all derived metrics
  - Store derived metrics to S3 + DynamoDB
  - Update subnet profiles (winner profile, intelligence notes)
  - Track hotkeys (earnings, position changes)
  - Publish completion to SNS
  - Full instrumentation
  - _Requirements: 3.1-3.7, 15.1-15.9, 17.1-17.6, 19.7-19.10_

- [ ] 4.2c Run tests — all must pass

### 4.3 Finalizer Lambda

- [ ] 4.3a Write unit tests for Finalizer
  - tests/unit/test_finalizer.py
  - Test: not all subnets done → early exit
  - Test: all subnets done → generates briefing, rankings, site
  - Test: briefing content matches expected for known input
  - Test: rankings sorted correctly
  - _Requirements: 5.1, 6.1_

- [ ] 4.3b Implement FinalizerHandler
  - lambda/src/finalizer/handler.py
  - handle() entry point: parse completion message, check if all done
  - check_cycle_complete() via StateManager
  - Generate daily briefing (BriefingGenerator)
  - Generate rankings (RankingGenerator)
  - Generate static site (SiteGenerator)
  - Mark cycle complete
  - Full instrumentation
  - _Requirements: 5.1-5.4, 6.1-6.4, 21.1-21.14_

- [ ] 4.3c Run tests — all must pass

### 4.4 Pipeline FSM Integration Test

- [ ] 4.4a Write property test (Property 6: FSM Transition Validity)
  - tests/properties/test_fsm.py
  - Generators: random event sequences (trigger, success, failure)
  - Properties: only valid transitions, retry_count increments, ERROR_FATAL after 3, 24h cooldown
  - _Validates: Requirements 7.3-7.7_

- [ ] 4.4b Write property test (Property 12: Subnet Discovery Set Operations)
  - tests/properties/test_discovery.py
  - Generators: random on-chain and stored subnet ID sets
  - Properties: new subnets added, removed archived, updated list = on-chain list
  - _Validates: Requirements 8.1-8.3_

- [ ] 4.4c Run tests — must pass

## Checkpoint

After Phase 4: All three Lambda handlers implemented and tested. Full pipeline flow works with moto mocks. Run `pytest tests/unit/ tests/properties/ -v` — all green.
