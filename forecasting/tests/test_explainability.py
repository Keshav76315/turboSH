"""
Unit tests for Explainability Layer (forecasting/explainability.py).
"""

import numpy as np
import pytest
import torch

from forecasting.config import AttackStage, FEATURE_NAMES, STAGE_NAMES
from forecasting.explainability import Explainer, ForecastExplanation
from forecasting.models.lstm_model import LSTMForecaster


class TestExplainer:
    """Test suite for gradient-based feature attribution and automated reasoning."""

    @pytest.fixture
    def model(self):
        m = LSTMForecaster(
            input_size=6,
            hidden_size=32,
            num_layers=1,
            num_classes=5,
            forecast_horizon=3,
        )
        m.eval()
        return m

    def test_attribute_features(self, model):
        explainer = Explainer(model)
        x = np.random.randn(10, 6).astype(np.float32)

        attributions = explainer.attribute_features(x, horizon_step=1)
        assert len(attributions) == len(FEATURE_NAMES)
        for feat in FEATURE_NAMES:
            assert feat in attributions
            assert attributions[feat] >= 0.0

        # Sum of attributions should be normalized to ~1.0
        assert pytest.approx(sum(attributions.values()), abs=1e-4) == 1.0

    def test_explain_single_horizon(self, model):
        explainer = Explainer(model)
        x = np.random.randn(10, 6).astype(np.float32)

        exp = explainer.explain(x, horizon_step=1)
        assert isinstance(exp, ForecastExplanation)
        assert exp.horizon_step == 1
        assert exp.horizon_label == "t+1"
        assert exp.predicted_stage in STAGE_NAMES
        assert exp.stage_name == STAGE_NAMES[exp.predicted_stage]
        assert 0.0 <= exp.confidence <= 1.0
        assert len(exp.top_features) == 6
        # Check sorted descending
        for i in range(len(exp.top_features) - 1):
            assert exp.top_features[i][1] >= exp.top_features[i + 1][1]

        assert isinstance(exp.reasoning, str)
        assert len(exp.reasoning) > 0
        assert exp.stage_name in exp.reasoning

        d = exp.to_dict()
        assert "horizon_step" in d
        assert "confidence" in d
        assert "reasoning" in d
        assert "mitre_techniques" in d

    def test_explain_all_horizons(self, model):
        explainer = Explainer(model)
        x = np.random.randn(10, 6).astype(np.float32)

        explanations = explainer.explain_all(x)
        assert len(explanations) == 3
        for i, exp in enumerate(explanations):
            assert exp.horizon_step == i + 1
            assert exp.horizon_label == f"t+{i + 1}"

    def test_mitre_mapping_in_explanation(self, model):
        explainer = Explainer(model)
        x = np.random.randn(10, 6).astype(np.float32)

        # Force attribution for SURGE
        exp = explainer.explain(x, horizon_step=2)
        # Verify mitre techniques list is list of dicts
        assert isinstance(exp.mitre_techniques, list)
        if exp.predicted_stage != AttackStage.NORMAL:
            assert len(exp.mitre_techniques) > 0
            assert "technique_id" in exp.mitre_techniques[0]
            assert "name" in exp.mitre_techniques[0]
