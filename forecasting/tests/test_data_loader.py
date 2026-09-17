"""
Unit tests for data loader and feature scaling pipeline (forecasting/models/data_loader.py).
"""

import json
import os
import tempfile
from typing import List

import numpy as np
import pytest
import torch

from forecasting.config import FEATURE_NAMES, FORECAST_HORIZON
from forecasting.models.data_loader import (
    FeatureScaler,
    StateSequenceDataset,
    create_dataloaders,
)


class TestFeatureScaler:
    """Test suite for FeatureScaler standardization and JSON serialization."""

    def test_fit_and_transform_2d(self):
        data = np.array([
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            [3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        ], dtype=np.float32)
        scaler = FeatureScaler(feature_names=list(FEATURE_NAMES))
        scaler.fit(data)

        transformed = scaler.transform(data)
        assert transformed.shape == (2, 6)
        # Mean of standardized data should be ~0, std ~1
        np.testing.assert_allclose(np.mean(transformed, axis=0), np.zeros(6), atol=1e-5)
        np.testing.assert_allclose(np.std(transformed, axis=0), np.ones(6), atol=1e-5)

        # Inverse transform
        reconstructed = scaler.inverse_transform(transformed)
        np.testing.assert_allclose(reconstructed, data, atol=1e-5)

    def test_transform_3d(self):
        # Shape: (batch=2, seq_len=4, num_features=6)
        data = np.random.randn(2, 4, 6).astype(np.float32)
        scaler = FeatureScaler(feature_names=list(FEATURE_NAMES))
        scaler.fit(data)
        transformed = scaler.transform(data)
        assert transformed.shape == (2, 4, 6)

        reconstructed = scaler.inverse_transform(transformed)
        np.testing.assert_allclose(reconstructed, data, atol=1e-4)

    def test_constant_feature_avoids_division_by_zero(self):
        # Constant feature with zero variance
        data = np.ones((5, 6), dtype=np.float32)
        scaler = FeatureScaler(feature_names=list(FEATURE_NAMES))
        scaler.fit(data)
        transformed = scaler.transform(data)
        assert not np.isnan(transformed).any()
        assert not np.isinf(transformed).any()
        np.testing.assert_allclose(transformed, np.zeros((5, 6)), atol=1e-5)

    def test_unfitted_scaler_raises_error(self):
        scaler = FeatureScaler(feature_names=list(FEATURE_NAMES))
        with pytest.raises(RuntimeError):
            scaler.transform(np.ones((2, 6)))

        with pytest.raises(RuntimeError):
            scaler.to_dict()

    def test_json_save_and_load(self):
        data = np.array([
            [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            [12.0, 22.0, 32.0, 42.0, 52.0, 62.0],
        ], dtype=np.float32)
        scaler = FeatureScaler(feature_names=list(FEATURE_NAMES))
        scaler.fit(data)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "scaler.json")
            scaler.save(path)
            assert os.path.exists(path)

            loaded = FeatureScaler.load(path)
            assert loaded.feature_names == scaler.feature_names
            np.testing.assert_allclose(loaded.mean_, scaler.mean_)
            np.testing.assert_allclose(loaded.std_, scaler.std_)

            # Test transform produces identical result
            test_x = np.array([[11.0, 21.0, 31.0, 41.0, 51.0, 61.0]], dtype=np.float32)
            np.testing.assert_allclose(scaler.transform(test_x), loaded.transform(test_x))


class TestStateSequenceDataset:
    """Test sliding window extraction and PyTorch tensor generation."""

    def test_sliding_window_extraction(self):
        # 1 sequence of length 15
        T = 15
        seq_x = np.arange(T * 6, dtype=np.float32).reshape(T, 6)
        seq_y = np.array([0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 3, 2, 1, 0], dtype=np.int64)

        dataset = StateSequenceDataset(
            sequences_x=[seq_x],
            sequences_y=[seq_y],
            seq_len=10,
            forecast_horizon=3,
        )

        # Expected samples: 15 - (10 + 3) + 1 = 3 samples
        assert len(dataset) == 3

        x_0, y_0 = dataset[0]
        assert isinstance(x_0, torch.Tensor)
        assert isinstance(y_0, torch.Tensor)
        assert x_0.shape == (10, 6)
        assert y_0.shape == (3,)
        assert x_0.dtype == torch.float32
        assert y_0.dtype == torch.int64

        # Targets should match indices 10, 11, 12 of seq_y
        np.testing.assert_array_equal(y_0.numpy(), [4, 3, 2])

    def test_short_sequence_handling(self):
        # Sequence shorter than seq_len + forecast_horizon (e.g. length 8 < 13)
        short_x = np.ones((8, 6), dtype=np.float32)
        short_y = np.zeros(8, dtype=np.int64)

        dataset = StateSequenceDataset(
            sequences_x=[short_x],
            sequences_y=[short_y],
            seq_len=10,
            forecast_horizon=3,
        )
        assert len(dataset) == 0

    def test_with_scaler(self):
        seq_x = np.ones((15, 6), dtype=np.float32) * 10.0
        seq_y = np.zeros(15, dtype=np.int64)

        scaler = FeatureScaler(feature_names=list(FEATURE_NAMES))
        scaler.fit(seq_x)

        dataset = StateSequenceDataset(
            sequences_x=[seq_x],
            sequences_y=[seq_y],
            seq_len=10,
            forecast_horizon=3,
            scaler=scaler,
        )
        x_sample, _ = dataset[0]
        # Since seq_x was constant, transformed should be all 0s
        np.testing.assert_allclose(x_sample.numpy(), np.zeros((10, 6)), atol=1e-5)


class TestCreateDataLoaders:
    """Test sequence-level splitting and dataloader creation."""

    def test_create_dataloaders_from_csv(self):
        csv_path = "datasets/labeled_states.csv"
        if not os.path.exists(csv_path):
            pytest.skip(f"CSV dataset not found at {csv_path}")

        train_loader, val_loader, test_loader, scaler = create_dataloaders(
            csv_path=csv_path,
            seq_len=10,
            forecast_horizon=3,
            batch_size=16,
            train_ratio=0.7,
            val_ratio=0.15,
            test_ratio=0.15,
            random_seed=42,
        )

        assert scaler.mean_ is not None
        assert scaler.std_ is not None
        assert len(train_loader) > 0
        assert len(val_loader) > 0
        assert len(test_loader) > 0

        # Verify a single batch from train_loader
        x_batch, y_batch = next(iter(train_loader))
        assert x_batch.shape == (16, 10, 6)
        assert y_batch.shape == (16, 3)
        assert not torch.isnan(x_batch).any()
