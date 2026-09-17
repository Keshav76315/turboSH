"""
Unit tests for HMMForecaster world model.
"""

import os
import shutil
import tempfile
import unittest
import numpy as np

from forecasting.config import AttackStage
from forecasting.models.hmm_model import HMMForecaster


class TestHMMForecaster(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="turbosh_test_hmm_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_fit_and_viterbi(self):
        # 2 features, 3 states (0, 1, 2)
        # State 0: features around [1.0, 1.0]
        # State 1: features around [5.0, 5.0]
        # State 2: features around [10.0, 10.0]
        obs_seqs = [
            [[1.0, 1.0], [5.0, 5.0], [10.0, 10.0]],
            [[1.1, 0.9], [4.9, 5.1], [10.2, 9.8]],
        ]
        st_seqs = [
            [0, 1, 2],
            [0, 1, 2],
        ]

        hmm = HMMForecaster(n_hidden_states=3, n_features=2)
        hmm.fit(obs_seqs, st_seqs, smoothing_alpha=0.1)

        self.assertTrue(hmm.is_fitted)

        # Test Viterbi decoding
        test_obs = [[0.95, 1.05], [5.05, 4.95], [9.9, 10.1]]
        decoded_path = hmm.viterbi(test_obs)
        self.assertEqual(decoded_path, [0, 1, 2])

        # Current state prediction
        current_state = hmm.predict(test_obs)
        self.assertEqual(current_state, 2)

    def test_forecast_and_proba(self):
        obs_seqs = [
            [[1.0, 1.0], [5.0, 5.0], [10.0, 10.0]],
        ]
        st_seqs = [
            [0, 1, 2],
        ]
        hmm = HMMForecaster(n_hidden_states=3, n_features=2)
        hmm.fit(obs_seqs, st_seqs)

        test_obs = [[1.0, 1.0]]  # Observed state 0
        forecast = hmm.forecast(test_obs, steps=2)
        self.assertEqual(len(forecast), 2)
        self.assertEqual(forecast[0], 1)
        self.assertEqual(forecast[1], 2)

        proba = hmm.forecast_proba(test_obs, steps=2)
        self.assertEqual(len(proba), 2)
        self.assertIn(1, proba[0])

    def test_serialization(self):
        obs_seqs = [[[1.0, 1.0], [5.0, 5.0]]]
        st_seqs = [[0, 1]]
        hmm = HMMForecaster(n_hidden_states=2, n_features=2)
        hmm.fit(obs_seqs, st_seqs)

        save_path = os.path.join(self.test_dir, "hmm.json")
        hmm.save(save_path)
        self.assertTrue(os.path.exists(save_path))

        loaded = HMMForecaster.load(save_path)
        self.assertEqual(loaded.n_states, hmm.n_states)
        self.assertEqual(loaded.n_features, hmm.n_features)
        np.testing.assert_allclose(loaded.transition_matrix, hmm.transition_matrix)
        np.testing.assert_allclose(loaded.means, hmm.means)
 
    def test_init_parameter_alias(self):
        """Verify HMMForecaster supports both n_hidden_states and n_states (alias)."""
        hmm1 = HMMForecaster(n_hidden_states=4, n_features=3)
        self.assertEqual(hmm1.n_states, 4)
        self.assertEqual(hmm1.n_features, 3)

        hmm2 = HMMForecaster(n_states=6, n_features=4)
        self.assertEqual(hmm2.n_states, 6)
        self.assertEqual(hmm2.n_features, 4)

        hmm3 = HMMForecaster()
        self.assertEqual(hmm3.n_states, 5)


if __name__ == "__main__":
    unittest.main()
