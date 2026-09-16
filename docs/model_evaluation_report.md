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

### 4. LSTM (Long Short-Term Memory)
  LSTM is a type of recurrent neural network (RNN) that is particularly well-suited for sequence data, such as time series. In time series we learn form the past till the present time 


  at each time stamp we have feature vector suppose X† ∈ R∂ . 
  in which the feature is just a vector in a vector space in R^∂ for e.g suppose∂=3 then the feature is a vector in 3D space . but we have several feture to be extracted through the pipeline that includes : 
          - source IP: from where the request is coming from in the server
          - destination IP: to which ip / port the request is going to 
          - source port: self explainotary
          - destination port: self explanatory
          - protocol: through which protocol the request came with tcp , ftp , http(s)…
          - bytes: how many bytes of data came
          - packets: how many packets came through
          - flow duration: duration of entire data flow
          - packet/byte ratio: self explanatory
          - bidirectional flow ratio: was there a bidirectional flow of data 

          - IAT ~ Inter-Arrival-Time : the time in between the arrival of two consecutive packets.
          - IAT mean:vg time between packets
          - IAT variance:variance of time from the mean time
          - IAT maximum: maximum time between consecutive packets ~ likely a normal distro
          
          
          - TCP FLAGS :
          - TTL:TTL is a value in an IP packet that limits how many network hops the packet can travel through.
          - TTL variance : How much the TTL values vary within a traffic window.
          - TCP window size : The TCP window tells the sender approximately how much data the receiver is currently willing to accept before requiring further acknowledgements.
          - fragmentation : splitting of network packets into smaller packets to fit through a threshold. 
          - payload size: how much data is getting carried by actual packet.
          - retransmissions: sometimes a packet gets loss in the traffic so , it gets retransmitted.
          - port access pattern: suppose that one source is behaving like an anomaly and its hopping on ports randomly , that can be the best way to figure out a reconnaissance. 

  these are some features that are going to be used in feature vector for the LSTM/GNN/Transformer. 

  
---

## Conclusion

The **Isolation Forest** model (`n_estimators=200`) has been selected as the primary intelligence engine for turboSH. It achieves our architectural requirement of >70% detection rate and <5% false positive rate.

The model object has been saved to `models/best_isolationforest.pkl` and will subsequently be exported to ONNX format (`models/anomaly_model.onnx`) for high-performance inference within our Go proxy (EPIC 7).
