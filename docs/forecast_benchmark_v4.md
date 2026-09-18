# TurboSH V4 — Model Competition Benchmark Report

**Generated**: 2026-09-18 06:49:21 UTC  
**Benchmark Duration**: 0.89 seconds  
**Evaluation Mode**: Independent Multi-Horizon Test Set  
**Production Selection**: **Markov Chain**  

---

## 1. Benchmark Configuration

- **Dataset**: `datasets/labeled_states.csv`
- **Random seed**: 42
- **Sequence length**: 10
- **Forecast horizon**: 3 steps (t+1, t+2, t+3)
- **Train/Val/Test split**: 70/15/15 (sequence-level, temporal ordering preserved)
- **Scaler**: Z-score fitted on training set only

### Class Distribution (Test Set, t+1)

| Stage | Count | Fraction |
|:------|:------|:---------|
| NORMAL | 167 | 23.0% |
| RECON | 98 | 13.5% |
| ESCALATION | 104 | 14.3% |
| SURGE | 174 | 24.0% |
| SUSTAINED | 183 | 25.2% |

---

## 2. Comparative Benchmark

| Model | t+1 Acc | t+2 Acc | t+3 Acc | Macro F1 (t+1) | Lead Time | Coverage | Latency (ms) | Size (KB) | Score |
|:------|:--------|:--------|:--------|:---------------|:----------|:---------|:-------------|:----------|:------|
| **Markov Chain** 🏆 | 66.25% | 50.00% | 46.01% | 0.6481 | 167.0s | 91.7% | 0.168 | 0.8 | 0.7991 |
| **Gaussian HMM** | 66.25% | 50.00% | 46.01% | 0.6481 | 167.0s | 91.7% | 0.175 | 2.6 | 0.7989 |
| **LSTM World Model** | 64.33% | 46.83% | 44.35% | 0.6233 | 167.5s | 91.7% | 0.238 | 827.2 | 0.7857 |
| **Transformer** | 64.19% | 47.80% | 41.87% | 0.6277 | 167.0s | 91.7% | 0.510 | 1864.0 | 0.7810 |

---

## 3. Detailed Stage Metrics (t+1)

### Markov Chain

| Stage | Precision | Recall | F1 | Support |
|:------|:----------|:-------|:---|:--------|
| NORMAL | 0.8225 | 0.8323 | 0.8274 | 167 |
| RECON | 0.6042 | 0.5918 | 0.5979 | 98 |
| ESCALATION | 0.5327 | 0.5481 | 0.5403 | 104 |
| SURGE | 0.5954 | 0.5920 | 0.5937 | 174 |
| SUSTAINED | 0.6851 | 0.6776 | 0.6813 | 183 |

### Gaussian HMM

| Stage | Precision | Recall | F1 | Support |
|:------|:----------|:-------|:---|:--------|
| NORMAL | 0.8225 | 0.8323 | 0.8274 | 167 |
| RECON | 0.6042 | 0.5918 | 0.5979 | 98 |
| ESCALATION | 0.5327 | 0.5481 | 0.5403 | 104 |
| SURGE | 0.5954 | 0.5920 | 0.5937 | 174 |
| SUSTAINED | 0.6851 | 0.6776 | 0.6813 | 183 |

### LSTM World Model

| Stage | Precision | Recall | F1 | Support |
|:------|:----------|:-------|:---|:--------|
| NORMAL | 0.7952 | 0.7904 | 0.7928 | 167 |
| RECON | 0.5435 | 0.5102 | 0.5263 | 98 |
| ESCALATION | 0.5135 | 0.5481 | 0.5302 | 104 |
| SURGE | 0.6184 | 0.5402 | 0.5767 | 174 |
| SUSTAINED | 0.6537 | 0.7322 | 0.6907 | 183 |

### Transformer

| Stage | Precision | Recall | F1 | Support |
|:------|:----------|:-------|:---|:--------|
| NORMAL | 0.8278 | 0.7485 | 0.7862 | 167 |
| RECON | 0.5268 | 0.6020 | 0.5619 | 98 |
| ESCALATION | 0.5413 | 0.5673 | 0.5540 | 104 |
| SURGE | 0.6204 | 0.4885 | 0.5466 | 174 |
| SUSTAINED | 0.6359 | 0.7541 | 0.6900 | 183 |

---

## 4. Lead-Time & False Alarm Analysis

| Model | Mean Lead Time | Median Lead Time | Detection Coverage | False Alarm Rate | Passes FPR Gate |
|:------|:---------------|:-----------------|:-------------------|:-----------------|:----------------|
| Markov Chain | 167.0s | 195.0s | 91.7% | 10.3% | ✅ |
| Gaussian HMM | 167.0s | 195.0s | 91.7% | 10.3% | ✅ |
| LSTM World Model | 167.5s | 195.0s | 91.7% | 10.6% | ✅ |
| Transformer | 167.0s | 195.0s | 91.7% | 10.3% | ✅ |

---

## 5. Production Selection

### Selection Criteria (Predefined)

1. Minimum macro F1 ≥ 0.45
2. Maximum false-positive rate ≤ 30%
3. Maximum inference latency ≤ 5.0ms
4. Compare composite operational score (accuracy, F1, lead time, latency, coverage)

### Results

- **Markov Chain**: ✅ QUALIFIES
  - Composite score: 0.7991
- **Gaussian HMM**: ✅ QUALIFIES
  - Composite score: 0.7989
- **LSTM World Model**: ✅ QUALIFIES
  - Composite score: 0.7857
- **Transformer**: ✅ QUALIFIES
  - Composite score: 0.7810

### 🏆 Selected Production Model: **Markov Chain**

The **Markov Chain** achieved the highest composite operational score among all qualifying candidates and is recommended for ONNX export and production deployment in the Go reverse proxy.


