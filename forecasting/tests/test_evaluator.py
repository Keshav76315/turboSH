"""
Unit tests for the forecasting evaluation / scoring utilities.

Tests cover:
  - Markov Chain next-step accuracy evaluation
  - HMM Viterbi path accuracy evaluation
  - Multi-step trajectory accuracy helpers
"""

import unittest
import numpy as np

from forecasting.config import AttackStage
from forecasting.models.markov_chain import MarkovChain
from forecasting.models.hmm_model import HMMForecaster


class TestMarkovChainEvaluation(unittest.TestCase):
    """Evaluate MarkovChain prediction accuracy on synthetic sequences."""

    def setUp(self):
        # Train a Markov Chain on deterministic escalation sequences
        self.mc = MarkovChain(n_states=5)
        self.train_seqs = [
            [0, 1, 2, 3, 4],
            [0, 1, 2, 3, 4],
            [0, 1, 2, 3, 4],
            [0, 0, 0, 1, 2],
        ]
        self.mc.fit(self.train_seqs, smoothing_alpha=0.1)

    def test_next_step_accuracy_on_training_data(self):
        """On strongly repeated patterns, next-step accuracy should be high."""
        correct = 0
        total = 0
        for seq in self.train_seqs:
            for t in range(len(seq) - 1):
                predicted = self.mc.predict(seq[t])
                if predicted == seq[t + 1]:
                    correct += 1
                total += 1
        accuracy = correct / total if total else 0.0
        self.assertGreater(accuracy, 0.5, "Next-step accuracy on training data should exceed 50%")

    def test_trajectory_accuracy(self):
        """Multi-step trajectory from state 0 should broadly follow escalation pattern."""
        traj = self.mc.predict_trajectory(0, steps=4)
        self.assertEqual(len(traj), 4)
        # Given the training sequences 0->1->2->3->4, trajectory from 0 should start with 1
        self.assertEqual(traj[0], 1, "First trajectory step from NORMAL should be RECON")

    def test_probability_distribution_valid(self):
        """predict_proba should return valid probability distributions."""
        for state in range(5):
            proba = self.mc.predict_proba(state)
            self.assertEqual(len(proba), 5)
            total = sum(proba.values())
            self.assertAlmostEqual(total, 1.0, places=5)
            for v in proba.values():
                self.assertGreaterEqual(v, 0.0)


class TestHMMEvaluation(unittest.TestCase):
    """Evaluate HMMForecaster Viterbi decoding accuracy on synthetic data."""

    def setUp(self):
        self.hmm = HMMForecaster(n_hidden_states=5, n_features=6)
        # Generate synthetic observations where each stage has a distinct feature signature
        np.random.seed(42)
        obs_seqs = []
        state_seqs = []
        for _ in range(20):
            seq_len = np.random.randint(5, 15)
            states = []
            obs = []
            current = 0
            for t in range(seq_len):
                states.append(current)
                # Feature vector clusters around stage * 0.2 + noise
                obs.append((np.ones(6) * current * 0.2 + np.random.normal(0, 0.05, 6)).tolist())
                # Occasionally escalate
                if np.random.random() < 0.3 and current < 4:
                    current += 1
            obs_seqs.append(obs)
            state_seqs.append(states)

        self.obs_seqs = obs_seqs
        self.state_seqs = state_seqs
        self.hmm.fit(obs_seqs, state_seqs, smoothing_alpha=0.1)

    def test_viterbi_path_length_matches_input(self):
        """Viterbi path should have the same length as input observations."""
        for obs_seq in self.obs_seqs[:5]:
            path = self.hmm.viterbi(obs_seq)
            self.assertEqual(len(path), len(obs_seq))

    def test_viterbi_accuracy_on_training_data(self):
        """Viterbi accuracy on training data should be reasonable (> 40%)."""
        correct = 0
        total = 0
        for obs_seq, state_seq in zip(self.obs_seqs, self.state_seqs):
            path = self.hmm.viterbi(obs_seq)
            for predicted, actual in zip(path, state_seq):
                if predicted == actual:
                    correct += 1
                total += 1
        accuracy = correct / total if total else 0.0
        self.assertGreater(accuracy, 0.4, f"Viterbi accuracy was {accuracy:.2%}, expected > 40%")

    def test_forecast_returns_correct_length(self):
        """forecast() should return exactly `steps` predictions."""
        obs = self.obs_seqs[0]
        preds = self.hmm.forecast(obs, steps=5)
        self.assertEqual(len(preds), 5)

    def test_forecast_proba_valid_distributions(self):
        """forecast_proba() should return valid probability distributions."""
        obs = self.obs_seqs[0]
        distributions = self.hmm.forecast_proba(obs, steps=3)
        self.assertEqual(len(distributions), 3)
        for dist in distributions:
            self.assertEqual(len(dist), 5)
            total = sum(dist.values())
            self.assertAlmostEqual(total, 1.0, places=5)

    def test_predict_returns_valid_state(self):
        """predict() should return a valid AttackStage integer."""
        obs = self.obs_seqs[0]
        state = self.hmm.predict(obs)
        self.assertIn(state, range(5))

    def test_empty_observations(self):
        """Empty observations should return safe defaults."""
        path = self.hmm.viterbi([])
        self.assertEqual(path, [])
        state = self.hmm.predict([])
        self.assertEqual(state, int(AttackStage.NORMAL))
        forecast = self.hmm.forecast([], steps=3)
        self.assertEqual(len(forecast), 3)


