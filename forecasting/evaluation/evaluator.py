"""
ForecastEvaluator for evaluating multi-class stage accuracy, confusion matrices, and predictive lead time.
"""

from dataclasses import asdict, dataclass
import os
from typing import Any, Dict, List, Optional
import numpy as np

from forecasting.config import AttackStage, STAGE_NAMES, TIME_STEP_SECONDS


@dataclass
class EvaluationMetrics:
    """Summary of model forecasting performance."""

    accuracy: float
    precision_macro: float
    recall_macro: float
    f1_macro: float
    stage_metrics: Dict[int, Dict[str, float]]
    confusion_matrix: List[List[int]]
    mean_lead_time_steps: float
    mean_lead_time_seconds: float
    total_samples: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ForecastEvaluator:
    """
    Computes statistical evaluation metrics and early-warning lead-time analysis
    for TurboSH forecasting models.
    """

    def __init__(self, n_states: int = 5, step_seconds: int = TIME_STEP_SECONDS):
        self.n_states = n_states
        self.step_seconds = step_seconds

    def evaluate(
        self,
        y_true: List[int],
        y_pred: List[int],
        lead_times: Optional[List[int]] = None,
    ) -> EvaluationMetrics:
        """
        Compute multi-class classification metrics (Accuracy, Precision, Recall, F1, Confusion Matrix).
        """
        if not y_true or len(y_true) != len(y_pred):
            return EvaluationMetrics(
                accuracy=0.0,
                precision_macro=0.0,
                recall_macro=0.0,
                f1_macro=0.0,
                stage_metrics={},
                confusion_matrix=[[0] * self.n_states for _ in range(self.n_states)],
                mean_lead_time_steps=0.0,
                mean_lead_time_seconds=0.0,
                total_samples=0,
            )

        N = len(y_true)
        # Confusion matrix: rows = true, columns = pred
        cm = np.zeros((self.n_states, self.n_states), dtype=np.int64)
        for t, p in zip(y_true, y_pred):
            if 0 <= t < self.n_states and 0 <= p < self.n_states:
                cm[t, p] += 1

        correct = int(np.trace(cm))
        accuracy = float(correct / N) if N > 0 else 0.0

        stage_metrics: Dict[int, Dict[str, float]] = {}
        precisions = []
        recalls = []
        f1s = []

        for s in range(self.n_states):
            tp = float(cm[s, s])
            fp = float(np.sum(cm[:, s]) - tp)
            fn = float(np.sum(cm[s, :]) - tp)
            support = int(np.sum(cm[s, :]))

            prec = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
            rec = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
            f1 = float(2.0 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

            stage_metrics[s] = {
                "stage_name": STAGE_NAMES.get(s, f"STAGE_{s}"),
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "support": support,
            }

            if support > 0:
                precisions.append(prec)
                recalls.append(rec)
                f1s.append(f1)

        prec_macro = float(np.mean(precisions)) if precisions else 0.0
        rec_macro = float(np.mean(recalls)) if recalls else 0.0
        f1_macro = float(np.mean(f1s)) if f1s else 0.0

        # Lead-time computation
        if lead_times:
            valid_lt = [lt for lt in lead_times if lt > 0]
            mean_lt_steps = float(np.mean(valid_lt)) if valid_lt else 0.0
        else:
            mean_lt_steps = 0.0
        mean_lt_seconds = mean_lt_steps * self.step_seconds

        return EvaluationMetrics(
            accuracy=round(accuracy, 4),
            precision_macro=round(prec_macro, 4),
            recall_macro=round(rec_macro, 4),
            f1_macro=round(f1_macro, 4),
            stage_metrics=stage_metrics,
            confusion_matrix=cm.tolist(),
            mean_lead_time_steps=round(mean_lt_steps, 2),
            mean_lead_time_seconds=round(mean_lt_seconds, 1),
            total_samples=N,
        )

    def analyze_lead_times(
        self,
        true_sequences: List[List[int]],
        pred_trajectory_func: Any,
        surge_threshold: int = AttackStage.SURGE,
        horizon: int = 3,
    ) -> List[int]:
        """
        Determine how many steps in advance a surge event (SURGE or SUSTAINED) is anticipated.
        Returns a list of advance lead-time steps (1, 2, or 3) for each detected surge episode.
        """
        lead_times: List[int] = []

        for seq in true_sequences:
            if not seq or len(seq) <= 1:
                continue
            # Find the first index where surge occurs
            surge_indices = [
                i for i, state in enumerate(seq) if state >= surge_threshold
            ]
            if not surge_indices:
                continue
            first_surge_idx = surge_indices[0]

            # Check previous history steps to see when forecast first predicted a surge at first_surge_idx
            max_lead = 0
            for step_back in range(1, min(horizon + 1, first_surge_idx + 1)):
                hist_state = seq[first_surge_idx - step_back]
                # Forecast ahead by step_back steps
                projected_trajectory = pred_trajectory_func(hist_state, steps=step_back)
                if projected_trajectory and projected_trajectory[-1] >= surge_threshold:
                    max_lead = max(max_lead, step_back)

            if max_lead > 0:
                lead_times.append(max_lead)

        return lead_times

    def generate_markdown_report(
        self,
        metrics: EvaluationMetrics,
        model_name: str = "Baseline Forecaster",
        output_path: Optional[str] = None,
    ) -> str:
        """Render evaluation metrics as a GitHub-flavored Markdown table report."""
        lines = [
            f"# {model_name} — Evaluation Report",
            "",
            "## Summary Metrics",
            f"- **Overall Accuracy**: {metrics.accuracy * 100:.2f}%",
            f"- **Macro F1 Score**: {metrics.f1_macro:.4f}",
            f"- **Macro Precision**: {metrics.precision_macro:.4f}",
            f"- **Macro Recall**: {metrics.recall_macro:.4f}",
            f"- **Mean Lead Time**: {metrics.mean_lead_time_seconds:.1f}s ({metrics.mean_lead_time_steps:.2f} time steps)",
            f"- **Total Test Samples**: {metrics.total_samples}",
            "",
            "## Per-Stage Breakdown",
            "| Stage | Name | Precision | Recall | F1 Score | Support |",
            "|:------|:-----|:----------|:-------|:---------|:--------|",
        ]

        for s in range(self.n_states):
            sm = metrics.stage_metrics.get(s, {})
            name = sm.get("stage_name", f"STAGE_{s}")
            p = sm.get("precision", 0.0)
            r = sm.get("recall", 0.0)
            f1 = sm.get("f1", 0.0)
            sup = sm.get("support", 0)
            lines.append(f"| **{s}** | {name} | {p:.4f} | {r:.4f} | {f1:.4f} | {sup} |")

        lines.extend(
            [
                "",
                "## Confusion Matrix",
                "Rows represent True Stages, Columns represent Predicted Stages:",
                "",
                "| True \\ Pred | NORMAL (0) | RECON (1) | ESCALATION (2) | SURGE (3) | SUSTAINED (4) |",
                "|:------------|:-----------|:----------|:---------------|:----------|:--------------|",
            ]
        )

        for s_true in range(self.n_states):
            row_vals = metrics.confusion_matrix[s_true]
            name = STAGE_NAMES.get(s_true, f"STAGE_{s_true}")
            cols_str = " | ".join(str(v) for v in row_vals)
            lines.append(f"| **{name} ({s_true})** | {cols_str} |")

        report_content = "\n".join(lines) + "\n"
        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report_content)

        return report_content

    def evaluate_multistep(
        self,
        y_true_steps: Any,
        y_pred_steps: Any,
    ) -> Dict[int, EvaluationMetrics]:
        """
        Evaluate multi-step forecast accuracy independently for each horizon step (1, 2, 3).
        Returns a dict mapping horizon step (1-indexed) to EvaluationMetrics.
        """
        true_arr = np.asarray(y_true_steps)
        pred_arr = np.asarray(y_pred_steps)
        if true_arr.ndim != 2 or pred_arr.ndim != 2:
            raise ValueError("Expected 2D arrays of shape (N, horizon) for multistep evaluation")
        if true_arr.shape != pred_arr.shape:
            raise ValueError(
                f"Shape mismatch in multistep evaluation: true shape {true_arr.shape} "
                f"does not match pred shape {pred_arr.shape}"
            )

        horizon = true_arr.shape[1]
        results: Dict[int, EvaluationMetrics] = {}
        for h in range(horizon):
            step_true = true_arr[:, h].tolist()
            step_pred = pred_arr[:, h].tolist()
            results[h + 1] = self.evaluate(step_true, step_pred)

        return results

    def accuracy_vs_horizon_curve(
        self,
        multistep_metrics: Dict[int, EvaluationMetrics],
    ) -> List[Dict[str, Any]]:
        """Compute performance trajectory across forecasting horizons."""
        curve: List[Dict[str, Any]] = []
        for step in sorted(multistep_metrics.keys()):
            m = multistep_metrics[step]
            curve.append({
                "horizon_step": step,
                "horizon_label": f"t+{step}",
                "accuracy": m.accuracy,
                "f1_macro": m.f1_macro,
                "precision_macro": m.precision_macro,
                "recall_macro": m.recall_macro,
            })
        return curve

    def compare_models(
        self,
        results: Dict[str, Dict[str, Any]],
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generate a Markdown comparison table across multiple models.
        `results` format:
        {
            "Model Name": {
                "multistep": Dict[int, EvaluationMetrics],  # or list of floats
                "f1_macro": float (optional if in multistep[1]),
                "mean_lead_time_seconds": float (optional),
            }
        }
        """
        lines = [
            "# Model Comparison Benchmark",
            "",
            "| Model | t+1 Accuracy | t+2 Accuracy | t+3 Accuracy | Macro F1 (t+1) | Mean Lead Time |",
            "|:------|:-------------|:-------------|:-------------|:---------------|:---------------|",
        ]

        for model_name, data in results.items():
            multistep = data.get("multistep", {})
            # Handle dictionary of EvaluationMetrics or raw dicts/floats
            if isinstance(multistep, dict):
                m1 = multistep.get(1)
                m2 = multistep.get(2)
                m3 = multistep.get(3)

                acc_1 = f"{m1.accuracy * 100:.2f}%" if isinstance(m1, EvaluationMetrics) else f"{float(m1) * 100:.2f}%" if m1 is not None else "N/A"
                acc_2 = f"{m2.accuracy * 100:.2f}%" if isinstance(m2, EvaluationMetrics) else f"{float(m2) * 100:.2f}%" if m2 is not None else "N/A"
                acc_3 = f"{m3.accuracy * 100:.2f}%" if isinstance(m3, EvaluationMetrics) else f"{float(m3) * 100:.2f}%" if m3 is not None else "N/A"

                f1_val = data.get("f1_macro")
                if f1_val is None and isinstance(m1, EvaluationMetrics):
                    f1_val = m1.f1_macro
                f1_str = f"{float(f1_val):.4f}" if f1_val is not None else "N/A"
            elif isinstance(multistep, (list, tuple)):
                acc_1 = f"{float(multistep[0]) * 100:.2f}%" if len(multistep) > 0 else "N/A"
                acc_2 = f"{float(multistep[1]) * 100:.2f}%" if len(multistep) > 1 else "N/A"
                acc_3 = f"{float(multistep[2]) * 100:.2f}%" if len(multistep) > 2 else "N/A"
                f1_val = data.get("f1_macro")
                f1_str = f"{float(f1_val):.4f}" if f1_val is not None else "N/A"
            else:
                acc_1, acc_2, acc_3, f1_str = "N/A", "N/A", "N/A", "N/A"

            lead_sec = data.get("mean_lead_time_seconds", data.get("lead_time_seconds"))
            lead_str = f"{float(lead_sec):.1f}s" if lead_sec is not None else "N/A"

            lines.append(
                f"| **{model_name}** | {acc_1} | {acc_2} | {acc_3} | {f1_str} | {lead_str} |"
            )

        report = "\n".join(lines) + "\n"
        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)

        return report
