"""Enumerations for the TAO Mining Intelligence Pipeline."""

from enum import Enum


class PipelineState(str, Enum):
    """Pipeline FSM states for tracking collection and processing progress."""

    IDLE = "IDLE"
    COLLECTING = "COLLECTING"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    ERROR_RETRYABLE = "ERROR_RETRYABLE"
    ERROR_FATAL = "ERROR_FATAL"


class SubnetCategory(str, Enum):
    """Classification of subnet purpose/domain."""

    LLM_INFERENCE = "LLM_INFERENCE"
    VISION_IMAGE = "VISION_IMAGE"
    TRADING_FINANCIAL = "TRADING_FINANCIAL"
    DATA_COLLECTION = "DATA_COLLECTION"
    COMPUTE = "COMPUTE"
    TRAINING = "TRAINING"
    PREDICTION = "PREDICTION"
    STORAGE = "STORAGE"
    SCIENTIFIC = "SCIENTIFIC"
    OTHER = "OTHER"


class MiningStyle(str, Enum):
    """Classification of mining approach required for a subnet."""

    GPU_INFERENCE = "GPU_INFERENCE"
    GPU_TRAINING = "GPU_TRAINING"
    RAW_COMPUTE = "RAW_COMPUTE"
    KNOWLEDGE_STRATEGY = "KNOWLEDGE_STRATEGY"
    DATA_COLLECTION = "DATA_COLLECTION"
    MODEL_QUALITY = "MODEL_QUALITY"
    LATENCY = "LATENCY"
    CAPITAL = "CAPITAL"


class RewardModel(str, Enum):
    """Classification of how a subnet distributes emission rewards."""

    WINNER_TAKES_ALL = "WINNER_TAKES_ALL"
    PROPORTIONAL = "PROPORTIONAL"
    TIERED = "TIERED"
    UNKNOWN = "UNKNOWN"


class HardwareTier(str, Enum):
    """Classification of hardware requirements for mining a subnet."""

    CPU_ONLY = "CPU_ONLY"
    CONSUMER_GPU = "CONSUMER_GPU"
    DATACENTER_GPU = "DATACENTER_GPU"
    MULTI_GPU = "MULTI_GPU"
    SPECIALIZED = "SPECIALIZED"



class CompetitionTrend(str, Enum):
    """Direction of competitive pressure in a subnet."""

    INCREASING = "INCREASING"
    STABLE = "STABLE"
    DECREASING = "DECREASING"


class TaoflowStatus(str, Enum):
    """Health status of a subnet under the Taoflow emission model."""

    HEALTHY = "HEALTHY"
    DECLINING = "DECLINING"
    DEATH_SPIRAL_RISK = "DEATH_SPIRAL_RISK"


class HoldVsSwap(str, Enum):
    """Recommendation for alpha token handling."""

    HOLD = "HOLD"
    SWAP = "SWAP"


class Confidence(str, Enum):
    """Confidence level for metric estimates."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
