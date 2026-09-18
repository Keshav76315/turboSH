"""
Unit tests for train_transformer.py (forecasting/train_transformer.py).
"""

import os
import tempfile
import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader, TensorDataset

from forecasting.config import FEATURE_NAMES, FORECAST_HORIZON, STAGE_NAMES
from forecasting.models.transformer_model import TransformerForecaster
from forecasting.train_transformer import set_seed, train_transformer_forecaster


class TestTrainTransformer:
    """Test suite for Transformer training pipeline and reproducibility."""

    def test_reproducibility_with_seed(self):
        set_seed(123)
        w1 = torch.randn(10, 10)
        set_seed(123)
        w2 = torch.randn(10, 10)
        np.testing.assert_allclose(w1.numpy(), w2.numpy())

    def test_train_transformer_forecaster_loop(self):
        # Create synthetic dataset: 16 sequences of length 10 with 6 features
        x_data = torch.randn(16, 10, 6)
        # Target: horizon 3 with classes 0..4
        y_data = torch.randint(0, 5, (16, 3))

        dataset = TensorDataset(x_data, y_data)
        train_loader = DataLoader(dataset, batch_size=4)
        val_loader = DataLoader(dataset, batch_size=4)

        model, history = train_transformer_forecaster(
            train_loader=train_loader,
            val_loader=val_loader,
            input_size=6,
            d_model=16,
            nhead=2,
            num_layers=1,
            dim_feedforward=32,
            epochs=2,
            lr=0.01,
            patience=2,
            pooling="last",
            device=torch.device("cpu"),
        )

        assert isinstance(model, TransformerForecaster)
        assert len(history["train_loss"]) == 2
        assert len(history["val_loss"]) == 2
        assert len(history["val_acc_t1"]) == 2
        assert all(isinstance(v, float) for v in history["train_loss"])
