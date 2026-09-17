# TurboSH V2 — Forecast Evaluation Report

> Generated: 2026-09-17T18:13:41.454338+00:00
> Training time: 0.49s

## Dataset Summary

| Metric | Value |
|---|---|
| Training sequences | 200 |
| Training steps | 5865 |
| Test sequences | 50 |
| Test steps | 1703 |

---

## 1. Markov Chain — Next-Step Accuracy

**Overall Accuracy: 66.61%**

### Per-Class Metrics

| Stage | Precision | Recall | F1 |
|---|---|---|---|
| NORMAL | 0.7920 | 0.8115 | 0.8016 |
| RECON | 0.6259 | 0.6306 | 0.6283 |
| ESCALATION | 0.5000 | 0.5000 | 0.5000 |
| SURGE | 0.5681 | 0.5568 | 0.5624 |
| SUSTAINED | 0.7541 | 0.7471 | 0.7506 |

### Confusion Matrix

| True \ Pred | NORMAL | RECON | ESCALATION | SURGE | SUSTAINED |
|---|---|---|---|---|---|
| **NORMAL** | 297 | 31 | 11 | 9 | 18 |
| **RECON** | 58 | 169 | 26 | 10 | 5 |
| **ESCALATION** | 19 | 60 | 120 | 33 | 8 |
| **SURGE** | 1 | 10 | 72 | 196 | 73 |
| **SUSTAINED** | 0 | 0 | 11 | 97 | 319 |

---

## 2. Gaussian HMM — Viterbi State Decoding

**Overall Accuracy: 99.53%**

### Per-Class Metrics

| Stage | Precision | Recall | F1 |
|---|---|---|---|
| NORMAL | 1.0000 | 1.0000 | 1.0000 |
| RECON | 1.0000 | 1.0000 | 1.0000 |
| ESCALATION | 1.0000 | 1.0000 | 1.0000 |
| SURGE | 0.9972 | 0.9806 | 0.9888 |
| SUSTAINED | 0.9839 | 0.9977 | 0.9907 |

### Confusion Matrix

| True \ Pred | NORMAL | RECON | ESCALATION | SURGE | SUSTAINED |
|---|---|---|---|---|---|
| **NORMAL** | 386 | 0 | 0 | 0 | 0 |
| **RECON** | 0 | 282 | 0 | 0 | 0 |
| **ESCALATION** | 0 | 0 | 247 | 0 | 0 |
| **SURGE** | 0 | 0 | 0 | 353 | 7 |
| **SUSTAINED** | 0 | 0 | 0 | 1 | 427 |

---

## 3. HMM Multi-Step Forecast (Horizon = 3)

**Accuracy: 56.00%**

This metric evaluates how well the HMM can predict attack stages 1–3 time steps
into the future, using only observations up to the midpoint of each test sequence.

---

## Model Artifacts

| Model | Path | Status |
|---|---|---|
| Markov Chain | `models/forecasting\markov_chain.json` | ✅ Saved |
| Gaussian HMM | `models/forecasting\hmm_model.json` | ✅ Saved |
| Labeled Dataset | `datasets\labeled_states.csv` | ✅ Exported |

---

## Methodology Notes

- **Data**: Synthetic sequences generated from a 5-state transition matrix with
  Gaussian feature centroids per stage. Each stage has a distinct feature signature
  to simulate realistic telemetry clusters.
- **Smoothing**: Laplace smoothing (α=0.5) applied to both Markov Chain and HMM
  transition / emission estimates.
- **Evaluation**: Train/test split is separate synthetic datasets (seeds 42 / 99)
  to prevent data leakage.
- **HMM**: Pure NumPy implementation using log-space Viterbi decoding for
  numerical stability. No external ML library dependencies.
