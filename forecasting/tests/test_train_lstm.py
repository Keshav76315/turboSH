"""
Unit tests for train_lstm.py helper functions, contracts, and report generation.
"""

import inspect
import os
import re
import tempfile
import typing
import unittest
import numpy as np

from forecasting.config import AttackStage
from forecasting.evaluation.evaluator import EvaluationMetrics
from forecasting.train_lstm import (
    compute_lead_times,
    evaluate_test_set,
    generate_v3_report,
)


def _dummy_metric(accuracy: float) -> EvaluationMetrics:
    """Helper to create dummy EvaluationMetrics for testing report generation."""
    cm = [[0] * 5 for _ in range(5)]
    cm[0][0] = int(accuracy * 100)
    cm[1][1] = int(accuracy * 100)
    stage_m = {
        s: {
            "stage_name": f"STAGE_{s}",
            "precision": accuracy,
            "recall": accuracy,
            "f1": accuracy,
            "support": 50,
        }
        for s in range(5)
    }
    return EvaluationMetrics(
        accuracy=accuracy,
        precision_macro=accuracy,
        recall_macro=accuracy,
        f1_macro=accuracy,
        stage_metrics=stage_m,
        confusion_matrix=cm,
        mean_lead_time_steps=1.5,
        mean_lead_time_seconds=15.0,
        total_samples=100,
    )


