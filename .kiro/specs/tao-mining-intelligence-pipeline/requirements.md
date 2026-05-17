# Requirements Document

## Introduction

The TAO Mining Intelligence Pipeline is an automated data collection and processing system that gathers Bittensor subnet data from the public Finney endpoint, computes derived metrics, and serves structured intelligence to an AI agent (Kiro) for TAO accumulation decision support. The system evaluates both **mining and validating** opportunities across all subnets, recommending whichever path yields the highest net TAO return given available resources (hardware, capital, skills). The primary strategic objective is **TAO accumulation through participation** — identifying subnets where mining or validating yields the highest net TAO return after costs. The pipeline runs daily on AWS free-tier infrastructure (Lambda, S3, DynamoDB, EventBridge Scheduler) and follows an assembly-line FSM model where each stage has defined inputs and outputs. Phase 1 focuses exclusively on on-chain data collection and derived metric computation — no LLM analysis, no Discord/YouTube intelligence.

## Glossary

- **Pipeline**: The end-to-end data processing system comprising Collector, Processor, and Storage stages
- **Collector**: The Lambda function responsible for pulling raw metagraph data from the Bittensor network
- **Processor**: The Lambda function responsible for computing derived metrics from raw snapshots
- **Metagraph**: The complete state of all neurons (miners and validators) in a single Bittensor subnet at a point in time
- **Subnet**: A specialized decentralized network within Bittensor focused on a specific AI task, identified by a netuid
- **Neuron**: A participant (miner or validator) registered on a subnet, occupying a UID slot
- **Miner**: A neuron that produces digital commodities (AI outputs, compute, storage) and receives emission rewards
- **Validator**: A neuron that evaluates miner work quality and assigns scores (weights)
- **Netuid**: The unique integer identifier for a subnet on the Bittensor network
- **UID**: The unique integer slot identifier for a neuron within a subnet (0-255)
- **Hotkey**: The public key identifying a neuron's operational identity on-chain
- **Coldkey**: The public key identifying a neuron's staking/ownership wallet
- **Emission**: TAO tokens distributed to neurons as rewards, measured in RAO (1 TAO = 10^9 RAO)
- **Incentive**: A neuron's proportional share of miner emissions within a subnet (sums to 1 across all miners)
- **Registration_Cost**: The dynamic TAO burn required to register a new hotkey on a subnet
- **Deregistration**: Removal of the lowest-emission neuron (outside immunity period) when a new registration occurs on a full subnet
- **Immunity_Period**: The block count after registration during which a neuron cannot be deregistered (typically 4096 blocks)
- **Alpha_Token**: The subnet-specific token that trades against TAO on a Constant Product AMM
- **Taoflow**: The emission model where subnets must maintain positive net TAO staking inflow to receive emissions
- **Snapshot**: A point-in-time capture of all metagraph data for a subnet
- **Derived_Metric**: A computed value calculated from raw snapshot data (e.g., deregistration risk, competitive density)
- **Pipeline_State**: The FSM state tracking collection and processing progress per subnet per cycle
- **Finney_Endpoint**: The public WebSocket endpoint for the Bittensor mainnet (wss://entrypoint-finney.opentensor.ai:443)
- **Collection_Cycle**: A single daily execution of the full pipeline across all monitored subnets
- **Subnet_Intelligence_Card**: A structured summary document for a subnet containing latest metrics and derived intelligence

## Requirements

### Requirement 1: Daily Metagraph Collection

**User Story:** As a mining strategist, I want daily snapshots of all active subnet metagraphs collected automatically, so that I have a consistent time-series of on-chain mining data to analyze.

#### Acceptance Criteria

1. WHEN the EventBridge Scheduler triggers at the configured daily time, THE Collector SHALL initiate a Collection_Cycle for all monitored subnets.
2. FOR EACH monitored subnet, THE Collector SHALL retrieve the complete metagraph via the Bittensor Python SDK connected to the Finney_Endpoint.
3. THE Collector SHALL capture the following fields per neuron: stake, incentive, emission, consensus, validator_trust, dividends, hotkey, coldkey, active status, alpha_stake, total_stake, block_at_registration, and blocks_since_last_step.
4. WHEN a metagraph is successfully retrieved, THE Collector SHALL store the raw snapshot as a JSON file in S3 at the path `raw/metagraph/{date}/{netuid}.json`.
5. WHEN a metagraph retrieval fails for a subnet, THE Collector SHALL log the error, update the Pipeline_State to ERROR_RETRYABLE, and continue collecting remaining subnets without halting the Collection_Cycle.
6. THE Collector SHALL complete a full Collection_Cycle for all monitored subnets within the Lambda 15-minute timeout by using asynchronous concurrent requests.

### Requirement 2: Registration Cost Collection

**User Story:** As a mining strategist, I want daily registration cost data for all subnets, so that I can identify optimal registration timing and compute ROI estimates.

#### Acceptance Criteria

1. WHEN the EventBridge Scheduler triggers, THE Collector SHALL retrieve the current registration cost (burn amount in TAO) for each monitored subnet.
2. WHEN registration costs are retrieved, THE Collector SHALL store the data as a JSON file in S3 at the path `raw/registration-costs/{date}.json` containing all subnet costs with timestamps.
3. THE Collector SHALL record each subnet's registration cost with the block number at which the cost was observed.

### Requirement 3: Derived Metrics Computation

**User Story:** As a mining strategist, I want pre-computed derived metrics from raw snapshots, so that Kiro can answer strategic questions without performing raw data analysis each time.

#### Acceptance Criteria

1. WHEN a new raw metagraph snapshot is stored in S3, THE Processor SHALL compute derived metrics for that subnet.
2. THE Processor SHALL compute a deregistration risk score for each miner in the subnet based on the miner's emission rank relative to other miners and the miner's immunity period status.
3. THE Processor SHALL compute competitive density as the ratio of active miners to total miner emission for the subnet.
4. THE Processor SHALL compute emission trend by comparing the current snapshot's total subnet emission against the previous day's snapshot for the same subnet.
5. THE Processor SHALL compute per-miner emission share as each miner's emission divided by total subnet miner emission.
6. THE Processor SHALL store derived metrics as a JSON file in S3 at the path `derived/metrics/{date}/{netuid}.json`.
7. THE Processor SHALL update the DynamoDB split profile records for the subnet (PK: `SUBNET#{netuid}`, SK: `PROFILE#basic`, `PROFILE#winner`, `PROFILE#validator`, `PROFILE#intelligence`, `PROFILE#composability`) with the latest derived metric values appropriate to each profile type.

### Requirement 4: Deregistration Risk Scoring

**User Story:** As a miner, I want to know my deregistration risk on each subnet I mine, so that I can take action before losing my registration.

#### Acceptance Criteria

1. THE Processor SHALL assign a deregistration risk score between 0.0 (safe) and 1.0 (imminent deregistration) to each miner in a subnet.
2. WHILE a miner is within the immunity period, THE Processor SHALL assign a deregistration risk score of 0.0 to that miner.
3. WHEN a subnet has all 256 UID slots occupied, THE Processor SHALL increase the deregistration risk score for the lowest-emission miners proportionally to their proximity to the minimum emission position.
4. WHEN a subnet has unoccupied UID slots, THE Processor SHALL assign a deregistration risk score of 0.0 to all miners in that subnet.
5. THE Processor SHALL include in the risk assessment the registration queue pressure (number of recent registrations in the past 24 hours of blocks).

### Requirement 5: Daily Briefing Generation

**User Story:** As a mining strategist, I want a daily diff summary showing what changed overnight, so that Kiro can brief me on significant developments each morning.

#### Acceptance Criteria

1. WHEN the Processor completes metrics computation for all subnets in a Collection_Cycle, THE Processor SHALL generate a daily briefing document.
2. THE Processor SHALL include in the daily briefing: new subnets detected, subnets with emission changes exceeding 10% day-over-day, registration cost changes exceeding 20% day-over-day, miners deregistered since the previous snapshot, and miners with rank changes exceeding 50 positions.
3. THE Processor SHALL store the daily briefing as a JSON file in S3 at the path `derived/briefings/{date}.json`.
4. THE Processor SHALL store the daily briefing as a markdown file in the local workspace at a configured path for direct Kiro consumption.

### Requirement 6: Subnet Ranking and Comparison

**User Story:** As a mining strategist focused on TAO accumulation, I want subnets ranked by net TAO yield potential, so that Kiro can recommend which subnet generates the most TAO for my investment.

#### Acceptance Criteria

1. THE Processor SHALL compute a mining attractiveness score for each subnet based primarily on: net TAO yield per day (alpha emission × alpha/TAO rate per miner), days-to-recoup registration cost, competitive density, emission trend direction, and Taoflow health status.
2. THE Processor SHALL rank all monitored subnets by mining attractiveness score in descending order.
3. THE Processor SHALL store the ranked subnet list in DynamoDB (PK: `RANKING`, SK: `LATEST`) and in S3 at `derived/rankings/{date}.json`.
4. THE Processor SHALL include in each subnet's ranking entry: netuid, net TAO yield per day, days-to-recoup, 30-day projected TAO accumulation, active miner count, registration cost (TAO), competitive density, emission trend (7-day), alpha/TAO price, alpha liquidity, and the computed attractiveness score.

### Requirement 7: Pipeline State Management

**User Story:** As a system operator, I want the pipeline to track its own state reliably, so that I can monitor progress, detect failures, and resume from partial completions.

#### Acceptance Criteria

1. THE Pipeline SHALL maintain state in DynamoDB for each subnet's collection status using PK: `SUBNET#{netuid}`, SK: `STATE`.
2. THE Pipeline SHALL track the following state fields per subnet: last_collected timestamp, last_processed timestamp, current_status (IDLE, COLLECTING, PROCESSING, COMPLETE, ERROR_RETRYABLE, ERROR_FATAL), last_error message, and retry_count.
3. WHEN a Collection_Cycle begins, THE Pipeline SHALL transition each subnet's state from IDLE to COLLECTING.
4. WHEN collection succeeds for a subnet, THE Pipeline SHALL transition that subnet's state from COLLECTING to PROCESSING.
5. WHEN processing completes for a subnet, THE Pipeline SHALL transition that subnet's state to COMPLETE.
6. WHEN a retryable error occurs, THE Pipeline SHALL increment the retry_count and attempt the failed operation up to 3 times with exponential backoff before transitioning to ERROR_FATAL.
7. IF a subnet remains in ERROR_FATAL state, THEN THE Pipeline SHALL skip that subnet in subsequent cycles until the error is manually acknowledged or a configurable cooldown period (24 hours) elapses.

### Requirement 8: Subnet Discovery and Lifecycle

**User Story:** As a mining strategist, I want the pipeline to automatically detect new subnets and track subnet lifecycle changes, so that I never miss a new mining opportunity or fail to notice a dying subnet.

#### Acceptance Criteria

1. WHEN a Collection_Cycle begins, THE Collector SHALL query the Bittensor network for the current list of active subnets and compare against the stored list of monitored subnets.
2. WHEN a new subnet is detected (present on-chain but absent from monitored list), THE Collector SHALL add the subnet to the monitored list and flag the subnet as newly discovered in the daily briefing.
3. WHEN a previously monitored subnet is no longer present on-chain, THE Pipeline SHALL transition that subnet's lifecycle state to ARCHIVED and include the archival event in the daily briefing.
4. THE Pipeline SHALL store the monitored subnet list in DynamoDB (PK: `CONFIG`, SK: `ACTIVE_SUBNETS`) and update the list at the start of each Collection_Cycle.

### Requirement 9: Historical Data Preservation

**User Story:** As a mining strategist, I want all collected data preserved with full history, so that Kiro can analyze trends over weeks and months and I never lose valuable time-series data.

#### Acceptance Criteria

1. THE Pipeline SHALL store all raw snapshots in S3 using an append-only pattern where existing files are never overwritten or deleted.
2. THE Pipeline SHALL store all derived metrics in S3 using date-partitioned paths that preserve the full history of computations.
3. THE Pipeline SHALL maintain a `latest` pointer in DynamoDB for each subnet's metrics that always references the most recent computation without removing historical records from S3.
4. WHEN the S3 storage exceeds 4 GB, THE Pipeline SHALL compress snapshots older than 30 days using gzip encoding to remain within the 5 GB free-tier limit.

### Requirement 10: Agent-Consumable Output Format

**User Story:** As an AI agent (Kiro), I want pipeline outputs in structured, well-documented formats, so that I can parse and reason over the data without ambiguity.

#### Acceptance Criteria

1. THE Pipeline SHALL produce all JSON output files with a consistent schema that includes: a metadata header (collection_timestamp, pipeline_version, source_block_number), and a data payload.
2. THE Pipeline SHALL include a JSON Schema definition file in S3 at `config/schemas/` for each output type (raw snapshot, derived metrics, daily briefing, subnet ranking).
3. THE Pipeline SHALL produce a local workspace summary file (markdown format) after each Collection_Cycle containing: the date, subnets collected, top 10 subnets by emission, any alerts or anomalies, and a pointer to the full data in S3.
4. THE Pipeline SHALL ensure all numeric values use consistent units: TAO for token amounts (not RAO), percentages as decimals between 0.0 and 1.0, and block numbers as integers.

### Requirement 11: Taoflow Health Indicators

**User Story:** As a mining strategist, I want to detect subnets entering a "death spiral" (declining staking inflow leading to zero emissions under Taoflow), so that Kiro can warn me to exit before emissions collapse.

#### Acceptance Criteria

1. THE Processor SHALL compute a net staking flow indicator for each subnet by comparing current total stake against the previous day's total stake.
2. THE Processor SHALL flag a subnet as "declining" when net staking flow is negative for 3 or more consecutive collection days.
3. THE Processor SHALL flag a subnet as "death spiral risk" when net staking flow is negative for 7 or more consecutive collection days AND total emission has decreased by more than 25% over the same period.
4. THE Processor SHALL include Taoflow health status (healthy, declining, death_spiral_risk) in the subnet's derived metrics and daily briefing.

### Requirement 12: ROI Estimation

**User Story:** As a mining strategist focused on TAO accumulation, I want estimated net TAO yield and payback timelines for each subnet, so that Kiro can tell me which subnets generate the most TAO relative to their registration cost.

#### Acceptance Criteria

1. THE Processor SHALL compute a **net TAO yield per day** for each subnet by: (average alpha emission per tempo for earning miners) × (7200 / subnet tempo) × (current alpha/TAO exchange rate) — representing the expected daily TAO-equivalent earnings for a miner who is actively earning on the subnet.
2. THE Processor SHALL compute a **days-to-recoup** metric by dividing the current registration cost (in TAO) by the net TAO yield per day.
3. THE Processor SHALL compute a **30-day projected TAO accumulation** per subnet: (net TAO yield per day × 30) - registration cost, representing expected net TAO gain after one month of mining.
4. WHEN fewer than 7 days of historical data exist for a subnet, THE Processor SHALL flag ROI estimates as low-confidence.
5. THE Processor SHALL rank subnets by net TAO yield per day (after alpha→TAO conversion) as the primary attractiveness metric.
6. THE Processor SHALL include in ROI output: the alpha→TAO conversion rate used, the slippage estimate for converting daily earnings, and whether holding alpha vs. swapping to TAO immediately is more favorable based on alpha price trend.

### Requirement 13: Infrastructure as Code Deployment

**User Story:** As a developer, I want the entire pipeline infrastructure defined as AWS CDK (Python) code, so that I can deploy, update, and tear down the pipeline with a single command.

#### Acceptance Criteria

1. THE Pipeline SHALL define all AWS resources (Lambda functions, S3 bucket, DynamoDB table, EventBridge Scheduler rule, IAM roles) in an AWS CDK Python application.
2. THE CDK application SHALL configure Lambda functions with the Python 3.12 runtime, 512 MB memory, and 15-minute timeout.
3. THE CDK application SHALL configure the EventBridge Scheduler to trigger the Collector Lambda daily at 00:00 UTC.
4. THE CDK application SHALL configure S3 event notifications to trigger the Processor Lambda when new objects are created in the `raw/` prefix.
5. THE CDK application SHALL configure DynamoDB in on-demand capacity mode to stay within the always-free tier (25 GB storage, 25 RCU/WCU equivalent).
6. THE CDK application SHALL be deployable with a single `cdk deploy` command and removable with `cdk destroy`.

### Requirement 14: Error Observability

**User Story:** As a system operator, I want visibility into pipeline failures and anomalies, so that I can diagnose and fix issues before they cause data gaps.

#### Acceptance Criteria

1. THE Pipeline SHALL log all collection and processing operations to CloudWatch Logs with structured JSON log entries containing: timestamp, subnet netuid, operation, status, duration, and error details when applicable.
2. WHEN a Collection_Cycle completes, THE Pipeline SHALL emit a CloudWatch custom metric recording: subnets collected successfully, subnets failed, total duration, and data volume stored.
3. IF more than 10% of subnets fail collection in a single cycle, THEN THE Pipeline SHALL publish an alert to an SNS topic.
4. THE Pipeline SHALL retain CloudWatch logs for 30 days to support debugging without exceeding free-tier log storage.
5. THE Pipeline SHALL define CloudWatch Alarms for: missed cycle (no successful collection in 25 hours), DLQ message count > 0, Lambda errors > 0, S3 storage exceeding 4GB threshold.
6. THE Pipeline SHALL generate a "Pipeline Health" page on the static site containing: last successful run timestamp, subnets collected vs. failed, DLQ depth, S3 storage usage, and any active alerts — so that pipeline operational status is visible alongside the intelligence data without requiring a separate CloudWatch Dashboard.

### Requirement 15: Subnet Profile and Mining Type Classification

**User Story:** As a mining strategist, I want each subnet to have a comprehensive profile describing what it does, what type of mining it requires, what the reward distribution model is, and what mining style it uses (the key resource consumed to compete), so that Kiro can match my hardware, capital, and skills to the right subnets.

#### Acceptance Criteria

1. THE Pipeline SHALL maintain a Subnet Profile record for each monitored subnet containing: netuid, name, description, category, mining_style, reward_distribution_model, hardware_requirements, and repo_url.
2. THE Pipeline SHALL classify each subnet into one of the following **categories** (what it produces): LLM_INFERENCE, VISION_IMAGE, TRADING_FINANCIAL, DATA_COLLECTION, COMPUTE, TRAINING, PREDICTION, STORAGE, SCIENTIFIC, or OTHER.
3. THE Pipeline SHALL classify each subnet's **mining style** (key resource consumed to compete) as one or more of: GPU_INFERENCE (VRAM + compute to serve models), GPU_TRAINING (sustained GPU for training/fine-tuning), RAW_COMPUTE (CPU/GPU cycles, commodity hardware), KNOWLEDGE_STRATEGY (human expertise, data analysis, trading signals), DATA_COLLECTION (bandwidth + storage, I/O-bound), MODEL_QUALITY (ML expertise, best model wins regardless of hardware), LATENCY (network proximity, fastest response wins), or CAPITAL (TAO stake, no hardware needed — validation/delegation).
4. THE Pipeline SHALL classify each subnet's reward distribution model as one of: WINNER_TAKES_ALL, PROPORTIONAL, TIERED, or UNKNOWN.
5. THE Pipeline SHALL store Subnet Profiles in DynamoDB (PK: `SUBNET#{netuid}`, SK: `PROFILE#basic`) and in S3 at `cards/subnet-{netuid}/profile.json`.
6. WHEN a subnet is newly discovered, THE Pipeline SHALL create a Subnet Profile with category, mining_style, and reward_distribution_model set to UNKNOWN and flag it for manual classification in the daily briefing.
7. THE Pipeline SHALL include in the Subnet Profile: minimum hardware requirements (GPU type, VRAM, CPU, RAM, bandwidth, storage) when known, or mark as UNKNOWN for manual population.
8. THE Pipeline SHALL support filtering and ranking subnets by mining style, enabling queries like "show me all KNOWLEDGE_STRATEGY subnets" or "which GPU_INFERENCE subnets are rental-profitable."
9. THE Pipeline SHALL include mining style in the static site's subnet pages and rankings table as a filterable/sortable column with color-coded badges.

### Requirement 16: Mining Requirements and Entry Barrier Assessment

**User Story:** As a mining strategist, I want to know the concrete requirements to start mining on each subnet (hardware, software, models, capital), so that Kiro can assess whether I can compete before I invest.

#### Acceptance Criteria

1. THE Pipeline SHALL compute an entry barrier score (LOW, MEDIUM, HIGH, VERY_HIGH) for each subnet based on: registration cost, hardware requirements category, and competitive density.
2. THE Pipeline SHALL include in each subnet's derived metrics: estimated monthly hardware cost (when hardware requirements are known), registration cost in TAO and USD, and the entry barrier score.
3. THE Pipeline SHALL classify mining requirements into tiers: CPU_ONLY (no GPU needed), CONSUMER_GPU (RTX 3090/4090 class), DATACENTER_GPU (A100/H100 class), MULTI_GPU (multiple datacenter GPUs), or SPECIALIZED (custom hardware).
4. THE Pipeline SHALL include in the subnet ranking output the mining requirements tier so that subnets can be filtered by available hardware.

### Requirement 17: On-Chain Miner Wallet Tracking

**User Story:** As a mining strategist, I want to track specific miner wallets (hotkeys) across subnets over time, so that Kiro can confirm actual earnings, detect top-performer strategies, and validate ROI estimates against real on-chain data.

#### Acceptance Criteria

1. THE Pipeline SHALL maintain a watchlist of tracked hotkeys stored in DynamoDB (PK: `CONFIG`, SK: `TRACKED_HOTKEYS`) that can be manually configured.
2. FOR EACH tracked hotkey, THE Pipeline SHALL record per Collection_Cycle: which subnets the hotkey is registered on, the UID held on each subnet, the emission received on each subnet, the incentive score, and the rank.
3. THE Pipeline SHALL compute cumulative earnings per tracked hotkey over configurable time windows (7-day, 30-day, all-time) and store in DynamoDB (PK: `HOTKEY#{ss58_address}`, SK: `EARNINGS#{period}`).
4. THE Pipeline SHALL detect when a tracked hotkey is deregistered from a subnet and include the event in the daily briefing with the hotkey's final emission rank and total earnings on that subnet.
5. THE Pipeline SHALL detect when a tracked hotkey registers on a new subnet and include the event in the daily briefing.
6. THE Pipeline SHALL support tracking competitor hotkeys (top 5 miners per subnet by incentive) automatically, storing their performance history for strategy analysis.

### Requirement 18: Reward Distribution Model Detection

**User Story:** As a mining strategist, I want to know whether a subnet uses winner-takes-all, proportional, or tiered reward distribution, so that Kiro can assess whether I can realistically earn on that subnet given my expected ranking.

#### Acceptance Criteria

1. THE Processor SHALL analyze the emission distribution across miners in each subnet snapshot to detect the reward distribution model.
2. THE Processor SHALL classify a subnet as WINNER_TAKES_ALL when the top 3 miners receive more than 70% of total miner emissions.
3. THE Processor SHALL classify a subnet as PROPORTIONAL when the Gini coefficient of miner emissions is below 0.5.
4. THE Processor SHALL classify a subnet as TIERED when emission distribution shows distinct clusters (step-function pattern) that don't fit WTA or proportional models.
5. THE Processor SHALL store the detected reward distribution model, the Gini coefficient, and the top-3 emission concentration percentage in the subnet's derived metrics.
6. THE Processor SHALL include in the daily briefing any subnet whose detected reward distribution model changed from the previous day (indicating an incentive mechanism update).

### Requirement 19: Subnet Context and Description

**User Story:** As a mining strategist, I want a comprehensive human-readable description of each subnet — including how mining works on it, what winners look like and why they win, and what intelligence the data analysis reveals — so that Kiro has full context when recommending mining targets.

#### Acceptance Criteria

1. THE Pipeline SHALL maintain a context description field in each Subnet Profile containing: a one-paragraph summary of the subnet's purpose, the digital commodity it produces, its target consumers, and its competitive position in the ecosystem.
2. THE Pipeline SHALL store the subnet's GitHub repository URL, documentation URL, and Discord/community URL when known.
3. THE Pipeline SHALL track the subnet owner's hotkey and any known identity information (name, organization) associated with the subnet.
4. THE Pipeline SHALL include in the Subnet Profile: the subnet's creation date (block_at_registration), age in days, and the number of incentive mechanism updates detected (based on emission distribution pattern changes).
5. WHEN a subnet's context description is empty or marked UNKNOWN, THE Pipeline SHALL flag it in the daily briefing as requiring manual research and population.
6. THE Pipeline SHALL maintain a "How Mining Works" section in each Subnet Profile describing: what task miners perform, how validators score responses, what the scoring criteria are, and what the typical request/response cycle looks like (populated manually or via code analysis in later phases).
7. THE Pipeline SHALL maintain a "Winner Profile" section in each Subnet Profile containing data-driven analysis of top performers: common characteristics of top-5 miners (hardware tier, response patterns, registration age, stake levels), what differentiates them from median miners, and any observable patterns in how they achieved and maintain their position.
8. THE Processor SHALL auto-populate the Winner Profile section by analyzing metagraph data: top-5 miner emission share, their average trust score vs. subnet average, their registration age vs. subnet average, their consistency (days in top-10 over past 30 days), and whether they appear on multiple subnets.
9. THE Pipeline SHALL maintain an "Intelligence Notes" section in each Subnet Profile for insights extracted from data analysis, including: detected anomalies, strategy observations (e.g., "top miners registered within 24h of last incentive change"), correlation findings (e.g., "trust score above 0.8 correlates with 3x emission vs. median"), and risk warnings.
10. THE Pipeline SHALL update the Winner Profile and Intelligence Notes sections automatically after each Collection_Cycle based on the latest derived metrics and historical trend data.

### Requirement 20: Data Format Specification

**User Story:** As a system designer, I want all pipeline outputs to follow explicit, versioned data format specifications, so that consuming agents can reliably parse data and we can evolve formats without breaking compatibility.

#### Acceptance Criteria

1. THE Pipeline SHALL version all output schemas using semantic versioning (e.g., v1.0.0) included in the metadata header of every output file.
2. THE Pipeline SHALL define and store JSON Schema files for: raw metagraph snapshot, registration cost record, derived metrics, daily briefing, subnet ranking, subnet profile, and hotkey tracking record.
3. THE Pipeline SHALL include in every output file a `schema_version` field and a `schema_url` field pointing to the corresponding JSON Schema definition in S3.
4. WHEN a schema change is introduced, THE Pipeline SHALL increment the schema version and maintain backward compatibility by supporting reading of the previous schema version for at least 30 days.
5. THE Pipeline SHALL define a canonical Subnet Intelligence Card format that aggregates: the Subnet Profile, latest derived metrics, latest ranking position, Taoflow health status, reward distribution model, and entry barrier assessment into a single queryable document per subnet.

### Requirement 21: Human-Readable Markdown Site Generation

**User Story:** As a mining strategist, I want a browsable static markdown site generated from pipeline data, so that I can visually inspect subnet intelligence, validate pipeline outputs, and eventually share mining guides with others.

#### Acceptance Criteria

1. WHEN the Processor completes a Collection_Cycle, THE Pipeline SHALL generate a set of markdown files representing the current state of all monitored subnets.
2. THE Pipeline SHALL generate an index page (`index.md`) listing all monitored subnets with: netuid, name, category, mining attractiveness rank, Taoflow health status, and entry barrier score.
3. THE Pipeline SHALL generate a per-subnet page (`subnets/{netuid}.md`) containing: the full Subnet Intelligence Card rendered as readable markdown, including description, mining type, hardware requirements, reward distribution model, current metrics, emission trend chart (ASCII or linked), top 5 miners, registration cost history, ROI estimate, and Taoflow health status.
4. THE Pipeline SHALL generate a daily briefing page (`briefings/{date}.md`) containing the daily diff summary in human-readable format.
5. THE Pipeline SHALL generate a rankings page (`rankings.md`) showing all subnets sorted by mining attractiveness with key metrics in a table format.
6. THE Pipeline SHALL store the generated markdown files in S3 at the path `site/` and optionally sync them to a configured local workspace directory for direct browsing.
7. THE Pipeline SHALL include in each per-subnet page a "How to Mine" section containing: registration command template, hardware setup notes, known tips or gotchas, and links to the subnet's repo and documentation (populated as UNKNOWN when not yet researched).
8. THE Pipeline SHALL include a last-updated timestamp on every generated page so that staleness is immediately visible.
9. THE Pipeline SHALL regenerate only pages whose underlying data changed since the previous cycle to minimize S3 write operations.
10. THE Pipeline SHALL render the markdown site as a static HTML site using a modern dark-theme design with: a black/dark background (#0d1117 or similar), high-contrast readable typography (light gray/white text, minimum 16px body font), accent colors for status indicators (green for healthy, amber for declining, red for death spiral risk), and clean spacing for scanability.
11. THE Pipeline SHALL use a static site generator (e.g., MkDocs with Material theme, or a custom HTML template) to convert the markdown files into styled HTML pages hosted on S3 with CloudFront or S3 static website hosting.
12. THE Pipeline SHALL ensure the site is responsive and readable on both desktop and mobile screens.
13. THE Pipeline SHALL use color-coded badges or indicators for: subnet health status, entry barrier level, reward distribution type, and mining category — so that key information is visually scannable without reading full text.
14. THE Pipeline SHALL include data visualization elements where applicable: sparkline-style emission trend indicators, bar representations for competitive density, and color-gradient risk indicators for deregistration scores.

### Requirement 22: Alpha Token Price and Liquidity Tracking

**User Story:** As a mining strategist, I want to know the current and historical alpha token price and liquidity for each subnet, so that Kiro can estimate actual USD earnings (not just TAO emissions) and warn me about illiquid subnets where I can't sell what I earn.

#### Acceptance Criteria

1. THE Collector SHALL retrieve the current alpha token price (in TAO) for each monitored subnet from the on-chain AMM pool data.
2. THE Collector SHALL retrieve the alpha token liquidity depth (total TAO in the AMM pool) for each subnet.
3. THE Pipeline SHALL store alpha token price and liquidity data alongside the metagraph snapshot at `raw/alpha-prices/{date}.json`.
4. THE Processor SHALL compute a real emission value per miner by multiplying the miner's alpha token emission by the current alpha/TAO price.
5. THE Processor SHALL flag subnets as "low liquidity risk" when the AMM pool contains less than 100 TAO (meaning large sell orders would cause significant slippage).
6. THE Processor SHALL include alpha token price, 7-day price trend, and liquidity status in the subnet's derived metrics and Subnet Intelligence Card.
7. THE Processor SHALL use alpha-adjusted emission values (not raw emission) when computing ROI estimates and mining attractiveness rankings.

### Requirement 23: TAO/USD Price Feed

**User Story:** As a mining strategist, I want TAO/USD price as informational context, so that Kiro can express the dollar value of my TAO holdings when useful — though the primary optimization target is TAO accumulation, not USD.

#### Acceptance Criteria

1. THE Collector SHALL retrieve the current TAO/USD price from a public price API (e.g., CoinGecko, Binance) during each Collection_Cycle.
2. THE Pipeline SHALL store the TAO/USD price with timestamp in S3 at `raw/tao-price/{date}.json`.
3. THE Processor SHALL include USD-equivalent values as supplementary context (not primary metrics) in: registration cost, net TAO yield, and cumulative earnings for tracked hotkeys.
4. THE Pipeline SHALL NOT depend on the price feed for core pipeline operation — if the price API fails, the pipeline SHALL continue without USD values and all TAO-denominated metrics remain fully functional.
5. THE Pipeline SHALL NOT use USD values in mining attractiveness rankings or ROI calculations — these SHALL be computed purely in TAO terms.

### Requirement 24: Subnet Hyperparameter Collection

**User Story:** As a mining strategist, I want the on-chain hyperparameters for each subnet (immunity period, tempo, burn dynamics), so that Kiro can predict registration cost trends, calculate immunity windows, and understand the competitive rules of each subnet.

#### Acceptance Criteria

1. THE Collector SHALL retrieve the following on-chain hyperparameters for each monitored subnet: immunity_period, tempo, max_allowed_validators, max_allowed_miners, min_allowed_weights, activity_cutoff, max_weight_limit, BurnHalfLife, BurnIncreaseMult, MinBurn, and MaxBurn.
2. THE Pipeline SHALL store subnet hyperparameters in S3 at `raw/hyperparameters/{date}/{netuid}.json` and in DynamoDB (PK: `SUBNET#{netuid}`, SK: `HYPERPARAMS`).
3. THE Processor SHALL detect hyperparameter changes between consecutive collection days and include any changes in the daily briefing (hyperparameter changes often signal incentive mechanism updates).
4. THE Processor SHALL use the immunity_period hyperparameter (not a hardcoded default) when computing deregistration risk scores.
5. THE Processor SHALL use BurnHalfLife and BurnIncreaseMult to compute a registration cost trend prediction (expected cost in 24h, 48h, 7d) based on recent registration activity.

### Requirement 25: Validator Landscape Analysis

**User Story:** As a mining strategist, I want visibility into the validator landscape of each subnet — how many, how concentrated, how active, what winners look like, and whether validating is a viable TAO accumulation strategy — so that Kiro can assess consensus stability, identify scoring risks, and evaluate validation as an alternative to mining.

#### Acceptance Criteria

1. THE Processor SHALL compute per subnet: active validator count, total validator stake, and validator stake concentration (top-1 validator stake share, top-3 validator stake share).
2. THE Processor SHALL flag a subnet as "validator concentrated" when a single validator holds more than 50% of total validator stake on that subnet.
3. THE Processor SHALL compute validator activity score based on how recently validators have updated their weights (using blocks_since_last_step for validator neurons).
4. THE Processor SHALL include validator landscape metrics (count, concentration, activity) in the subnet's derived metrics and Subnet Intelligence Card.
5. THE Processor SHALL flag in the daily briefing any subnet where validator count drops below 3 (consensus becomes unreliable with too few validators).
6. THE Pipeline SHALL maintain a "Validator Profile" section in each Subnet Profile containing data-driven analysis of validators: top validators by dividends earned, their stake levels, their VTrust scores, how long they've been active, and their weight-setting frequency.
7. THE Processor SHALL auto-populate the Validator Profile by analyzing metagraph data: top-3 validators by dividends, their stake vs. subnet average, their VTrust score, their registration age, and whether they validate on multiple subnets.
8. THE Processor SHALL compute net TAO yield for validators per subnet: (average daily alpha dividends per validator) × (alpha/TAO rate), enabling comparison of validator vs. miner TAO accumulation on the same subnet.
9. THE Processor SHALL include in the Validator Profile: estimated capital requirement to validate (minimum stake needed to earn meaningful dividends), validator permit threshold, and whether validator slots are available.
10. THE Pipeline SHALL maintain "Validator Intelligence Notes" with observations such as: "top validator sets weights every 50 blocks — very active scoring", "validator X controls 60% of stake and appears to favor miners with low latency", or "new validator joined 3 days ago and is disrupting consensus scores."

### Requirement 26: Miner Churn and Competitive Dynamics

**User Story:** As a mining strategist, I want to understand how competitive and stable each subnet is over time (churn rate, average miner lifespan, trend direction), so that Kiro can distinguish stable earning opportunities from volatile ones.

#### Acceptance Criteria

1. THE Processor SHALL compute daily miner churn rate per subnet by comparing the set of active miner hotkeys between consecutive snapshots (new registrations + deregistrations / total miners).
2. THE Processor SHALL compute average miner lifespan per subnet using block_at_registration data (current_block - registration_block for all active miners).
3. THE Processor SHALL compute a competition trend indicator: INCREASING (more miners joining than leaving over 7 days), STABLE (net change < 5%), or DECREASING (more miners leaving than joining).
4. THE Processor SHALL include churn rate, average miner lifespan, and competition trend in the subnet's derived metrics.
5. THE Processor SHALL flag in the daily briefing any subnet with churn rate exceeding 10% in a single day (indicating a major event — incentive change, mass deregistration, or new opportunity attracting miners).

### Requirement 27: Validator Opportunity Assessment

**User Story:** As a TAO accumulation strategist, I want validation opportunities evaluated with the same rigor as mining opportunities — including capital requirements, expected TAO yield, hardware needs, and what successful validators do — so that Kiro can recommend whether to mine or validate on each subnet.

#### Acceptance Criteria

1. THE Processor SHALL compute net TAO yield per day for validators on each subnet: (average daily alpha dividends per validator) × (alpha/TAO rate).
2. THE Processor SHALL compute the minimum effective stake required to validate on each subnet: the stake level below which a validator earns negligible dividends (bottom 10% of validator dividends).
3. THE Processor SHALL compute validator ROI as: net TAO dividends per day relative to the stake committed (yield percentage), enabling comparison across subnets.
4. THE Processor SHALL determine validator slot availability per subnet: current validator count vs. max_allowed_validators, and whether a new validator could obtain a permit.
5. THE Processor SHALL include in the Subnet Intelligence Card a "Validation Requirements" section containing: minimum stake to be competitive, hardware requirements for running a validator (typically lighter than mining), software requirements (validator code, scoring models), and estimated setup complexity.
6. THE Processor SHALL compute a validator attractiveness score per subnet based on: net TAO yield, stake requirement, slot availability, VTrust stability, and subnet health.
7. THE Processor SHALL produce a unified ranking that compares mining and validating opportunities side-by-side, showing for each subnet: best mining TAO yield, best validating TAO yield, mining capital required (registration cost + hardware), validating capital required (stake + hardware), and a recommendation (MINE, VALIDATE, or BOTH).
8. THE Processor SHALL include in the Validator Profile: what successful validators do differently (weight-setting frequency, number of miners scored, consensus alignment), and whether running a validator on this subnet requires specialized infrastructure (e.g., running the full scoring model to evaluate miners).
9. THE Processor SHALL track validator permit requirements and flag in the daily briefing when a subnet's validator slots open up (a validator deregisters or max_allowed_validators increases).

### Requirement 28: Cloud Hardware Rental Profitability Analysis

**User Story:** As a TAO accumulation strategist, I want to know whether renting cloud GPUs to mine a subnet is profitable (yields more TAO than the rental costs), so that Kiro can recommend when renting makes sense and which provider/configuration is optimal.

#### Acceptance Criteria

1. THE Pipeline SHALL maintain a cloud pricing reference table containing hourly rental costs for common GPU configurations from major providers (Vast.ai, RunPod, Lambda Labs, AWS), stored in DynamoDB (PK: `CONFIG`, SK: `CLOUD_PRICING`) and updatable manually or via periodic API calls.
2. THE Processor SHALL compute for each subnet (where hardware requirements are known) a **rental profitability score**: (net TAO yield per day × TAO/USD price) - (daily rental cost for required hardware in USD), expressed as daily net profit/loss in USD and in TAO-equivalent.
3. THE Processor SHALL compute a **rent-vs-buy comparison**: compare the TAO accumulated by renting hardware and mining for 30 days against the TAO that could be purchased directly with the same USD spent on rental — expressed as a multiplier (e.g., "mining yields 2.3x more TAO than buying").
4. THE Processor SHALL flag subnets as "rental profitable" when the rent-vs-buy multiplier exceeds 1.0 (mining yields more TAO than buying with the same money).
5. THE Processor SHALL include in the rental analysis: the cheapest viable GPU configuration per subnet, the recommended provider, estimated monthly rental cost, expected monthly TAO yield, and the break-even TAO price (the TAO/USD price below which renting becomes unprofitable).
6. THE Processor SHALL include rental profitability data in the Subnet Intelligence Card and the unified ranking output, enabling filtering for "subnets profitable to mine with rented hardware."
7. THE Processor SHALL compute rental profitability at multiple hardware tiers when a subnet can be mined with different GPU classes (e.g., "RTX 4090: marginal profit, A100: strong profit, H100: best yield but higher cost").
8. THE Pipeline SHALL flag in the daily briefing any subnet that transitions from rental-unprofitable to rental-profitable (or vice versa), as this represents an actionable opportunity change.

### Requirement 29: Cross-Subnet Optimization and Composability

**User Story:** As a TAO accumulation strategist, I want to know when services from one Bittensor subnet can reduce costs or improve performance for mining/validating on another subnet, so that Kiro can suggest composite strategies that leverage the ecosystem itself for competitive advantage.

#### Acceptance Criteria

1. THE Pipeline SHALL maintain a cross-subnet dependency map identifying which subnets provide services that could be consumed by miners or validators on other subnets (e.g., SN110 provides GPU compute, SN13 provides data, SN33 provides LLM inference, storage subnets provide model hosting).
2. THE Pipeline SHALL maintain in each Subnet Profile a "Dependencies" field listing external services the subnet's miners typically need (inference APIs, data feeds, compute, storage, models) and a "Can Be Served By" field mapping those dependencies to Bittensor subnets that provide equivalent services.
3. THE Processor SHALL compute a **composite strategy cost** when a subnet's mining requirements can be partially or fully served by another subnet: (cost of using subnet service) vs. (cost of self-hosting or cloud rental for the same capability).
4. THE Processor SHALL flag composite strategies as "ecosystem-optimized" when using another subnet's service is cheaper than external alternatives and include the estimated cost savings in TAO terms.
5. THE Pipeline SHALL include in the Subnet Intelligence Card a "Composability Notes" section describing known cross-subnet optimizations (e.g., "Mine SN33 using SN110 for inference compute instead of renting an A100 — saves ~0.3 TAO/day").
6. THE Processor SHALL include cross-subnet strategies in the unified ranking when they materially improve the net TAO yield (>10% improvement over standalone mining).
7. THE Pipeline SHALL track which subnets are both service providers AND profitable to mine, identifying "double-dip" opportunities where you can mine subnet A while simultaneously using subnet A's service to reduce costs on subnet B.

### Requirement 30: Configurable Thresholds and Parameters

**User Story:** As a system operator, I want all tunable thresholds and parameters stored in DynamoDB (editable via AWS Console), so that I can adjust pipeline behavior without code changes or redeployment.

#### Acceptance Criteria

1. THE Pipeline SHALL store all tunable thresholds in DynamoDB (PK: `CONFIG`, SK: `THRESHOLDS`) as a JSON document editable via the AWS DynamoDB Console.
2. THE Pipeline SHALL read thresholds once per Collection_Cycle at startup and cache them in memory for the duration of the cycle.
3. THE following parameters SHALL be configurable without code changes: WTA top-3 concentration threshold (default 0.70), proportional Gini max threshold (default 0.50), briefing emission change threshold (default 0.10), briefing registration cost change threshold (default 0.20), briefing rank change threshold (default 50), max retries (default 3), error cooldown hours (default 24), low liquidity TAO threshold (default 100), death spiral consecutive days (default 7), death spiral emission decline threshold (default 0.25), concurrent collection limit (default 32).
4. WHEN a threshold value is missing from DynamoDB, THE Pipeline SHALL use the hardcoded default value and log a warning.
5. THE Pipeline SHALL validate threshold values at load time (e.g., percentages between 0 and 1, integers positive) and reject invalid configurations with an error log.

### Requirement 31: Instrumentation and Distributed Tracing

**User Story:** As a system operator, I want every pipeline operation traced with a shared correlation ID across all Lambda functions, so that I can follow a single subnet's journey from collection through processing to finalization when debugging issues.

#### Acceptance Criteria

1. THE Pipeline SHALL generate a unique `trace_id` per Collection_Cycle (format: `cycle-{date}-{short_uuid}`) and propagate it through all SQS messages, SNS notifications, and log entries.
2. EVERY structured log entry SHALL include: trace_id, cycle_id, component (collector/processor/finalizer), operation name, netuid (when applicable), status (start/success/error), duration_ms, and data_size_bytes (when applicable).
3. THE Pipeline SHALL instrument every significant operation with timing: SDK connection, metagraph fetch per subnet, metric computation per subnet, S3 read/write, DynamoDB read/write, SQS publish, SNS publish.
4. WHEN an error occurs, THE log entry SHALL include: the full error type and message (truncated to 500 chars), the operation that failed, the input parameters (excluding sensitive data), and whether the error is retryable.
5. THE Pipeline SHALL support filtering CloudWatch Logs by trace_id to reconstruct the full lifecycle of any cycle or subnet processing.

### Requirement 32: Data Validation at Ingestion

**User Story:** As a system operator, I want raw data validated before storage, so that corrupt or anomalous data from the Bittensor endpoint doesn't propagate through the pipeline and produce incorrect derived metrics.

#### Acceptance Criteria

1. THE Collector SHALL validate each metagraph snapshot before storing: neuron count must be > 0, block number must be >= 0, emission values must be non-negative, incentive values must sum to approximately 1.0 (within 0.01 tolerance for active miners).
2. THE Collector SHALL validate that the source block number is >= the previous collection's block number for the same subnet (chain doesn't go backwards).
3. WHEN validation fails for a subnet, THE Collector SHALL log the validation failure with details, skip storing the invalid snapshot, and mark the subnet as ERROR_RETRYABLE.
4. THE Collector SHALL include validation status in the daily briefing: count of subnets that passed/failed validation, and details of any validation failures.

### Requirement 33: Graceful Shutdown and Partial Results

**User Story:** As a system operator, I want the Collector Lambda to save partial results when approaching timeout, so that work already completed is not lost and uncollected subnets can be retried next cycle.

#### Acceptance Criteria

1. THE Collector SHALL monitor remaining Lambda execution time using `context.get_remaining_time_in_millis()`.
2. WHEN remaining time drops below 60 seconds, THE Collector SHALL stop initiating new subnet collections, store all completed snapshots to S3, publish SQS messages for successfully collected subnets, and mark uncollected subnets as ERROR_RETRYABLE.
3. THE Collector SHALL use a configurable concurrency semaphore (default: 32 concurrent connections) to limit simultaneous WebSocket connections to the Finney endpoint.
4. THE Collector SHALL log the partial completion: subnets collected, subnets skipped due to timeout, total duration.

### Requirement 34: Data Freshness Indicator

**User Story:** As a data consumer, I want every output to clearly indicate how fresh the data is, so that I never make decisions based on stale data without knowing it's stale.

#### Acceptance Criteria

1. EVERY pipeline output (derived metrics, rankings, briefings, site pages) SHALL include a `data_age_hours` field computed as the difference between the current time and the collection_timestamp.
2. THE static site SHALL display a prominent warning banner when data is older than 36 hours (indicating a missed cycle).
3. THE Pipeline Health page SHALL show the exact timestamp of the last successful collection and the time elapsed since then.

### Requirement 35: Security — S3 Bucket Isolation

**User Story:** As a system operator, I want pipeline data (raw metagraphs, derived metrics, tracked hotkeys) stored in a private bucket separate from the public static site, so that sensitive strategy data is never accidentally exposed.

#### Acceptance Criteria

1. THE Pipeline SHALL use two separate S3 buckets: a private data bucket (all raw/derived/cards/config data) and a public site bucket (HTML files only, served via CloudFront).
2. THE private data bucket SHALL have `BlockPublicAccess` enabled on all four settings (BlockPublicAcls, IgnorePublicAcls, BlockPublicPolicy, RestrictPublicBuckets).
3. THE public site bucket SHALL be accessible ONLY through CloudFront using Origin Access Control (OAC) — direct S3 URL access SHALL be denied.
4. THE CDK stack SHALL NOT create any S3 bucket policy that grants public read access to the data bucket.

### Requirement 36: Security — Least Privilege IAM

**User Story:** As a system operator, I want each Lambda function to have only the minimum IAM permissions it needs, so that a compromised or buggy Lambda cannot access or modify resources beyond its scope.

#### Acceptance Criteria

1. THE Collector Lambda IAM role SHALL permit ONLY: `s3:PutObject` on the data bucket `raw/*` prefix, `dynamodb:GetItem`/`UpdateItem`/`PutItem` on CONFIG and STATE items, `sqs:SendMessage` on the process-subnet queue, `ssm:GetParameter` on `/tao-pipeline/*` parameters, and `logs:CreateLogGroup`/`PutLogEvents`.
2. THE Processor Lambda IAM role SHALL permit ONLY: `s3:GetObject` on the data bucket `raw/*` prefix, `s3:PutObject` on the data bucket `derived/*` and `cards/*` prefixes, `dynamodb:GetItem`/`UpdateItem`/`PutItem` on SUBNET and HOTKEY items, `sns:Publish` on the subnet-processed topic, and `logs:*`.
3. THE Finalizer Lambda IAM role SHALL permit ONLY: `s3:GetObject` on the data bucket `derived/*` prefix, `s3:PutObject` on the site bucket, `dynamodb:GetItem`/`UpdateItem` on RANKING and BRIEFING items, and `logs:*`.
4. NO Lambda IAM role SHALL include `s3:DeleteObject`, `dynamodb:DeleteTable`, `dynamodb:DeleteItem` on STATE/METRICS items, or wildcard (`*`) actions.
5. THE SQS process-subnet queue policy SHALL restrict `sqs:SendMessage` to ONLY the Collector Lambda's IAM role ARN.

### Requirement 37: Security — Dependency Pinning and Supply Chain

**User Story:** As a developer, I want all Python dependencies pinned to exact versions with integrity hashes, so that supply chain attacks via compromised PyPI packages cannot inject malicious code into the pipeline.

#### Acceptance Criteria

1. THE `lambda/requirements.txt` SHALL pin all dependencies to exact versions (e.g., `bittensor==10.3.2`, not `bittensor>=10.0.0`).
2. THE project SHALL include a `requirements.lock` file generated with `pip freeze` or `pip-compile` that includes all transitive dependencies with exact versions.
3. THE Dockerfile SHALL use `pip install --no-cache-dir --require-hashes -r requirements.lock` when a hash-verified lockfile is available.
4. THE project SHALL include a CI/development step to run `pip-audit` or equivalent to check for known vulnerabilities in dependencies.

### Requirement 38: Security — Data Sensitivity and Logging

**User Story:** As a system operator, I want sensitive data (coldkey addresses, API keys) never logged in full, so that CloudWatch logs don't become a data leak vector.

#### Acceptance Criteria

1. THE Pipeline SHALL NEVER log full coldkey addresses — truncate to first 12 characters in all log entries.
2. THE Pipeline SHALL NEVER log Parameter Store values (API keys) — log only the parameter name, not the value.
3. THE Pipeline SHALL NEVER store API keys or secrets in Lambda environment variables — all secrets SHALL be read from Parameter Store at runtime.
4. THE CDK stack SHALL include an assertion test verifying no Lambda environment variable contains the substrings "KEY", "SECRET", "PASSWORD", or "TOKEN" (excluding AWS-managed variables).

### Requirement 39: CI/CD Pipeline (Phase 2)

**User Story:** As a developer, I want automated testing and deployment via GitHub Actions, so that dependency updates are validated before deployment and breaking changes are caught before they affect the running pipeline.

#### Acceptance Criteria (Phase 2 — not implemented in Phase 1)

1. THE project SHALL include a GitHub Actions workflow that runs all tests (property, unit, integration, CDK) on every push to main and on pull requests.
2. THE project SHALL include Dependabot or Renovate configuration to automatically create PRs for dependency updates (security patches auto-merged, major versions require manual review).
3. THE GitHub Actions workflow SHALL run `pip-audit` to check for known vulnerabilities and fail the build if critical vulnerabilities are found.
4. THE project SHALL include a staging deployment step that runs one full Collection_Cycle against the live Finney endpoint before promoting infrastructure changes to production.
5. THE project SHALL include a `scripts/update_deps.sh` script for manual dependency updates that: checks for updates, runs pip-audit, updates the lockfile, runs tests, and reports a summary of changes.

### Requirement 40: Reliability — Circuit Breaker and Poison Pill Handling

**User Story:** As a system operator, I want the pipeline to detect when the Bittensor endpoint is completely down (circuit breaker) and when a specific subnet consistently fails (poison pill), so that the system doesn't waste resources on doomed operations.

#### Acceptance Criteria

1. THE Collector SHALL implement a circuit breaker: if the first 5 subnet collections all fail with connection/timeout errors, THE Collector SHALL abort the remaining cycle, mark all subnets as ERROR_RETRYABLE, and log a "circuit breaker tripped" alert.
2. THE Pipeline SHALL track consecutive failure count per subnet across cycles in DynamoDB (STATE item: `consecutive_cycle_failures` field).
3. WHEN a subnet has failed for 5 consecutive cycles, THE Pipeline SHALL auto-archive that subnet (transition to ARCHIVED lifecycle state) and include a "poison pill detected" alert in the daily briefing.
4. THE Collector SHALL enforce a per-subnet timeout (configurable, default 30 seconds) for individual metagraph fetches, independent of the Lambda execution timeout.
5. THE Pipeline SHALL include circuit breaker status and poison pill detections in the Pipeline Health page.

### Requirement 41: Reliability — Per-Operation Timeouts

**User Story:** As a system operator, I want individual operations (metagraph fetch, S3 write, DynamoDB write) to have their own timeouts, so that one slow operation doesn't consume the entire Lambda execution time.

#### Acceptance Criteria

1. THE Collector SHALL enforce a configurable timeout per metagraph fetch (default: 30 seconds). If a single subnet exceeds this timeout, it SHALL be marked as ERROR_RETRYABLE and the Collector SHALL proceed to the next subnet.
2. THE Collector SHALL enforce a configurable timeout for the TAO/USD price API call (default: 10 seconds). If exceeded, the pipeline SHALL continue without USD prices.
3. ALL S3 and DynamoDB operations SHALL use boto3 client-level timeouts (connect_timeout=5s, read_timeout=30s) to prevent hanging on AWS service issues.

### Requirement 42: Cost Safety — Budget Alarm

**User Story:** As a system operator, I want an AWS Budget alarm that alerts me if monthly spending exceeds $1, so that accidental resource creation or misconfiguration doesn't result in unexpected charges.

#### Acceptance Criteria

1. THE CDK stack SHALL create an AWS Budget with a $1/month threshold that sends an alert to the SNS alert topic when 80% of the budget is forecasted to be exceeded.
2. THE Pipeline Health page SHALL display current month's estimated AWS cost (from CloudWatch billing metrics if available, or "monitoring not enabled" otherwise).

### Requirement 43: Operational Runbook

**User Story:** As a system operator, I want a documented runbook covering common operational scenarios, so that I can quickly diagnose and resolve issues without reverse-engineering the system each time.

#### Acceptance Criteria

1. THE project SHALL include an `OPERATIONS.md` file in the repository root documenting: how to check pipeline health, how to investigate DLQ messages, how to manually trigger a cycle, how to add/remove tracked hotkeys, how to reprocess a day's data, how to update cloud pricing, how to add a subnet classification, how to handle a circuit breaker trip, and how to recover from ERROR_FATAL states.
2. THE `OPERATIONS.md` SHALL include troubleshooting decision trees for common failure modes: "pipeline didn't run today", "subnet X has no data", "metrics look wrong", "S3 approaching limit".
