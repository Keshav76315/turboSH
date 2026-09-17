# TurboSH V3 — Temporal Intelligence Benchmark Report

**Generated**: 2026-09-17 18:46:55 UTC  
**Architecture**: 2-Layer Stacked LSTM + Multi-Horizon Dense Head  
**Training Duration**: 15.22 seconds  
**Evaluation Mode**: Independent Multi-Horizon Test Set (726 samples)  

---

## 1. Executive Summary & SIH Alignment

TurboSH Version 3 upgrades the predictive engine to **deep temporal intelligence** using PyTorch LSTM networks. Unlike memoryless Markov Chains and emission-limited Gaussian HMMs, the LSTM model captures protracted non-linear temporal dependencies across multi-step sliding windows ($L = 100\text{s}$) and produces direct multi-step horizon forecasts ($t+1, t+2, t+3$) in a single $<1\text{ms}$ forward pass.

### Key Milestones & Initial Benchmark Observations:
- **Initial Benchmark Status**: In this initial V3 benchmark on synthetic telemetry, the LSTM serves as a baseline deep architecture. It currently underperforms the Markov Chain and Gaussian HMM baselines across all three horizons.
- **t+1 Accuracy Gap**: LSTM 64.33% vs HMM 66.25% (Gap: -1.92%), Markov: 66.25% (Gap: -1.92%)
- **t+2 Accuracy Gap**: LSTM 46.83% vs HMM 50.00% (Gap: -3.17%), Markov: 50.00% (Gap: -3.17%)
- **t+3 Accuracy Gap**: LSTM 44.35% vs HMM 46.01% (Gap: -1.66%), Markov: 46.01% (Gap: -1.66%)
- **Early Warning Lead Time**: **12.5 seconds** advance notice before full DDoS volumetric saturation (HMM: 12.3s, Markov: 12.3s).
- **Explainability Engine**: Gradient-based feature attribution ($<2\text{ms}$) with automated MITRE ATT&CK mapping.
- **Production Export**: Fully validated ONNX model ready for sub-millisecond Go reverse proxy inference.

---

## 2. Comparative Benchmark (Markov vs HMM vs LSTM)

| Architecture | Model Family | t+1 Accuracy | t+2 Accuracy | t+3 Accuracy | Macro F1 (t+1) | Mean Lead Time | Inference Latency |
|:-------------|:-------------|:-------------|:-------------|:-------------|:---------------|:---------------|:-------------------|
| **Markov Chain** | Discrete Probabilistic | **66.25%** | **50.00%** | **46.01%** | **0.6481** | 12.3s | < 0.05ms |
| **Gaussian HMM** | Generative State-Space | **66.25%** | **50.00%** | **46.01%** | **0.6481** | 12.3s | ~0.80ms |
| **LSTM World Model (Initial)** | Deep Recurrent Neural Net | 64.33% | 46.83% | 44.35% | 0.6233 | **12.5s** | **~0.35ms (ONNX)** |

> **Benchmark Note:** In this initial V3 benchmark, the baseline Markov Chain and Gaussian HMM achieve higher classification accuracy across all three forecast horizons. The LSTM model represents an initial deep temporal baseline prior to hyperparameter tuning, sequence augmentation, and graph topology integration (planned in V4/V5).

---

## 3. LSTM Multi-Step Horizon Degradation

| Horizon Step | Target Offset | Accuracy | Macro Precision | Macro Recall | Macro F1 |
|:-------------|:--------------|:---------|:----------------|:-------------|:---------|
| **t+1** | +10s ahead | 64.33% | 0.6249 | 0.6242 | 0.6233 |
| **t+2** | +20s ahead | 46.83% | 0.4261 | 0.4277 | 0.4108 |
| **t+3** | +30s ahead | 44.35% | 0.3965 | 0.3826 | 0.3579 |

---

## 4. Detailed Stage Metrics (LSTM at t+1)

| Stage ID | Threat Stage | Precision | Recall | F1 Score | Test Support |
|:---------|:-------------|:----------|:-------|:---------|:-------------|
| **0** | `NORMAL` | 0.7952 | 0.7904 | 0.7928 | 167 |
| **1** | `RECON` | 0.5435 | 0.5102 | 0.5263 | 98 |
| **2** | `ESCALATION` | 0.5135 | 0.5481 | 0.5302 | 104 |
| **3** | `SURGE` | 0.6184 | 0.5402 | 0.5767 | 174 |
| **4** | `SUSTAINED` | 0.6537 | 0.7322 | 0.6907 | 183 |