class TestTrainLSTMReport(unittest.TestCase):
    """Test dynamic benchmark report generation and gap formatting."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.report_path = os.path.join(self.tmp_dir.name, "test_report.md")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_gap_formatting_no_double_negatives(self):
        """Ensure no double negatives occur when LSTM trails or leads."""
        # Case 1: LSTM trails (e.g. LSTM 60% vs HMM 65%)
        lstm_metrics = {h: _dummy_metric(0.60) for h in [1, 2, 3]}
        hmm_metrics = {h: _dummy_metric(0.65) for h in [1, 2, 3]}
        mc_metrics = {h: _dummy_metric(0.65) for h in [1, 2, 3]}

        content = generate_v3_report(
            lstm_metrics=lstm_metrics,
            hmm_metrics=hmm_metrics,
            mc_metrics=mc_metrics,
            explanations=[],
            output_path=self.report_path,
            training_duration_sec=10.0,
            lstm_lead_time_sec=15.0,
            hmm_lead_time_sec=12.0,
            mc_lead_time_sec=10.0,
            onnx_exported=True,
            onnx_parity_diff=5e-5,
        )

        self.assertIsNone(re.search(r"--\d", content), "Report must not contain double negative numbers")
        self.assertIn("(-5.00%)", content, "Trailing gap should be formatted as (-5.00%)")
        self.assertIn("trails both the Markov Chain and Gaussian HMM baselines", content)
        self.assertIn("✅ Validated (diff: 5.00e-05)", content)

    def test_gap_formatting_lstm_leading(self):
        """Ensure positive gaps are formatted with + and appropriate observation."""
        # Case 2: LSTM leads (e.g. LSTM 75% vs HMM 70% and MC 68%)
        lstm_metrics = {h: _dummy_metric(0.75) for h in [1, 2, 3]}
        hmm_metrics = {h: _dummy_metric(0.70) for h in [1, 2, 3]}
        mc_metrics = {h: _dummy_metric(0.68) for h in [1, 2, 3]}

        content = generate_v3_report(
            lstm_metrics=lstm_metrics,
            hmm_metrics=hmm_metrics,
            mc_metrics=mc_metrics,
            explanations=[],
            output_path=self.report_path,
            training_duration_sec=10.0,
            lstm_lead_time_sec=20.0,
            hmm_lead_time_sec=15.0,
            mc_lead_time_sec=12.0,
            onnx_exported=False,
            onnx_parity_diff=None,
        )

        self.assertIsNone(re.search(r"--\d", content), "Report must not contain double negative numbers")
        self.assertIn("(+5.00%)", content, "Leading gap should be formatted as (+5.00%)")
        self.assertIn("(+7.00%)", content, "Leading gap should be formatted as (+7.00%)")
        self.assertIn("outperforms both the Markov Chain and Gaussian HMM", content)
        self.assertIn("⚪ Not Exported / Pending", content, "ONNX pending status when not exported")

    def test_onnx_export_status_reporting(self):
        """Test ONNX status table reporting when export is enabled vs disabled."""
        metrics = {h: _dummy_metric(0.70) for h in [1, 2, 3]}

        # When ONNX export is disabled or failed
        content_disabled = generate_v3_report(
            lstm_metrics=metrics,
            hmm_metrics=metrics,
            mc_metrics=metrics,
            explanations=[],
            output_path=self.report_path,
            training_duration_sec=5.0,
            lstm_lead_time_sec=10.0,
            hmm_lead_time_sec=10.0,
            mc_lead_time_sec=10.0,
            onnx_exported=False,
            onnx_parity_diff=None,
        )
        self.assertIn("⚪ Not Exported / Pending", content_disabled)
        self.assertIn("ONNX export not performed or pending validation", content_disabled)

        # When ONNX export succeeded and passed parity check
        content_enabled = generate_v3_report(
            lstm_metrics=metrics,
            hmm_metrics=metrics,
            mc_metrics=metrics,
            explanations=[],
            output_path=self.report_path,
            training_duration_sec=5.0,
            lstm_lead_time_sec=10.0,
            hmm_lead_time_sec=10.0,
            mc_lead_time_sec=10.0,
            onnx_exported=True,
            onnx_parity_diff=1.23e-5,
        )
        self.assertIn("✅ Validated (diff: 1.23e-05)", content_enabled)
        self.assertIn("Fully validated ONNX model ready", content_enabled)


class TestEvaluateTestSetSignature(unittest.TestCase):
    """Verify evaluate_test_set return annotation and docstring contract."""

    def test_return_annotation_and_docstring(self):
        sig = inspect.signature(evaluate_test_set)
        ret_type = sig.return_annotation

        # Verify return type is a 6-element tuple
        origin = typing.get_origin(ret_type)
        args = typing.get_args(ret_type)
        self.assertIs(origin, tuple)
        self.assertEqual(len(args), 6, "evaluate_test_set return type must annotate all 6 returned values")

        # First 3 should be Dict[int, EvaluationMetrics]
        for i in range(3):
            self.assertIs(typing.get_origin(args[i]), dict)

        # Last 3 should be np.ndarray
        for i in range(3, 6):
            self.assertIs(args[i], np.ndarray)

        # Verify docstring documents all 6 returned values
        doc = evaluate_test_set.__doc__ or ""
        self.assertIn("lstm_metrics", doc)
        self.assertIn("hmm_metrics", doc)
        self.assertIn("mc_metrics", doc)
        self.assertIn("lstm_preds", doc)
        self.assertIn("hmm_preds_arr", doc)
        self.assertIn("mc_preds_arr", doc)

    def test_evaluate_test_set_fallback(self):
        """Verify evaluate_test_set runs fallback HMM and MC successfully when model files do not exist."""
        from unittest.mock import MagicMock
        from forecasting.evaluation.evaluator import ForecastEvaluator

        mock_model = MagicMock()
        mock_model.predict.return_value = np.zeros((4, 3), dtype=np.int64)

        mock_dataset = MagicMock()
        mock_dataset.samples_x = np.zeros((4, 10, 6), dtype=np.float32)
        mock_dataset.samples_y = np.zeros((4, 3), dtype=np.int64)

        mock_scaler = MagicMock()
        mock_scaler.inverse_transform.return_value = np.zeros((4, 10, 6), dtype=np.float32)

        evaluator = ForecastEvaluator(n_states=5)

        results = evaluate_test_set(
            model=mock_model,
            test_dataset=mock_dataset,
            evaluator=evaluator,
            scaler=mock_scaler,
            hmm_model_path="nonexistent_hmm.json",
            mc_model_path="nonexistent_mc.json",
        )

        self.assertEqual(len(results), 6)
        lstm_metrics, hmm_metrics, mc_metrics, lstm_preds, hmm_preds, mc_preds = results
        self.assertEqual(lstm_preds.shape, (4, 3))
        self.assertEqual(hmm_preds.shape, (4, 3))
        self.assertEqual(mc_preds.shape, (4, 3))


class TestLeadTimeComputation(unittest.TestCase):
    """Test lead-time analysis logic."""

    def test_no_surge_episodes(self):
        y_true = np.array([[0, 0, 0], [1, 1, 1]])
        preds = np.array([[0, 0, 0], [1, 1, 1]])
        lead_time = compute_lead_times(y_true, preds, surge_threshold=AttackStage.SURGE)
        self.assertEqual(lead_time, 0.0)

    def test_detected_surge_episode(self):
        # Surge occurs and is predicted at step 2 (h index 1) -> lead time is (1 + 1) * 10 = 20s
        y_true = np.array([[0, 3, 4]])
        preds = np.array([[0, 3, 4]])
        lead_time = compute_lead_times(y_true, preds, surge_threshold=AttackStage.SURGE)
        self.assertEqual(lead_time, 20.0)


if __name__ == "__main__":
    unittest.main()
