import argparse
import glob
import joblib
import os
import onnx
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

# Default paths
DEFAULT_ONNX_OUTPUT_PATH = "models/anomaly_model.onnx"


def find_latest_model():
    """Auto-discover the most recently trained model in models/best_*.pkl."""
    candidates = glob.glob("models/best_*.pkl")
    if not candidates:
        return None
    # Pick the most recently modified file
    latest = max(candidates, key=os.path.getmtime)
    return latest


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export a trained scikit-learn anomaly model to ONNX format."
    )
    parser.add_argument(
        "--model-path",
        default=None,
        help=(
            "Path to the trained .pkl model file. "
            "If not specified, auto-discovers the most recently trained model "
            "from models/best_*.pkl."
        ),
    )
    parser.add_argument(
        "--output-path",
        default=DEFAULT_ONNX_OUTPUT_PATH,
        help=f"Output path for the ONNX model (default: {DEFAULT_ONNX_OUTPUT_PATH})",
    )
    return parser.parse_args()


def export_model(model_path, output_path):
    print(f"Loading scikit-learn model from {model_path}...")
    if not os.path.exists(model_path):
        print(f"Error: Model file {model_path} not found.")
        return

    model = joblib.load(model_path)
    model_type = type(model).__name__
    print(f"Detected model type: {model_type}")

    # Define the input type and shape for the ONNX model.
    # Our data pipeline outputs 6 features of type float32.
    # The shape is (None, 6) where None allows for batch processing.
    initial_type = [("float_input", FloatTensorType([None, 6]))]

    print("Converting model to ONNX format...")
    # Convert the sklearn model to an ONNX protobuf representation
    onnx_model = convert_sklearn(
        model, initial_types=initial_type, target_opset={"": 12, "ai.onnx.ml": 3}
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Save the ONNX model to disk
    with open(output_path, "wb") as f:
        f.write(onnx_model.SerializeToString())

    print(f"[OK] {model_type} model successfully exported to {output_path}!")


if __name__ == "__main__":
    args = parse_args()

    model_path = args.model_path
    if model_path is None:
        model_path = find_latest_model()
        if model_path is None:
            print(
                "Error: No trained model found. Run train_model.py first, "
                "or specify --model-path explicitly."
            )
            exit(1)
        print(f"Auto-discovered model: {model_path}")

    export_model(model_path, args.output_path)
