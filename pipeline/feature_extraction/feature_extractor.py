#!/usr/bin/env python3
"""
feature_extractor.py — turboSH Feature Extraction Pipeline (EPIC 4, Story 4.2)

Reads JSON Lines traffic logs produced by the Traffic Logger middleware
and computes per-IP behavioral features for the ML anomaly detection system.

Usage:
    python3 pipeline/feature_extraction/feature_extractor.py \
        --input  logs/traffic.jsonl \
        --output datasets/features.csv

Input  : logs/traffic.jsonl   (one JSON object per line)
Output : datasets/features.csv (one row per IP per time window)

Features computed (per IP):
    1. requests_per_ip_10s  — request count in 10-second windows
    2. requests_per_ip_60s  — request count in 60-second windows
    3. endpoint_entropy     — Shannon entropy of endpoint distribution (0–1)
    4. latency_spike        — 1 if response_time > baseline * 3, else 0
    5. error_rate           — ratio of 4xx/5xx responses
    6. request_variance     — variance of backend response latencies (ms)
"""

import argparse
import csv
import json
import math
import os
import sys
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ─────────────────────────────────────────────
# Log Reader
# ─────────────────────────────────────────────


def read_traffic_logs(filepath: str) -> List[Dict]:
    """Read a JSON Lines file and return a list of log entries."""
    entries = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  ⚠ Skipping malformed line {line_num}: {e}", file=sys.stderr)
    return entries


# ─────────────────────────────────────────────
# Feature Computation
# ─────────────────────────────────────────────


def parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a datetime object."""
    # Handle formats like "2026-03-06T17:19:47Z"
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def compute_entropy(endpoint_counts: Dict[str, int]) -> float:
    """
    Compute normalized Shannon entropy of endpoint distribution.
    Returns a value between 0.0 (single endpoint) and 1.0 (uniform distribution).
    """
    total = sum(endpoint_counts.values())
    if total == 0:
        return 0.0

    num_endpoints = len(endpoint_counts)
    if num_endpoints <= 1:
        return 0.0

    entropy = 0.0
    for count in endpoint_counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    # Normalize by max possible entropy (log2 of number of distinct endpoints)
    max_entropy = math.log2(num_endpoints)
    return entropy / max_entropy if max_entropy > 0 else 0.0


def compute_variance(values: List[float]) -> float:
    """Compute the variance of a list of values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((x - mean) ** 2 for x in values) / (len(values) - 1)


def compute_inter_arrival_times(timestamps: List[datetime]) -> List[float]:
    """Compute time differences between consecutive requests (in seconds)."""
    if len(timestamps) < 2:
        return []
    sorted_ts = sorted(timestamps)
    return [
        (sorted_ts[i + 1] - sorted_ts[i]).total_seconds()
        for i in range(len(sorted_ts) - 1)
    ]


