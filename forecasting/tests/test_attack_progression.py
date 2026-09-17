"""
Unit tests for AttackProgressionModel.
"""

import unittest
import numpy as np

from forecasting.config import AttackStage
from forecasting.models.markov_chain import MarkovChain
from forecasting.attack_progression import AttackProgressionModel


class TestAttackProgressionModel(unittest.TestCase):

    def _make_model(self, sequences=None):
        """Helper: fit a MarkovChain from sample sequences and wrap in AttackProgressionModel."""
        mc = MarkovChain(n_states=5)
        if sequences:
            mc.fit(sequences, smoothing_alpha=1.0)
        return AttackProgressionModel(markov_model=mc)

    # ── Escalation / De-escalation Probabilities ──────────────────────────

    def test_escalation_prob_at_normal(self):
        # With strong escalation sequences, P(escalate | NORMAL) should be significant
        seqs = [[0, 1, 2, 3, 4]] * 10
        model = self._make_model(seqs)
        p = model.get_escalation_probability(AttackStage.NORMAL)
        self.assertGreater(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_escalation_prob_at_sustained_is_zero(self):
        # SUSTAINED (4) is the highest stage — cannot escalate further
        model = self._make_model([[0, 1, 2, 3, 4]])
        self.assertAlmostEqual(model.get_escalation_probability(AttackStage.SUSTAINED), 0.0)

    def test_deescalation_prob_at_normal_is_zero(self):
        # NORMAL (0) is the lowest stage — cannot de-escalate
        model = self._make_model([[0, 0, 0]])
        self.assertAlmostEqual(model.get_deescalation_probability(AttackStage.NORMAL), 0.0)

    def test_deescalation_prob_at_surge(self):
        # With sequences that include de-escalation, P(de-escalate | SURGE) should be > 0
        seqs = [[3, 2, 1, 0], [3, 3, 2, 0]]
        model = self._make_model(seqs)
        p = model.get_deescalation_probability(AttackStage.SURGE)
        self.assertGreater(p, 0.0)

    def test_stability_prob(self):
        # Stability probability should be P(stay in same state)
        seqs = [[0, 0, 0, 0, 0]] * 5
        model = self._make_model(seqs)
        p = model.get_stability_probability(AttackStage.NORMAL)
        self.assertGreater(p, 0.5)  # Strong self-loop from repeated 0->0

    def test_probabilities_sum_to_one(self):
        """escalation + deescalation + stability should equal 1.0 for any valid state."""
        model = self._make_model([[0, 1, 2, 3, 4], [4, 3, 2, 1, 0]])
        for stage in range(5):
            total = (
                model.get_escalation_probability(stage)
                + model.get_deescalation_probability(stage)
                + model.get_stability_probability(stage)
            )
            self.assertAlmostEqual(total, 1.0, places=6,
                                   msg=f"Probabilities for stage {stage} don't sum to 1.0")

    # ── Trajectory Prediction ─────────────────────────────────────────────

    def test_trajectory_length(self):
        model = self._make_model([[0, 1, 2, 3, 4]])
        traj = model.get_likely_trajectory(AttackStage.RECON, horizon=5)
        self.assertEqual(len(traj), 5)

    def test_trajectory_entries_are_tuples(self):
        model = self._make_model([[0, 1, 2]])
        traj = model.get_likely_trajectory(0, horizon=3)
        for entry in traj:
            self.assertIsInstance(entry, tuple)
            self.assertEqual(len(entry), 2)
            stage, confidence = entry
            self.assertIn(stage, range(5))
            self.assertGreater(confidence, 0.0)
            self.assertLessEqual(confidence, 1.0)

    # ── Escalation Detection ──────────────────────────────────────────────

    def test_is_escalating_positive(self):
        model = self._make_model([[0, 1, 2, 3]])
        self.assertTrue(model.is_escalating([0, 1, 2, 3]))

    def test_is_escalating_negative_flat(self):
        model = self._make_model([[0, 0, 0]])
        self.assertFalse(model.is_escalating([0, 0, 0]))

    def test_is_escalating_negative_decreasing(self):
        model = self._make_model([[3, 2, 1, 0]])
        self.assertFalse(model.is_escalating([3, 2, 1, 0]))

    def test_is_escalating_too_short(self):
        model = self._make_model([[0, 1]])
        self.assertFalse(model.is_escalating([2]))
        self.assertFalse(model.is_escalating([]))

    # ── Edge Cases ────────────────────────────────────────────────────────

    def test_invalid_stage_escalation(self):
        model = self._make_model([[0, 1]])
        self.assertAlmostEqual(model.get_escalation_probability(-1), 0.0)
        self.assertAlmostEqual(model.get_escalation_probability(99), 0.0)

    def test_invalid_stage_deescalation(self):
        model = self._make_model([[0, 1]])
        self.assertAlmostEqual(model.get_deescalation_probability(-1), 0.0)

    def test_unfitted_model(self):
        """An unfitted model (uniform transitions) should still produce valid outputs."""
        model = AttackProgressionModel(markov_model=MarkovChain(n_states=5))
        p = model.get_escalation_probability(0)
        self.assertGreater(p, 0.0)
        traj = model.get_likely_trajectory(0, horizon=3)
        self.assertEqual(len(traj), 3)


if __name__ == "__main__":
    unittest.main()
