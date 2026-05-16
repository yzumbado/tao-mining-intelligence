# Phase 3: Metrics Engine (TDD)

## Status: Not Started

## Approach: Test-Driven Development

For EACH algorithm:
1. Write the property test FIRST (it will fail — no implementation yet)
2. Implement the algorithm
3. Run the test — must pass
4. Move to next algorithm

All tests are MANDATORY. No algorithm ships without its property test passing.

## Tasks

### 3.1 Deregistration Risk Scoring

- [ ] 3.1a Write property test (Property 1: Deregistration Risk Invariants)
  - tests/properties/test_deregistration_risk.py
  - Generators: random neuron lists with varying emissions, immunity periods, subnet occupancy
  - Properties: scores in [0,1], immune=0.0, non-full subnet=all 0.0, monotonicity by emission rank
  - _Validates: Requirements 4.1, 4.2, 4.3, 4.4_

- [ ] 3.1b Implement compute_deregistration_risk()
  - lambda/src/processor/metrics.py
  - Uses thresholds from configurable parameters
  - Uses immunity_period from on-chain hyperparams (not hardcoded)
  - Edge cases: empty subnet, all immune, single miner, non-full subnet
  - _Requirements: 4.1-4.5_

- [ ] 3.1c Run test — must pass

### 3.2 Gini Coefficient

- [ ] 3.2a Write property test (Property 2: Gini Coefficient Bounds)
  - tests/properties/test_gini.py
  - Generators: random float lists, all-equal, single-value, zeros
  - Properties: result in [0,1], all-equal→0.0, single-holder→approaching 1.0
  - _Validates: Requirements 18.3, 18.5_

- [ ] 3.2b Implement compute_gini_coefficient()
  - O(n log n) sorted-array algorithm
  - _Requirements: 18.3, 18.5_

- [ ] 3.2c Run test — must pass

### 3.3 Reward Distribution Model Detection

- [ ] 3.3a Write property test (Property 3: Classification Consistency)
  - tests/properties/test_reward_model.py
  - Generators: emission distributions with known WTA/PROPORTIONAL/TIERED characteristics
  - Properties: top-3 >70% → WTA, Gini <0.5 → PROPORTIONAL, deterministic, correct top-3 calculation
  - Uses configurable thresholds (not hardcoded 0.70/0.50)
  - _Validates: Requirements 18.1-18.4_

- [ ] 3.3b Implement detect_reward_distribution_model()
  - Includes _has_tiered_pattern() helper
  - Reads thresholds from config
  - _Requirements: 18.1-18.5_

- [ ] 3.3c Run test — must pass

### 3.4 ROI Estimation

- [ ] 3.4a Write property test (Property 4: ROI Computation Correctness)
  - tests/properties/test_roi.py
  - Generators: random emissions, prices, costs, tempo values
  - Properties: net_tao_yield formula correct, days_to_recoup formula, thirty_day_projection, low confidence when <7 days
  - _Validates: Requirements 12.1-12.4_

- [ ] 3.4b Write property test (Property 11: AMM Slippage Estimation)
  - tests/properties/test_slippage.py
  - Generators: random pool sizes and sell amounts
  - Properties: slippage in [0,1), monotonically increasing, zero-sell→zero-slippage
  - _Validates: Requirements 12.6, 22.5_

- [ ] 3.4c Implement compute_roi_estimates() and _estimate_slippage()
  - Includes tempo-to-daily conversion (×7200/tempo)
  - Only averages across earning miners (emission > 0)
  - Conservative slippage upper bound (constant-product, ignoring concentrated liquidity)
  - _Requirements: 12.1-12.6_

- [ ] 3.4d Run tests — both must pass

### 3.5 Taoflow Health Detection

- [ ] 3.5a Write property test (Property 5: Taoflow Health Status)
  - tests/properties/test_taoflow.py
  - Generators: random stake/emission time series of varying lengths
  - Properties: <3 negative→healthy, 3-6→declining, 7+ with >25% drop→death_spiral_risk
  - Uses configurable thresholds
  - _Validates: Requirements 11.1-11.3_

- [ ] 3.5b Implement compute_taoflow_health()
  - Reads consecutive_days and emission_decline thresholds from config
  - _Requirements: 11.1-11.4_

- [ ] 3.5c Run test — must pass

### 3.6 Miner Churn and Competition Trend

- [ ] 3.6a Write property test (Property 8: Miner Churn Computation)
  - tests/properties/test_churn.py
  - Generators: random hotkey sets with overlap
  - Properties: churn_rate formula, set differences, trend classification thresholds
  - _Validates: Requirements 26.1-26.4_

- [ ] 3.6b Implement compute_miner_churn()
  - _Requirements: 26.1-26.5_

- [ ] 3.6c Run test — must pass

### 3.7 Validator Landscape and Opportunity

- [ ] 3.7a Write property test (Property 9: Validator Concentration Flag)
  - tests/properties/test_validator.py
  - Generators: random stake distributions
  - Properties: top-1 >50% → concentrated, yield formula correct
  - _Validates: Requirements 25.1, 25.2, 25.8_

- [ ] 3.7b Implement compute_validator_landscape() and compute_validator_opportunity()
  - _Requirements: 25.1-25.10, 27.1-27.9_

- [ ] 3.7c Run test — must pass

### 3.8 Rental Profitability

- [ ] 3.8a Write property test (Property 10: Rental Profitability)
  - tests/properties/test_rental.py
  - Generators: random yields, prices, costs
  - Properties: rent_vs_buy formula, profitable iff multiplier >1.0, break_even formula
  - _Validates: Requirements 28.2-28.5_

- [ ] 3.8b Implement compute_rental_profitability()
  - Reads cloud pricing from DynamoDB config
  - _Requirements: 28.1-28.8_

- [ ] 3.8c Run test — must pass

### 3.9 Ranking and Attractiveness Score

- [ ] 3.9a Write property test (Property 7: Ranking Sort Order)
  - tests/properties/test_ranking.py
  - Generators: random subnet score lists
  - Properties: strictly descending order, one entry per subnet, all required fields present
  - _Validates: Requirements 6.2, 6.4_

- [ ] 3.9b Implement compute_attractiveness_score() and generate_rankings()
  - _Requirements: 6.1-6.4_

- [ ] 3.9c Run test — must pass

### 3.10 Daily Briefing Thresholds

- [ ] 3.10a Write property test (Property 13: Briefing Threshold Filtering)
  - tests/properties/test_briefing.py
  - Generators: random day-over-day metric changes
  - Properties: emission >10% included, reg cost >20% included, below-threshold excluded
  - Uses configurable thresholds
  - _Validates: Requirements 5.2_

- [ ] 3.10b Implement briefing threshold logic
  - _Requirements: 5.1-5.4_

- [ ] 3.10c Run test — must pass

### 3.11 Output Schema Compliance

- [ ] 3.11a Write property test (Property 14: Output Schema Compliance)
  - tests/properties/test_schema_compliance.py
  - Generators: random pipeline outputs
  - Properties: metadata header present, TAO units (not RAO), percentages in [0,1], block numbers positive
  - _Validates: Requirements 10.1, 10.4, 20.1_

- [ ] 3.11b Verify all output models pass schema compliance
  - _Requirements: 10.1-10.4, 20.1-20.5_

- [ ] 3.11c Run test — must pass

## Checkpoint

After Phase 3: ALL 14 property tests pass. The metrics engine is mathematically correct and handles all edge cases. Run `pytest tests/properties/ -v` — all green.
