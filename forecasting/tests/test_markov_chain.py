"""
Unit tests for MarkovChain world model.
"""

import os
import shutil
import tempfile
import unittest
import numpy as np

from forecasting.config import AttackStage
from forecasting.models.markov_chain import MarkovChain


class TestMarkovChain(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="turbosh_test_mc_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_fit_and_predict(self):
        # Sequences that consistently transition 0 -> 1 -> 2 -> 3 -> 4
        sequences = [
            [0, 1, 2, 3, 4],
            [0, 1, 2, 3, 4],
            [0, 1, 2, 3, 3],
        ]
        mc = MarkovChain(n_states=5)
        mc.fit(sequences, smoothing_alpha=0.1)

        self.assertTrue(mc.is_fitted)
        # Transition row sums should all equal 1.0
        row_sums = mc.transition_matrix.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0)

        # 0 should transition most likely to 1
        self.assertEqual(mc.predict(0), 1)
        # 1 should transition most likely to 2
        self.assertEqual(mc.predict(1), 2)
        # 2 should transition most likely to 3
        self.assertEqual(mc.predict(2), 3)

    def test_predict_trajectory(self):
        sequences = [
            [0, 1, 2, 3, 4],
            [0, 1, 2, 3, 4],
        ]
        mc = MarkovChain(n_states=5)
        mc.fit(sequences, smoothing_alpha=0.01)

        # Multi-step forecasting starting at state 0
        traj = mc.predict_trajectory(current_state=0, steps=3)
        self.assertEqual(len(traj), 3)
        self.assertEqual(traj, [1, 2, 3])

        # Multi-step proba
        traj_proba = mc.predict_trajectory_proba(current_state=0, steps=3)
        self.assertEqual(len(traj_proba), 3)
        self.assertGreater(traj_proba[0][1], 0.8)

    def test_serialization(self):
        sequences = [[0, 1, 2]]
        mc = MarkovChain(n_states=5)
        mc.fit(sequences)

        save_path = os.path.join(self.test_dir, "markov.json")
        mc.save(save_path)
        self.assertTrue(os.path.exists(save_path))

        loaded = MarkovChain.load(save_path)
        self.assertEqual(loaded.n_states, mc.n_states)
        np.testing.assert_allclose(loaded.transition_matrix, mc.transition_matrix)
        self.assertEqual(loaded.predict(0), mc.predict(0))


if __name__ == "__main__":
    unittest.main()
