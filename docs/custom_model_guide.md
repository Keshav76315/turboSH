# Customizing the turboSH ML Model

This guide explains how to generate a custom synthetic dataset, tweak machine learning hyperparameters, and train your own customized anomaly detection model for the turboSH middleware.

## 1. Generating a Custom Dataset

The default model relies on a synthetic traffic dataset that simulates baseline normal traffic and common attacks like DDoS, request floods, and brute force attempts.

To change the volume or characteristics of the data, open `ml/data/generate_synthetic_data.py`:

- Modify `NUM_NORMAL` and `NUM_ATTACK` to change dataset size.
- Tweak the `generate_*` functions to simulate different attack intensities (e.g. increase the base `error_rate` for brute force attempts, or change the `requests_per_ip_60s` threshold for floods).

Run the generator:

```bash
python3 ml/data/generate_synthetic_data.py
```

This will recreate `datasets/synthetic_traffic_dataset.csv`.

## 2. Tuning Model Hyperparameters

By default, the training script uses `GridSearchCV` to find the best configuration for an **Isolation Forest** model (among others). You can customize this search space in `ml/training/train_model.py`.

Look for the `models` dictionary:

```python
models = {
    'IsolationForest': {
        'estimator': IsolationForest(random_state=42, n_jobs=-1),
        'params': {
            'n_estimators': [100, 200, 500], # Add or change tree counts here
            'contamination': ['auto', 0.05, 0.09, 0.15], # Adjust the expected anomaly ratio
            'max_samples': ['auto', 256, 512] # Adjust max samples per tree
        }
    },
    ...
}
```

### Parameter Recommendations:

- **`n_estimators` (Isolation Forest)**: Increasing this beyond 200 may slightly improve detection precision at the cost of marginally slower ONNX inference speeds in the proxy. Start with `100` or `200`.
- **`contamination`**: This should roughly match the ratio of attacks in your generated dataset. For example, if you generate `2000` attacks and `20000` normal requests, the contamination is `~0.091`. Explicitly setting this often yields better boundaries than `'auto'`.
- **`max_samples`**: Limiting this (e.g. `256`) speeds up training and forces the trees to learn simpler, more robust rules, avoiding overfitting on massive datasets.

## 3. Training the Model

Run the modified training script. It will run a full grid search using 3-fold cross validation.

```bash
python3 ml/training/train_model.py
```

The script will automatically grab the best configuration and save the raw `scikit-learn` model to `models/best_isolationforest.pkl`.

## 4. Exporting to ONNX

The turboSH core proxy (written in Go) does not run Python. It uses ONNX Runtime. You must export your `.pkl` model into an `.onnx` file.

Run the export script:

```bash
python3 ml/export/export_onnx.py
```

This will generate `models/anomaly_model.onnx`.

## 5. Restarting the Proxy

Once `models/anomaly_model.onnx` is generated, restart the turboSH Go application. The decision engine will automatically load the new ONNX model and begin applying your custom rules to incoming traffic.
