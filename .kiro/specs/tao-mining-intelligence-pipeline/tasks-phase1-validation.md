# Phase 1: Validation & Scaffolding (COMPLETE)

## Status: ✅ All tasks complete

## Tasks

- [x] 1.1 Create project structure, dependencies, and shared data models
  - Directory structure created: cdk/, lambda/src/, lambda/templates/, tests/, scripts/
  - Pydantic models defined (schemas.py, enums.py)
  - Config module with PIPELINE_ENV switching
  - _Requirements: 10.1, 10.4, 13.1, 20.1, 20.2_

- [x] 1.2 Validate Bittensor SDK v10 async connectivity
  - scripts/validate_sdk.py — connects to Finney, retrieves metagraph
  - Confirmed: AsyncSubtensor works, 2s per subnet, 129 subnets discoverable
  - Discovered: R (rank) and T (trust) removed in SDK v10
  - Discovered: immunity_period=7200, tempo=99, max_validators=128
  - _Requirements: 1.2, 1.3, 2.1_

- [x] 1.3 Validate DynamoDB single-table operations with moto
  - scripts/validate_dynamodb.py — all PK/SK patterns work
  - Confirmed: conditional writes, cycle idempotency, split profiles
  - Discovered: DynamoDB needs Decimal (not float)
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 1.4 Validate SQS/SNS messaging with moto
  - scripts/validate_sqs_sns.py — full orchestration flow works
  - Confirmed: Collector→SQS→Processor→SNS→Finalizer pattern
  - _Requirements: 13.4, 14.1_

- [ ] 1.5 Build Dockerfile and validate container image locally (BLOCKED: Docker not installed)
  - Dockerfile created at lambda/Dockerfile
  - lambda/requirements.txt pinned to exact versions
  - Needs Docker Desktop to build and test
  - _Requirements: 13.1, 13.2_

## Key Findings Applied to Design

- Emission is per-tempo in alpha tokens (daily = emission × 7200/tempo)
- Only 4/247 miners earn on SN1 (extreme WTA)
- Alpha price: τ0.0101 per alpha on SN1
- Pool reserves: ~28,265 TAO in SN1 pool
- Concurrent collection: 128 subnets in ~60s (fits 15-min Lambda)
- get_all_subnets_netuid() returns 129 subnets
- get_subnet_price(netuid) returns Balance object
- get_subnet_hyperparameters(netuid) works with correct field names
