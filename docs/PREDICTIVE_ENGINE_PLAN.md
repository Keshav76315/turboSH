# TurboSH Predictive Intelligence Engine — Version-Wise Implementation Plan

## Evolved Architecture

This is the target architecture we are building toward across 5 versions. Each version lights up a new section of this pipeline.

```
                            CLIENT TRAFFIC
                                  │
                                  ▼
                         ┌─────────────────┐
                         │  TURBOSH PROXY  │
                         └────────┬────────┘
                                  │
                     ┌────────────┴────────────┐
                     │                         │
                     ▼                         ▼
              RATE LIMIT / CACHE        TRAFFIC TELEMETRY ·············· VERSION 1
                                               │
                                               ▼
                                     FEATURE EXTRACTION ················ VERSION 1
                                               │
                                               ▼
                                     NETWORK STATE S(t) ················ VERSION 1
                                               │
                                ┌──────────────┴──────────────┐
                                │                             │
                                ▼                             ▼
                        CURRENT DETECTOR              WORLD MODEL
                        IF / SVM / LOF             Markov / HMM ········ VERSION 2
                         (existing)                LSTM ················· VERSION 3
                                │                  Transformer ·········· VERSION 4
                                ▼                             │
                        CURRENT ANOMALY               FUTURE STATE
                                │                             │
                                │                             ▼
                                │                    ATTACK PROGRESSION · VERSION 2
                                │                             │
                                │                             ▼
                                │                      MITRE ATT&CK ···· VERSION 2
                                │                             │
                                │                             ▼
                                │                     EXPLAINABILITY ···· VERSION 3
                                │                             │
                                │                             ▼
                                │                 FORECAST + RISK SCORE
                                │                             │
                                └──────────────┬──────────────┘
                                               ▼
                                        DECISION ENGINE ················ VERSION 5
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         ▼                     ▼                     ▼
                      ALLOW               RATE LIMIT              BLOCK
                                               │
                                               ▼
                                           BACKEND
```

---

## What Each Version Delivers

| Version | Codename | What It Builds | Key Outcome |
|:--------|:---------|:---------------|:------------|
| **V1** | State Foundation | Traffic Telemetry + Feature Extraction + Network State S(t) | Historical state data flowing and stored |
| **V2** | Baseline Forecaster | Markov/HMM World Model + Attack Progression + MITRE ATT&CK Mapping | First attack-stage predictions with kill chain labels |
| **V3** | Temporal Intelligence | LSTM World Model + Explainability Layer + Multi-step Forecasting | Predict t+1/t+2/t+3 with reasoning |
| **V4** | Model Competition | Transformer World Model + Benchmark Suite + Lead-Time Evaluation | Best model selected with evidence |
| **V5** | Predictive Defense | Unified Decision Engine + Go Integration + Dashboard + Policy Fusion | Full production system — preemptive defense live |

---

---

# VERSION 1 — State Foundation

**Goal**: Build the data pipeline that captures, extracts, and stores network states over time. This is the foundation every subsequent version depends on.

## What V1 Builds

```
                         ┌─────────────────┐
                         │  TURBOSH PROXY  │
                         └────────┬────────┘
                                  │
                     ┌────────────┴────────────┐
                     │                         │
                     ▼                         ▼
              RATE LIMIT / CACHE        ┌─────────────────┐
              (existing, untouched)     │ TRAFFIC TELEMETRY│ ◄── NEW: Go StateExporter
                                        └────────┬────────┘
                                                  │  writes logs/state_telemetry.jsonl
                                                  ▼
                                        ┌─────────────────┐
                                        │FEATURE EXTRACTION│ ◄── EXISTING: 6D features
                                        └────────┬────────┘     (computed in middleware)
                                                  │
                                                  ▼
                                        ┌─────────────────┐
                                        │NETWORK STATE S(t)│ ◄── NEW: Python StateStore
                                        └─────────────────┘     (ring buffer + SQLite)
                                                  │
                                                  ▼
                                        CURRENT DETECTOR ◄── EXISTING: IsolationForest
                                        (existing, untouched)
```

## V1 — Files to Create & Modify

### Go Side (State Telemetry Export)

#### [NEW] `core/inference/state_export.go`
State snapshot exporter that runs alongside the existing ML middleware.

```go
// What this file contains:
// - StateSnapshot struct: {Timestamp, IPHash, Features[6], AnomalyScore, Action}
// - StateExporter: buffered JSONL writer (same pattern as TrafficLogger)
// - ExportSnapshot() method: called after each ML inference, non-blocking
// - Background flush goroutine with configurable interval
```

