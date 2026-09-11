# Customizing the turboSH ML Model

This guide explains how to generate a custom synthetic dataset, tune machine learning hyperparameters, train an anomaly detection model, and export it to ONNX for real-time in-process inference within the turboSH Go proxy.

---

## 1. Generating a Custom Dataset

The default model relies on a synthetic traffic dataset that simulates baseline normal browsing alongside common network attacks (DDoS bursts, brute force login attempts, request flooding, and latency spikes).

The generator script (`ml/data/generate_synthetic_data.py`) includes command-line argument support via `argparse`:

```bash
python3 ml/data/generate_synthetic_data.py --help
```

### CLI Options

| Argument | Shorthand | Default | Description |
| :--- | :---: | :--- | :--- |
| `--output` | `-o` | `datasets/synthetic_traffic_dataset.csv` | Output file path |
| `--num-normal` | | `20000` | Number of normal browsing samples |
| `--num-attack` | | `2000` | Number of attack samples (split evenly across attack profiles) |

### Example Execution

To generate a custom dataset with 30,000 normal records and 3,000 attack records:

```bash
python3 ml/data/generate_synthetic_data.py --output datasets/synthetic_traffic_dataset.csv --num-normal 30000 --num-attack 3000
```

> **Feature Invariant:** The generator outputs 6 normalized features where `endpoint_entropy` is strictly bounded in $[0.0, 1.0]$ matching the Go feature extractor in `core/inference/features.go`.

---

## 2. Tuning Model Hyperparameters

The training script (`ml/training/train_model.py`) uses `GridSearchCV` with 3-fold cross-validation to search across hyperparameter grids for **Isolation Forest**, **One-Class SVM**, and **Local Outlier Factor**.

You can adjust the search space directly in `ml/training/train_model.py`:

```python
models = {
    'IsolationForest': {
        'estimator': IsolationForest(random_state=42, n_jobs=-1),
        'params': {
            'n_estimators': [100, 200, 500],             # Number of decision trees
            'contamination': ['auto', 0.05, 0.091, 0.15], # Expected anomaly ratio
            'max_samples': ['auto', 256, 512]             # Sub-sampling size per tree
        }
    },
    ...
}
```

### Parameter Recommendations

- **`n_estimators` (Isolation Forest):** 200 trees provides an optimal balance between validation F1 score (~0.983) and in-process ONNX inference latency ($<1\text{ ms}$).
- **`contamination`:** Should roughly match your attack ratio (e.g., $3000 / 33000 \approx 0.091$). Explicit ratios perform substantially better than `'auto'`.
- **`max_samples`:** Setting `256` prevents overfitting on large datasets and keeps decision trees shallow and fast.

---

## 3. Training the Model

Run the training script within your virtual environment:

```bash
python3 ml/training/train_model.py
```

The script will:
1. Load `datasets/synthetic_traffic_dataset.csv`
2. Run cross-validated grid search across candidate algorithms
3. Select the best estimator based on custom anomaly F1 score
4. Save the trained model to `models/best_isolationforest.pkl`

---

## 4. Exporting to ONNX Format

The turboSH Go middleware runs ONNX models directly in-process via CGO (`yalue/onnxruntime_go`) without calling Python. You must convert the trained `.pkl` file into an `.onnx` model.

Run the exporter:

```bash
python3 ml/export/export_onnx.py
```

This exports the model to `models/anomaly_model.onnx` with a 6-dimensional float32 input tensor (`[batch_size, 6]`).

---

## 5. Validating & Loading in turboSH

Once `models/anomaly_model.onnx` is placed in `models/`, restart turboSH:

```bash
# Verify detection accuracy on the new model
go run cmd/accuracy_test/main.go

# Or run the live proxy
go run cmd/turbosh/main.go
```

The middleware will automatically load the new ONNX model at startup and begin scoring incoming traffic with continuous anomaly values in $[0.0, 1.0]$.
