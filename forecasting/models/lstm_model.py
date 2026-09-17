"""
LSTM World Model for TurboSH Forecasting Engine (Temporal Intelligence).

Provides:
- LSTMForecaster: 2-layer stacked LSTM network with multi-step horizon projection head (t+1, t+2, t+3).
- Probabilistic and confidence-annotated multi-step inference.
- Checkpoint serialization and PyTorch weight restoration.
"""

from dataclasses import dataclass
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from forecasting.config import AttackStage, FEATURE_NAMES, FORECAST_HORIZON, STAGE_NAMES


@dataclass
class StepForecast:
    """Structured prediction for an individual future horizon step."""

    horizon_step: int  # 1, 2, or 3
    stage: int  # 0 to 4 (AttackStage)
    stage_name: str
    confidence: float
    probabilities: List[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_step": self.horizon_step,
            "stage": self.stage,
            "stage_name": self.stage_name,
            "confidence": round(float(self.confidence), 4),
            "probabilities": [round(float(p), 4) for p in self.probabilities],
        }


class LSTMForecaster(nn.Module):
    """
    Temporal sequence forecaster using stacked LSTM with multi-horizon output head.

    Architecture:
      Input (batch, seq_len, input_size=6)
        -> LSTM(input_size=6, hidden_size=128, num_layers=2, batch_first=True, dropout=0.3)
        -> Last hidden state: h_T (batch, 128)
        -> Linear(128, 64) -> ReLU() -> Dropout(0.3)
        -> Linear(64, forecast_horizon * num_classes)
        -> Reshape (batch, forecast_horizon=3, num_classes=5)
    """

    def __init__(
        self,
        input_size: int = len(FEATURE_NAMES),
        hidden_size: int = 128,
        num_layers: int = 2,
        num_classes: int = len(STAGE_NAMES),
        forecast_horizon: int = FORECAST_HORIZON,
        dropout: float = 0.3,
    ):
        super().__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.num_classes = num_classes
        self.forecast_horizon = forecast_horizon
        self.dropout_rate = dropout

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
        )

        self.head = nn.Linear(64, forecast_horizon * num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.
        Args:
            x: Tensor of shape (batch_size, seq_len, input_size)
        Returns:
            logits: Tensor of shape (batch_size, forecast_horizon, num_classes)
        """
        batch_size = x.size(0)
        lstm_out, _ = self.lstm(x)
        # Extract last time step representation: shape (batch_size, hidden_size)
        h_t = lstm_out[:, -1, :]

        feat = self.fc(h_t)
        logits_flat = self.head(feat)
        logits = logits_flat.view(batch_size, self.forecast_horizon, self.num_classes)
        return logits

    def predict_proba(
        self,
        x: Union[torch.Tensor, np.ndarray],
    ) -> np.ndarray:
        """
        Compute predicted class probability distributions for all horizon steps.
        Args:
            x: Input of shape (batch_size, seq_len, input_size) or (seq_len, input_size)
        Returns:
            probs: Numpy array of shape (batch_size, forecast_horizon, num_classes)
        """
        self.eval()
        squeeze_batch = False

        if isinstance(x, np.ndarray):
            if x.ndim == 2:
                x = np.expand_dims(x, axis=0)
                squeeze_batch = True
            tensor_x = torch.from_numpy(x).float()
        else:
            if x.ndim == 2:
                tensor_x = x.unsqueeze(0).float()
                squeeze_batch = True
            else:
                tensor_x = x.float()

        device = next(self.parameters()).device
        tensor_x = tensor_x.to(device)

        with torch.no_grad():
            logits = self.forward(tensor_x)
            probs = F.softmax(logits, dim=-1).cpu().numpy()

        if squeeze_batch:
            return probs[0]
        return probs

    def predict(
        self,
        x: Union[torch.Tensor, np.ndarray],
    ) -> np.ndarray:
        """
        Compute discrete stage predictions across all horizon steps.
        Args:
            x: Input of shape (batch_size, seq_len, input_size) or (seq_len, input_size)
        Returns:
            preds: Numpy array of shape (batch_size, forecast_horizon) or (forecast_horizon,)
        """
        probs = self.predict_proba(x)
        return np.argmax(probs, axis=-1)

    def predict_with_confidence(
        self,
        x: Union[torch.Tensor, np.ndarray],
    ) -> List[List[StepForecast]]:
        """
        Produce human-readable step forecasts with confidence scores and probability distributions.
        Returns:
            List of lists of StepForecast (one list per batch item).
        """
        probs = self.predict_proba(x)
        if probs.ndim == 2:
            probs = np.expand_dims(probs, axis=0)

        batch_results: List[List[StepForecast]] = []
        for b in range(probs.shape[0]):
            steps: List[StepForecast] = []
            for h in range(self.forecast_horizon):
                p_h = probs[b, h]
                best_stage = int(np.argmax(p_h))
                conf = float(p_h[best_stage])
                steps.append(
                    StepForecast(
                        horizon_step=h + 1,
                        stage=best_stage,
                        stage_name=STAGE_NAMES.get(best_stage, f"STAGE_{best_stage}"),
                        confidence=conf,
                        probabilities=p_h.tolist(),
                    )
                )
            batch_results.append(steps)

        return batch_results

    def save_weights(self, filepath: str) -> None:
        """Save model architecture parameters and weights to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        checkpoint = {
            "config": {
                "input_size": self.input_size,
                "hidden_size": self.hidden_size,
                "num_layers": self.num_layers,
                "num_classes": self.num_classes,
                "forecast_horizon": self.forecast_horizon,
                "dropout": self.dropout_rate,
            },
            "state_dict": self.state_dict(),
        }
        torch.save(checkpoint, filepath)

    @classmethod
    def load_weights(
        cls,
        filepath: str,
        map_location: Optional[str] = "cpu",
    ) -> "LSTMForecaster":
        """Load model architecture and weights from disk."""
        checkpoint = torch.load(filepath, map_location=map_location, weights_only=True)
        config = checkpoint.get("config", {})
        model = cls(**config)
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        return model
