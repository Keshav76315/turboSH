"""
Training CLI for TurboSH Forecasting Engine — V2 Baseline Forecaster.

Usage:
    python -m forecasting.train_hmm [--data DATA_DIR] [--output OUTPUT_DIR] [--report REPORT_PATH]

This script:
  1. Generates synthetic labeled training data (or loads from JSONL if available).
  2. Fits both MarkovChain and HMMForecaster models.
  3. Evaluates next-step and multi-step accuracy.
  4. Serializes model artifacts to JSON.
  5. Writes a benchmark evaluation report to Markdown.
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

import numpy as np

# Ensure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from forecasting.config import AttackStage, FEATURE_NAMES, STAGE_NAMES
from forecasting.models.markov_chain import MarkovChain
from forecasting.models.hmm_model import HMMForecaster
from forecasting.state_labeler import label_state, label_sequence
from forecasting.state_store import NetworkState


# ── Synthetic Data Generation ────────────────────────────────────────────────

# Feature centroids for each attack stage (6-dim feature vectors)
STAGE_CENTROIDS = {
    AttackStage.NORMAL:     [2.0,  8.0, 3.5, 0.1, 0.02, 0.5],
    AttackStage.RECON:      [5.0, 18.0, 4.2, 0.3, 0.05, 2.0],
    AttackStage.ESCALATION: [15.0, 50.0, 2.8, 0.5, 0.10, 8.0],
    AttackStage.SURGE:      [60.0, 200.0, 1.5, 0.9, 0.25, 40.0],
    AttackStage.SUSTAINED:  [80.0, 300.0, 1.2, 0.95, 0.30, 55.0],
}

# Noise standard deviation per feature per stage
STAGE_NOISE = {
    AttackStage.NORMAL:     [1.0,  3.0, 0.5, 0.05, 0.01, 0.3],
    AttackStage.RECON:      [2.0,  5.0, 0.8, 0.10, 0.02, 0.8],
    AttackStage.ESCALATION: [5.0, 15.0, 0.6, 0.15, 0.04, 3.0],
    AttackStage.SURGE:      [10.0, 40.0, 0.4, 0.10, 0.05, 8.0],
    AttackStage.SUSTAINED:  [8.0, 30.0, 0.3, 0.05, 0.04, 6.0],
}

# Transition probability matrix for synthetic sequence generation
SYNTHETIC_TRANSITIONS = np.array([
    # NORMAL  RECON  ESCAL  SURGE  SUST
    [0.80,   0.15,  0.04,  0.01,  0.00],  # NORMAL
    [0.10,   0.60,  0.25,  0.05,  0.00],  # RECON
    [0.05,   0.10,  0.50,  0.30,  0.05],  # ESCALATION
    [0.02,   0.03,  0.10,  0.55,  0.30],  # SURGE
    [0.05,   0.02,  0.03,  0.15,  0.75],  # SUSTAINED
], dtype=np.float64)


def generate_synthetic_sequence(
    rng: np.random.Generator, length: int, start_stage: int = 0
) -> Tuple[List[List[float]], List[int]]:
    """Generate a single synthetic observation sequence with stage labels."""
    observations: List[List[float]] = []
    stages: List[int] = []
    current_stage = start_stage

    for _ in range(length):
        centroid = np.array(STAGE_CENTROIDS[current_stage])
        noise_std = np.array(STAGE_NOISE[current_stage])
        obs = (centroid + rng.normal(0, noise_std)).tolist()
        # Clamp non-negative features
        obs = [max(0.0, v) for v in obs]
        observations.append(obs)
        stages.append(current_stage)

        # Transition to next state
        current_stage = rng.choice(5, p=SYNTHETIC_TRANSITIONS[current_stage])

    return observations, stages


def generate_training_data(
    n_sequences: int = 200, min_len: int = 10, max_len: int = 50, seed: int = 42
) -> Tuple[List[List[List[float]]], List[List[int]]]:
    """Generate a full synthetic training dataset."""
    rng = np.random.default_rng(seed)
    all_obs: List[List[List[float]]] = []
    all_stages: List[List[int]] = []

    for _ in range(n_sequences):
        length = rng.integers(min_len, max_len + 1)
        start = rng.choice(5, p=[0.50, 0.20, 0.15, 0.10, 0.05])
        obs, stages = generate_synthetic_sequence(rng, length, start)
        all_obs.append(obs)
        all_stages.append(stages)

    return all_obs, all_stages


# ── Evaluation Utilities ─────────────────────────────────────────────────────


def compute_accuracy(y_true: List[int], y_pred: List[int]) -> float:
    if not y_true:
        return 0.0
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return correct / len(y_true)


def compute_confusion_matrix(y_true: List[int], y_pred: List[int], n_classes: int = 5) -> np.ndarray:
    cm = np.zeros((n_classes, n_classes), dtype=int)
    for t, p in zip(y_true, y_pred):
        if 0 <= t < n_classes and 0 <= p < n_classes:
            cm[t, p] += 1
    return cm


def compute_per_class_metrics(cm: np.ndarray) -> Dict[int, Dict[str, float]]:
    """Compute precision, recall, and F1 per class from confusion matrix."""
    metrics: Dict[int, Dict[str, float]] = {}
    n = cm.shape[0]
    for c in range(n):
        tp = cm[c, c]
        fp = cm[:, c].sum() - tp
        fn = cm[c, :].sum() - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        metrics[c] = {"precision": precision, "recall": recall, "f1": f1}
    return metrics


# ── Training Pipeline ────────────────────────────────────────────────────────


def train_and_evaluate(
    output_dir: str = "models/forecasting",
    data_dir: str = "datasets",
    report_path: str = "docs/forecast_evaluation_v2.md",
) -> Dict[str, Any]:
    """Main training and evaluation pipeline."""
    print("=" * 60)
    print("  TurboSH V2 — Baseline Forecaster Training Pipeline")
    print("=" * 60)

    t_start = time.time()

    # ── 1. Generate synthetic training data ───────────────────────────────
    print("\n[1/5] Generating synthetic training data...")
    train_obs, train_stages = generate_training_data(n_sequences=200, seed=42)
    test_obs, test_stages = generate_training_data(n_sequences=50, seed=99)

    total_train_steps = sum(len(s) for s in train_stages)
    total_test_steps = sum(len(s) for s in test_stages)
    print(f"       Training: {len(train_obs)} sequences, {total_train_steps} total steps")
    print(f"       Test:     {len(test_obs)} sequences, {total_test_steps} total steps")

    # ── 2. Export labeled CSV dataset ─────────────────────────────────────
    print("\n[2/5] Exporting labeled dataset CSV...")
    os.makedirs(data_dir, exist_ok=True)
    csv_path = os.path.join(data_dir, "labeled_states.csv")
    fieldnames = ["sequence_id", "step", "stage_label", "stage_name"] + FEATURE_NAMES
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for seq_id, (obs_seq, st_seq) in enumerate(zip(train_obs, train_stages)):
            for step, (obs, stage) in enumerate(zip(obs_seq, st_seq)):
                row = {
                    "sequence_id": seq_id,
                    "step": step,
                    "stage_label": stage,
                    "stage_name": STAGE_NAMES.get(stage, "UNKNOWN"),
                }
                for fi, fname in enumerate(FEATURE_NAMES):
                    row[fname] = f"{obs[fi]:.6f}"
                writer.writerow(row)
    print(f"       Exported to {csv_path}")

    # ── 3. Train MarkovChain ──────────────────────────────────────────────
    print("\n[3/5] Training Markov Chain model...")
    mc = MarkovChain(n_states=5)
    mc.fit(train_stages, smoothing_alpha=0.5)
    mc_path = os.path.join(output_dir, "markov_chain.json")
    mc.save(mc_path)
    print(f"       Saved to {mc_path}")

    # Evaluate Markov Chain
    mc_y_true: List[int] = []
    mc_y_pred: List[int] = []
    for st_seq in test_stages:
        for t in range(len(st_seq) - 1):
            mc_y_true.append(st_seq[t + 1])
            mc_y_pred.append(mc.predict(st_seq[t]))
    mc_accuracy = compute_accuracy(mc_y_true, mc_y_pred)
    mc_cm = compute_confusion_matrix(mc_y_true, mc_y_pred)
    mc_per_class = compute_per_class_metrics(mc_cm)
    print(f"       Next-step accuracy (test): {mc_accuracy:.2%}")

    # ── 4. Train HMM Forecaster ───────────────────────────────────────────
    print("\n[4/5] Training HMM Forecaster model...")
    hmm = HMMForecaster(n_hidden_states=5, n_features=len(FEATURE_NAMES))
    hmm.fit(train_obs, train_stages, smoothing_alpha=0.5)
    hmm_path = os.path.join(output_dir, "hmm_model.json")
    hmm.save(hmm_path)
    print(f"       Saved to {hmm_path}")

    # Evaluate HMM Viterbi decoding
    hmm_y_true: List[int] = []
    hmm_y_pred: List[int] = []
    for obs_seq, st_seq in zip(test_obs, test_stages):
        path = hmm.viterbi(obs_seq)
        for actual, predicted in zip(st_seq, path):
            hmm_y_true.append(actual)
            hmm_y_pred.append(predicted)
    hmm_accuracy = compute_accuracy(hmm_y_true, hmm_y_pred)
    hmm_cm = compute_confusion_matrix(hmm_y_true, hmm_y_pred)
    hmm_per_class = compute_per_class_metrics(hmm_cm)
    print(f"       Viterbi state decoding accuracy (test): {hmm_accuracy:.2%}")

    # Multi-step forecast evaluation (horizon=3)
    hmm_forecast_true: List[int] = []
    hmm_forecast_pred: List[int] = []
    for obs_seq, st_seq in zip(test_obs, test_stages):
        if len(obs_seq) < 6:
            continue
        # Use first half as context, evaluate forecasts on second half
        split = len(obs_seq) // 2
        context = obs_seq[:split]
        future_true = st_seq[split : split + 3]
        future_pred = hmm.forecast(context, steps=3)
        for ft, fp in zip(future_true, future_pred):
            hmm_forecast_true.append(ft)
            hmm_forecast_pred.append(fp)
    hmm_forecast_accuracy = compute_accuracy(hmm_forecast_true, hmm_forecast_pred)
    print(f"       Multi-step forecast accuracy (h=3): {hmm_forecast_accuracy:.2%}")

    t_elapsed = time.time() - t_start

    # ── 5. Generate Evaluation Report ─────────────────────────────────────
    print(f"\n[5/5] Generating evaluation report -> {report_path}")
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(t_elapsed, 2),
        "train_sequences": len(train_obs),
        "train_steps": total_train_steps,
        "test_sequences": len(test_obs),
        "test_steps": total_test_steps,
        "markov_chain": {
            "accuracy": round(mc_accuracy, 4),
            "per_class": {STAGE_NAMES[k]: {m: round(v, 4) for m, v in metrics.items()} for k, metrics in mc_per_class.items()},
            "confusion_matrix": mc_cm.tolist(),
        },
        "hmm": {
            "viterbi_accuracy": round(hmm_accuracy, 4),
            "forecast_accuracy_h3": round(hmm_forecast_accuracy, 4),
            "per_class": {STAGE_NAMES[k]: {m: round(v, 4) for m, v in metrics.items()} for k, metrics in hmm_per_class.items()},
            "confusion_matrix": hmm_cm.tolist(),
        },
    }

    _write_evaluation_report(results, report_path, mc_cm, hmm_cm)

    print(f"\n{'=' * 60}")
    print(f"  Training complete in {t_elapsed:.1f}s")
    print(f"  Markov Chain accuracy:   {mc_accuracy:.2%}")
    print(f"  HMM Viterbi accuracy:    {hmm_accuracy:.2%}")
    print(f"  HMM Forecast (h=3):      {hmm_forecast_accuracy:.2%}")
    print(f"{'=' * 60}")

    return results


def _write_evaluation_report(
    results: Dict[str, Any],
    report_path: str,
    mc_cm: np.ndarray,
    hmm_cm: np.ndarray,
) -> None:
    """Write evaluation results as a Markdown document."""
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)

    stage_labels = [STAGE_NAMES[i] for i in range(5)]

    def _format_cm(cm: np.ndarray) -> str:
        header = "| True \\ Pred | " + " | ".join(stage_labels) + " |"
        sep = "|" + "|".join(["---"] * 6) + "|"
        rows = [header, sep]
        for i, label in enumerate(stage_labels):
            row_vals = " | ".join(str(cm[i, j]) for j in range(5))
            rows.append(f"| **{label}** | {row_vals} |")
        return "\n".join(rows)

    def _format_metrics(per_class: Dict[str, Dict[str, float]]) -> str:
        header = "| Stage | Precision | Recall | F1 |"
        sep = "|---|---|---|---|"
        rows = [header, sep]
        for stage_name in stage_labels:
            m = per_class.get(stage_name, {"precision": 0, "recall": 0, "f1": 0})
            rows.append(f"| {stage_name} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} |")
        return "\n".join(rows)

    mc_res = results["markov_chain"]
    hmm_res = results["hmm"]

    report = f"""# TurboSH V2 — Forecast Evaluation Report

