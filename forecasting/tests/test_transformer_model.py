"""
Unit tests for TransformerForecaster model (forecasting/models/transformer_model.py).
"""

import os
import tempfile
import numpy as np
import pytest
import torch

from forecasting.config import FEATURE_NAMES, FORECAST_HORIZON, STAGE_NAMES
from forecasting.models.transformer_model import (
    CustomTransformerEncoderLayer,
    PositionalEncoding,
    TransformerForecaster,
)
from forecasting.models.lstm_model import StepForecast


class TestTransformerForecaster:
    """Test suite for Transformer world model architecture, attention, and inference."""

    def test_forward_output_shape_last_pooling(self):
        batch_size = 4
        seq_len = 10
        input_size = 6
        x = torch.randn(batch_size, seq_len, input_size)

        model = TransformerForecaster(
            input_size=input_size,
            d_model=32,
            nhead=4,
            num_layers=2,
            dim_feedforward=64,
            num_classes=5,
            forecast_horizon=3,
            pooling_mode="last",
        )
        logits = model(x)
        assert logits.shape == (batch_size, 3, 5)

    def test_forward_output_shape_mean_pooling(self):
        batch_size = 4
        seq_len = 10
        input_size = 6
        x = torch.randn(batch_size, seq_len, input_size)

        model = TransformerForecaster(
            input_size=input_size,
            d_model=32,
            nhead=4,
            num_layers=2,
            dim_feedforward=64,
            num_classes=5,
            forecast_horizon=3,
            pooling_mode="mean",
        )
        logits = model(x)
        assert logits.shape == (batch_size, 3, 5)

    def test_predict_proba_and_predict_shapes(self):
        model = TransformerForecaster(
            input_size=6,
            d_model=32,
            nhead=2,
            num_layers=1,
            num_classes=5,
            forecast_horizon=3,
        )

        # Test with 3D numpy array
        x_3d = np.random.randn(2, 10, 6).astype(np.float32)
        probs_3d = model.predict_proba(x_3d)
        assert probs_3d.shape == (2, 3, 5)
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
        assert np.all((preds_2d >= 0) & (preds_2d < 5))

    def test_forecast_step_objects(self):
        model = TransformerForecaster(
            input_size=6,
            d_model=32,
            nhead=2,
            num_layers=1,
            num_classes=5,
            forecast_horizon=3,
        )
        x = np.random.randn(10, 6).astype(np.float32)
        forecasts = model.forecast(x)

        assert len(forecasts) == 3
        for i, step_fc in enumerate(forecasts):
            assert isinstance(step_fc, StepForecast)
            assert step_fc.horizon_step == i + 1
            assert step_fc.predicted_stage in STAGE_NAMES.values()
            assert 0.0 <= step_fc.probability <= 1.0
            assert len(step_fc.all_probabilities) == 5

    def test_attention_weights_exposed(self):
        """Transformer attention weights per layer and head must be retrievable."""
        model = TransformerForecaster(
            input_size=6,
            d_model=32,
            nhead=4,
            num_layers=2,
            forecast_horizon=3,
        )
        x = torch.randn(2, 8, 6)
        attention_maps = model.get_attention_weights(x)

        # 2 layers
        assert len(attention_maps) == 2
        for attn in attention_maps:
            # Shape: (batch_size, nhead, seq_len, seq_len)
            assert attn.shape == (2, 4, 8, 8)
            # Attention across keys should sum to ~1.0
            np.testing.assert_allclose(
                attn.sum(dim=-1).detach().cpu().numpy(),
                np.ones((2, 4, 8)),
                atol=1e-4,
            )

    def test_temporal_importance(self):
        """Test temporal importance signal extraction."""
        model = TransformerForecaster(
            input_size=6,
            d_model=32,
            nhead=2,
            num_layers=2,
            forecast_horizon=3,
        )
        x = np.random.randn(2, 10, 6).astype(np.float32)
        importance = model.get_temporal_importance(x)

        # Shape: (batch_size, seq_len)
        assert importance.shape == (2, 10)
        assert np.all(importance >= 0)
        # Sum across seq_len should be ~1.0
        np.testing.assert_allclose(importance.sum(axis=-1), np.ones(2), atol=1e-5)

        # 2D input
        x_2d = np.random.randn(10, 6).astype(np.float32)
        importance_2d = model.get_temporal_importance(x_2d)
        assert importance_2d.shape == (10,)
        np.testing.assert_allclose(importance_2d.sum(), 1.0, atol=1e-5)

    def test_save_and_load_checkpoint(self):
        model = TransformerForecaster(
            input_size=6,
            d_model=32,
            nhead=2,
            num_layers=2,
            forecast_horizon=3,
            pooling_mode="last",
        )
        x = np.random.randn(2, 10, 6).astype(np.float32)
        preds_orig = model.predict_proba(x)

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = os.path.join(tmpdir, "model.pt")
            model.save(ckpt_path)

            loaded = TransformerForecaster.load(ckpt_path)
            preds_loaded = loaded.predict_proba(x)

            np.testing.assert_allclose(preds_orig, preds_loaded, atol=1e-5)
            assert loaded.pooling_mode == "last"
            assert loaded.d_model == 32
