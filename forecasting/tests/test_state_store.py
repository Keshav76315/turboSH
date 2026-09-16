"""
Tests for StateStore and NetworkState dataclass.
"""

from datetime import datetime, timedelta, timezone
import os
import shutil
import tempfile
import unittest

from forecasting.state_store import NetworkState, StateStore


class TestStateStore(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="turbosh_test_state_store_")
        self.db_path = os.path.join(self.test_dir, "test_states.db")
        self.store = StateStore(capacity=10, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_network_state_serialization(self):
        now = datetime.now(timezone.utc)
        state = NetworkState(
            timestamp=now,
            ip_hash="test_ip_1",
            requests_per_ip_10s=12.5,
            requests_per_ip_60s=45.0,
            endpoint_entropy=0.88,
            latency_spike=1.0,
            error_rate=0.04,
            request_variance=14.2,
            anomaly_score=0.82,
            action="BLOCK",
            extended_features={"iat_mean": 0.05},
        )
        d = state.to_dict()
        self.assertEqual(d["ip_hash"], "test_ip_1")
        self.assertEqual(d["action"], "BLOCK")
        self.assertEqual(d["extended_features"]["iat_mean"], 0.05)

        restored = NetworkState.from_dict(d)
        self.assertEqual(restored.ip_hash, state.ip_hash)
        self.assertAlmostEqual(restored.anomaly_score, state.anomaly_score, places=3)
        self.assertEqual(restored.action, state.action)

    def test_append_and_capacity(self):
        now = datetime.now(timezone.utc)
        for i in range(15):
            s = NetworkState(
                timestamp=now + timedelta(seconds=i),
                ip_hash="client_a",
                requests_per_ip_10s=float(i),
            )
            self.store.append(s)

        # Capacity is 10, so buffer length should be capped at 10
        self.assertEqual(len(self.store), 10)

    def test_get_ip_history(self):
        now = datetime.now(timezone.utc)
        for i in range(5):
            self.store.append(
                NetworkState(
                    timestamp=now + timedelta(seconds=i),
                    ip_hash="ip_alpha",
                    requests_per_ip_10s=float(i),
                )
            )
            self.store.append(
                NetworkState(
                    timestamp=now + timedelta(seconds=i),
                    ip_hash="ip_beta",
                    requests_per_ip_10s=float(i * 10),
                )
            )

        alpha_history = self.store.get_ip_history("ip_alpha", n=3)
        self.assertEqual(len(alpha_history), 3)
        self.assertEqual(alpha_history[-1].requests_per_ip_10s, 4.0)

        beta_history = self.store.get_ip_history("ip_beta", n=10)
        self.assertEqual(len(beta_history), 5)

        empty_history = self.store.get_ip_history("non_existent_ip")
        self.assertEqual(empty_history, [])

    def test_sqlite_persistence_flush_and_load(self):
        now = datetime.now(timezone.utc)
        for i in range(5):
            self.store.append(
                NetworkState(
                    timestamp=now + timedelta(seconds=i),
                    ip_hash=f"ip_{i}",
                    anomaly_score=0.1 * i,
                    action="ALLOW" if i < 3 else "BLOCK",
                )
            )

        # Flush to SQLite
        flushed_count = self.store.flush_to_sqlite()
        self.assertEqual(flushed_count, 5)

        # Create a new empty store pointing to the same DB and load records
        new_store = StateStore(capacity=10, db_path=self.db_path)
        loaded_count = new_store.load_from_sqlite(limit=10)
        self.assertEqual(loaded_count, 5)
        self.assertEqual(len(new_store), 5)
        history = new_store.get_ip_history("ip_4")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].action, "BLOCK")

    def test_get_all_sequences(self):
        now = datetime.now(timezone.utc)
        # Add 6 states for ip_seq
        for i in range(6):
            self.store.append(
                NetworkState(
                    timestamp=now + timedelta(seconds=i),
                    ip_hash="ip_seq",
                    requests_per_ip_10s=float(i),
                )
            )

        seqs = self.store.get_all_sequences(window_size=3, min_length=3)
        # 6 states with window=3 gives 4 sliding windows: [0,1,2], [1,2,3], [2,3,4], [3,4,5]
        self.assertEqual(len(seqs), 4)
        self.assertEqual(len(seqs[0]), 3)


if __name__ == "__main__":
    unittest.main()
