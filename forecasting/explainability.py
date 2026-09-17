"""
Explainability Layer for TurboSH Forecasting Engine (SIH Requirement §13.5).

Provides:
- Gradient-based feature attribution (Input x Gradient saliency mapping).
- ForecastExplanation: Diagnostic dataclass linking top features, confidence, and MITRE ATT&CK.
- Explainer: Diagnostic attribution engine for deep sequence models.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import torch

from forecasting.config import AttackStage, FEATURE_NAMES, FORECAST_HORIZON, STAGE_NAMES
from forecasting.mitre_mapping import MITRETechnique, map_stage_to_techniques
from forecasting.models.data_loader import FeatureScaler
from forecasting.models.lstm_model import LSTMForecaster


@dataclass
class ForecastExplanation:
    """Diagnostic breakdown of a forecasted attack stage."""

    horizon_step: int  # 1, 2, or 3
    horizon_label: str  # "t+1", "t+2", "t+3"
    predicted_stage: int
    stage_name: str
    confidence: float
    top_features: List[Tuple[str, float]]  # [("requests_per_ip_10s", 0.442), ...]
    feature_attributions: Dict[str, float]  # Full map of all feature attribution ratios
    mitre_techniques: List[Dict[str, str]]
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_step": self.horizon_step,
            "horizon_label": self.horizon_label,
            "predicted_stage": self.predicted_stage,
            "stage_name": self.stage_name,
            "confidence": round(float(self.confidence), 4),
            "top_features": [
                (feat, round(float(val), 4)) for feat, val in self.top_features
            ],
            "feature_attributions": {
                feat: round(float(val), 4)
                for feat, val in self.feature_attributions.items()
            },
            "mitre_techniques": self.mitre_techniques,
            "reasoning": self.reasoning,
        }


class Explainer:
    """
    Diagnostic explanation engine for TurboSH LSTM Forecaster.

    Uses native PyTorch autograd Input x Gradient saliency mapping to compute
    exact feature attributions across the temporal window in <2ms with zero
    heavy external dependencies.
    """

    def __init__(
        self,
        model: LSTMForecaster,
        feature_names: Optional[List[str]] = None,
        scaler: Optional[FeatureScaler] = None,
    ):
        self.model = model
        self.feature_names: List[str] = feature_names or list(FEATURE_NAMES)
        self.scaler = scaler

    def attribute_features(
        self,
        input_seq: Union[torch.Tensor, np.ndarray],
        horizon_step: int = 1,
        target_class: Optional[int] = None,
    ) -> Dict[str, float]:
        """
        Compute Input x Gradient feature attribution for a specified forecast horizon step.

        Args:
            input_seq: Array of shape (seq_len, num_features) or (1, seq_len, num_features)
            horizon_step: 1-indexed horizon step (1 for t+1, 2 for t+2, etc.)
            target_class: Optional target class index. Defaults to model's predicted class.

        Returns:
            Dictionary mapping feature names to normalized attribution fractions (summing to 1.0).
        """
        if horizon_step < 1 or horizon_step > self.model.forecast_horizon:
            raise ValueError(
                f"horizon_step must be between 1 and {self.model.forecast_horizon}, got {horizon_step}"
            )

        h_idx = horizon_step - 1

        # Format input tensor with requires_grad=True
        if isinstance(input_seq, np.ndarray):
            arr = np.copy(input_seq)
            if arr.ndim == 2:
                arr = np.expand_dims(arr, axis=0)
            tensor_x = torch.from_numpy(arr).float()
        else:
            tensor_x = input_seq.clone().float()
            if tensor_x.ndim == 2:
                tensor_x = tensor_x.unsqueeze(0)

        device = next(self.model.parameters()).device
        tensor_x = tensor_x.to(device)
        tensor_x.requires_grad_(True)

        was_training = self.model.training
        self.model.eval()

        try:
            # Disable cuDNN optimization during backward in eval mode to avoid RNN backward error
            with torch.backends.cudnn.flags(enabled=False):
                logits = self.model(tensor_x)  # Shape: (1, forecast_horizon, num_classes)

                if target_class is None:
                    target_class = int(torch.argmax(logits[0, h_idx]).item())

                target_score = logits[0, h_idx, target_class]
                grads = torch.autograd.grad(
                    target_score,
                    tensor_x,
                    retain_graph=False,
                    create_graph=False,
                )
                grad = grads[0].detach()  # Shape: (1, seq_len, num_features)
        finally:
            self.model.train(was_training)

        # Input x Gradient saliency magnitude
        saliency = torch.abs(tensor_x.detach() * grad)

        # Sum saliency over temporal window (dim=1)
        feature_importance = torch.sum(saliency[0], dim=0).cpu().numpy()

        total = float(np.sum(feature_importance))
        if total > 1e-12:
            normalized = feature_importance / total
        else:
            normalized = np.ones_like(feature_importance) / len(feature_importance)

        if len(self.feature_names) != len(normalized):
            raise ValueError(
                f"Feature count mismatch: {len(self.feature_names)} feature names provided, "
                f"but model produced attributions for {len(normalized)} features"
            )

        return {
            name: float(score)
            for name, score in zip(self.feature_names, normalized)
        }

    def generate_reasoning(
        self,
        stage: int,
        stage_name: str,
        confidence: float,
        top_features: List[Tuple[str, float]],
        mitre_techniques: List[MITRETechnique],
        horizon_step: int = 1,
    ) -> str:
        """Construct natural language explanation linking features, threat taxonomy, and MITRE."""
        top_strs = [
            f"{feat} ({val * 100:.1f}% attribution)" for feat, val in top_features[:2]
        ]
        drivers_text = ", ".join(top_strs) if top_strs else "nominal features"

        if stage == AttackStage.NORMAL:
            return (
                f"Predicted NORMAL at t+{horizon_step} ({confidence * 100:.1f}% confidence). "
                f"Network telemetry parameters remain within baseline operating bounds "
                f"({drivers_text}). No active threat signature detected."
            )

        # Adversarial or attack stage
        if mitre_techniques:
            primary_mitre = mitre_techniques[0]
            mitre_info = f"Maps to MITRE ATT&CK {primary_mitre.technique_id} ({primary_mitre.name}) [{primary_mitre.severity} Severity] — {primary_mitre.description}"
        else:
            mitre_info = "No specific MITRE technique associated."

        return (
            f"Predicted {stage_name} at t+{horizon_step} with {confidence * 100:.1f}% confidence. "
            f"Primary telemetry drivers: {drivers_text}. {mitre_info}"
        )

    def explain(
        self,
        input_seq: Union[torch.Tensor, np.ndarray],
        horizon_step: int = 1,
    ) -> ForecastExplanation:
        """
        Produce a comprehensive diagnostic explanation for a specific future horizon step.
        """
        if horizon_step < 1 or horizon_step > self.model.forecast_horizon:
            raise ValueError(
                f"horizon_step must be between 1 and {self.model.forecast_horizon}, got {horizon_step}"
            )

        h_idx = horizon_step - 1

        # Step 1: Model inference
        probs = self.model.predict_proba(input_seq)
        if probs.ndim == 3:
            step_probs = probs[0, h_idx]
        else:
            step_probs = probs[h_idx]

        predicted_stage = int(np.argmax(step_probs))
        confidence = float(step_probs[predicted_stage])
        stage_name = STAGE_NAMES.get(predicted_stage, f"STAGE_{predicted_stage}")

        # Step 2: Feature attribution
        attributions = self.attribute_features(
            input_seq,
            horizon_step=horizon_step,
            target_class=predicted_stage,
        )

        sorted_features = sorted(
            attributions.items(), key=lambda item: item[1], reverse=True
        )

        # Step 3: MITRE ATT&CK mapping
        mitre_techs = map_stage_to_techniques(predicted_stage)
        mitre_dicts = [t.to_dict() for t in mitre_techs]

        # Step 4: Automated natural language reasoning
        reasoning = self.generate_reasoning(
            stage=predicted_stage,
            stage_name=stage_name,
            confidence=confidence,
            top_features=sorted_features,
            mitre_techniques=mitre_techs,
            horizon_step=horizon_step,
        )

        return ForecastExplanation(
            horizon_step=horizon_step,
            horizon_label=f"t+{horizon_step}",
            predicted_stage=predicted_stage,
            stage_name=stage_name,
            confidence=confidence,
            top_features=sorted_features,
            feature_attributions=attributions,
            mitre_techniques=mitre_dicts,
            reasoning=reasoning,
        )

    def explain_all(
        self,
        input_seq: Union[torch.Tensor, np.ndarray],
    ) -> List[ForecastExplanation]:
        """Generate explanations for all future horizon steps (t+1, t+2, t+3)."""
        return [
            self.explain(input_seq, horizon_step=h)
            for h in range(1, self.model.forecast_horizon + 1)
        ]
