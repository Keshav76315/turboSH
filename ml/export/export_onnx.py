import joblib
import os
import onnx
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

# Define paths
MODEL_PATH = "models/best_isolationforest.pkl"
ONNX_OUTPUT_PATH = "models/anomaly_model.onnx"


def export_model():
    print(f"Loading scikit-learn model from {MODEL_PATH}...")
    if not os.path.exists(MODEL_PATH):
        print(f"Error: Model file {MODEL_PATH} not found.")
        return

    model = joblib.load(MODEL_PATH)

    # Define the input type and shape for the ONNX model.
    # Our data pipeline outputs 6 features of type float32.
    # The shape is (None, 6) where None allows for batch processing.
    initial_type = [("float_input", FloatTensorType([None, 6]))]

    print("Converting model to ONNX format...")
    # Convert the sklearn model to an ONNX protobuf representation
    onnx_model = convert_sklearn(
        model, initial_types=initial_type, target_opset={"": 12, "ai.onnx.ml": 3}
    )

    os.makedirs(os.path.dirname(ONNX_OUTPUT_PATH), exist_ok=True)

    # Save the ONNX model to disk
    with open(ONNX_OUTPUT_PATH, "wb") as f:
        f.write(onnx_model.SerializeToString())

    print(f"✅ Model successfully exported to {ONNX_OUTPUT_PATH}!")


if __name__ == "__main__":
    export_model()
