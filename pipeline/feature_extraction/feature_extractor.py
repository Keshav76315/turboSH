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
    4. latency_spike        — 1 if response_time > avg * 1.5 and > 100ms, else 0
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
from datetime import datetime, timezone, timedelta
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
                print(f"  [WARN] Skipping malformed line {line_num}: {e}", file=sys.stderr)
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

    non_zero = [count for count in endpoint_counts.values() if count > 0]
    num_endpoints = len(non_zero)
    if num_endpoints <= 1:
        return 0.0

    entropy = 0.0
    for count in non_zero:
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


def extract_features(
    entries: List[Dict],
    latency_baseline: float = None,
    window_size: float = 60.0,
    window_step: float = 10.0,
) -> List[Dict]:
    """
    Extract per-IP behavioral features from raw traffic log entries using sliding windows.

    Args:
        entries: list of log entry dicts (from traffic.jsonl)
        latency_baseline: optional baseline response_time (ms). If None, auto-computed
                          per window matching real-time Go middleware.
        window_size: sliding window duration in seconds (default: 60.0).
        window_step: sliding window step in seconds (default: 10.0).

    Returns:
        list of feature row dicts.
    """
    if window_size <= 0:
        raise ValueError("window_size must be strictly positive")
    if window_step <= 0:
        raise ValueError("window_step must be strictly positive")

    if not entries:
        return []

    # ── Group entries by IP hash ──
    ip_entries = defaultdict(list)
    for entry in entries:
        ip_hash = entry.get("ip_hash", "unknown")
        ip_entries[ip_hash].append(entry)

    feature_rows = []

    for ip_hash, ip_logs in ip_entries.items():
        # Parse timestamps
        valid_logs = []
        for log in ip_logs:
            try:
                ts = parse_timestamp(log["timestamp"])
                valid_logs.append((ts, log))
            except (KeyError, ValueError):
                pass

        # Fallback if logs have no valid timestamps: treat as single batch window with conservative 10s count
        if not valid_logs:
            total_reqs = len(ip_logs)
            fallback_10s = min(total_reqs, 1)
            latencies = [log.get("response_time", 0.0) for log in ip_logs]
            avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
            max_lat = max(latencies) if latencies else 0.0
            effective_base = latency_baseline if latency_baseline is not None else avg_lat
            spike = 1 if max_lat > (effective_base * 1.5) and max_lat > 100.0 else 0
            errs = sum(1 for log in ip_logs if log.get("status_code", 200) >= 400)
            err_rate = round(errs / total_reqs, 4) if total_reqs > 0 else 0.0
            var = round(compute_variance(latencies), 4)

            ep_counts = defaultdict(int)
            for log in ip_logs:
                ep_counts[log.get("endpoint", "/")] += 1
            ent = round(compute_entropy(ep_counts), 4)

            feature_rows.append({
                "ip_hash": ip_hash,
                "requests_per_ip_10s": fallback_10s,
                "requests_per_ip_60s": total_reqs,
                "endpoint_entropy": ent,
                "latency_spike": spike,
                "error_rate": err_rate,
                "request_variance": var,
            })
            continue

        valid_logs.sort(key=lambda x: x[0])
        t_first = valid_logs[0][0]
        t_last = valid_logs[-1][0]

        span_seconds = (t_last - t_first).total_seconds()
        # If all requests occur within a single window step, evaluate at t_last
        if span_seconds <= window_step:
            window_eval_times = [t_last]
        else:
            window_eval_times = []
            curr_end = t_first + timedelta(seconds=window_step)
            while curr_end <= t_last + timedelta(seconds=window_step):
                # Only evaluate windows that contain requests in the 60s window
                has_reqs = any(
                    0 <= (curr_end - ts).total_seconds() <= window_size
                    for ts, _ in valid_logs
                )
                if has_reqs:
                    window_eval_times.append(curr_end)

                # Skip long idle gaps (> window_size) where the client is inactive
                next_reqs = [ts for ts, _ in valid_logs if ts > curr_end]
                if next_reqs:
                    next_ts = next_reqs[0]
                    if (next_ts - curr_end).total_seconds() > window_size:
                        curr_end = next_ts + timedelta(seconds=window_step)
                        continue

                curr_end += timedelta(seconds=window_step)

        for w_end in window_eval_times:
            # Requests in 60-second window: [w_end - 60s, w_end]
            w_60_logs = [
                log for ts, log in valid_logs
                if 0 <= (w_end - ts).total_seconds() <= window_size
            ]
            if not w_60_logs:
                continue

            # Requests in 10-second sub-window: [w_end - 10s, w_end]
            w_10_logs = [
                log for ts, log in valid_logs
                if 0 <= (w_end - ts).total_seconds() <= 10.0
            ]

            reqs_10s = len(w_10_logs)
            reqs_60s = len(w_60_logs)

            # Feature 3: endpoint_entropy (normalized Shannon entropy strictly in [0.0, 1.0])
            ep_counts = defaultdict(int)
            for log in w_60_logs:
                ep_counts[log.get("endpoint", "/")] += 1
            entropy = round(compute_entropy(ep_counts), 4)

            # Feature 4: latency_spike (max > avg * 1.5 and max > 100.0)
            latencies = [log.get("response_time", 0.0) for log in w_60_logs]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
            max_latency = max(latencies) if latencies else 0.0
            base = latency_baseline if latency_baseline is not None else avg_latency
            latency_spike = 1 if max_latency > (base * 1.5) and max_latency > 100.0 else 0

            # Feature 5: error_rate
            error_count = sum(1 for log in w_60_logs if log.get("status_code", 200) >= 400)
            error_rate = round(error_count / reqs_60s, 4) if reqs_60s > 0 else 0.0

            # Feature 6: request_variance
            request_variance = round(compute_variance(latencies), 4)

            feature_rows.append({
                "ip_hash": ip_hash,
                "requests_per_ip_10s": reqs_10s,
                "requests_per_ip_60s": reqs_60s,
                "endpoint_entropy": entropy,
                "latency_spike": latency_spike,
                "error_rate": error_rate,
                "request_variance": request_variance,
            })

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
    parser.add_argument(
        "--window-size",
        type=float,
        default=60.0,
        help="Sliding window duration in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--window-step",
        type=float,
        default=10.0,
        help="Sliding window step in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--baseline",
        type=float,
        default=None,
        help="Optional latency baseline in ms (auto-computed per window if omitted)",
    )
    args = parser.parse_args()

    # Read logs
    print(f"[INFO] Reading traffic logs from: {args.input}")
    entries = read_traffic_logs(args.input)
    print(f"       Found {len(entries)} log entries")

    if not entries:
        print("[WARN] No entries found. Nothing to extract.", file=sys.stderr)
        sys.exit(1)

    # Extract features
    print("[INFO] Extracting features...")
    features = extract_features(
        entries,
        latency_baseline=args.baseline,
        window_size=args.window_size,
        window_step=args.window_step,
    )
    unique_ips = len(set(f["ip_hash"] for f in features))
    print(f"       Computed {len(features)} feature window(s) across {unique_ips} unique IP(s)")

    # Write output
    print(f"[INFO] Writing features to: {args.output}")
    write_features_csv(features, args.output)

    # Preview
    print("\n[INFO] Feature Preview:")
    print(
        f"   {'ip_hash':<18} {'req/10s':>7} {'req/60s':>7} {'entropy':>8} {'spike':>5} {'err_rate':>8} {'variance':>9}"
    )
    print(f"   {'-' * 18} {'-' * 7} {'-' * 7} {'-' * 8} {'-' * 5} {'-' * 8} {'-' * 9}")
    for row in features[:10]:  # show first 10
        print(
            f"   {row['ip_hash']:<18} {row['requests_per_ip_10s']:>7} {row['requests_per_ip_60s']:>7} "
            f"{row['endpoint_entropy']:>8.4f} {row['latency_spike']:>5} {row['error_rate']:>8.4f} "
            f"{row['request_variance']:>9.4f}"
        )

    print(f"\n[OK] Done. {len(features)} feature rows written to {args.output}")


if __name__ == "__main__":
    main()
