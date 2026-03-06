#!/usr/bin/env python3
"""
build_dataset.py — turboSH Dataset Builder (EPIC 4, Story 4.3)

Converts feature vectors into labeled, ML-ready training datasets.

Pipeline:
    traffic.jsonl  →  feature_extractor.py  →  features.csv  →  build_dataset.py  →  datasets/

Usage:
    python3 pipeline/dataset_builder/build_dataset.py \
        --input  datasets/features.csv \
        --output datasets/

Outputs:
    datasets/traffic_dataset.csv  — all labeled rows (normal + attack)
    datasets/attack_dataset.csv   — attack rows only (label=1)

Labeling rules (thresholds):
    - DDoS burst:        requests_per_ip_10s >= 50
    - Brute force login: error_rate >= 0.5 AND requests_per_ip_60s >= 20
    - Request flooding:  requests_per_ip_60s >= 200
    - Latency attack:    latency_spike == 1 AND error_rate >= 0.3

    Any match → label = 1 (anomalous)
    No match  → label = 0 (normal)
"""

import argparse
import csv
import os
import sys
from typing import Dict, List


# ─────────────────────────────────────────────
# Data Cleaning
# ─────────────────────────────────────────────

FEATURE_COLUMNS = [
    "ip_hash",
    "requests_per_ip_10s",
    "requests_per_ip_60s",
    "endpoint_entropy",
    "latency_spike",
    "error_rate",
    "request_variance",
]

# Columns to include in the final dataset (features + label, no ip_hash)
DATASET_COLUMNS = [
    "requests_per_ip_10s",
    "requests_per_ip_60s",
    "endpoint_entropy",
    "latency_spike",
    "error_rate",
    "request_variance",
    "label",
]


def read_features_csv(filepath: str) -> List[Dict]:
    """Read the features CSV and return a list of row dicts with parsed types."""
    rows = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for line_num, row in enumerate(reader, start=2):
            try:
                cleaned = {
                    "ip_hash":             row["ip_hash"].strip(),
                    "requests_per_ip_10s": int(float(row["requests_per_ip_10s"])),
                    "requests_per_ip_60s": int(float(row["requests_per_ip_60s"])),
                    "endpoint_entropy":    round(float(row["endpoint_entropy"]), 4),
                    "latency_spike":       int(float(row["latency_spike"])),
                    "error_rate":          round(float(row["error_rate"]), 4),
                    "request_variance":    round(float(row["request_variance"]), 4),
                }
                rows.append(cleaned)
            except (ValueError, KeyError) as e:
                print(f"  ⚠ Skipping malformed row {line_num}: {e}", file=sys.stderr)
    return rows


# ─────────────────────────────────────────────
# Labeling Rules
# ─────────────────────────────────────────────

def classify_row(row: Dict) -> int:
    """
    Apply anomaly detection rules to label a feature row.

    Returns:
        0 = normal traffic
        1 = anomalous / attack traffic
    """
    # Rule 1: DDoS burst — extremely high request rate
    if row["requests_per_ip_10s"] >= 50:
        return 1

    # Rule 2: Brute force — high error rate with sustained requests
    if row["error_rate"] >= 0.5 and row["requests_per_ip_60s"] >= 20:
        return 1

    # Rule 3: Request flooding — very high sustained request count
    if row["requests_per_ip_60s"] >= 200:
        return 1

    # Rule 4: Latency attack — spikes combined with errors
    if row["latency_spike"] == 1 and row["error_rate"] >= 0.3:
        return 1

    return 0


def label_dataset(rows: List[Dict]) -> List[Dict]:
    """Apply labeling rules to all feature rows."""
    labeled = []
    for row in rows:
        row_copy = dict(row)
        row_copy["label"] = classify_row(row)
        labeled.append(row_copy)
    return labeled


# ─────────────────────────────────────────────
# Dataset Writer
# ─────────────────────────────────────────────

def write_dataset(rows: List[Dict], output_path: str, columns: List[str]):
    """Write labeled rows to a CSV file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="turboSH Dataset Builder — labels features and produces training datasets"
    )
    parser.add_argument(
        "--input", "-i",
        default="datasets/features.csv",
        help="Path to the features CSV (default: datasets/features.csv)"
    )
    parser.add_argument(
        "--output", "-o",
        default="datasets/",
        help="Output directory for datasets (default: datasets/)"
    )
    args = parser.parse_args()

    # ── Read features ──
    print(f"📂 Reading features from: {args.input}")
    rows = read_features_csv(args.input)
    print(f"   Loaded {len(rows)} feature rows")

    if not rows:
        print("⚠ No feature rows found. Nothing to build.", file=sys.stderr)
        sys.exit(1)

    # ── Label ──
    print("🏷  Labeling rows...")
    labeled = label_dataset(rows)

    normal_rows  = [r for r in labeled if r["label"] == 0]
    attack_rows  = [r for r in labeled if r["label"] == 1]

    print(f"   Normal:  {len(normal_rows)} rows (label=0)")
    print(f"   Attack:  {len(attack_rows)} rows (label=1)")

    # ── Write datasets ──
    traffic_path = os.path.join(args.output, "traffic_dataset.csv")
    attack_path  = os.path.join(args.output, "attack_dataset.csv")

    print(f"💾 Writing traffic_dataset.csv  → {traffic_path}")
    write_dataset(labeled, traffic_path, DATASET_COLUMNS)

    print(f"💾 Writing attack_dataset.csv   → {attack_path}")
    write_dataset(attack_rows, attack_path, DATASET_COLUMNS)

    # ── Summary ──
    print("\n📊 Dataset Summary:")
    print(f"   ┌─────────────────────────┬───────┐")
    print(f"   │ Dataset                 │ Rows  │")
    print(f"   ├─────────────────────────┼───────┤")
    print(f"   │ traffic_dataset.csv     │ {len(labeled):>5} │")
    print(f"   │ attack_dataset.csv      │ {len(attack_rows):>5} │")
    print(f"   └─────────────────────────┴───────┘")

    if labeled:
        attack_pct = len(attack_rows) / len(labeled) * 100
        print(f"\n   Attack ratio: {attack_pct:.1f}% ({len(attack_rows)}/{len(labeled)})")

    # Preview labeled rows
    print("\n📋 Preview (first 10 rows):")
    print(f"   {'req/10s':>7} {'req/60s':>7} {'entropy':>8} {'spike':>5} {'err_rate':>8} {'variance':>9} {'label':>5}")
    print(f"   {'─' * 7} {'─' * 7} {'─' * 8} {'─' * 5} {'─' * 8} {'─' * 9} {'─' * 5}")
    for row in labeled[:10]:
        lbl = "ATTACK" if row["label"] == 1 else "normal"
        print(f"   {row['requests_per_ip_10s']:>7} {row['requests_per_ip_60s']:>7} "
              f"{row['endpoint_entropy']:>8.4f} {row['latency_spike']:>5} "
              f"{row['error_rate']:>8.4f} {row['request_variance']:>9.4f} {lbl:>6}")

    print(f"\n✅ Done! Datasets ready for model training (EPIC 6).")


if __name__ == "__main__":
    main()