**Key design decisions:**
- The `StateSnapshot` struct includes **placeholder fields** for future expanded features (IAT, TCP flags, TTL, etc.) — they'll be zero-valued in V1 but the schema won't break in V2+
- Uses the same buffered I/O pattern as the existing [TrafficLogger](file:///Users/anzalkabeer/turboSH/pipeline/logging) for consistency
- Writes to `logs/state_telemetry.jsonl` (separate from `traffic.jsonl`)

#### [MODIFY] [middleware.go](file:///Users/anzalkabeer/turboSH/core/inference/middleware.go)
Add state export after ML inference.

```diff
 // In MLProtection struct, add:
+stateExporter *StateExporter

 // In NewMLProtection(), add:
+if cfg.ForecastingEnabled {
+    exporter, err := NewStateExporter(cfg.StateLogPath)
+    if err == nil {
+        mlp.stateExporter = exporter
+    }
+}

 // In Middleware(), after step 3 (Evaluate Decision), add:
+// 3.5 Export state snapshot for forecasting pipeline (async, non-blocking)
+if mlp.stateExporter != nil {
+    mlp.stateExporter.ExportSnapshot(StateSnapshot{
+        Timestamp:    time.Now(),
+        IPHash:       ipHash,
+        Features:     features,
+        AnomalyScore: score,
+        Action:       action.String(),
+    })
+}
```

> [!NOTE]
> The existing middleware pipeline flow (extract → predict → decide → enforce) is **completely unchanged**. We're only adding a side-channel export after the decision is made.

#### [MODIFY] [config.go](file:///Users/anzalkabeer/turboSH/config/config.go)
Add forecasting configuration.

```diff
+// Forecasting settings
+ForecastingEnabled bool   // Enable state telemetry export for forecasting pipeline
+StateLogPath       string // Path to state telemetry JSONL file
```

New environment variables:
- `TURBOSH_FORECASTING_ENABLED` (default: `false`)
- `TURBOSH_STATE_LOG_PATH` (default: `logs/state_telemetry.jsonl`)

---

### Python Side (State Store & Collector)

#### [NEW] `forecasting/__init__.py`
Package init. Defines the forecasting subsystem version.

#### [NEW] `forecasting/config.py`
Centralized configuration for the forecasting subsystem.

```python
# What this file contains:
# - RING_BUFFER_CAPACITY = 10_000   (in-memory state history)
# - SQLITE_DB_PATH = "data/state_history.db"
# - TIME_STEP_SECONDS = 10          (matches existing 10s window)
# - FORECAST_HORIZON = 3            (predict t+1, t+2, t+3)
# - STATE_LOG_PATH = "logs/state_telemetry.jsonl"
#
# Attack stage labels (used from V2 onward):
# - NORMAL = 0
# - RECON = 1
# - ESCALATION = 2
# - SURGE = 3
# - SUSTAINED = 4
#
# Future feature schema (populated incrementally across versions):
# - V1: 6 existing features + anomaly_score + action
# - V2+: + IAT stats, TCP flags, TTL, port patterns, etc.
```

#### [NEW] `forecasting/state_store.py`
The core data layer — stores and retrieves network state history.

```python
# What this file contains:
#
# NetworkState dataclass:
#   - timestamp: datetime
#   - ip_hash: str
#   - requests_per_ip_10s: float
#   - requests_per_ip_60s: float
#   - endpoint_entropy: float
#   - latency_spike: float
#   - error_rate: float
#   - request_variance: float
#   - anomaly_score: float
#   - action: str  ("ALLOW" / "RATE_LIMIT" / "BLOCK")
#   - extended_features: dict  (empty in V1, populated in V2+)
#
# StateStore class:
#   - __init__(capacity, db_path)
#   - append(state: NetworkState)         → adds to ring buffer
#   - get_ip_history(ip_hash, n) → list   → last N states for an IP
#   - get_time_range(start, end) → list   → all states in time range
#   - get_all_sequences(window) → list    → sliding window sequences for training
#   - to_dataframe() → pd.DataFrame       → export for analysis
#   - flush_to_sqlite()                   → persist to disk
#   - load_from_sqlite()                  → restore on startup
#   - Thread-safe with threading.Lock
```

#### [NEW] `forecasting/telemetry_collector.py`
Daemon process that reads the Go-produced state telemetry JSONL and feeds it into the StateStore.

```python
# What this file contains:
#
# TelemetryCollector class:
#   - __init__(state_store, log_path)
#   - watch()                    → tail the JSONL file (polling-based)
#   - parse_line(line) → NetworkState
#   - run()                      → main loop: watch + parse + store
#
# CLI entry point:
#   python -m forecasting.telemetry_collector
#   --input logs/state_telemetry.jsonl
#   --db data/state_history.db
#   --buffer-size 10000
```

#### [NEW] `forecasting/state_labeler.py`
Rule-based labeler that assigns attack-stage labels to historical states. Used to generate training data for V2+ models.

```python
# What this file contains:
#
# Label assignment rules (threshold-based, V1):
#   NORMAL:     anomaly_score < 0.3
#   RECON:      0.3 ≤ score < 0.5, low request rate, varied endpoints
#   ESCALATION: 0.5 ≤ score < 0.7, rising request rate OR rising error rate
#   SURGE:      score ≥ 0.7, high request rate, latency spikes
#   SUSTAINED:  SURGE persisted for ≥ 3 consecutive time steps
#
# Functions:
#   label_state(state: NetworkState) → int
#   label_sequence(states: list) → list[int]  (context-aware: uses neighbors for SUSTAINED)
#   generate_labeled_dataset(store: StateStore) → pd.DataFrame
#   export_csv(df, path="datasets/labeled_states.csv")
```

#### [NEW] `forecasting/tests/test_state_store.py`
Unit tests for StateStore: append, query, capacity limits, SQLite persistence, thread safety.

#### [NEW] `forecasting/tests/test_telemetry_collector.py`
Unit tests for TelemetryCollector: JSONL parsing, file tailing, error handling.

#### [NEW] `forecasting/tests/test_state_labeler.py`
Unit tests for state labeling: threshold correctness, SUSTAINED detection, edge cases.

---

### V1 — New Dependencies

**Python** (add to `requirements.txt`):
```
# --- Forecasting (V1) ---
# No new dependencies — uses stdlib + existing numpy/pandas
```

**Go**: No new dependencies.

### V1 — Deliverables

- [ ] `core/inference/state_export.go` — Go state snapshot exporter
- [ ] `config.go` updated with forecasting settings
- [ ] `middleware.go` updated with state export hook
- [ ] `forecasting/` Python package with `config.py`, `state_store.py`, `telemetry_collector.py`, `state_labeler.py`
- [ ] Unit tests for all Python modules
- [ ] Go tests for state export
- [ ] `logs/state_telemetry.jsonl` flowing with data when `TURBOSH_FORECASTING_ENABLED=true`
- [ ] `datasets/labeled_states.csv` generated from historical data

### V1 — Verification

```bash
# Go: Build and verify state export
go build ./...
go test ./core/inference/ -run TestStateExport -v

# Python: Unit tests
python -m pytest forecasting/tests/ -v

# Integration: Start proxy with forecasting, send traffic, verify JSONL
TURBOSH_FORECASTING_ENABLED=true go run cmd/turbosh/main.go &
# (run some traffic)
wc -l logs/state_telemetry.jsonl  # should have entries
python -m forecasting.telemetry_collector --input logs/state_telemetry.jsonl
python -c "from forecasting.state_labeler import *; print('Labeler OK')"
```

---

---

# VERSION 2 — Baseline Forecaster

**Goal**: Build the first World Model (Markov/HMM) that predicts the next attack state, map predictions to MITRE ATT&CK framework, and model attack progression.

## What V2 Adds

```
                                     NETWORK STATE S(t)
                                               │
                                ┌──────────────┴──────────────┐
                                │                             │
                                ▼                             ▼
                        CURRENT DETECTOR        ┌─────────────────────┐
                        (existing)              │     WORLD MODEL     │
                                                │   Markov Chain      │ ◄── NEW
                                                │   Hidden Markov     │ ◄── NEW
                                                └────────┬────────────┘
                                                         │
                                                         ▼
                                                ┌─────────────────────┐
                                                │ ATTACK PROGRESSION  │ ◄── NEW
                                                │ State transition    │
                                                │ probability chains  │
                                                └────────┬────────────┘
                                                         │
                                                         ▼
                                                ┌─────────────────────┐
                                                │   MITRE ATT&CK     │ ◄── NEW
                                                │ Stage → Technique   │
                                                │ mapping             │
                                                └────────┬────────────┘
                                                         │
                                                         ▼
                                                FORECAST + RISK SCORE
```

## V2 — Files to Create & Modify

### World Models

#### [NEW] `forecasting/models/__init__.py`
Package init for models.

#### [NEW] `forecasting/models/markov_chain.py`
Simple first-order Markov Chain — the simplest possible baseline.

```python
# What this file contains:
#
# MarkovChain class:
#   - __init__(n_states=5)
#   - fit(state_sequences: list[list[int]])
#     → Builds transition matrix P[i][j] = P(next=j | current=i)
#   - predict(current_state: int) → int
#     → Most likely next state
#   - predict_proba(current_state: int) → dict[int, float]
#     → Full probability distribution over next states
#   - predict_trajectory(current_state, steps=3) → list[int]
#     → Multi-step: iteratively apply transitions
#   - transition_matrix → np.ndarray (5×5)
#   - save(path) / load(path) → JSON serialization
```

#### [NEW] `forecasting/models/hmm_model.py`
Hidden Markov Model — models hidden attack intent behind observable traffic features.

```python
# What this file contains:
#
# HMMForecaster class:
#   - __init__(n_hidden_states=5, n_observable_bins=10)
#   - fit(observation_sequences, state_sequences)
#     → Baum-Welch training via hmmlearn.GaussianHMM
#   - predict(observation_sequence) → int
#     → Viterbi decoding → predicted current hidden state
#   - forecast(observation_sequence, steps=3) → list[int]
#     → Predict future hidden states using learned transitions
#   - forecast_proba(observation_sequence, steps=3) → list[dict]
#     → Probability distributions for each future step
#   - save(path) / load(path)
#
# Key insight: Hidden states = actual attack intent (NORMAL, RECON, etc.)
#              Observations = the 6D feature vectors we measure
#              The HMM learns the mapping between what we see and what's really happening
```

### Attack Progression

#### [NEW] `forecasting/attack_progression.py`
Models how attacks evolve through stages over time.

```python
# What this file contains:
#
# AttackProgressionModel class:
#   - __init__(transition_matrix)
#   - from_state_store(store: StateStore) → classmethod
#     → Learns progression patterns from historical labeled data
#   - get_escalation_probability(current_stage) → float
#     → P(next stage is worse than current)
#   - get_likely_trajectory(current_stage, horizon=3) → list[tuple[int, float]]
#     → Most likely attack trajectory with confidences
#   - is_escalating(recent_states: list[int]) → bool
#     → Detects escalation trend in recent history
#
# Attack Stage Transitions (what we learn):
#   NORMAL → RECON:       Port scanning begins
#   RECON → ESCALATION:   Brute force / credential stuffing starts
#   ESCALATION → SURGE:   Full DDoS / request flood
#   SURGE → SUSTAINED:    Attack persists with adaptation
#   Any → NORMAL:         Attack subsides
```

### MITRE ATT&CK Mapping

#### [NEW] `forecasting/mitre_mapping.py`
Maps predicted attack stages to MITRE ATT&CK techniques.

```python
# What this file contains:
#
# MITRE_MAPPING dict:
#   RECON: [
#     T1595 - Active Scanning,
#     T1046 - Network Service Discovery,
#     T1592 - Gather Victim Host Information
#   ]
#   ESCALATION: [
#     T1110 - Brute Force,
#     T1078 - Valid Accounts (credential stuffing),
#     T1498 - Network Denial of Service (early stage)
#   ]
#   SURGE: [
#     T1498 - Network Denial of Service,
#     T1499 - Endpoint Denial of Service,
#     T1496 - Resource Hijacking
#   ]
#   SUSTAINED: [
#     T1498.001 - Direct Network Flood,
#     T1499.001 - OS Exhaustion Flood,
#     T1499.002 - Service Exhaustion Flood
#   ]
#
# Functions:
#   map_stage_to_techniques(stage: int) → list[MITRETechnique]
#   map_forecast_to_mitre(forecast: list[int]) → list[MITREMapping]
#
# MITRETechnique dataclass:
#   - technique_id: str    ("T1498")
#   - name: str            ("Network Denial of Service")
#   - tactic: str          ("Impact")
#   - description: str
#   - severity: str        ("HIGH" / "CRITICAL")
```

### Forecast Evaluation

#### [NEW] `forecasting/evaluation/__init__.py`
#### [NEW] `forecasting/evaluation/evaluator.py`
Measures how good the forecasts are.

```python
# What this file contains:
#
# ForecastEvaluator class:
#   - __init__(model, test_sequences)
#   - evaluate() → EvaluationReport
#   - accuracy_per_stage() → dict     (per-class accuracy)
#   - confusion_matrix() → np.ndarray
#   - f1_scores() → dict              (per-class F1)
#   - lead_time_analysis() → dict     (how early attacks are predicted)
#   - generate_report(path) → writes markdown report
#
# EvaluationReport dataclass:
#   - overall_accuracy: float
#   - per_stage_f1: dict
#   - avg_lead_time_steps: float
#   - confusion_matrix: np.ndarray
```

### Training Script

#### [NEW] `forecasting/train_hmm.py`
End-to-end training pipeline for V2 models.

```python
# CLI:
#   python forecasting/train_hmm.py
#   --data datasets/labeled_states.csv
#   --model-type hmm          (or "markov")
#   --output models/forecasting/
#   --evaluate
#
# Steps:
#   1. Load labeled state sequences from CSV
#   2. Split into train/test (80/20)
#   3. Train Markov Chain baseline
#   4. Train HMM model
#   5. Evaluate both on test set
#   6. Save best model
#   7. Generate evaluation report → docs/forecast_evaluation_v2.md
```

### V2 — Tests

#### [NEW] `forecasting/tests/test_markov_chain.py`
#### [NEW] `forecasting/tests/test_hmm_model.py`
#### [NEW] `forecasting/tests/test_attack_progression.py`
#### [NEW] `forecasting/tests/test_mitre_mapping.py`
#### [NEW] `forecasting/tests/test_evaluator.py`

### V2 — New Dependencies

**Python** (add to `requirements.txt`):
```
# --- Forecasting (V2) ---
hmmlearn>=0.3.0
```

### V2 — Deliverables

- [ ] Markov Chain baseline model trained and evaluated
- [ ] HMM model trained and evaluated
- [ ] Attack progression model learned from data
- [ ] MITRE ATT&CK mapping for all 5 attack stages
- [ ] Evaluation report: `docs/forecast_evaluation_v2.md`
- [ ] Saved models in `models/forecasting/`
- [ ] All unit tests passing

### V2 — Verification

```bash
# Train and evaluate
python forecasting/train_hmm.py --evaluate

# Inspect results
cat docs/forecast_evaluation_v2.md

# Verify MITRE mapping
python -c "from forecasting.mitre_mapping import *; print(map_stage_to_techniques(3))"
```

---

---

# VERSION 3 — Temporal Intelligence

**Goal**: Replace the baseline Markov/HMM with an LSTM World Model that captures long-range temporal dependencies, adds multi-step forecasting (t+1/t+2/t+3), and introduces the Explainability layer.

## What V3 Adds

```
                                     NETWORK STATE S(t)
                                               │
                                ┌──────────────┴──────────────┐
                                │                             │
                                ▼                             ▼
                        CURRENT DETECTOR        ┌─────────────────────┐
                                                │     WORLD MODEL     │
                                                │   Markov (V2) ✓     │
                                                │   HMM (V2) ✓        │
                                                │   LSTM ◄──────────  │ ◄── NEW
                                                └────────┬────────────┘
                                                         │
                                                         ▼
                                                 ATTACK PROGRESSION (V2) ✓
                                                         │
                                                         ▼
                                                   MITRE ATT&CK (V2) ✓
                                                         │
                                                         ▼
                                                ┌─────────────────────┐
                                                │   EXPLAINABILITY    │ ◄── NEW
                                                │ "Why this forecast?"│
                                                │ Feature attribution │
                                                │ + MITRE reasoning   │
                                                └────────┬────────────┘
                                                         │
                                                         ▼
                                                FORECAST + RISK SCORE
```

## V3 — Files to Create & Modify

### LSTM World Model

#### [NEW] `forecasting/models/data_loader.py`
PyTorch Dataset and DataLoader for time-series state sequences.

```python
# What this file contains:
#
# StateSequenceDataset(torch.utils.data.Dataset):
#   - __init__(sequences, labels, seq_length=30)
#   - Sliding window: takes seq_length consecutive states as input,
#     next 3 states as targets (multi-step: t+1, t+2, t+3)
#   - Feature normalization with StandardScaler (fitted on train split)
#   - __getitem__ returns (input_tensor[30, 6], target_tensor[3])
#
# create_dataloaders(labeled_csv, seq_length, batch_size, splits):
#   - Train/Val/Test split (70/15/15)
#   - Returns 3 DataLoaders + fitted scaler
```

#### [NEW] `forecasting/models/lstm_model.py`
LSTM-based temporal forecaster.

```python
# What this file contains:
#
# LSTMForecaster(nn.Module):
#   - __init__(input_dim=6, hidden_dim=128, num_layers=2, n_classes=5, forecast_steps=3, dropout=0.3)
#   - Architecture:
#       Input (seq_len, 6) → LSTM(2 layers, hidden=128, dropout=0.3)
#                           → take last hidden state
#                           → Dense(128, 64) → ReLU → Dropout
#                           → Dense(64, 5 × 3) → reshape to (3, 5)
#                           → Softmax per step
#   - forward(x) → (batch, 3, 5)  — probability over 5 stages for each of 3 future steps
#   - predict(x) → (batch, 3)     — argmax stage labels
#   - predict_with_confidence(x) → list[dict]  — stage + confidence per step
#
# Key design decisions:
#   - Multi-output head: one prediction per forecast step (not autoregressive)
#   - This avoids error accumulation across steps
#   - 30 timesteps × 10 seconds = 5 minutes of history as context
```

### Explainability Layer

#### [NEW] `forecasting/explainability.py`
Explains why a particular forecast was made.

```python
# What this file contains:
#
# ForecastExplanation dataclass:
#   - predicted_stage: int
#   - confidence: float
#   - top_features: list[tuple[str, float]]     (feature name, attribution score)
#   - mitre_techniques: list[MITRETechnique]
#   - reasoning: str                            (human-readable explanation)
#   - historical_pattern: str                   (what past pattern this matches)
#
# Explainer class:
#   - __init__(model, mitre_mapper)
#   - explain(input_sequence, forecast) → ForecastExplanation
#   - feature_attribution(input_sequence) → dict
#     → Gradient-based attribution: which features drove the prediction
#     → For each of the 6 features: how much did it contribute to the forecast?
#   - generate_reasoning(stage, features, mitre) → str
#     → Template-based reasoning:
#       "Predicted SURGE at t+2 (confidence: 87%). Primary drivers:
#        requests_per_ip_10s increased 340% over last 5 windows.
#        endpoint_entropy dropped to 0.05 (single-target pattern).
#        Maps to MITRE T1498 (Network Denial of Service).
#        Similar pattern observed in 3 previous SURGE events in history."
```

### Training & Export

#### [NEW] `forecasting/train_lstm.py`
LSTM training pipeline.

```python
# CLI:
#   python forecasting/train_lstm.py
#   --data datasets/labeled_states.csv
#   --epochs 50
#   --seq-length 30
#   --hidden-dim 128
#   --batch-size 64
#   --lr 0.001
#   --output models/forecasting/
#   --evaluate
#
# Steps:
#   1. Create DataLoaders
#   2. Train with early stopping (patience=10)
#   3. Evaluate on test set (per-step accuracy, F1, lead time)
#   4. Compare against HMM baseline
#   5. Export best model to ONNX
#   6. Generate report → docs/forecast_evaluation_v3.md
```

#### [NEW] `forecasting/export/__init__.py`
#### [NEW] `forecasting/export/export_lstm_onnx.py`
Export trained LSTM to ONNX format.

```python
# What this file contains:
#
# export_lstm_to_onnx(model, scaler, output_path):
#   - Creates dummy input matching expected shape (1, 30, 6)
#   - torch.onnx.export with dynamic batch size
#   - Validates exported model with onnxruntime
#   - Saves scaler parameters alongside model (for Go-side normalization)
#   - Output: models/forecasting/forecast_lstm.onnx
```

#### [MODIFY] `forecasting/evaluation/evaluator.py`
Extend evaluator for multi-step forecasting.

```diff
+# New methods:
+def evaluate_multistep(predictions_t1, predictions_t2, predictions_t3, actuals):
+    """Evaluate accuracy at each forecast horizon separately."""
+
+def accuracy_vs_horizon_curve(results):
+    """Plot: x-axis = forecast horizon, y-axis = accuracy."""
+
+def compare_models(model_results: dict):
+    """Compare HMM vs LSTM side-by-side."""
```

### V3 — Tests

#### [NEW] `forecasting/tests/test_lstm_model.py`
#### [NEW] `forecasting/tests/test_data_loader.py`
#### [NEW] `forecasting/tests/test_explainability.py`

### V3 — New Dependencies

**Python** (add to `requirements.txt`):
```
# --- Forecasting (V3) ---
torch>=2.0.0
torchvision>=0.15.0
```

### V3 — Deliverables

- [ ] LSTM model trained and evaluated with multi-step predictions
- [ ] LSTM vs HMM comparison with accuracy metrics
- [ ] Explainability layer generating human-readable forecast reasoning
- [ ] ONNX export of LSTM model (`models/forecasting/forecast_lstm.onnx`)
- [ ] Evaluation report: `docs/forecast_evaluation_v3.md`
- [ ] All unit tests passing

### V3 — Verification

```bash
# Train LSTM
python forecasting/train_lstm.py --epochs 50 --evaluate

# Verify ONNX export
python forecasting/export/export_lstm_onnx.py
python -c "import onnxruntime as ort; s = ort.InferenceSession('models/forecasting/forecast_lstm.onnx'); print('ONNX OK')"

# Test explainability
python -c "
from forecasting.explainability import Explainer
# (load model and test sequence)
print(explainer.explain(test_seq, forecast).reasoning)
"
```

---

---

# VERSION 4 — Model Competition

**Goal**: Build a Transformer World Model, benchmark all models head-to-head, and perform rigorous lead-time evaluation to select the production model.

## What V4 Adds

```
                                        WORLD MODEL
                                   ┌─────────────────────┐
                                   │   Markov (V2) ✓     │
                                   │   HMM (V2) ✓        │
                                   │   LSTM (V3) ✓       │
                                   │   Transformer ◄───  │ ◄── NEW
                                   └────────┬────────────┘
                                            │
                                   ┌────────┴────────────┐
                                   │     BENCHMARK       │ ◄── NEW
                                   │ All 4 models        │
                                   │ head-to-head        │
                                   └────────┬────────────┘
                                            │
                                   ┌────────┴────────────┐
                                   │  LEAD-TIME EVAL     │ ◄── NEW
                                   │ How early can we    │
                                   │ detect attacks?     │
                                   └─────────────────────┘
```

## V4 — Files to Create & Modify

### Transformer World Model

#### [NEW] `forecasting/models/transformer_model.py`
Transformer-based temporal forecaster using self-attention.

```python
# What this file contains:
#
# PositionalEncoding(nn.Module):
#   - Sinusoidal positional encoding for temporal ordering
#
# TransformerForecaster(nn.Module):
#   - __init__(input_dim=6, d_model=128, nhead=4, num_layers=3,
#              dim_feedforward=256, n_classes=5, forecast_steps=3, dropout=0.1)
#   - Architecture:
#       Input (seq_len, 6) → Linear projection to d_model
#                           → PositionalEncoding
#                           → TransformerEncoder(3 layers, 4 heads)
#                           → Global average pooling
#                           → Dense(d_model, 5 × 3) → reshape to (3, 5)
#                           → Softmax per step
#   - forward(x) → (batch, 3, 5)
#   - get_attention_weights(x) → attention maps for explainability
#
# Key advantages over LSTM:
#   - Parallel computation (faster training)
#   - Self-attention captures non-local temporal dependencies
#   - Attention weights provide natural explainability
```

#### [NEW] `forecasting/train_transformer.py`
Transformer training pipeline (same structure as `train_lstm.py`).

#### [NEW] `forecasting/export/export_transformer_onnx.py`
Export trained Transformer to ONNX format.

### Benchmark Suite

#### [NEW] `forecasting/benchmark/__init__.py`
#### [NEW] `forecasting/benchmark/benchmark.py`
Head-to-head model comparison.

```python
# CLI:
#   python -m forecasting.benchmark.benchmark
#   --data datasets/labeled_states.csv
#   --models markov,hmm,lstm,transformer
#   --output docs/forecast_benchmark_v4.md
#
# What it measures:
#
# | Metric              | Markov | HMM   | LSTM  | Transformer |
# |---------------------|--------|-------|-------|-------------|
# | t+1 Accuracy        |        |       |       |             |
# | t+2 Accuracy        |        |       |       |             |
# | t+3 Accuracy        |        |       |       |             |
# | F1 (macro)          |        |       |       |             |
# | RECON Detection F1  |        |       |       |             |
# | SURGE Detection F1  |        |       |       |             |
# | Avg Lead Time (steps)|       |       |       |             |
# | Inference Latency   |        |       |       |             |
# | Model Size (MB)     |        |       |       |             |
# | Memory Usage (MB)   |        |       |       |             |
#
# Also generates:
#   - Accuracy vs. horizon curves (all models overlaid)
#   - Confusion matrices for each model
#   - Lead-time distribution histograms
#   - ROC curves for each attack stage
```

### Lead-Time Evaluation

#### [NEW] `forecasting/evaluation/lead_time.py`
Specialized lead-time analysis.

```python
# What this file contains:
#
# LeadTimeEvaluator class:
#   - __init__(model, test_sequences, test_labels)
#   - compute_lead_times() → dict
#     → For each actual attack in the test set:
#       "How many steps before the attack peaked did the model first predict it?"
#   - cumulative_detection_curve() → (x_axis, y_axis)
#     → x = lead time in steps, y = % of attacks detected by that lead time
#   - average_lead_time() → float
#   - statistical_comparison(model_a_times, model_b_times) → p_value
#     → Wilcoxon signed-rank test: is one model significantly earlier?
#   - generate_report(path)
```

### V4 — Tests

#### [NEW] `forecasting/tests/test_transformer_model.py`
#### [NEW] `forecasting/tests/test_benchmark.py`
#### [NEW] `forecasting/tests/test_lead_time.py`

### V4 — Deliverables

- [ ] Transformer model trained and evaluated
- [ ] Full 4-model benchmark with comparison tables and charts
- [ ] Lead-time analysis with statistical significance tests
- [ ] Production model selected with evidence
- [ ] ONNX export of winning model
- [ ] Benchmark report: `docs/forecast_benchmark_v4.md`

### V4 — Verification

```bash
# Train Transformer
python forecasting/train_transformer.py --epochs 50 --evaluate

# Run full benchmark
python -m forecasting.benchmark.benchmark --models markov,hmm,lstm,transformer

# Verify the winning model's ONNX
python -c "import onnxruntime as ort; s = ort.InferenceSession('models/forecasting/forecast_best.onnx'); print('OK')"
```

---

---

# VERSION 5 — Predictive Defense

**Goal**: Integrate the winning forecast model into the Go middleware pipeline, create the unified Decision Engine that merges real-time anomaly scores with forecast risk scores, and expose forecast data through the dashboard.

## What V5 Completes

```
                            CLIENT TRAFFIC
                                  │
                                  ▼
                         ┌─────────────────┐
                         │  TURBOSH PROXY  │
                         └────────┬────────┘
                                  │
                     ┌────────────┴────────────┐
                     │                         │
                     ▼                         ▼
              RATE LIMIT / CACHE        TRAFFIC TELEMETRY (V1) ✓
                     │                         │
                     │                   FEATURE EXTRACTION (V1) ✓
                     │                         │
                     │                  NETWORK STATE S(t) (V1) ✓
                     │                         │
                     │              ┌──────────┴──────────┐
                     │              │                     │
                     │              ▼                     ▼
                     │      CURRENT DETECTOR        WORLD MODEL (V2-V4) ✓
                     │      (existing)              (best from benchmark)
                     │              │                     │
                     │              ▼                     ▼
                     │      CURRENT ANOMALY         FUTURE STATE
                     │              │                     │
                     │              │              ATTACK PROGRESSION (V2) ✓
                     │              │                     │
                     │              │                MITRE ATT&CK (V2) ✓
                     │              │                     │
                     │              │              EXPLAINABILITY (V3) ✓
                     │              │                     │
                     │              │          FORECAST + RISK SCORE
                     │              │                     │
                     │              └──────────┬──────────┘
                     │                         ▼
                     │              ┌──────────────────────────┐
                     │              │    UNIFIED DECISION       │ ◄── NEW
                     │              │    ENGINE (Go)             │
                     │              │                            │
                     │              │  Current Score + Forecast  │
                     │              │  → Fused Risk Level        │
                     │              │  → Preemptive Action       │
                     │              └──────────┬───────────────┘
                     │                         │
                     └─────────────┬───────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
                 ALLOW        RATE LIMIT        BLOCK
                                   │
                                   ▼
                               BACKEND
```

## V5 — Files to Create & Modify

### Go Forecast Engine

#### [NEW] `core/forecasting/forecaster.go`
Loads the winning ONNX forecast model and runs inference in Go.

```go
// What this file contains:
//
// ForecastResult struct:
//   PredictedStages  [3]string    // e.g., ["RECON", "ESCALATION", "SURGE"]
//   Confidences      [3]float64   // e.g., [0.82, 0.74, 0.61]
//   RiskLevel        string       // "LOW" / "ELEVATED" / "HIGH" / "CRITICAL"
//   LeadTimeSeconds  int          // seconds until predicted threat peak
//
// Forecaster struct:
//   - session *ort.DynamicAdvancedSession   (ONNX inference)
//   - stateBuffer []StateSnapshot            (sliding window of recent states)
//   - bufferSize int                         (default: 30 = 5 minutes)
//   - scaler ScalerParams                   (normalization params from training)
//
// Methods:
//   NewForecaster(modelPath, scalerPath, bufferSize) → *Forecaster
//   AddState(snapshot StateSnapshot)                 → updates buffer
//   Predict() → (ForecastResult, error)              → runs ONNX inference
//   Close()                                          → cleanup
```

#### [NEW] `core/forecasting/risk_advisor.go`
Merges real-time anomaly score with forecast predictions into a unified risk assessment.

```go
// What this file contains:
//
// RiskAdvisory struct:
//   ThreatLevel       string     // "NORMAL" / "ELEVATED" / "HIGH" / "CRITICAL"
//   RecommendedAction Action     // decision.ActionAllow / ActionRateLimit / ActionBlock
//   CurrentScore      float64    // from IsolationForest
//   ForecastStages    [3]string  // from World Model
//   ForecastConf      [3]float64
//   LeadTimeSec       int
//   Justification     string    // human-readable (from Explainability)
//   MITRETechniques   []string  // e.g., ["T1498", "T1499"]
//
// RiskAdvisor struct:
//   forecaster *Forecaster
//
// Methods:
//   NewRiskAdvisor(forecaster) → *RiskAdvisor
//   Assess(currentScore float64, currentAction Action) → RiskAdvisory
//
// Fusion Policy:
//   1. If forecast predicts SURGE at ANY horizon with conf > 0.7
//      AND currentScore > 0.5 → upgrade to BLOCK (preemptive)
//   2. If forecast predicts ESCALATION at t+1 with conf > 0.6
//      AND currentAction == ALLOW → upgrade to RATE_LIMIT
//   3. If forecast predicts RECON at t+1 → increase logging, no action change
//   4. If forecast predicts NORMAL at all horizons → no change
//   5. If forecast unavailable → fall back to currentAction (graceful degradation)
```

### Unified Decision Engine

#### [MODIFY] [decision_engine.go](file:///Users/anzalkabeer/turboSH/core/decision/decision_engine.go)
Add `ForecastAwarePolicy` that wraps the existing `ThresholdPolicy`.

```diff
+// ForecastAwarePolicy wraps ThresholdPolicy and adjusts decisions
+// based on forecast risk advisories.
+type ForecastAwarePolicy struct {
+    base       *ThresholdPolicy
+    advisor    *forecasting.RiskAdvisor
+}
+
+func NewForecastAwarePolicy(base *ThresholdPolicy, advisor *forecasting.RiskAdvisor) *ForecastAwarePolicy
+
+func (fp *ForecastAwarePolicy) Evaluate(prediction Prediction) Action {
+    // 1. Get base decision from ThresholdPolicy
+    baseAction := fp.base.Evaluate(prediction)
+
+    // 2. Consult risk advisor for forecast-based adjustment
+    advisory := fp.advisor.Assess(prediction.AnomalyScore, baseAction)
+
+    // 3. Never downgrade: if forecast recommends stronger action, upgrade
+    if advisory.RecommendedAction > baseAction {
+        return advisory.RecommendedAction
+    }
+    return baseAction
+}
```

> [!IMPORTANT]
> The `ForecastAwarePolicy` can only **upgrade** actions (ALLOW→RATE_LIMIT, RATE_LIMIT→BLOCK), never downgrade. This ensures the existing enforcement engine's protections are never weakened by a faulty forecast.

### Middleware Integration

#### [MODIFY] [middleware.go](file:///Users/anzalkabeer/turboSH/core/inference/middleware.go)
Update the middleware to use forecaster state and log advisory decisions.

```diff
 // In Middleware(), after the existing enforcement logic:
+
+// 4.5 Predictive Defense Advisory (if enabled)
+if mlp.riskAdvisor != nil {
+    advisory := mlp.riskAdvisor.LatestAdvisory()
+    if advisory != nil && advisory.ThreatLevel != "NORMAL" {
+        log.Printf("[Predictive Defense] ⚡ %s — Forecast: %v (conf: %.0f%%) | MITRE: %v | %s",
+            advisory.ThreatLevel,
+            advisory.ForecastStages,
+            advisory.ForecastConf[0]*100,
+            advisory.MITRETechniques,
+            advisory.Justification)
+    }
+}
```

### Dashboard Integration

#### [MODIFY] [dashboard_state.go](file:///Users/anzalkabeer/turboSH/monitoring/dashboard_state.go)
Add forecast data to the dashboard snapshot.

```diff
+// ForecastSnapshot holds predictive intelligence data for the dashboard.
+type ForecastSnapshot struct {
+    Enabled         bool       `json:"enabled"`
+    ModelName       string     `json:"model_name"`       // "LSTM" / "Transformer"
+    ThreatLevel     string     `json:"threat_level"`     // "NORMAL"/"ELEVATED"/"HIGH"/"CRITICAL"
+    Predictions     [3]string  `json:"predictions"`      // t+1, t+2, t+3 stage labels
+    Confidences     [3]float64 `json:"confidences"`
+    LeadTimeSec     int        `json:"lead_time_seconds"`
+    MITRETechniques []string   `json:"mitre_techniques"`
+    Justification   string     `json:"justification"`
+    LastUpdated     time.Time  `json:"last_updated"`
+}

 // Add to StatusSnapshot:
+Forecast ForecastSnapshot `json:"forecast"`
```

#### [MODIFY] Dashboard UI (`ui/dark_desktop_ui.html`, `ui/light_desktop_ui.html`)
Add forecast panel to the dashboard.

```
New dashboard panel: "Predictive Intelligence"
- Threat level indicator with color coding:
    NORMAL → green
    ELEVATED → yellow
    HIGH → orange
    CRITICAL → red (pulsing animation)
- Forecast timeline: visual 3-step prediction strip
- MITRE ATT&CK technique badges
- Justification text
- Forecast confidence bars
```

### Config Updates

#### [MODIFY] [config.go](file:///Users/anzalkabeer/turboSH/config/config.go)

```diff
+// Forecasting settings (V5 additions)
+ForecastModelPath         string // Path to ONNX forecast model
+ForecastScalerPath        string // Path to normalization scaler params
+ForecastWindowSize        int    // Number of past states to use (default: 30)
+PreemptiveDefenseEnabled  bool   // Enable forecast-based action upgrades
```

New environment variables:
- `TURBOSH_FORECAST_MODEL_PATH` (default: `models/forecasting/forecast_best.onnx`)
- `TURBOSH_FORECAST_SCALER_PATH` (default: `models/forecasting/scaler.json`)
- `TURBOSH_FORECAST_WINDOW` (default: `30`)
- `TURBOSH_PREEMPTIVE_DEFENSE` (default: `false`)

### Proxy Assembly

#### [MODIFY] [proxy middleware.go](file:///Users/anzalkabeer/turboSH/core/proxy/middleware.go)
Wire up the forecaster in `NewComponents()` and `SetupMiddleware()`.

```diff
 // In Components struct:
+Forecaster       *forecasting.Forecaster
+RiskAdvisor      *forecasting.RiskAdvisor
+ForecastStop     chan struct{}

 // In NewComponents():
+if cfg.ForecastingEnabled && cfg.PreemptiveDefenseEnabled {
+    forecaster, err := forecasting.NewForecaster(cfg.ForecastModelPath, cfg.ForecastScalerPath, cfg.ForecastWindowSize)
+    if err == nil {
+        advisor := forecasting.NewRiskAdvisor(forecaster)
+        // Use ForecastAwarePolicy instead of plain ThresholdPolicy
+        de = decision.NewForecastAwarePolicy(de, advisor)
+    }
+}
```

### V5 — Tests

#### [NEW] `core/forecasting/forecaster_test.go`
#### [NEW] `core/forecasting/risk_advisor_test.go`
#### [MODIFY] `core/decision/decision_engine_test.go` — add `TestForecastAwarePolicy`

### V5 — Deliverables

- [ ] Go forecast engine loading ONNX model and running inference
- [ ] Risk advisor merging current + forecast scores
- [ ] `ForecastAwarePolicy` in decision engine (never downgrades, only upgrades)
- [ ] Dashboard showing forecast panel with threat level, MITRE techniques, justification
- [ ] Preemptive defense logged: `[Predictive Defense] ⚡ PREEMPTIVE THROTTLE...`
- [ ] Config flags for enabling/disabling forecast features independently
- [ ] All Go + Python tests passing
- [ ] End-to-end demo: attack → forecast → preemptive defense before attack peaks

### V5 — Verification

```bash
# Go build and test
go build ./...
go test ./core/forecasting/ -v
go test ./core/decision/ -run TestForecastAwarePolicy -v

# End-to-end test
TURBOSH_FORECASTING_ENABLED=true \
TURBOSH_PREEMPTIVE_DEFENSE=true \
TURBOSH_FORECAST_MODEL_PATH=models/forecasting/forecast_best.onnx \
go run cmd/turbosh/main.go &

# Run attacker simulation
go run cmd/attacker/main.go

# Verify preemptive defense in logs
grep "Predictive Defense" logs/turbosh.log

# Verify dashboard shows forecast data
curl http://localhost:9090/api/v1/status | jq '.forecast'
```

---

---

## Full Directory Structure (After All 5 Versions)

```
turboSH/
├── core/
│   ├── inference/
│   │   ├── middleware.go              ← V1: +state export hook | V5: +advisory logging
│   │   ├── inference.go               (unchanged)
│   │   ├── features.go                (unchanged)
│   │   └── state_export.go            ← V1: NEW — state snapshot JSONL writer
│   ├── forecasting/                   ← V5: NEW — Go forecast engine
│   │   ├── forecaster.go              ← ONNX forecast inference
│   │   └── risk_advisor.go            ← Risk advisory merger
│   ├── decision/
│   │   └── decision_engine.go         ← V5: +ForecastAwarePolicy
│   ├── proxy/
│   │   └── middleware.go              ← V5: +forecaster wiring
│   ├── security/                      (unchanged)
│   ├── cache/                         (unchanged)
│   └── scheduler/                     (unchanged)
│
├── forecasting/                       ← NEW: Predictive Intelligence Engine (Python)
│   ├── __init__.py                    ← V1
│   ├── config.py                      ← V1
│   ├── state_store.py                 ← V1
│   ├── telemetry_collector.py         ← V1
│   ├── state_labeler.py               ← V1
│   ├── attack_progression.py          ← V2
│   ├── mitre_mapping.py               ← V2
│   ├── explainability.py              ← V3
│   ├── train_hmm.py                   ← V2
│   ├── train_lstm.py                  ← V3
│   ├── train_transformer.py           ← V4
│   ├── models/
│   │   ├── __init__.py                ← V2
│   │   ├── markov_chain.py            ← V2
│   │   ├── hmm_model.py               ← V2
│   │   ├── lstm_model.py              ← V3
│   │   ├── transformer_model.py       ← V4
│   │   └── data_loader.py             ← V3
│   ├── evaluation/
│   │   ├── __init__.py                ← V2
│   │   ├── evaluator.py               ← V2 (extended V3)
│   │   └── lead_time.py               ← V4
│   ├── benchmark/
│   │   ├── __init__.py                ← V4
│   │   └── benchmark.py               ← V4
│   ├── export/
│   │   ├── __init__.py                ← V3
│   │   ├── export_lstm_onnx.py        ← V3
│   │   └── export_transformer_onnx.py ← V4
│   └── tests/
│       ├── test_state_store.py        ← V1
│       ├── test_telemetry_collector.py← V1
│       ├── test_state_labeler.py      ← V1
│       ├── test_markov_chain.py       ← V2
│       ├── test_hmm_model.py          ← V2
│       ├── test_attack_progression.py ← V2
│       ├── test_mitre_mapping.py      ← V2
│       ├── test_evaluator.py          ← V2
│       ├── test_lstm_model.py         ← V3
│       ├── test_data_loader.py        ← V3
│       ├── test_explainability.py     ← V3
│       ├── test_transformer_model.py  ← V4
│       ├── test_benchmark.py          ← V4
│       └── test_lead_time.py          ← V4
│
├── config/
│   └── config.go                      ← V1: +forecasting flags | V5: +forecast model paths
│
├── monitoring/
│   └── dashboard_state.go             ← V5: +ForecastSnapshot
│
├── ui/
│   ├── dark_desktop_ui.html           ← V5: +forecast panel
│   └── light_desktop_ui.html          ← V5: +forecast panel
│
├── models/
│   ├── anomaly_model.onnx             (existing — IsolationForest)
│   └── forecasting/                   ← NEW
│       ├── markov_chain.json          ← V2
│       ├── hmm_model.pkl              ← V2
│       ├── forecast_lstm.onnx         ← V3
│       ├── forecast_transformer.onnx  ← V4
│       ├── forecast_best.onnx         ← V4 (symlink to winner)
│       └── scaler.json                ← V3 (normalization params)
│
├── datasets/
│   ├── synthetic_traffic_dataset.csv  (existing)
│   └── labeled_states.csv             ← V1
│
├── data/
│   └── state_history.db               ← V1 (SQLite)
│
└── docs/
    ├── ARCHITECTURE.md                ← V5: updated with evolved architecture
    ├── forecast_evaluation_v2.md      ← V2
    ├── forecast_evaluation_v3.md      ← V3
    └── forecast_benchmark_v4.md       ← V4
```

---

## Dependency Summary

| Version | Python Additions | Go Additions |
|:--------|:-----------------|:-------------|
| **V1** | None (stdlib + existing numpy/pandas) | None |
| **V2** | `hmmlearn>=0.3.0` | None |
| **V3** | `torch>=2.0.0` | None |
| **V4** | None (uses torch from V3) | None |
| **V5** | None | None (uses existing `onnxruntime_go`) |

---

## Implementation Order Summary

```
V1 ──────────► V2 ──────────► V3 ──────────► V4 ──────────► V5
State          Markov/HMM     LSTM            Transformer    Go Integration
Foundation     + MITRE        + Explainability + Benchmark    + Unified Decision
                                                              + Dashboard
```

Each version is independently deployable. You can stop at any version and have a working system:
- **Stop at V1**: You have state history for offline analysis
- **Stop at V2**: You have baseline forecasts with MITRE mappings
- **Stop at V3**: You have production-grade forecasts with explanations
- **Stop at V4**: You have evidence-based model selection
- **Complete V5**: Full predictive defense system

**Shall I begin implementing VERSION 1?**
