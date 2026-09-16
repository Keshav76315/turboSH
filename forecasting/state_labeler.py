"""
Rule-based state labeler for assigning attack-stage taxonomy labels to historical states.
"""

import csv
import os
from typing import Any, Dict, List

from forecasting.config import (
    AttackStage,
    FEATURE_NAMES,
    STAGE_NAMES,
    SUSTAINED_MIN_CONSECUTIVE_STEPS,
    THRESHOLD_ESCALATION_MAX,
    THRESHOLD_NORMAL_MAX,
    THRESHOLD_RECON_MAX,
    THRESHOLD_SURGE_MIN,
)
from forecasting.state_store import NetworkState, StateStore


def label_state(state: NetworkState) -> AttackStage:
    """
    Assign a point-in-time AttackStage label based on anomaly score and telemetry characteristics.
    Note: For temporal context-dependent stages like SUSTAINED, use label_sequence().
    """
    score = state.anomaly_score

    if score < THRESHOLD_NORMAL_MAX:
        return AttackStage.NORMAL

    if score < THRESHOLD_RECON_MAX:
        # Reconnaissance: moderate score, typically diverse endpoints (high entropy) with lower rate
        return AttackStage.RECON

    if score < THRESHOLD_ESCALATION_MAX:
        # Escalation: ramping up traffic, error rate, or latency
        return AttackStage.ESCALATION

    # score >= THRESHOLD_SURGE_MIN: Volumetric burst / DDoS
    return AttackStage.SURGE


def label_sequence(states: List[NetworkState]) -> List[AttackStage]:
    """
    Assign context-aware attack stages across a sequence of states.
    Identifies SUSTAINED attacks when SURGE conditions persist for >= 3 consecutive steps.
    """
    if not states:
        return []

    # First pass: point-in-time stage assignments
    raw_labels = [label_state(s) for s in states]

    # Second pass: promote SURGE to SUSTAINED when sustained >= SUSTAINED_MIN_CONSECUTIVE_STEPS
    consecutive_surge = 0
    refined_labels = list(raw_labels)

    for i, label in enumerate(raw_labels):
        if label == AttackStage.SURGE:
            consecutive_surge += 1
            if consecutive_surge >= SUSTAINED_MIN_CONSECUTIVE_STEPS:
                # Mark current and previous consecutive surge steps as SUSTAINED
                for j in range(i - consecutive_surge + 1, i + 1):
                    refined_labels[j] = AttackStage.SUSTAINED
        else:
            consecutive_surge = 0

    return refined_labels


def generate_labeled_dataset(store: StateStore) -> List[Dict[str, Any]]:
    """
    Label all states in the StateStore grouped by IP hash, returning a structured dataset.
    """
    labeled_records: List[Dict[str, Any]] = []

    # Group records by IP to preserve chronological order for sequence labeling
    records_by_ip: Dict[str, List[NetworkState]] = {}
    with store._lock:
        for s in store._buffer:
            records_by_ip.setdefault(s.ip_hash, []).append(s)

    for ip_hash, ip_states in records_by_ip.items():
        # Sort chronologically
        sorted_states = sorted(ip_states, key=lambda x: x.timestamp)
        labels = label_sequence(sorted_states)

        for state, assigned_label in zip(sorted_states, labels):
            state.label = int(assigned_label)
            row = state.to_dict()
            row["stage_label"] = int(assigned_label)
            row["stage_name"] = STAGE_NAMES[assigned_label]
            labeled_records.append(row)

    return labeled_records


def export_csv(records: List[Dict[str, Any]], output_path: str = "datasets/labeled_states.csv") -> str:
    """Export labeled state records to a CSV file."""
    if not records:
        return ""

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    fieldnames = [
        "timestamp",
        "ip_hash",
        "stage_label",
        "stage_name",
        "anomaly_score",
        "action",
    ] + FEATURE_NAMES

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow(r)

    return output_path
