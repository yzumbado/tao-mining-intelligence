# TAO Mining Intelligence Pipeline — Architecture Document

**Version**: 2.0 (2026-05-25)
**Status**: Stage 1 COMPLETE, deployed, autonomous
**Author**: Human-agent collaboration (yvvargas + Kiro agents)

---

## Document Index

| Section | File | Description |
|---------|------|-------------|
| 1. System Overview | [01-system-overview.md](01-system-overview.md) | Vision, current state, data flow, deployment topology |
| 2. Component Architecture | [02-components.md](02-components.md) | Each Lambda, its responsibilities, interfaces, and contracts |
| 3. Data Architecture | [03-data-architecture.md](03-data-architecture.md) | DynamoDB schema, S3 layout, data lifecycle |
| 4. Metrics Engine | [04-metrics-engine.md](04-metrics-engine.md) | All 17 algorithms, their status, formulas, and validation state |
| 5. Quality & Testing | [05-quality-testing.md](05-quality-testing.md) | Test strategy, contract tests, conformance system, known lies |
| 6. Architecture Assessment | [06-assessment.md](06-assessment.md) | What we're proud of, what's OK, what needs improvement |
| 7. Technical Roadmap | [07-roadmap.md](07-roadmap.md) | Evolution path from Stage 1 → Stage 7 |

---

## Quick Reference

- **Live data**: https://dkfh19zkgqq18.cloudfront.net/llms.txt
- **AWS Account**: 651484323929 (us-east-1)
- **Cost**: $0/month (all free tier)
- **Tests**: 210 passing (properties: 96, unit: 90, integration: 6, CDK: 13, contract: 4)
- **Metrics**: 17 algorithms (5 PROVEN, 10 HYPOTHESIS, 2 NEEDS_VALIDATION)
- **Subnets tracked**: 129, self-refreshing every 1-4 hours per subnet
