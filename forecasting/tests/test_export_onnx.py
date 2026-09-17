"""
Unit tests for ONNX export and runtime numerical parity (forecasting/export/export_lstm_onnx.py).
"""

import os
import tempfile
import numpy as np
import pytest
import torch

from forecasting.export.export_lstm_onnx import export_lstm_to_onnx, validate_onnx_parity
from forecasting.models.lstm_model import LSTMForecaster


class TestONNXExport:
    """Test suite for ONNX export, checker validation, and runtime inference parity."""

    @pytest.fixture
    def model(self):
        m = LSTMForecaster(
            input_size=6,
            hidden_size=32,
            num_layers=2,
            num_classes=5,
            forecast_horizon=3,
        )
        m.eval()
        return m

    def test_export_and_parity_validation(self, model):
        with tempfile.TemporaryDirectory() as tmpdir:
            onnx_path = os.path.join(tmpdir, "test_model.onnx")

            exported_path = export_lstm_to_onnx(
                model=model,
                output_path=onnx_path,
                seq_len=10,
                batch_size=1,
            )
            assert os.path.exists(exported_path)

            # Validate numerical parity
            is_valid, max_diff = validate_onnx_parity(
                model=model,
                onnx_path=exported_path,
                seq_len=10,
                batch_size=2,
                atol=1e-4,
            )
            assert is_valid
            assert max_diff < 1e-4

    def test_dynamic_axes_support(self, model):
        import onnxruntime as ort

        with tempfile.TemporaryDirectory() as tmpdir:
            onnx_path = os.path.join(tmpdir, "test_dynamic.onnx")
            export_lstm_to_onnx(model=model, output_path=onnx_path, seq_len=10)

            session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
            input_name = session.get_inputs()[0].name
            output_name = session.get_outputs()[0].name

            # Test different batch sizes and sequence lengths
            for b, l in [(1, 10), (3, 10), (5, 12)]:
                test_input = np.random.randn(b, l, 6).astype(np.float32)
                output = session.run([output_name], {input_name: test_input})[0]
                assert output.shape == (b, 3, 5)

    def test_training_mode_preserved_during_export_and_validation(self, model):
        model.train()  # Explicitly start in training mode

        with tempfile.TemporaryDirectory() as tmpdir:
            onnx_path = os.path.join(tmpdir, "test_mode.onnx")

            export_lstm_to_onnx(model=model, output_path=onnx_path, seq_len=10)
            assert model.training is True, "export_lstm_to_onnx must preserve model.training state"

            validate_onnx_parity(model=model, onnx_path=onnx_path, seq_len=10)
            assert model.training is True, "validate_onnx_parity must preserve model.training state"