class TestEvaluationMetrics(unittest.TestCase):
    """Test evaluation metric computation helpers."""

    def test_confusion_matrix_shape(self):
        """Basic confusion matrix should be NxN for N classes."""
        from collections import Counter
        y_true = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
        y_pred = [0, 1, 2, 3, 4, 0, 0, 2, 3, 3]

        n_classes = 5
        confusion = np.zeros((n_classes, n_classes), dtype=int)
        for t, p in zip(y_true, y_pred):
            confusion[t, p] += 1

        self.assertEqual(confusion.shape, (5, 5))
        # Diagonal should sum to at least the correct predictions
        correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
        self.assertEqual(np.trace(confusion), correct)

    def test_accuracy_computation(self):
        y_true = [0, 0, 1, 1, 2, 2]
        y_pred = [0, 0, 1, 2, 2, 2]
        correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
        accuracy = correct / len(y_true)
        self.assertAlmostEqual(accuracy, 5 / 6)

    def test_per_class_accuracy(self):
        """Per-class accuracy: correct for each class / total for that class."""
        y_true = [0, 0, 1, 1, 2, 2]
        y_pred = [0, 1, 1, 1, 2, 0]
        # Class 0: 1/2, Class 1: 2/2, Class 2: 1/2
        per_class = {}
        for cls in range(3):
            total = sum(1 for t in y_true if t == cls)
            correct = sum(1 for t, p in zip(y_true, y_pred) if t == cls and t == p)
            per_class[cls] = correct / total if total else 0.0

        self.assertAlmostEqual(per_class[0], 0.5)
        self.assertAlmostEqual(per_class[1], 1.0)
        self.assertAlmostEqual(per_class[2], 0.5)


class TestMultiStepEvaluator(unittest.TestCase):
    """Test multi-step evaluation, horizon degradation curves, and model comparison."""

    def setUp(self):
        from forecasting.evaluation.evaluator import ForecastEvaluator
        self.evaluator = ForecastEvaluator(n_states=5)

    def test_evaluate_multistep(self):
        y_true = np.array([
            [0, 1, 2],
            [1, 2, 3],
            [2, 3, 4],
            [0, 0, 1],
        ])
        y_pred = np.array([
            [0, 1, 1],  # step 3 wrong
            [1, 2, 3],  # all correct
            [2, 3, 4],  # all correct
            [0, 1, 1],  # step 2 wrong
        ])

        results = self.evaluator.evaluate_multistep(y_true, y_pred)
        self.assertEqual(len(results), 3)
        self.assertIn(1, results)
        self.assertIn(2, results)
        self.assertIn(3, results)

        # Step 1: 4/4 correct
        self.assertEqual(results[1].accuracy, 1.0)
        # Step 2: 3/4 correct
        self.assertEqual(results[2].accuracy, 0.75)
        # Step 3: 3/4 correct
        self.assertEqual(results[3].accuracy, 0.75)

    def test_accuracy_vs_horizon_curve(self):
        y_true = np.array([[0, 1, 2], [1, 2, 3]])
        y_pred = np.array([[0, 1, 1], [1, 2, 3]])
        results = self.evaluator.evaluate_multistep(y_true, y_pred)

        curve = self.evaluator.accuracy_vs_horizon_curve(results)
        self.assertEqual(len(curve), 3)
        self.assertEqual(curve[0]["horizon_label"], "t+1")
        self.assertEqual(curve[1]["horizon_label"], "t+2")
        self.assertEqual(curve[2]["horizon_label"], "t+3")
        self.assertIn("accuracy", curve[0])
        self.assertIn("f1_macro", curve[0])

    def test_compare_models(self):
        y_true = np.array([[0, 1, 2], [1, 2, 3]])
        y_pred = np.array([[0, 1, 1], [1, 2, 3]])
        multistep = self.evaluator.evaluate_multistep(y_true, y_pred)

        comparison_data = {
            "Model A": {
                "multistep": multistep,
                "f1_macro": 0.85,
                "mean_lead_time_seconds": 15.0,
            },
            "Model B": {
                "multistep": [0.80, 0.70, 0.60],
                "f1_macro": 0.75,
                "mean_lead_time_seconds": 10.0,
            },
        }

        report = self.evaluator.compare_models(comparison_data)
        self.assertIn("# Model Comparison Benchmark", report)
        self.assertIn("Model A", report)
        self.assertIn("Model B", report)
        self.assertIn("15.0s", report)

    def test_evaluate_multistep_shape_mismatch(self):
        y_true = np.array([[0, 1, 2], [1, 2, 3]])
        y_pred = np.array([[0, 1], [1, 2]])  # Mismatched horizon
        with self.assertRaises(ValueError) as ctx:
            self.evaluator.evaluate_multistep(y_true, y_pred)
        self.assertIn("Shape mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
