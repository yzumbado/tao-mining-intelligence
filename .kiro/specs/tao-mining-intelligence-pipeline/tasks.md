# Implementation Plan: TAO Mining Intelligence Pipeline

## Overview

This plan follows **TDD (Test-Driven Development)** — for every algorithm and component, we write the test FIRST, then implement until the test passes. All property tests are MANDATORY, not optional.

The plan is split into focused task files by phase for manageability:

| Phase | File | Focus | Status |
|-------|------|-------|--------|
| 1 | `tasks-phase1-validation.md` | SDK validation, project scaffolding | ✅ Complete |
| 2 | `tasks-phase2-core.md` | State Manager, Storage, Instrumentation | ✅ Complete |
| 3 | `tasks-phase3-metrics.md` | Metrics Engine (TDD: test first, then implement) | ✅ Complete |
| 4 | `tasks-phase4-lambdas.md` | Collector, Processor, Finalizer Lambdas | ✅ Complete |
| 5 | `tasks-phase5-site.md` | Static site, CDK infrastructure, deployment | Not Started |

## Execution Approach

- **TDD**: Write property test → run (fails) → implement algorithm → run (passes)
- **All tests mandatory**: No optional test tasks
- **Validate assumptions first**: Phase 1 proves SDK/AWS work before building
- **Incremental**: Each phase builds on the previous, with checkpoints

## Key Decisions

- Python 3.12, Container Image Lambda (Bittensor SDK too large for zip)
- SQS/SNS orchestration (not S3 events)
- Two S3 buckets (private data + CloudFront site)
- DynamoDB single-table with configurable thresholds
- Jinja2 + Tailwind CSS (not MkDocs)
- Hypothesis for property-based testing
- moto for AWS mocking in unit tests

## Task Dependency Graph

```
Phase 1 (Validation) → Phase 2 (Core) → Phase 3 (Metrics) → Phase 4 (Lambdas) → Phase 5 (Site/Deploy)
```

Within Phase 3 (Metrics), each algorithm follows:
```
Write Property Test → Implement Algorithm → Run Test → Pass → Next Algorithm
```
