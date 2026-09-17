"""
Unit tests for LSTMForecaster model (forecasting/models/lstm_model.py).
"""

import os
import tempfile
import numpy as np
import pytest
import torch

from forecasting.config import FEATURE_NAMES, FORECAST_HORIZON, STAGE_NAMES
from forecasting.models.lstm_model import LSTMForecaster, StepForecast


class TestLSTMForecaster:
    """Test suite for LSTM world model architecture and inference."""

    def test_forward_output_shape(self):
        batch_size = 4
        seq_len = 10
        input_size = 6
        x = torch.randn(batch_size, seq_len, input_size)

        model = LSTMForecaster(
            input_size=input_size,
            hidden_size=64,
            num_layers=2,
            num_classes=5,
            forecast_horizon=3,
        )
        logits = model(x)
        assert logits.shape == (batch_size, 3, 5)

    def test_predict_proba_and_predict_shapes(self):
        model = LSTMForecaster(
            input_size=6,
            hidden_size=32,
            num_layers=1,
            num_classes=5,
            forecast_horizon=3,
        )

        # Test with 3D numpy array
        x_3d = np.random.randn(2, 10, 6).astype(np.float32)
        probs_3d = model.predict_proba(x_3d)
        assert probs_3d.shape == (2, 3, 5)
        # Sum of probabilities across classes should be 1.0
        np.testing.assert_allclose(np.sum(probs_3d, axis=-1), np.ones((2, 3)), atol=1e-5)

        preds_3d = model.predict(x_3d)
        assert preds_3d.shape == (2, 3)
        assert np.all((preds_3d >= 0) & (preds_3d < 5))

        # Test with 2D numpy array (single sequence)
        x_2d = np.random.randn(10, 6).astype(np.float32)
        probs_2d = model.predict_proba(x_2d)
        assert probs_2d.shape == (3, 5)
        np.testing.assert_allclose(np.sum(probs_2d, axis=-1), np.ones(3), atol=1e-5)

        preds_2d = model.predict(x_2d)
        assert preds_2d.shape == (3,)

    def test_predict_with_confidence(self):
        model = LSTMForecaster(
            input_size=6,
            hidden_size=32,
            num_layers=1,
            num_classes=5,
            forecast_horizon=3,
        )
        x = np.random.randn(1, 10, 6).astype(np.float32)
        results = model.predict_with_confidence(x)

        assert len(results) == 1
        steps = results[0]
        assert len(steps) == 3

        for i, step in enumerate(steps):
            assert isinstance(step, StepForecast)
            assert step.horizon_step == i + 1
            assert step.stage in STAGE_NAMES
            assert step.stage_name == STAGE_NAMES[step.stage]
            assert 0.0 <= step.confidence <= 1.0
            assert len(step.probabilities) == 5
            assert pytest.approx(sum(step.probabilities), abs=1e-4) == 1.0

            d = step.to_dict()
            assert "horizon_step" in d
            assert "stage_name" in d
            assert "confidence" in d

    def test_save_and_load_weights(self):
        model = LSTMForecaster(
            input_size=6,
            hidden_size=48,
            num_layers=2,
            num_classes=5,
            forecast_horizon=3,
            dropout=0.2,
        )
        x = np.random.randn(2, 10, 6).astype(np.float32)
        preds_before = model.predict_proba(x)

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = os.path.join(tmpdir, "test_lstm.pt")
            model.save_weights(ckpt_path)
            assert os.path.exists(ckpt_path)

            loaded_model = LSTMForecaster.load_weights(ckpt_path)
            assert loaded_model.input_size == model.input_size
            assert loaded_model.hidden_size == model.hidden_size
            assert loaded_model.num_layers == model.num_layers

            preds_after = loaded_model.predict_proba(x)
            np.testing.assert_allclose(preds_before, preds_after, atol=1e-5)