> Generated: {results['timestamp']}
> Training time: {results['elapsed_seconds']}s

## Dataset Summary

| Metric | Value |
|---|---|
| Training sequences | {results['train_sequences']} |
| Training steps | {results['train_steps']} |
| Test sequences | {results['test_sequences']} |
| Test steps | {results['test_steps']} |

---

## 1. Markov Chain — Next-Step Accuracy

**Overall Accuracy: {mc_res['accuracy']:.2%}**

### Per-Class Metrics

{_format_metrics(mc_res['per_class'])}

### Confusion Matrix

{_format_cm(mc_cm)}

---

## 2. Gaussian HMM — Viterbi State Decoding

**Overall Accuracy: {hmm_res['viterbi_accuracy']:.2%}**

### Per-Class Metrics

{_format_metrics(hmm_res['per_class'])}

### Confusion Matrix

{_format_cm(hmm_cm)}

---

## 3. HMM Multi-Step Forecast (Horizon = 3)

**Accuracy: {hmm_res['forecast_accuracy_h3']:.2%}**

This metric evaluates how well the HMM can predict attack stages 1–3 time steps
into the future, using only observations up to the midpoint of each test sequence.

---

## Model Artifacts

| Model | Path | Status |
|---|---|---|
| Markov Chain | `models/forecasting/markov_chain.json` | ✅ Saved |
| Gaussian HMM | `models/forecasting/hmm_model.json` | ✅ Saved |
| Labeled Dataset | `datasets/labeled_states.csv` | ✅ Exported |

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
"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="TurboSH V2 Baseline Forecaster — Train & Evaluate",
    )
    parser.add_argument(
        "--data", default="datasets", help="Directory for labeled dataset CSV output",
    )
    parser.add_argument(
        "--output", default="models/forecasting", help="Directory for serialized model artifacts",
    )
    parser.add_argument(
        "--report", default="docs/forecast_evaluation_v2.md", help="Path for Markdown evaluation report",
    )
    args = parser.parse_args()
    train_and_evaluate(output_dir=args.output, data_dir=args.data, report_path=args.report)


if __name__ == "__main__":
    main()
