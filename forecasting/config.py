"""
Configuration parameters and constants for the TurboSH Forecasting Engine.
"""

from enum import IntEnum
from typing import Dict, List

# In-memory buffer and storage parameters
DEFAULT_RING_BUFFER_CAPACITY: int = 10_000
DEFAULT_SQLITE_DB_PATH: str = "data/state_history.db"
DEFAULT_STATE_LOG_PATH: str = "logs/state_telemetry.jsonl"

# Time-series temporal window settings
TIME_STEP_SECONDS: int = 10  # 10s aggregation step (matches TurboSH 10s window)
FORECAST_HORIZON: int = 3    # Multi-step forecasting horizon (t+1, t+2, t+3)

# 6 Core ML Features extracted from telemetry
FEATURE_NAMES: List[str] = [
    "requests_per_ip_10s",
    "requests_per_ip_60s",
    "endpoint_entropy",
    "latency_spike",
    "error_rate",
    "request_variance",
]

# Attack Stage Taxonomy (aligned with threat lifecycle & MITRE ATT&CK)
class AttackStage(IntEnum):
    NORMAL = 0      # Baseline regular client traffic
    RECON = 1       # Scanning, probing diverse endpoints (T1595)
    ESCALATION = 2  # Rate ramp-up or error rate increase (T1498/T1499 preparation)
    SURGE = 3       # Active high-volume DDoS or volumetric flood (T1498/T1499)
    SUSTAINED = 4   # Protracted saturation across consecutive intervals

STAGE_NAMES: Dict[int, str] = {
    AttackStage.NORMAL: "NORMAL",
    AttackStage.RECON: "RECON",
    AttackStage.ESCALATION: "ESCALATION",
    AttackStage.SURGE: "SURGE",
    AttackStage.SUSTAINED: "SUSTAINED",
}

# Labeling thresholds for Version 1 rule-based stage assignment
THRESHOLD_NORMAL_MAX: float = 0.30
THRESHOLD_RECON_MAX: float = 0.50
THRESHOLD_ESCALATION_MAX: float = 0.70
THRESHOLD_SURGE_MIN: float = 0.70
SUSTAINED_MIN_CONSECUTIVE_STEPS: int = 3
