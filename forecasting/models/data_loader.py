"""
Data loading and preprocessing pipeline for TurboSH Temporal Intelligence (LSTM).

Provides:
- FeatureScaler: Standardization scaler with JSON serialization for Go/C++ runtime interop.
- StateSequenceDataset: PyTorch Dataset generating sliding windows and multi-step targets.
- create_dataloaders: Sequence-level train/val/test splits preventing cross-window leakage.
"""

from dataclasses import dataclass
import json
import os
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset

from forecasting.config import FEATURE_NAMES, FORECAST_HORIZON


class FeatureScaler:
    """
    Z-score feature standardizer (X - mu) / sigma with JSON serialization.
    Designed for zero-dependency serialization and cross-language runtime serving.
    """

    def __init__(
        self,
        feature_names: Optional[List[str]] = None,
        eps: float = 1e-8,
    ):
        self.feature_names: List[str] = feature_names or list(FEATURE_NAMES)
        self.eps: float = eps
        self.mean_: Optional[np.ndarray] = None
        self.std_: Optional[np.ndarray] = None

    def fit(self, X: Union[np.ndarray, List[List[float]]]) -> "FeatureScaler":
        """
        Compute feature means and standard deviations from a 2D array of shape (N, num_features).
        """
        arr = np.asarray(X, dtype=np.float32)
        if arr.ndim == 3:
            # If shape is (num_sequences, seq_len, num_features), flatten over batch and time
            arr = arr.reshape(-1, arr.shape[-1])
        elif arr.ndim != 2:
            raise ValueError(f"Expected 2D or 3D array for fit(), got shape {arr.shape}")

        if arr.shape[1] != len(self.feature_names):
            raise ValueError(
                f"Feature count mismatch: expected {len(self.feature_names)}, got {arr.shape[1]}"
            )

        self.mean_ = np.mean(arr, axis=0)
        self.std_ = np.std(arr, axis=0)
        # Avoid division by zero
        self.std_ = np.where(self.std_ < self.eps, 1.0, self.std_)
        return self

    def transform(self, X: Union[np.ndarray, List[List[float]]]) -> np.ndarray:
        """
        Apply standardization to 2D (N, D) or 3D (B, L, D) data.
        """
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("FeatureScaler must be fitted before calling transform()")

        arr = np.asarray(X, dtype=np.float32)
        if arr.ndim == 2:
            return (arr - self.mean_) / self.std_
        elif arr.ndim == 3:
            # Broadcasting over (B, L, D)
            return (arr - self.mean_) / self.std_
        else:
            raise ValueError(f"Expected 2D or 3D array for transform(), got shape {arr.shape}")

    def fit_transform(self, X: Union[np.ndarray, List[List[float]]]) -> np.ndarray:
        """Fit scaler and transform input in one step."""
        return self.fit(X).transform(X)

    def inverse_transform(self, X: Union[np.ndarray, List[List[float]]]) -> np.ndarray:
        """Reverse standardization (X * sigma + mu)."""
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("FeatureScaler must be fitted before calling inverse_transform()")

        arr = np.asarray(X, dtype=np.float32)
        return (arr * self.std_) + self.mean_

    def to_dict(self) -> Dict[str, Any]:
        """Serialize scaler parameters to dictionary."""
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("Cannot serialize unfitted FeatureScaler")
        return {
            "feature_names": self.feature_names,
            "means": self.mean_.tolist(),
            "stds": self.std_.tolist(),
            "eps": self.eps,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeatureScaler":
        """Deserialize scaler parameters from dictionary."""
        scaler = cls(
            feature_names=data.get("feature_names", list(FEATURE_NAMES)),
            eps=data.get("eps", 1e-8),
        )
        scaler.mean_ = np.array(data["means"], dtype=np.float32)
        scaler.std_ = np.array(data["stds"], dtype=np.float32)
        return scaler

    def save(self, filepath: str) -> None:
        """Save scaler parameters to a JSON file."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath: str) -> "FeatureScaler":
        """Load scaler parameters from a JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


class StateSequenceDataset(Dataset):
    """
    PyTorch Dataset providing sliding temporal windows of state telemetry.

    Each item returns:
      - x: torch.FloatTensor of shape (seq_len, n_features)
      - y: torch.LongTensor of shape (forecast_horizon,) representing stages [t+1, t+2, t+3]
    """

    def __init__(
        self,
        sequences_x: Optional[List[np.ndarray]] = None,
        sequences_y: Optional[List[np.ndarray]] = None,
        seq_len: int = 10,
        forecast_horizon: int = FORECAST_HORIZON,
        scaler: Optional[FeatureScaler] = None,
        windows_x: Optional[np.ndarray] = None,
        windows_y: Optional[np.ndarray] = None,
    ):
        self.seq_len = seq_len
        self.forecast_horizon = forecast_horizon
        self.scaler = scaler

        if windows_x is not None and windows_y is not None:
            self.samples_x = np.asarray(windows_x, dtype=np.float32)
            self.samples_y = np.asarray(windows_y, dtype=np.int64)
        elif sequences_x is not None and sequences_y is not None:
            self.samples_x, self.samples_y = self._extract_sliding_windows(
                sequences_x, sequences_y
            )
        else:
            self.samples_x = np.empty((0, seq_len, len(FEATURE_NAMES)), dtype=np.float32)
            self.samples_y = np.empty((0, forecast_horizon), dtype=np.int64)

        if self.scaler is not None and len(self.samples_x) > 0:
            self.samples_x = self.scaler.transform(self.samples_x)

    def _extract_sliding_windows(
        self,
        sequences_x: List[np.ndarray],
        sequences_y: List[np.ndarray],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Extract multi-step sliding windows across independent sequences."""
        all_x: List[np.ndarray] = []
        all_y: List[np.ndarray] = []

        for x_seq, y_seq in zip(sequences_x, sequences_y):
            T = len(x_seq)
            total_window = self.seq_len + self.forecast_horizon
            if T < total_window:
                continue

            for i in range(T - total_window + 1):
                window_x = x_seq[i : i + self.seq_len]
                window_y = y_seq[i + self.seq_len : i + total_window]
                all_x.append(window_x)
                all_y.append(window_y)

        if not all_x:
            n_feat = sequences_x[0].shape[-1] if sequences_x and len(sequences_x[0]) > 0 else len(FEATURE_NAMES)
            return (
                np.empty((0, self.seq_len, n_feat), dtype=np.float32),
                np.empty((0, self.forecast_horizon), dtype=np.int64),
            )

        return (
            np.asarray(all_x, dtype=np.float32),
            np.asarray(all_y, dtype=np.int64),
        )

    def __len__(self) -> int:
        return len(self.samples_x)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        x_tensor = torch.from_numpy(self.samples_x[idx])
        y_tensor = torch.from_numpy(self.samples_y[idx]).long()
        return x_tensor, y_tensor


def create_dataloaders(
    csv_path: str,
    seq_len: int = 10,
    forecast_horizon: int = FORECAST_HORIZON,
    batch_size: int = 32,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    random_seed: int = 42,
    scaler: Optional[FeatureScaler] = None,
) -> Tuple[DataLoader, DataLoader, DataLoader, FeatureScaler]:
    """
    Load dataset from CSV, split strictly at sequence boundary, fit FeatureScaler
    only on training data, and return PyTorch DataLoaders.

    Returns:
        (train_loader, val_loader, test_loader, fitted_scaler)
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Dataset CSV not found at: {csv_path}")

    df = pd.read_csv(csv_path)
    required_cols = ["sequence_id", "step", "stage_label"] + FEATURE_NAMES
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column '{col}' in CSV {csv_path}")

    # Group rows by sequence_id, sorted by step
    sequences_x: List[np.ndarray] = []
    sequences_y: List[np.ndarray] = []
    sequence_ids: List[int] = []

    grouped = df.sort_values(by=["sequence_id", "step"]).groupby("sequence_id")
    for seq_id, group in grouped:
        x_seq = group[FEATURE_NAMES].to_numpy(dtype=np.float32)
        y_seq = group["stage_label"].to_numpy(dtype=np.int64)
        sequences_x.append(x_seq)
        sequences_y.append(y_seq)
        sequence_ids.append(seq_id)

    num_sequences = len(sequence_ids)
    if num_sequences == 0:
        raise ValueError("Dataset contains no sequences")

    # Sequence-level train/val/test splitting
    rng = random.Random(random_seed)
    indices = list(range(num_sequences))
    rng.shuffle(indices)

    n_train = max(1, int(num_sequences * train_ratio))
    n_val = max(1, int(num_sequences * val_ratio)) if val_ratio > 0 else 0
    # Ensure train + val does not exceed total
    if n_train + n_val >= num_sequences:
        n_val = max(0, num_sequences - n_train)

    train_indices = indices[:n_train]
    val_indices = indices[n_train : n_train + n_val]
    test_indices = indices[n_train + n_val :]

    if not test_indices and val_indices:
        # If test set empty due to small count, borrow one from val or train
        if len(val_indices) > 1:
            test_indices = [val_indices.pop()]

    train_x = [sequences_x[i] for i in train_indices]
    train_y = [sequences_y[i] for i in train_indices]

    val_x = [sequences_x[i] for i in val_indices]
    val_y = [sequences_y[i] for i in val_indices]

    test_x = [sequences_x[i] for i in test_indices]
    test_y = [sequences_y[i] for i in test_indices]

    # Fit FeatureScaler exclusively on training sequences
    if scaler is None:
        all_train_features = np.concatenate(train_x, axis=0) if train_x else np.empty((0, len(FEATURE_NAMES)))
        scaler = FeatureScaler(feature_names=list(FEATURE_NAMES))
        scaler.fit(all_train_features)

    # Instantiate datasets
    train_dataset = StateSequenceDataset(
        sequences_x=train_x,
        sequences_y=train_y,
        seq_len=seq_len,
        forecast_horizon=forecast_horizon,
        scaler=scaler,
    )
    val_dataset = StateSequenceDataset(
        sequences_x=val_x,
        sequences_y=val_y,
        seq_len=seq_len,
        forecast_horizon=forecast_horizon,
        scaler=scaler,
    )
    test_dataset = StateSequenceDataset(
        sequences_x=test_x,
        sequences_y=test_y,
        seq_len=seq_len,
        forecast_horizon=forecast_horizon,
        scaler=scaler,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        drop_last=False,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        drop_last=False,
    )
    test_loader = DataLoader(
        test_dataset,
        batch_size=batch_size,
        shuffle=False,
        drop_last=False,
    )

    return train_loader, val_loader, test_loader, scaler