def extract_features(entries: List[Dict], latency_baseline: float = None) -> List[Dict]:
    """
    Extract per-IP behavioral features from raw traffic log entries.

    Args:
        entries: list of log entry dicts (from traffic.jsonl)
        latency_baseline: baseline response_time (ms). If None, auto-computed
                          as the median of all response times.

    Returns:
        list of feature row dicts, one per IP.
    """
    if not entries:
        return []

    # ── Group entries by IP hash ──
    ip_entries = defaultdict(list)
    for entry in entries:
        ip_hash = entry.get("ip_hash", "unknown")
        ip_entries[ip_hash].append(entry)

    # ── Auto-compute latency baseline (median) ──
    if latency_baseline is None:
        all_latencies = [e.get("response_time", 0) for e in entries]
        latency_baseline = statistics.median(all_latencies) if all_latencies else 100.0

    # Spike threshold: 3x baseline (or at least 500ms)
    spike_threshold = max(latency_baseline * 3, 500.0)

    # ── Compute features per IP ──
    feature_rows = []

    for ip_hash, ip_logs in ip_entries.items():
        # Parse timestamps
        timestamps = []
        for log in ip_logs:
            try:
                timestamps.append(parse_timestamp(log["timestamp"]))
            except (KeyError, ValueError):
                pass

        # Time span for windowed counts
        if timestamps:
            sorted_ts = sorted(timestamps)
            span_seconds = (sorted_ts[-1] - sorted_ts[0]).total_seconds()
        else:
            span_seconds = 0

        total_requests = len(ip_logs)

        # ── Feature 1 & 2: requests_per_ip_10s / 60s ──
        # Estimate: total_requests / (span / window), minimum 1 window
        windows_10s = max(1, span_seconds / 10)
        windows_60s = max(1, span_seconds / 60)
        requests_per_10s = round(total_requests / windows_10s)
        requests_per_60s = round(total_requests / windows_60s)

        # ── Feature 3: endpoint_entropy ──
        endpoint_counts = defaultdict(int)
        for log in ip_logs:
            endpoint_counts[log.get("endpoint", "/")] += 1
        entropy = round(compute_entropy(endpoint_counts), 4)

        # ── Feature 4: latency_spike ──
        max_latency = max((log.get("response_time", 0) for log in ip_logs), default=0)
        latency_spike = 1 if max_latency > spike_threshold else 0

        # ── Feature 5: error_rate ──
        error_count = sum(1 for log in ip_logs if log.get("status_code", 200) >= 400)
        error_rate = (
            round(error_count / total_requests, 4) if total_requests > 0 else 0.0
        )

        # ── Feature 6: request_variance ──
        latencies = [log.get("response_time", 0.0) for log in ip_logs]
        request_variance = round(compute_variance(latencies), 4)

        feature_rows.append(
            {
                "ip_hash": ip_hash,
                "requests_per_ip_10s": requests_per_10s,
                "requests_per_ip_60s": requests_per_60s,
                "endpoint_entropy": entropy,
                "latency_spike": latency_spike,
                "error_rate": error_rate,
                "request_variance": request_variance,
            }
        )

    return feature_rows


# ─────────────────────────────────────────────
# CSV Writer
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


def write_features_csv(features: List[Dict], output_path: str):
    """Write feature rows to a CSV file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FEATURE_COLUMNS)
        writer.writeheader()
        writer.writerows(features)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="turboSH Feature Extractor — converts traffic logs to ML features"
    )
    parser.add_argument(
        "--input",
        "-i",
        default="logs/traffic.jsonl",
        help="Path to the JSON Lines traffic log file (default: logs/traffic.jsonl)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="datasets/features.csv",
        help="Path to write the features CSV (default: datasets/features.csv)",
    )
    args = parser.parse_args()

    # Read logs
    print(f"📂 Reading traffic logs from: {args.input}")
    entries = read_traffic_logs(args.input)
    print(f"   Found {len(entries)} log entries")

    if not entries:
        print("⚠ No entries found. Nothing to extract.", file=sys.stderr)
        sys.exit(1)

    # Extract features
    print("🔬 Extracting features...")
    features = extract_features(entries)
    print(f"   Computed features for {len(features)} unique IPs")

    # Write output
    print(f"💾 Writing features to: {args.output}")
    write_features_csv(features, args.output)

    # Preview
    print("\n📊 Feature Preview:")
    print(
        f"   {'ip_hash':<18} {'req/10s':>7} {'req/60s':>7} {'entropy':>8} {'spike':>5} {'err_rate':>8} {'variance':>9}"
    )
    print(f"   {'─' * 18} {'─' * 7} {'─' * 7} {'─' * 8} {'─' * 5} {'─' * 8} {'─' * 9}")
    for row in features[:10]:  # show first 10
        print(
            f"   {row['ip_hash']:<18} {row['requests_per_ip_10s']:>7} {row['requests_per_ip_60s']:>7} "
            f"{row['endpoint_entropy']:>8.4f} {row['latency_spike']:>5} {row['error_rate']:>8.4f} "
            f"{row['request_variance']:>9.4f}"
        )

    print(f"\n Done {len(features)} feature rows written to {args.output}")


if __name__ == "__main__":
    main()
