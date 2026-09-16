"""
Tests for state labeling and dataset generation.
"""

from datetime import datetime, timedelta, timezone
import os
import shutil
import tempfile
import unittest

from forecasting.config import AttackStage
from forecasting.state_labeler import (
    export_csv,
    generate_labeled_dataset,
    label_sequence,
    label_state,
)
from forecasting.state_store import NetworkState, StateStore


class TestStateLabeler(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="turbosh_test_labeler_")
        self.db_path = os.path.join(self.test_dir, "label_test.db")
        self.store = StateStore(capacity=100, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_label_state_thresholds(self):
        now = datetime.now(timezone.utc)

        s_normal = NetworkState(timestamp=now, ip_hash="ip", anomaly_score=0.15)
        self.assertEqual(label_state(s_normal), AttackStage.NORMAL)

        s_recon = NetworkState(timestamp=now, ip_hash="ip", anomaly_score=0.38)
        self.assertEqual(label_state(s_recon), AttackStage.RECON)

        s_escl = NetworkState(timestamp=now, ip_hash="ip", anomaly_score=0.62)
        self.assertEqual(label_state(s_escl), AttackStage.ESCALATION)

        s_surge = NetworkState(timestamp=now, ip_hash="ip", anomaly_score=0.89)
        self.assertEqual(label_state(s_surge), AttackStage.SURGE)

    def test_label_sequence_sustained_promotion(self):
        now = datetime.now(timezone.utc)
        # Sequence: NORMAL, RECON, SURGE, SURGE, SURGE (>= 3 surges should promote to SUSTAINED)
        scores = [0.1, 0.4, 0.85, 0.90, 0.95]
        states = [
            NetworkState(timestamp=now + timedelta(seconds=i * 10), ip_hash="ip_attacker", anomaly_score=s)
            for i, s in enumerate(scores)
        ]

        labels = label_sequence(states)
        self.assertEqual(labels[0], AttackStage.NORMAL)
        self.assertEqual(labels[1], AttackStage.RECON)
        self.assertEqual(labels[2], AttackStage.SUSTAINED)
        self.assertEqual(labels[3], AttackStage.SUSTAINED)
        self.assertEqual(labels[4], AttackStage.SUSTAINED)

    def test_label_sequence_interrupted_surge(self):
        now = datetime.now(timezone.utc)
        # Only 2 consecutive surges, followed by drop back to normal
        scores = [0.85, 0.90, 0.2]
        states = [
            NetworkState(timestamp=now + timedelta(seconds=i * 10), ip_hash="ip_spike", anomaly_score=s)
            for i, s in enumerate(scores)
        ]

        labels = label_sequence(states)
        # Should stay SURGE, not SUSTAINED
        self.assertEqual(labels[0], AttackStage.SURGE)
        self.assertEqual(labels[1], AttackStage.SURGE)
        self.assertEqual(labels[2], AttackStage.NORMAL)

    def test_generate_labeled_dataset_and_export(self):
        now = datetime.now(timezone.utc)
        for i, score in enumerate([0.1, 0.35, 0.55, 0.88]):
            self.store.append(
                NetworkState(
                    timestamp=now + timedelta(seconds=i * 10),
                    ip_hash="ip_test",
                    requests_per_ip_10s=float(i * 10),
                    anomaly_score=score,
                    action="ALLOW" if score < 0.7 else "BLOCK",
                )
            )

        records = generate_labeled_dataset(self.store)
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0]["stage_name"], "NORMAL")
        self.assertEqual(records[1]["stage_name"], "RECON")
        self.assertEqual(records[2]["stage_name"], "ESCALATION")
        self.assertEqual(records[3]["stage_name"], "SURGE")

        csv_path = os.path.join(self.test_dir, "labeled.csv")
        out = export_csv(records, output_path=csv_path)
        self.assertTrue(os.path.exists(out))

        with open(out, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 1 header + 4 rows
        self.assertEqual(len(lines), 5)


if __name__ == "__main__":
    unittest.main()
