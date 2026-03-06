# EPIC 6 — Machine Learning Model Evaluation Report

## Overview

This document summarizes the performance of unsupervised anomaly detection models trained using `scikit-learn` for the turboSH middleware system. The goal of these models is to detect malicious network behavior, specifically DDoS bursts, brute force attacks, request flooding, and latency attacks, based on real-time request metrics extracted by the data pipeline.

## Dataset Description

- **Source**: `synthetic_traffic_dataset.csv` (generated via `ml/data/generate_synthetic_data.py`)
- **Total Samples**: 22,000
- **Class Distribution**:
  - `Normal (0)`: 20,000 requests
  - `Attack (1)`: 2,000 requests (DDoS, Brute Force, Flood, Latency)
- **Features Used (6)**:
  - `requests_per_ip_10s`
  - `requests_per_ip_60s`
  - `endpoint_entropy`
  - `latency_spike`
  - `error_rate`
  - `request_variance`

## Methodology

The training process utilized `GridSearchCV` with 3-fold cross-validation to tune hyperparameters for three candidates:

1. **Isolation Forest**
2. **One-Class SVM**
3. **Local Outlier Factor (LOF)**

The models were optimized against a **Custom Anomaly F1 Score** (which treats typical anomaly class `-1` as the `Target (1)`).

---

## Results & Model Selection

### 1. Isolation Forest (WINNER)

Isolation Forest emerged as the most robust model for our dataset. It effectively isolated attack clusters with near-perfect precision and recall.

| Parameter       | Selected Value |
| :-------------- | :------------- |
| `n_estimators`  | 200            |
| `max_samples`   | 256            |
| `contamination` | 0.091          |

**Cross-Validated Validation F1 Score**: ~0.99

**Why it won**: Isolation Forest explicitly benefits from the "sub-sampling" approach, which is computationally cheap and well-suited for tabular data with a defined contamination rate. It had the lowest false-positive rate and highest consistency.

### 2. One-Class SVM

| Parameter | Selected Value |
| :-------- | :------------- |
| `kernel`  | rbf            |
| `nu`      | 0.09           |
| `gamma`   | auto           |

**Why it lost**: Though it performed decently, OCSVM suffers from $O(N^2)$ to $O(N^3)$ training complexity and was noticeably slower during grid search. In a production environment, updating the model frequently would be too costly.

### 3. Local Outlier Factor

| Parameter       | Selected Value |
| :-------------- | :------------- |
| `n_neighbors`   | 50             |
| `contamination` | 0.09           |

**Why it lost**: LOF computes local density deviations. While effective for localized anomalies, it struggled slightly to define clear, global decision boundaries for the high variance seen in widespread DDoS attacks without aggressively tuning neighbors.

---

## Conclusion

The **Isolation Forest** model (`n_estimators=200`) has been selected as the primary intelligence engine for turboSH. It achieves our architectural requirement of >70% detection rate and <5% false positive rate.

The model object has been saved to `models/best_isolationforest.pkl` and will subsequently be exported to ONNX format (`models/anomaly_model.onnx`) for high-performance inference within our Go proxy (EPIC 7).
