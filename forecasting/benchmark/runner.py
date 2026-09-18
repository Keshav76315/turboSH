"""
V4 Benchmark Runner — Head-to-Head Model Competition for TurboSH Forecasting Engine.

Benchmarks all four models (Markov, HMM, LSTM, Transformer) under identical
conditions and selects the production model using a predefined selection rule.

Benchmark Integrity Guarantees:
- All models use identical train/val/test splits (same seed, same data pipeline).
- Temporal ordering is preserved (sequence-level splits).
- Feature scaling is fitted ONLY on the training set.
- Inference latency is measured under identical hardware conditions.
- Model size and memory usage are measured consistently.
- Class imbalance is reported.
- The production model is described as a "candidate" until the benchmark completes.

CLI:
    python -m forecasting.benchmark.runner \\
        --data datasets/labeled_states.csv \\
        --models markov,hmm,lstm,transformer \\
        --output docs/forecast_benchmark_v4.md
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import sys
import time
import tracemalloc
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from forecasting.config import (
    AttackStage,
    FEATURE_NAMES,
    FORECAST_HORIZON,
    STAGE_NAMES,
    TIME_STEP_SECONDS,
)
from forecasting.evaluation.evaluator import EvaluationMetrics, ForecastEvaluator
from forecasting.evaluation.lead_time import (
    LeadTimeConfig,
    LeadTimeEvaluator,
    LeadTimeResults,
)
from forecasting.models.data_loader import (
    FeatureScaler,
    StateSequenceDataset,
    create_dataloaders,
)
from forecasting.models.protocol import (
    ForecastModel,
    HMMAdapter,
    LSTMAdapter,
    MarkovChainAdapter,
    TransformerAdapter,
    InferenceTimingResult,
    measure_inference_latency,
)


@dataclass
class SelectionRule:
    """
    Predefined production model selection criteria.

    Models must pass all threshold gates before being compared on
    composite operational score.
    """
    min_f1_macro: float = 0.45
    max_false_positive_rate: float = 0.30
    max_inference_latency_ms: float = 5.0
    # Weights for composite score (forecast quality, lead time, deployment)
    weight_accuracy: float = 0.30
    weight_f1: float = 0.25
    weight_lead_time: float = 0.25
    weight_latency: float = 0.10
    weight_coverage: float = 0.10


@dataclass
class ModelBenchmarkResult:
    """Complete benchmark results for a single model."""
    model_name: str
    multistep_metrics: Dict[int, EvaluationMetrics]
    lead_time_results: Optional[LeadTimeResults]
    timing: Optional[InferenceTimingResult]
    model_size_bytes: int
    peak_memory_mb: float
    # Derived scores
    passes_thresholds: bool = True
    composite_score: float = 0.0
    disqualification_reasons: List[str] = field(default_factory=list)


@dataclass
class BenchmarkConfig:
    """Configuration for the benchmark run."""
    data_path: str = "datasets/labeled_states.csv"
    output_path: str = "docs/forecast_benchmark_v4.md"
    models_dir: str = "models/forecasting"
    seed: int = 42
    seq_len: int = 10
    batch_size: int = 32
    selection_rule: SelectionRule = field(default_factory=SelectionRule)
    lead_time_config: LeadTimeConfig = field(default_factory=LeadTimeConfig)


class BenchmarkRunner:
    """
    Head-to-head model competition runner.

    Evaluates all models under identical conditions and selects the
    production model using predefined criteria.
    """

    def __init__(self, config: Optional[BenchmarkConfig] = None):
        self.config = config or BenchmarkConfig()
        self.evaluator = ForecastEvaluator(n_states=len(STAGE_NAMES))
        self.lead_evaluator = LeadTimeEvaluator(self.config.lead_time_config)
        self.results: Dict[str, ModelBenchmarkResult] = {}
        self._scaler: Optional[FeatureScaler] = None
        self._test_dataset: Optional[StateSequenceDataset] = None

    def _load_data(self) -> Tuple[Any, Any, Any, FeatureScaler]:
        """Load data with identical splits for all models."""
        print("[Benchmark] Loading data with identical splits...")
        train_loader, val_loader, test_loader, scaler = create_dataloaders(
            csv_path=self.config.data_path,
            seq_len=self.config.seq_len,
            forecast_horizon=FORECAST_HORIZON,
            batch_size=self.config.batch_size,
            train_ratio=0.70,
            val_ratio=0.15,
            test_ratio=0.15,
            random_seed=self.config.seed,
        )
        self._scaler = scaler
        self._test_dataset = test_loader.dataset

        # Report class distribution
        all_y = self._test_dataset.samples_y
        print(f"  Test samples: {len(all_y)}")
        print(f"  Class distribution (t+1):")
        unique, counts = np.unique(all_y[:, 0], return_counts=True)
        for u, c in zip(unique, counts):
            name = STAGE_NAMES.get(int(u), f"STAGE_{u}")
            pct = c / len(all_y) * 100
            print(f"    {name}: {c} ({pct:.1f}%)")

        return train_loader, val_loader, test_loader, scaler

    def _build_adapters(
        self,
        model_names: List[str],
    ) -> Dict[str, ForecastModel]:
        """Build and load model adapters."""
        adapters: Dict[str, ForecastModel] = {}
        models_dir = self.config.models_dir

        for name in model_names:
            name_lower = name.lower().strip()
            try:
                if name_lower == "markov":
                    adapter = MarkovChainAdapter()
                    adapter.load(os.path.join(models_dir, "markov_chain.json"))
                    adapter.set_scaler(self._scaler)
                    # Load HMM for state decoding
                    hmm_path = os.path.join(models_dir, "hmm_model.json")
                    if os.path.exists(hmm_path):
                        hmm_adapter = HMMAdapter()
                        hmm_adapter.load(hmm_path)
                        adapter.set_hmm(hmm_adapter.hmm)
                    adapters[adapter.model_name] = adapter

                elif name_lower == "hmm":
                    adapter = HMMAdapter()
                    adapter.load(os.path.join(models_dir, "hmm_model.json"))
                    adapter.set_scaler(self._scaler)
                    adapters[adapter.model_name] = adapter

                elif name_lower == "lstm":
                    adapter = LSTMAdapter()
                    adapter.load(os.path.join(models_dir, "lstm_model.pt"))
                    adapters[adapter.model_name] = adapter

                elif name_lower == "transformer":
                    adapter = TransformerAdapter()
                    adapter.load(os.path.join(models_dir, "transformer_model.pt"))
                    adapters[adapter.model_name] = adapter

                else:
                    print(f"  Warning: Unknown model '{name}', skipping.")

            except Exception as e:
                print(f"  Warning: Failed to load '{name}': {e}")

        return adapters

    def _evaluate_model(
        self,
        adapter: ForecastModel,
        test_x: np.ndarray,
        test_y: np.ndarray,
    ) -> ModelBenchmarkResult:
        """Evaluate a single model on the shared test set."""
        model_name = adapter.model_name
        print(f"\n  Evaluating: {model_name}")

        # 1. Multi-step predictions
        preds = adapter.predict_batch(test_x)
        multistep_metrics = self.evaluator.evaluate_multistep(test_y, preds)

        for h in [1, 2, 3]:
            m = multistep_metrics[h]
            print(f"    t+{h}: Acc={m.accuracy * 100:.2f}%, F1={m.f1_macro:.4f}")

        # 2. Lead-time analysis
        lead_results = self.lead_evaluator.compute_lead_times(
            test_y, preds, model_name=model_name
        )
        print(f"    Lead time: {lead_results.mean_lead_time_seconds:.1f}s, "
              f"Coverage: {lead_results.detection_coverage * 100:.1f}%")

        # 3. Inference latency
        sample_input = test_x[0]  # Single sample
        timing = measure_inference_latency(adapter, sample_input, num_runs=50, warmup_runs=5)
        print(f"    Latency: {timing.median_ms:.3f}ms (median)")

        # 4. Model size
        model_size = adapter.get_model_size_bytes()
        print(f"    Model size: {model_size / 1024:.1f} KB")

        # 5. Peak memory (approximate)
        tracemalloc.start()
        _ = adapter.predict_batch(test_x[:10])
        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak_mem / (1024 * 1024)

        return ModelBenchmarkResult(
            model_name=model_name,
            multistep_metrics=multistep_metrics,
            lead_time_results=lead_results,
            timing=timing,
            model_size_bytes=model_size,
            peak_memory_mb=round(peak_mb, 2),
        )

    def _apply_selection_rule(self) -> Optional[str]:
        """Apply predefined selection rule to find the best model."""
        rule = self.config.selection_rule
        candidates: Dict[str, float] = {}

        for name, result in self.results.items():
            reasons: List[str] = []

            # Gate 1: Minimum F1
            f1 = result.multistep_metrics[1].f1_macro
            if f1 < rule.min_f1_macro:
                reasons.append(f"F1 {f1:.4f} < threshold {rule.min_f1_macro}")

            # Gate 2: Maximum FPR
            if result.lead_time_results:
                fpr = result.lead_time_results.false_alarms.false_alarm_rate
                if fpr > rule.max_false_positive_rate:
                    reasons.append(f"FPR {fpr:.4f} > threshold {rule.max_false_positive_rate}")

            # Gate 3: Maximum latency
            if result.timing:
                lat = result.timing.median_ms
                if lat > rule.max_inference_latency_ms:
                    reasons.append(f"Latency {lat:.3f}ms > threshold {rule.max_inference_latency_ms}ms")

            if reasons:
                result.passes_thresholds = False
                result.disqualification_reasons = reasons
                print(f"  ✗ {name} DISQUALIFIED: {'; '.join(reasons)}")
                continue

            # Compute composite score for qualifying models
            acc_t1 = result.multistep_metrics[1].accuracy
            lead_secs = result.lead_time_results.mean_lead_time_seconds if result.lead_time_results else 0.0
            coverage = result.lead_time_results.detection_coverage if result.lead_time_results else 0.0
            latency_score = 1.0 - min(1.0, (result.timing.median_ms / rule.max_inference_latency_ms)) if result.timing else 0.5

            composite = (
                rule.weight_accuracy * acc_t1
                + rule.weight_f1 * f1
                + rule.weight_lead_time * min(1.0, lead_secs / 30.0)  # Normalize to 30s max
                + rule.weight_latency * latency_score
                + rule.weight_coverage * coverage
            )

            result.composite_score = round(composite, 4)
            result.passes_thresholds = True
            candidates[name] = composite
            print(f"  ✓ {name} QUALIFIES: composite={composite:.4f}")

        if not candidates:
            print("  ⚠ No model passed all selection thresholds!")
            return None

        best = max(candidates, key=candidates.get)
        print(f"\n  🏆 Selected production model: {best} (score={candidates[best]:.4f})")
        return best

    def _generate_report(
        self,
        selected_model: Optional[str],
        duration: float,
    ) -> str:
        """Generate comprehensive Markdown benchmark report."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        rule = self.config.selection_rule

        lines = [
            "# TurboSH V4 — Model Competition Benchmark Report",
            "",
            f"**Generated**: {timestamp}  ",
            f"**Benchmark Duration**: {duration:.2f} seconds  ",
            f"**Evaluation Mode**: Independent Multi-Horizon Test Set  ",
            f"**Production Selection**: {'**' + selected_model + '**' if selected_model else 'No model selected'}  ",
            "",
            "---",
            "",
            "## 1. Benchmark Configuration",
            "",
            f"- **Dataset**: `{self.config.data_path}`",
            f"- **Random seed**: {self.config.seed}",
            f"- **Sequence length**: {self.config.seq_len}",
            f"- **Forecast horizon**: {FORECAST_HORIZON} steps (t+1, t+2, t+3)",
            f"- **Train/Val/Test split**: 70/15/15 (sequence-level, temporal ordering preserved)",
            f"- **Scaler**: Z-score fitted on training set only",
            "",
        ]

        # Class distribution
        if self._test_dataset is not None:
            all_y = self._test_dataset.samples_y
            lines.extend([
                "### Class Distribution (Test Set, t+1)",
                "",
                "| Stage | Count | Fraction |",
                "|:------|:------|:---------|",
            ])
            unique, counts = np.unique(all_y[:, 0], return_counts=True)
            for u, c in zip(unique, counts):
                name = STAGE_NAMES.get(int(u), f"STAGE_{u}")
                pct = c / len(all_y) * 100
                lines.append(f"| {name} | {c} | {pct:.1f}% |")
            lines.extend(["", "---", ""])

        # Comparative benchmark table
        lines.extend([
            "## 2. Comparative Benchmark",
            "",
            "| Model | t+1 Acc | t+2 Acc | t+3 Acc | Macro F1 (t+1) | Lead Time | Coverage | Latency (ms) | Size (KB) | Score |",
            "|:------|:--------|:--------|:--------|:---------------|:----------|:---------|:-------------|:----------|:------|",
        ])

        for name, r in self.results.items():
            m1 = r.multistep_metrics.get(1)
            m2 = r.multistep_metrics.get(2)
            m3 = r.multistep_metrics.get(3)
            acc1 = f"{m1.accuracy * 100:.2f}%" if m1 else "N/A"
            acc2 = f"{m2.accuracy * 100:.2f}%" if m2 else "N/A"
            acc3 = f"{m3.accuracy * 100:.2f}%" if m3 else "N/A"
            f1 = f"{m1.f1_macro:.4f}" if m1 else "N/A"
            lt = f"{r.lead_time_results.mean_lead_time_seconds:.1f}s" if r.lead_time_results else "N/A"
            cov = f"{r.lead_time_results.detection_coverage * 100:.1f}%" if r.lead_time_results else "N/A"
            lat = f"{r.timing.median_ms:.3f}" if r.timing else "N/A"
            size = f"{r.model_size_bytes / 1024:.1f}" if r.model_size_bytes else "N/A"
            score = f"{r.composite_score:.4f}" if r.passes_thresholds else "DQ"

            marker = " 🏆" if name == selected_model else ""
            lines.append(
                f"| **{name}**{marker} | {acc1} | {acc2} | {acc3} | {f1} | {lt} | {cov} | {lat} | {size} | {score} |"
            )

        lines.extend(["", "---", ""])

        # Per-model detailed stage metrics
        lines.extend(["## 3. Detailed Stage Metrics (t+1)", ""])

        for name, r in self.results.items():
            m1 = r.multistep_metrics.get(1)
            if not m1:
                continue

            lines.extend([
                f"### {name}",
                "",
                "| Stage | Precision | Recall | F1 | Support |",
                "|:------|:----------|:-------|:---|:--------|",
            ])

            for s in range(len(STAGE_NAMES)):
                sm = m1.stage_metrics.get(s, {})
                sname = sm.get("stage_name", f"STAGE_{s}")
                p = sm.get("precision", 0.0)
                rec = sm.get("recall", 0.0)
                f1v = sm.get("f1", 0.0)
                sup = sm.get("support", 0)
                lines.append(f"| {sname} | {p:.4f} | {rec:.4f} | {f1v:.4f} | {sup} |")

            lines.extend([""])

        lines.extend(["---", ""])

        # Lead-time analysis
        lines.extend(["## 4. Lead-Time & False Alarm Analysis", ""])

        lines.extend([
            "| Model | Mean Lead Time | Median Lead Time | Detection Coverage | False Alarm Rate | Passes FPR Gate |",
            "|:------|:---------------|:-----------------|:-------------------|:-----------------|:----------------|",
        ])

        for name, r in self.results.items():
            if r.lead_time_results:
                lt = r.lead_time_results
                fpr = lt.false_alarms.false_alarm_rate
                fpr_pass = "✅" if fpr <= rule.max_false_positive_rate else "❌"
                lines.append(
                    f"| {name} | {lt.mean_lead_time_seconds:.1f}s | "
                    f"{lt.median_lead_time_steps * self.config.lead_time_config.step_seconds:.1f}s | "
                    f"{lt.detection_coverage * 100:.1f}% | {fpr * 100:.1f}% | {fpr_pass} |"
                )

        lines.extend(["", "---", ""])

        # Selection rule summary
        lines.extend([
            "## 5. Production Selection",
            "",
            "### Selection Criteria (Predefined)",
            "",
            f"1. Minimum macro F1 ≥ {rule.min_f1_macro}",
            f"2. Maximum false-positive rate ≤ {rule.max_false_positive_rate * 100:.0f}%",
            f"3. Maximum inference latency ≤ {rule.max_inference_latency_ms:.1f}ms",
            "4. Compare composite operational score (accuracy, F1, lead time, latency, coverage)",
            "",
            "### Results",
            "",
        ])

        for name, r in self.results.items():
            status = "✅ QUALIFIES" if r.passes_thresholds else "❌ DISQUALIFIED"
            lines.append(f"- **{name}**: {status}")
            if r.disqualification_reasons:
                for reason in r.disqualification_reasons:
                    lines.append(f"  - {reason}")
            elif r.passes_thresholds:
                lines.append(f"  - Composite score: {r.composite_score:.4f}")

        lines.extend([""])

        if selected_model:
            selected_lower = selected_model.lower()
            if "transformer" in selected_lower or "lstm" in selected_lower:
                deployment_note = (
                    f"The **{selected_model}** achieved the highest composite operational score "
                    f"among all qualifying candidates and is recommended for ONNX export and "
                    f"production deployment in the Go reverse proxy."
                )
            else:
                deployment_note = (
                    f"The **{selected_model}** achieved the highest composite operational score "
                    f"among all qualifying candidates and is recommended for production deployment "
                    f"via native Go matrix/transition tables (statistical model; neural ONNX export not applicable)."
                )

            lines.extend([
                f"### 🏆 Selected Production Model: **{selected_model}**",
                "",
                deployment_note,
            ])
        else:
            lines.extend([
                "### ⚠ No Production Model Selected",
                "",
                "No model passed all selection threshold gates. Consider adjusting "
                "thresholds or improving model performance.",
            ])

        lines.extend(["", ""])

        report = "\n".join(lines) + "\n"

        # Write report
        os.makedirs(os.path.dirname(os.path.abspath(self.config.output_path)), exist_ok=True)
        with open(self.config.output_path, "w", encoding="utf-8") as f:
            f.write(report)

        return report

    def run(
        self,
        model_names: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Run the full benchmark pipeline.

        Args:
            model_names: List of model names to benchmark.
                Default: ["markov", "hmm", "lstm", "transformer"]

        Returns:
            Name of the selected production model, or None.
        """
        if model_names is None:
            model_names = ["markov", "hmm", "lstm", "transformer"]

        t_start = time.time()

        print("=" * 70)
        print("  TurboSH V4 — Model Competition Benchmark")
        print("=" * 70)

        # 1. Load data (identical for all models)
        self._load_data()

        # 2. Build model adapters
        print("\n[Benchmark] Loading model adapters...")
        adapters = self._build_adapters(model_names)

        if not adapters:
            print("  Error: No models could be loaded!")
            return None

        print(f"  Loaded {len(adapters)} models: {', '.join(adapters.keys())}")

        # 3. Evaluate each model
        test_x = self._test_dataset.samples_x
        test_y = self._test_dataset.samples_y

        print("\n[Benchmark] Evaluating models on identical test set...")
        for name, adapter in adapters.items():
            result = self._evaluate_model(adapter, test_x, test_y)
            self.results[name] = result

        # 4. Apply selection rule
        print("\n[Benchmark] Applying production selection rule...")
        selected = self._apply_selection_rule()

        # 5. Statistical comparison (lead times between top 2)
        sorted_results = sorted(
            [(n, r) for n, r in self.results.items() if r.passes_thresholds],
            key=lambda x: x[1].composite_score,
            reverse=True,
        )

        if len(sorted_results) >= 2:
            name_a, res_a = sorted_results[0]
            name_b, res_b = sorted_results[1]
            if res_a.lead_time_results and res_b.lead_time_results:
                # Pair detections by episode to ensure paired Wilcoxon comparisons align
                det_map_a = {
                    (d.episode.sequence_idx, d.episode.onset_idx): d
                    for d in res_a.lead_time_results.detections
                }
                det_map_b = {
                    (d.episode.sequence_idx, d.episode.onset_idx): d
                    for d in res_b.lead_time_results.detections
                }

                times_a, times_b = [], []
                for ep_key, da in det_map_a.items():
                    if ep_key in det_map_b:
                        db = det_map_b[ep_key]
                        # Preserve shared detected episodes for paired Wilcoxon comparison
                        if da.detected and db.detected:
                            times_a.append(da.lead_time_seconds)
                            times_b.append(db.lead_time_seconds)

                if times_a and times_b:
                    stat_result = LeadTimeEvaluator.statistical_comparison(
                        times_a, times_b, name_a, name_b
                    )
                    print(f"\n  Statistical comparison: {stat_result.conclusion}")

        # 6. Generate report
        duration = time.time() - t_start
        print(f"\n[Benchmark] Generating report at: {self.config.output_path}")
        self._generate_report(selected, duration)

        print("\n" + "=" * 70)
        print(f"  V4 Benchmark Complete in {duration:.2f}s!")
        if selected:
            print(f"  🏆 Selected: {selected}")
        print("=" * 70)

        return selected


def main():
    parser = argparse.ArgumentParser(
        description="Run TurboSH V4 Model Competition Benchmark."
    )
    parser.add_argument("--data", type=str, default="datasets/labeled_states.csv")
    parser.add_argument(
        "--models",
        type=str,
        default="markov,hmm,lstm,transformer",
        help="Comma-separated model names to benchmark",
    )
    parser.add_argument("--output", type=str, default="docs/forecast_benchmark_v4.md")
    parser.add_argument("--models-dir", type=str, default="models/forecasting")
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    config = BenchmarkConfig(
        data_path=args.data,
        output_path=args.output,
        models_dir=args.models_dir,
        seed=args.seed,
    )

    runner = BenchmarkRunner(config)
    model_names = [m.strip() for m in args.models.split(",")]
    runner.run(model_names)


if __name__ == "__main__":
    main()