### Confusion Matrix (t+1)
Rows: Ground Truth Stage, Columns: Predicted Stage

| True \ Pred | NORMAL (0) | RECON (1) | ESCALATION (2) | SURGE (3) | SUSTAINED (4) |
|:------------|:-----------|:----------|:---------------|:----------|:--------------|
| **NORMAL (0)** | 132 | 16 | 5 | 2 | 12 |
| **RECON (1)** | 21 | 50 | 16 | 5 | 6 |
| **ESCALATION (2)** | 13 | 20 | 57 | 8 | 6 |
| **SURGE (3)** | 0 | 6 | 27 | 94 | 47 |
| **SUSTAINED (4)** | 0 | 0 | 6 | 43 | 134 |

---

## 5. Explainability Layer & MITRE ATT&CK Mapping Case Studies

The diagnostic engine utilizes native autograd Input x Gradient saliency mapping to compute exact feature attribution percentages across the 6 network telemetry dimensions.

### Scenario 1: Predicted `RECON` at t+1
- **Confidence**: `47.3%`
- **Primary Drivers**: `latency_spike` (38.3%), `error_rate` (19.7%), `endpoint_entropy` (13.8%)
- **MITRE ATT&CK Mapping**: `T1595` (Active Scanning), `T1046` (Network Service Discovery), `T1592` (Gather Victim Host Information)
- **Automated Security Reasoning**: *"Predicted RECON at t+1 with 47.3% confidence. Primary telemetry drivers: latency_spike (38.3% attribution), error_rate (19.7% attribution). Maps to MITRE ATT&CK T1595 (Active Scanning) [MEDIUM Severity] — Adversaries scan public IP blocks and endpoints to gather vulnerability or routing information."*

### Scenario 2: Predicted `RECON` at t+1
- **Confidence**: `48.8%`
- **Primary Drivers**: `latency_spike` (26.9%), `error_rate` (20.8%), `requests_per_ip_10s` (16.7%)
- **MITRE ATT&CK Mapping**: `T1595` (Active Scanning), `T1046` (Network Service Discovery), `T1592` (Gather Victim Host Information)
- **Automated Security Reasoning**: *"Predicted RECON at t+1 with 48.8% confidence. Primary telemetry drivers: latency_spike (26.9% attribution), error_rate (20.8% attribution). Maps to MITRE ATT&CK T1595 (Active Scanning) [MEDIUM Severity] — Adversaries scan public IP blocks and endpoints to gather vulnerability or routing information."*

### Scenario 3: Predicted `SUSTAINED` at t+1
- **Confidence**: `68.3%`
- **Primary Drivers**: `requests_per_ip_60s` (22.5%), `requests_per_ip_10s` (20.9%), `request_variance` (19.5%)
- **MITRE ATT&CK Mapping**: `T1498.001` (Direct Network Flood), `T1499.001` (OS Exhaustion Flood), `T1499.002` (Service Exhaustion Flood)
- **Automated Security Reasoning**: *"Predicted SUSTAINED at t+1 with 68.3% confidence. Primary telemetry drivers: requests_per_ip_60s (22.5% attribution), requests_per_ip_10s (20.9% attribution). Maps to MITRE ATT&CK T1498.001 (Direct Network Flood) [CRITICAL Severity] — Protracted high-volume packet and HTTP flood targeting proxy listeners across consecutive windows."*

---

## 6. Production Artifacts & Deployment Status

| Artifact File | Description | Purpose |
|:--------------|:------------|:--------|
| `models/forecasting/lstm_model.pt` | PyTorch model checkpoint | Retraining and offline evaluation |
| `models/forecasting/forecast_lstm.onnx` | Exported ONNX compute graph | Zero-Python sub-millisecond Go runtime serving |
| `models/forecasting/scaler.json` | JSON FeatureScaler parameters | Real-time telemetry standardization in proxy |
| `docs/forecast_evaluation_v3.md` | Benchmark report & scorecard | SIH submission documentation |

