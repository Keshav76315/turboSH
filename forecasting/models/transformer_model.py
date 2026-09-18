"""
Transformer World Model for TurboSH Forecasting Engine (Model Competition V4).

Provides:
- TransformerForecaster: Multi-head self-attention temporal forecaster with
  custom encoder layers that reliably expose per-layer, per-head attention
  weights for explainability.
- PositionalEncoding: Sinusoidal positional encoding for temporal ordering.
- Configurable pooling strategy: "last" (final timestep) or "avg" (global average).

IMPORTANT: Attention weights returned by get_attention_weights() should be treated
as interpretability signals, NOT definitive causal explanations. They indicate
which input positions the model attends to, but do not necessarily represent
true feature importance or causal reasoning.
"""

from dataclasses import dataclass
import math
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from forecasting.config import AttackStage, FEATURE_NAMES, FORECAST_HORIZON, STAGE_NAMES
from forecasting.models.lstm_model import StepForecast


class PositionalEncoding(nn.Module):
    """
    Sinusoidal positional encoding for temporal ordering.

    Injects position information into the input embeddings using fixed
    sinusoidal functions (Vaswani et al. 2017). This allows the Transformer
    to understand temporal ordering without recurrence.
    """

    def __init__(self, d_model: int, max_len: int = 500, dropout: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term[: d_model // 2 + d_model % 2])
        pe = pe.unsqueeze(0)  # (1, max_len, d_model)
        self.register_buffer("pe", pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Tensor of shape (batch_size, seq_len, d_model)
        Returns:
            Tensor of same shape with positional encoding added.
        """
        x = x + self.pe[:, : x.size(1), :]
        return self.dropout(x)


class CustomMultiHeadAttention(nn.Module):
    """
    Custom multi-head attention that reliably stores and returns attention weights.

    Standard PyTorch TransformerEncoder does not reliably expose attention weights
    through a simple get_attention_weights() method. This custom implementation
    stores attention weights per forward pass for later retrieval.

    NOTE: Attention weights are interpretability signals, not definitive causal
    explanations. They show which positions the model attends to during inference.
    """

    def __init__(self, d_model: int, nhead: int, dropout: float = 0.1):
        super().__init__()
        assert d_model % nhead == 0, f"d_model ({d_model}) must be divisible by nhead ({nhead})"

        self.d_model = d_model
        self.nhead = nhead
        self.d_k = d_model // nhead

        self.W_q = nn.Linear(d_model, d_model)
        self.W_k = nn.Linear(d_model, d_model)
        self.W_v = nn.Linear(d_model, d_model)
        self.W_o = nn.Linear(d_model, d_model)

        self.attn_dropout = nn.Dropout(p=dropout)
        self.last_attention_weights: Optional[torch.Tensor] = None

    def forward(
        self,
        query: torch.Tensor,
        key: torch.Tensor,
        value: torch.Tensor,
        mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Args:
            query, key, value: (batch_size, seq_len, d_model)
            mask: Optional attention mask.

        Returns:
            output: (batch_size, seq_len, d_model)

        Side effect:
            Stores attention weights in self.last_attention_weights
            Shape: (batch_size, nhead, seq_len, seq_len)
        """
        batch_size = query.size(0)

        # Project and reshape: (batch, seq, d_model) → (batch, nhead, seq, d_k)
        Q = self.W_q(query).view(batch_size, -1, self.nhead, self.d_k).transpose(1, 2)
        K = self.W_k(key).view(batch_size, -1, self.nhead, self.d_k).transpose(1, 2)
        V = self.W_v(value).view(batch_size, -1, self.nhead, self.d_k).transpose(1, 2)

        # Scaled dot-product attention
        scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(self.d_k)

        if mask is not None:
            # Use dtype-safe large negative value to prevent NaN in half-precision or all-masked rows
            fill_val = -1e4 if scores.dtype == torch.float16 else -1e9
            scores = scores.masked_fill(mask == 0, fill_val)

        attn_weights = F.softmax(scores, dim=-1)  # (batch, nhead, seq, seq)
        self.last_attention_weights = attn_weights.detach()

        attn_weights = self.attn_dropout(attn_weights)
        context = torch.matmul(attn_weights, V)  # (batch, nhead, seq, d_k)

        # Reshape back: (batch, nhead, seq, d_k) → (batch, seq, d_model)
        context = context.transpose(1, 2).contiguous().view(batch_size, -1, self.d_model)
        output = self.W_o(context)

        return output


class CustomTransformerEncoderLayer(nn.Module):
    """
    Custom Transformer encoder layer with attention weight exposure.

    Pre-norm architecture (LayerNorm before attention/FFN) for more stable
    training. Stores attention weights for explainability access.
    """

    def __init__(
        self,
        d_model: int,
        nhead: int,
        dim_feedforward: int = 256,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.self_attn = CustomMultiHeadAttention(d_model, nhead, dropout)

        self.ffn = nn.Sequential(
            nn.Linear(d_model, dim_feedforward),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(dim_feedforward, d_model),
            nn.Dropout(dropout),
        )

        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        """
        Args:
            x: (batch_size, seq_len, d_model)
        Returns:
            (batch_size, seq_len, d_model)
        """
        # Pre-norm self-attention with residual connection
        normed = self.norm1(x)
        attn_out = self.self_attn(normed, normed, normed, mask=mask)
        x = x + self.dropout(attn_out)

        # Pre-norm FFN with residual connection
        normed = self.norm2(x)
        ffn_out = self.ffn(normed)
        x = x + ffn_out

        return x

    def get_attention_weights(self) -> Optional[torch.Tensor]:
        """Return stored attention weights from last forward pass. Shape: (batch, nhead, seq, seq)."""
        return self.self_attn.last_attention_weights


class TransformerForecaster(nn.Module):
    """
    Temporal sequence forecaster using self-attention with custom encoder layers.

    Architecture:
      Input (batch, seq_len, input_size=6)
        → Linear(6, d_model=128) projection
        → PositionalEncoding (sinusoidal)
        → CustomTransformerEncoder(3 layers, 4 heads, dim_ff=256, dropout=0.1)
            ↳ Each layer stores attention weights: (batch, nhead, seq_len, seq_len)
        → Pooling: configurable "last" (final timestep) or "avg" (global average)
        → Dense(d_model, 64) → ReLU → Dropout
        → Dense(64, forecast_horizon * num_classes)
        → Reshape (batch, forecast_horizon=3, num_classes=5)

    Pooling Strategy:
        "last" (default): Uses the final timestep representation. Better for
            sequential future-state prediction from historical observations.
        "avg": Global average pooling over the temporal dimension. Useful when
            the entire sequence context is equally important.

    Attention Weight Caveat:
        Attention weights returned by get_attention_weights() are interpretability
        signals, NOT definitive causal explanations. They show relative attention
        patterns but should not be over-interpreted as feature importance.
    """

    def __init__(
        self,
        input_size: int = len(FEATURE_NAMES),
        d_model: int = 128,
        nhead: int = 4,
        num_layers: int = 3,
        dim_feedforward: int = 256,
        num_classes: int = len(STAGE_NAMES),
        forecast_horizon: int = FORECAST_HORIZON,
        dropout: float = 0.1,
        pooling: str = "last",
        pooling_mode: Optional[str] = None,
    ):
        super().__init__()
        self.input_size = input_size
        self.d_model = d_model
        self.nhead = nhead
        self.num_layers = num_layers
        self.dim_feedforward = dim_feedforward
        self.num_classes = num_classes
        self.forecast_horizon = forecast_horizon
        self.dropout_rate = dropout

        effective_pooling = pooling_mode if pooling_mode is not None else pooling
        if effective_pooling in ("avg", "mean"):
            effective_pooling = "avg"
        elif effective_pooling != "last":
            raise ValueError(f"pooling must be 'last', 'avg', or 'mean', got '{effective_pooling}'")
        self.pooling = effective_pooling

        # Input projection: (batch, seq_len, 6) → (batch, seq_len, d_model)
        self.input_projection = nn.Linear(input_size, d_model)

        # Positional encoding
        self.pos_encoder = PositionalEncoding(d_model, dropout=dropout)

        # Custom Transformer encoder layers with attention weight exposure
        self.encoder_layers = nn.ModuleList([
            CustomTransformerEncoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
            )
            for _ in range(num_layers)
        ])

        # Final layer norm (post-encoder normalization)
        self.final_norm = nn.LayerNorm(d_model)

        # Projection head: pooled representation → multi-step forecasts
        self.fc = nn.Sequential(
            nn.Linear(d_model, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.head = nn.Linear(64, forecast_horizon * num_classes)

    @property
    def pooling_mode(self) -> str:
        return self.pooling

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.

        Args:
            x: Tensor of shape (batch_size, seq_len, input_size)
        Returns:
            logits: Tensor of shape (batch_size, forecast_horizon, num_classes)
        """
        batch_size = x.size(0)

        # Project input features to d_model dimension
        x = self.input_projection(x)  # (batch, seq, d_model)

        # Add positional encoding
        x = self.pos_encoder(x)

        # Pass through custom encoder layers
        for layer in self.encoder_layers:
            x = layer(x)

        # Final normalization
        x = self.final_norm(x)

        # Pooling strategy
        if self.pooling == "last":
            pooled = x[:, -1, :]  # (batch, d_model)
        else:  # "avg"
            pooled = x.mean(dim=1)  # (batch, d_model)

        # Projection head
        feat = self.fc(pooled)
        logits_flat = self.head(feat)
        logits = logits_flat.view(batch_size, self.forecast_horizon, self.num_classes)
        return logits

    def get_attention_weights(
        self,
        x: Union[torch.Tensor, np.ndarray],
    ) -> List[torch.Tensor]:
        """
        Extract attention weights from all encoder layers for explainability.

        IMPORTANT: These weights are interpretability signals, NOT definitive
        causal explanations. They indicate which input positions the model
        attends to, but do not necessarily represent true feature importance.

        Args:
            x: Input of shape (seq_len, input_size) or (batch, seq_len, input_size)

        Returns:
            List of attention weight tensors, one per layer.
            Each has shape (batch, nhead, seq_len, seq_len).
        """
        self.eval()

        if isinstance(x, np.ndarray):
            if x.ndim == 2:
                x = np.expand_dims(x, axis=0)
            x = torch.from_numpy(x).float()
        elif x.ndim == 2:
            x = x.unsqueeze(0).float()
        else:
            x = x.float()

        device = next(self.parameters()).device
        x = x.to(device)

        with torch.no_grad():
            # Run forward pass to populate attention weights
            self.forward(x)

        # Collect stored attention weights from each layer
        weights = []
        for layer in self.encoder_layers:
            w = layer.get_attention_weights()
            if w is not None:
                weights.append(w)

        return weights

    def get_temporal_importance(
        self,
        x: Union[torch.Tensor, np.ndarray],
    ) -> np.ndarray:
        """
        Extract temporal importance signal over input sequence positions.

        Computed by averaging attention weights across all encoder layers and heads.
        If pooling is 'last', examines attention paid by the final query step.
        If pooling is 'avg', examines average attention paid across all query steps.

        IMPORTANT: Attention weights should be treated as interpretability signals,
        NOT definitive causal explanations.

        Args:
            x: Input of shape (batch, seq_len, input_size) or (seq_len, input_size)

        Returns:
            Numpy array of shape (batch, seq_len) or (seq_len,) normalized to sum to 1.0.
        """
        is_2d = (isinstance(x, np.ndarray) and x.ndim == 2) or (isinstance(x, torch.Tensor) and x.ndim == 2)
        weights = self.get_attention_weights(x)
        if not weights:
            seq_len = x.shape[1] if not is_2d else x.shape[0]
            batch_size = x.shape[0] if not is_2d else 1
            res = np.ones((batch_size, seq_len), dtype=np.float32) / seq_len
            return res[0] if is_2d else res

        # weights is a list of (batch, nhead, seq_len, seq_len)
        stacked = torch.stack(weights, dim=0)  # (layers, batch, nhead, seq, seq)
        mean_layers = stacked.mean(dim=0)      # (batch, nhead, seq, seq)
        mean_heads = mean_layers.mean(dim=1)   # (batch, seq, seq)

        if self.pooling == "last":
            importance = mean_heads[:, -1, :]  # (batch, seq_len)
        else:
            importance = mean_heads.mean(dim=1)  # (batch, seq_len)

        sum_val = importance.sum(dim=-1, keepdim=True) + 1e-9
        normalized = (importance / sum_val).detach().cpu().numpy()

        if is_2d:
            return normalized[0]
        return normalized

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
                   or (forecast_horizon, num_classes) if single sample.
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

    def forecast(
        self,
        x: Union[torch.Tensor, np.ndarray],
    ) -> Union[List[StepForecast], List[List[StepForecast]]]:
        """
        Convenience wrapper returning structured StepForecast objects.
        Returns a single List[StepForecast] for 2D inputs, or List[List[StepForecast]] for 3D inputs.
        """
        is_2d = (isinstance(x, np.ndarray) and x.ndim == 2) or (isinstance(x, torch.Tensor) and x.ndim == 2)
        batch_results = self.predict_with_confidence(x)
        if is_2d and batch_results:
            return batch_results[0]
        return batch_results

    def save_weights(self, filepath: str) -> None:
        """Save model architecture parameters and weights to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        checkpoint = {
            "config": {
                "input_size": self.input_size,
                "d_model": self.d_model,
                "nhead": self.nhead,
                "num_layers": self.num_layers,
                "dim_feedforward": self.dim_feedforward,
                "num_classes": self.num_classes,
                "forecast_horizon": self.forecast_horizon,
                "dropout": self.dropout_rate,
                "pooling": self.pooling,
            },
            "state_dict": self.state_dict(),
        }
        torch.save(checkpoint, filepath)

    save = save_weights

    @classmethod
    def load_weights(
        cls,
        filepath: str,
        map_location: Optional[str] = "cpu",
    ) -> "TransformerForecaster":
        """Load model architecture and weights from disk."""
        checkpoint = torch.load(filepath, map_location=map_location, weights_only=True)
        config = checkpoint.get("config", {})
        model = cls(**config)
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        return model

    load = load_weights
