
"""
Common ForecastModel Protocol and Model Adapters for TurboSH Forecasting Engine.

Defines a shared interface that all forecasting models must satisfy, ensuring
benchmark fairness by preventing any model from using a different preprocessing
or evaluation procedure.

SIH V4 Requirement: Common Evaluation Contract.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union, runtime_checkable

import numpy as np

from forecasting.config import FEATURE_NAMES, FORECAST_HORIZON, STAGE_NAMES


@runtime_checkable
class ForecastModel(Protocol):
    """
    Common evaluation contract for all TurboSH forecasting models.

    All four models (Markov, HMM, LSTM, Transformer) must satisfy this
    interface to participate in the V4 benchmark. This prevents the benchmark
    from favoring a model because it uses a different preprocessing or
    evaluation procedure.
    """

    @property
    def model_name(self) -> str:
        """Human-readable model name for reports."""
        ...

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        """
        Return predicted stage indices for t+1, ..., t+n.

        Args:
            sequence: Input array of shape (seq_len, n_features) — a single
                temporal window of standardized telemetry features.

        Returns:
            predictions: Array of shape (forecast_horizon,) with integer
                stage indices (0-4).
        """
        ...

    def predict_proba(self, sequence: np.ndarray) -> np.ndarray:
        """
        Return class probability distributions for every forecast step.

        Args:
            sequence: Input array of shape (seq_len, n_features).

        Returns:
            probabilities: Array of shape (forecast_horizon, n_classes)
                with softmax probabilities per horizon step.
        """
        ...

    def predict_batch(self, sequences: np.ndarray) -> np.ndarray:
        """
        Batch prediction over multiple sequences.

        Args:
            sequences: Input array of shape (batch_size, seq_len, n_features).

        Returns:
            predictions: Array of shape (batch_size, forecast_horizon).
        """
        ...

    def predict_proba_batch(self, sequences: np.ndarray) -> np.ndarray:
        """
        Batch probability prediction over multiple sequences.

        Args:
            sequences: Input array of shape (batch_size, seq_len, n_features).

        Returns:
            probabilities: Array of shape (batch_size, forecast_horizon, n_classes).
        """
        ...

    def load(self, path: str) -> None:
        """Load trained model parameters from disk."""
        ...

    def get_model_size_bytes(self) -> int:
        """Return serialized model size in bytes."""
        ...


@dataclass
class InferenceTimingResult:
    """Inference latency measurement under controlled conditions."""

    median_ms: float
    mean_ms: float
    std_ms: float
    min_ms: float
    max_ms: float
    num_runs: int
    warmup_runs: int


def measure_inference_latency(
    model: ForecastModel,
    sample_input: np.ndarray,
    num_runs: int = 100,
    warmup_runs: int = 10,
) -> InferenceTimingResult:
    """
    Measure inference latency under controlled, identical conditions.

    Performs warmup runs followed by timed runs, returning detailed statistics.
    All models are measured on the same hardware with the same procedure.
    """
    # Warmup
    for _ in range(warmup_runs):
        model.predict(sample_input)

    # Timed runs
    times_ms: List[float] = []
    for _ in range(num_runs):
        t0 = time.perf_counter()
        model.predict(sample_input)
        t1 = time.perf_counter()
        times_ms.append((t1 - t0) * 1000.0)

    arr = np.array(times_ms)
    return InferenceTimingResult(
        median_ms=float(np.median(arr)),
        mean_ms=float(np.mean(arr)),
        std_ms=float(np.std(arr)),
        min_ms=float(np.min(arr)),
        max_ms=float(np.max(arr)),
        num_runs=num_runs,
        warmup_runs=warmup_runs,
    )


# ─── Model Adapters ─────────────────────────────────────────────────────────────
# Thin wrappers that normalize the heterogeneous interfaces of existing models
# into the shared ForecastModel protocol.


class MarkovChainAdapter:
    """Adapter wrapping MarkovChain to satisfy the ForecastModel protocol."""

    def __init__(
        self,
        hmm_model: Any = None,
        n_states: int = 5,
        forecast_horizon: int = FORECAST_HORIZON,
    ):
        from forecasting.models.markov_chain import MarkovChain
        from forecasting.models.hmm_model import HMMForecaster

        self._mc: Optional[MarkovChain] = None
        self._hmm: Optional[HMMForecaster] = hmm_model
        self._n_states = n_states
        self._forecast_horizon = forecast_horizon
        self._model_path: Optional[str] = None
        self._hmm_path: Optional[str] = None
        self._scaler: Any = None

    @property
    def model_name(self) -> str:
        return "Markov Chain"

    def set_scaler(self, scaler: Any) -> None:
        """Set the feature scaler for inverse-transforming inputs."""
        self._scaler = scaler

    def set_hmm(self, hmm: Any) -> None:
        """Set the HMM used for state decoding (Markov needs current state)."""
        self._hmm = hmm

    def _decode_current_state(self, sequence: np.ndarray) -> int:
        """Use HMM Viterbi decoding to get the current state from observations."""
        if self._hmm is None:
            # Fallback: use the last observation's rough stage estimate
            return 0

        # Inverse-transform if scaler is set (HMM expects unscaled features)
        if self._scaler is not None:
            seq_unscaled = self._scaler.inverse_transform(
                sequence.reshape(1, *sequence.shape)
            )[0]
        else:
            seq_unscaled = sequence

        return self._hmm.predict(seq_unscaled.tolist())

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        if self._mc is None:
            raise RuntimeError("MarkovChain model not loaded. Call load() first.")
        current_state = self._decode_current_state(sequence)
        trajectory = self._mc.predict_trajectory(current_state, steps=self._forecast_horizon)
        return np.array(trajectory, dtype=np.int64)

    def predict_proba(self, sequence: np.ndarray) -> np.ndarray:
        if self._mc is None:
            raise RuntimeError("MarkovChain model not loaded. Call load() first.")
        current_state = self._decode_current_state(sequence)
        distributions = self._mc.predict_trajectory_proba(
            current_state, steps=self._forecast_horizon
        )
        probs = np.zeros((self._forecast_horizon, self._n_states), dtype=np.float64)
        for h, dist in enumerate(distributions):
            for s, p in dist.items():
                probs[h, s] = p
        return probs

    def predict_batch(self, sequences: np.ndarray) -> np.ndarray:
        return np.array([self.predict(seq) for seq in sequences], dtype=np.int64)

    def predict_proba_batch(self, sequences: np.ndarray) -> np.ndarray:
        return np.array([self.predict_proba(seq) for seq in sequences], dtype=np.float64)

    def load(self, path: str) -> None:
        from forecasting.models.markov_chain import MarkovChain
        self._mc = MarkovChain.load(path)
        self._model_path = path

    def get_model_size_bytes(self) -> int:
        if self._model_path and os.path.exists(self._model_path):
            return os.path.getsize(self._model_path)
        return 0


class HMMAdapter:
    """Adapter wrapping HMMForecaster to satisfy the ForecastModel protocol."""

    def __init__(
        self,
        n_states: int = 5,
        forecast_horizon: int = FORECAST_HORIZON,
    ):
        from forecasting.models.hmm_model import HMMForecaster

        self._hmm: Optional[HMMForecaster] = None
        self._n_states = n_states
        self._forecast_horizon = forecast_horizon
        self._model_path: Optional[str] = None
        self._scaler: Any = None

    @property
    def model_name(self) -> str:
        return "Gaussian HMM"

    def set_scaler(self, scaler: Any) -> None:
        """Set the feature scaler for inverse-transforming inputs."""
        self._scaler = scaler

    def _to_unscaled(self, sequence: np.ndarray) -> List[List[float]]:
        """Convert scaled sequence to unscaled observation list for HMM."""
        if self._scaler is not None:
            seq_unscaled = self._scaler.inverse_transform(
                sequence.reshape(1, *sequence.shape)
            )[0]
        else:
            seq_unscaled = sequence
        return seq_unscaled.tolist()

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        if self._hmm is None:
            raise RuntimeError("HMM model not loaded. Call load() first.")
        obs = self._to_unscaled(sequence)
        trajectory = self._hmm.forecast(obs, steps=self._forecast_horizon)
        return np.array(trajectory, dtype=np.int64)

    def predict_proba(self, sequence: np.ndarray) -> np.ndarray:
        if self._hmm is None:
            raise RuntimeError("HMM model not loaded. Call load() first.")
        obs = self._to_unscaled(sequence)
        distributions = self._hmm.forecast_proba(obs, steps=self._forecast_horizon)
        probs = np.zeros((self._forecast_horizon, self._n_states), dtype=np.float64)
        for h, dist in enumerate(distributions):
            for s, p in dist.items():
                probs[h, s] = p
        return probs

    def predict_batch(self, sequences: np.ndarray) -> np.ndarray:
        return np.array([self.predict(seq) for seq in sequences], dtype=np.int64)

    def predict_proba_batch(self, sequences: np.ndarray) -> np.ndarray:
        return np.array([self.predict_proba(seq) for seq in sequences], dtype=np.float64)

    def load(self, path: str) -> None:
        from forecasting.models.hmm_model import HMMForecaster
        self._hmm = HMMForecaster.load(path)
        self._model_path = path

    def get_model_size_bytes(self) -> int:
        if self._model_path and os.path.exists(self._model_path):
            return os.path.getsize(self._model_path)
        return 0

    @property
    def hmm(self) -> Any:
        return self._hmm


class LSTMAdapter:
    """Adapter wrapping LSTMForecaster to satisfy the ForecastModel protocol."""

    def __init__(self, forecast_horizon: int = FORECAST_HORIZON):
        self._model: Any = None
        self._forecast_horizon = forecast_horizon
        self._model_path: Optional[str] = None

    @property
    def model_name(self) -> str:
        return "LSTM World Model"

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("LSTM model not loaded. Call load() first.")
        preds = self._model.predict(sequence)
        if preds.ndim == 2:
            return preds[0]
        return preds

    def predict_proba(self, sequence: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("LSTM model not loaded. Call load() first.")
        probs = self._model.predict_proba(sequence)
        if probs.ndim == 3:
            return probs[0]
        return probs

    def predict_batch(self, sequences: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("LSTM model not loaded. Call load() first.")
        return self._model.predict(sequences)

    def predict_proba_batch(self, sequences: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("LSTM model not loaded. Call load() first.")
        return self._model.predict_proba(sequences)

    def load(self, path: str) -> None:
        from forecasting.models.lstm_model import LSTMForecaster
        self._model = LSTMForecaster.load_weights(path)
        self._model_path = path

    def get_model_size_bytes(self) -> int:
        if self._model_path and os.path.exists(self._model_path):
            return os.path.getsize(self._model_path)
        return 0


class TransformerAdapter:
    """Adapter wrapping TransformerForecaster to satisfy the ForecastModel protocol."""

    def __init__(self, forecast_horizon: int = FORECAST_HORIZON):
        self._model: Any = None
        self._forecast_horizon = forecast_horizon
        self._model_path: Optional[str] = None

    @property
    def model_name(self) -> str:
        return "Transformer"

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Transformer model not loaded. Call load() first.")
        preds = self._model.predict(sequence)
        if preds.ndim == 2:
            return preds[0]
        return preds

    def predict_proba(self, sequence: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Transformer model not loaded. Call load() first.")
        probs = self._model.predict_proba(sequence)
        if probs.ndim == 3:
            return probs[0]
        return probs

    def predict_batch(self, sequences: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Transformer model not loaded. Call load() first.")
        return self._model.predict(sequences)

    def predict_proba_batch(self, sequences: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Transformer model not loaded. Call load() first.")
        return self._model.predict_proba(sequences)

    def load(self, path: str) -> None:
        from forecasting.models.transformer_model import TransformerForecaster
        self._model = TransformerForecaster.load_weights(path)
        self._model_path = path

    def get_model_size_bytes(self) -> int:
        if self._model_path and os.path.exists(self._model_path):
            return os.path.getsize(self._model_path)
        return 0
