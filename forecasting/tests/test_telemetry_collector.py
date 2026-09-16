"""
Tests for TelemetryCollector.
"""

import json
import os
import shutil
import tempfile
import unittest

from forecasting.state_store import StateStore
from forecasting.telemetry_collector import TelemetryCollector


class TestTelemetryCollector(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="turbosh_test_collector_")
        self.db_path = os.path.join(self.test_dir, "collector_test.db")
        self.log_path = os.path.join(self.test_dir, "test_telemetry.jsonl")
        self.store = StateStore(capacity=100, db_path=self.db_path)
        self.collector = TelemetryCollector(state_store=self.store, log_path=self.log_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_valid_and_invalid_line(self):
        valid_json = json.dumps(
            {
                "timestamp": "2026-09-16T12:30:00.000Z",
                "ip_hash": "abc123hash",
                "requests_per_ip_10s": 25.0,
                "requests_per_ip_60s": 80.0,
                "endpoint_entropy": 0.75,
                "latency_spike": 0.0,
                "error_rate": 0.02,
                "request_variance": 5.1,
                "anomaly_score": 0.42,
                "action": "ALLOW",
                "extended_features": {},
            }
        )

        state = self.collector.parse_line(valid_json)
        self.assertIsNotNone(state)
        self.assertEqual(state.ip_hash, "abc123hash")
        self.assertEqual(state.requests_per_ip_10s, 25.0)

        # Empty line
        self.assertIsNone(self.collector.parse_line("   \n"))

        # Malformed JSON
        self.assertIsNone(self.collector.parse_line("{malformed_json..."))

    def test_ingest_file(self):
        lines = [
            json.dumps(
                {
                    "timestamp": f"2026-09-16T12:00:0{i}.000Z",
                    "ip_hash": f"ip_{i}",
                    "requests_per_ip_10s": float(i * 5),
                    "anomaly_score": float(i * 0.2),
                    "action": "ALLOW",
                }
            )
            for i in range(5)
        ]

        with open(self.log_path, "w", encoding="utf-8") as f:
            for l in lines:
                f.write(l + "\n")

        count = self.collector.ingest_file()
        self.assertEqual(count, 5)
        self.assertEqual(len(self.store), 5)

        # Verify persisted in SQLite
        history = self.store.get_ip_history("ip_3")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].requests_per_ip_10s, 15.0)


if __name__ == "__main__":
    unittest.main()
