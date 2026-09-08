#!/usr/bin/env python3
"""
test_feature_extractor.py — Unit tests for turboSH Feature Extractor

Tests:
1. Normalized Shannon entropy in [0.0, 1.0] (Flaw 6.1)
2. Latency spike threshold unification (Flaw 6.3)
3. Sliding window extraction vs duration averaging (Flaw 6.4)
"""

import math
import unittest
from datetime import datetime, timedelta, timezone

from pipeline.feature_extraction.feature_extractor import (
    compute_entropy,
    compute_variance,
    extract_features,
    parse_timestamp,
)


class TestFeatureExtractor(unittest.TestCase):

    def test_compute_entropy_normalized(self):
        # Deterministic: 1 endpoint -> 0.0
        self.assertEqual(compute_entropy({"/api/login": 10}), 0.0)
        self.assertEqual(compute_entropy({}), 0.0)
        self.assertEqual(compute_entropy({"/api/a": 0}), 0.0)

        # 2 endpoints equally visited -> 1.0
        ent2 = compute_entropy({"/api/a": 5, "/api/b": 5})
        self.assertAlmostEqual(ent2, 1.0, places=4)

        # 4 endpoints equally visited -> 1.0 (normalized, was 2.0 unnormalized)
        ent4 = compute_entropy({"/api/a": 10, "/api/b": 10, "/api/c": 10, "/api/d": 10})
        self.assertAlmostEqual(ent4, 1.0, places=4)

        # 8 endpoints equally visited -> 1.0
        ent8 = compute_entropy({f"/api/{i}": 10 for i in range(8)})
        self.assertAlmostEqual(ent8, 1.0, places=4)

        # Skewed distribution: strictly in (0.0, 1.0)
        ent_skewed = compute_entropy({"/api/a": 90, "/api/b": 10})
        self.assertTrue(0.0 < ent_skewed < 1.0)

    def test_compute_variance(self):
        self.assertEqual(compute_variance([]), 0.0)
        self.assertEqual(compute_variance([42.0]), 0.0)
        self.assertEqual(compute_variance([10.0, 10.0, 10.0]), 0.0)
        # Sample variance of [10, 20, 30] is ((10-20)^2 + (20-20)^2 + (30-20)^2) / 2 = 200 / 2 = 100.0
        self.assertAlmostEqual(compute_variance([10.0, 20.0, 30.0]), 100.0)

    def test_latency_spike_detection(self):
        """Test Flaw 6.3: Latency spike flagged if max > avg * 1.5 AND max > 100.0"""
        base_time = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)

        # Case 1: Spike present (avg ~ 69ms, max = 250ms > 103.5ms and > 100ms)
        entries_with_spike = [
            {"timestamp": (base_time + timedelta(seconds=i)).isoformat(),
             "ip_hash": "ip_spike", "endpoint": "/api/test", "status_code": 200,
             "response_time": lat, "request_size": 100}
            for i, lat in enumerate([20.0, 25.0, 20.0, 30.0, 250.0])
        ]
        features = extract_features(entries_with_spike)
        self.assertTrue(len(features) >= 1)
        self.assertEqual(features[-1]["latency_spike"], 1)

        # Case 2: Max > 1.5x avg, but max <= 100ms -> NO spike
        entries_low_latency = [
            {"timestamp": (base_time + timedelta(seconds=i)).isoformat(),
             "ip_hash": "ip_low", "endpoint": "/api/test", "status_code": 200,
             "response_time": lat, "request_size": 100}
            for i, lat in enumerate([10.0, 10.0, 10.0, 10.0, 30.0])
        ]
        features_low = extract_features(entries_low_latency)
        self.assertEqual(features_low[-1]["latency_spike"], 0)

    def test_sliding_window_burst_capture(self):
        """Test Flaw 6.4: 100 requests in 5 seconds over a 1-hour log file must NOT calculate as ~0 requests/10s"""
        base_time = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)

        # Request 1 at 12:00:00
        entries = [{
            "timestamp": base_time.isoformat(),
            "ip_hash": "attacker_1",
            "endpoint": "/api/home",
            "status_code": 200,
            "response_time": 20.0,
            "request_size": 100,
        }]

        # 100 attack requests sent between 12:59:55 and 13:00:00 (5-second burst, 1 hour later)
        burst_start = base_time + timedelta(minutes=60)
        for i in range(100):
            ts = burst_start + timedelta(milliseconds=i * 50)  # 50ms interval = 5 seconds total
            entries.append({
                "timestamp": ts.isoformat(),
                "ip_hash": "attacker_1",
                "endpoint": "/api/attack",
                "status_code": 200,
                "response_time": 30.0,
                "request_size": 100,
            })

        features = extract_features(entries, window_size=60.0, window_step=10.0)

        # Find the window containing the burst
        burst_windows = [f for f in features if f["requests_per_ip_10s"] >= 50]
        self.assertTrue(
            len(burst_windows) > 0,
            f"Expected at least one window with requests_per_ip_10s >= 50, but got max: {max(f['requests_per_ip_10s'] for f in features)}"
        )
        self.assertEqual(burst_windows[0]["requests_per_ip_10s"], 100)
        self.assertEqual(burst_windows[0]["requests_per_ip_60s"], 100)

    def test_empty_and_fallback(self):
        self.assertEqual(extract_features([]), [])

        # Fallback when timestamps are invalid
        entries = [
            {"timestamp": "invalid_ts", "ip_hash": "bad_ts", "endpoint": "/api/test",
             "status_code": 200, "response_time": 50.0, "request_size": 100}
        ]
        features = extract_features(entries)
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["requests_per_ip_10s"], 1)


if __name__ == "__main__":
    unittest.main()
