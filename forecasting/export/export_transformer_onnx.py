"""
ONNX Model Exporter and Runtime Validation for TurboSH Transformer Forecaster.

Same export pattern as export_lstm_onnx.py:
- Exports PyTorch TransformerForecaster to ONNX with dynamic batch/seq axes.
- Validates numerical parity between PyTorch and ONNX Runtime.
"""

import argparse
import os
import sys
from typing import Optional, Tuple

import numpy as np
import onnx
import onnxruntime as ort
import torch

from forecasting.models.transformer_model import TransformerForecaster


def export_transformer_to_onnx(
    model: TransformerForecaster,
    output_path: str,
    seq_len: int = 10,
    batch_size: int = 1,
    opset_version: int = 17,
) -> str:
    """
    Export PyTorch TransformerForecaster to an ONNX model file with dynamic axes.

    Args:
        model: Trained TransformerForecaster instance.
        output_path: Destination path for the .onnx file.
        seq_len: Default sequence length for dummy trace.
        batch_size: Default batch size for dummy trace.
        opset_version: ONNX operator set version (default 17).

    Returns:
        Absolute path to exported ONNX model.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    was_training = model.training
    model.eval()

    try:
        device = next(model.parameters()).device
        dummy_input = torch.randn(
            batch_size, seq_len, model.input_size, dtype=torch.float32, device=device
        )

        export_kwargs: dict = {
            "export_params": True,
            "opset_version": opset_version,
            "do_constant_folding": True,
            "input_names": ["input"],
            "output_names": ["output"],
            "dynamic_axes": {
                "input": {0: "batch_size", 1: "seq_len"},
                "output": {0: "batch_size"},
            },
        }
        import inspect
        if "dynamo" in inspect.signature(torch.onnx.export).parameters:
            export_kwargs["dynamo"] = False

        torch.onnx.export(
            model,
            dummy_input,
            output_path,
            **export_kwargs,
        )

        # Validate ONNX model graph structure
        onnx_model = onnx.load(output_path)
        onnx.checker.check_model(onnx_model)
    finally:
        model.train(was_training)

    return os.path.abspath(output_path)


def validate_onnx_parity(
    model: TransformerForecaster,
    onnx_path: str,
    seq_len: int = 10,
    batch_size: int = 2,
    atol: float = 1e-4,
) -> Tuple[bool, float]:
    """
    Verify numerical parity between PyTorch forward pass and ONNX Runtime.

    Returns:
        Tuple of (is_parity_verified: bool, max_absolute_difference: float)
    """
    was_training = model.training
    model.eval()

    try:
        test_input = np.random.randn(batch_size, seq_len, model.input_size).astype(np.float32)

        # PyTorch inference
        with torch.no_grad():
            device = next(model.parameters()).device
            pt_tensor = torch.from_numpy(test_input).to(device)
            pt_output = model(pt_tensor).cpu().numpy()

        # ONNX Runtime inference
        session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name
        ort_output = session.run([output_name], {input_name: test_input})[0]

        max_diff = float(np.max(np.abs(pt_output - ort_output)))
        is_valid = max_diff < atol

        return is_valid, max_diff
    finally:
        model.train(was_training)


def main():
    parser = argparse.ArgumentParser(
        description="Export TurboSH Transformer Forecaster to ONNX format."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="models/forecasting/transformer_model.pt",
        help="Path to trained PyTorch weights (.pt)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="models/forecasting/forecast_transformer.onnx",
        help="Path for exported ONNX model (.onnx)",
    )
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--seq-len", type=int, default=10)

    args = parser.parse_args()

    if not os.path.exists(args.model):
        print(f"Error: Model checkpoint not found at: {args.model}")
        sys.exit(1)

    print(f"Loading Transformer model from {args.model}...")
    model = TransformerForecaster.load_weights(args.model)

    print(f"Exporting to ONNX at {args.output} (opset {args.opset})...")
    export_path = export_transformer_to_onnx(
        model=model,
        output_path=args.output,
        seq_len=args.seq_len,
        opset_version=args.opset,
    )
    print(f"Exported successfully to: {export_path}")

    print("Verifying numerical parity against ONNX Runtime...")
    is_valid, max_diff = validate_onnx_parity(model, args.output, seq_len=args.seq_len)
    if is_valid:
        print(f"Numerical parity VERIFIED (Max absolute diff: {max_diff:.6e})")
    else:
        print(f"Warning: Discrepancy detected (Max absolute diff: {max_diff:.6e})")
        sys.exit(1)


if __name__ == "__main__":
    main()
