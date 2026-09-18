"""
Unit tests for BenchmarkRunner and SelectionRule (forecasting/benchmark/runner.py).
"""

import os
import tempfile
import numpy as np
import pytest

from forecasting.benchmark.runner import (
    BenchmarkConfig,
    BenchmarkRunner,
    ModelBenchmarkResult,
    SelectionRule,
)
from forecasting.evaluation.evaluator import EvaluationMetrics
from forecasting.evaluation.lead_time import (
    FalseAlarmMetrics,
    LeadTimeConfig,
    LeadTimeResults,
)
from forecasting.models.protocol import InferenceTimingResult


def _mock_eval_metrics(f1: float, acc: float) -> EvaluationMetrics:
    cm = [[0] * 5 for _ in range(5)]
    stage_m = {s: {"precision": f1, "recall": f1, "f1": f1, "support": 20} for s in range(5)}
    return EvaluationMetrics(
        accuracy=acc,
        precision_macro=f1,
        recall_macro=f1,
        f1_macro=f1,
        stage_metrics=stage_m,
        confusion_matrix=cm,
        mean_lead_time_steps=1.0,
        mean_lead_time_seconds=10.0,
        total_samples=100,
    )


def _mock_lead_time(fpr: float, lead_secs: float, coverage: float) -> LeadTimeResults:
    fa = FalseAlarmMetrics(
        total_non_attack_windows=100,
        false_alarms=int(fpr * 100),
        false_alarm_rate=fpr,
        false_alarm_by_stage={},
    )
    return LeadTimeResults(
        model_name="MockModel",
        config=LeadTimeConfig(),
        episodes=[],
        detections=[],
        false_alarms=fa,
        mean_lead_time_steps=lead_secs / 10.0,
        mean_lead_time_seconds=lead_secs,
        median_lead_time_steps=lead_secs / 10.0,
        detection_coverage=coverage,
        total_episodes=5,
        detected_episodes=int(coverage * 5),
    )


def _mock_timing(lat_ms: float) -> InferenceTimingResult:
    return InferenceTimingResult(
        median_ms=lat_ms,
        mean_ms=lat_ms,
        std_ms=0.1,
        min_ms=lat_ms - 0.1,
        max_ms=lat_ms + 0.1,
        num_runs=50,
        warmup_runs=5,
    )


class TestBenchmarkRunnerSelection:
    """Test suite for threshold gating and composite score selection logic."""

    def test_selection_rule_gating_disqualification(self):
        runner = BenchmarkRunner()

        # Model A fails F1 gate (< 0.45)
        runner.results["Model_LowF1"] = ModelBenchmarkResult(
            model_name="Model_LowF1",
            multistep_metrics={1: _mock_eval_metrics(f1=0.30, acc=0.50)},
            lead_time_results=_mock_lead_time(fpr=0.10, lead_secs=15.0, coverage=0.8),
            timing=_mock_timing(lat_ms=1.5),
            model_size_bytes=10000,
            peak_memory_mb=10.0,
        )

        # Model B fails FPR gate (> 0.30)
        runner.results["Model_HighFPR"] = ModelBenchmarkResult(
            model_name="Model_HighFPR",
            multistep_metrics={1: _mock_eval_metrics(f1=0.70, acc=0.80)},
            lead_time_results=_mock_lead_time(fpr=0.45, lead_secs=20.0, coverage=0.9),
            timing=_mock_timing(lat_ms=1.5),
            model_size_bytes=10000,
            peak_memory_mb=10.0,
        )

        # Model C fails Latency gate (> 5.0ms)
        runner.results["Model_Slow"] = ModelBenchmarkResult(
            model_name="Model_Slow",
            multistep_metrics={1: _mock_eval_metrics(f1=0.80, acc=0.85)},
            lead_time_results=_mock_lead_time(fpr=0.10, lead_secs=20.0, coverage=0.9),
            timing=_mock_timing(lat_ms=12.0),
            model_size_bytes=10000,
            peak_memory_mb=10.0,
        )

        best = runner._apply_selection_rule()
        assert best is None
        assert runner.results["Model_LowF1"].passes_thresholds is False
        assert runner.results["Model_HighFPR"].passes_thresholds is False
        assert runner.results["Model_Slow"].passes_thresholds is False

    def test_selection_rule_picks_best_qualifying_model(self):
        runner = BenchmarkRunner()

        # Model 1 passes all gates, moderate score
        runner.results["Model1"] = ModelBenchmarkResult(
            model_name="Model1",
            multistep_metrics={1: _mock_eval_metrics(f1=0.60, acc=0.70)},
            lead_time_results=_mock_lead_time(fpr=0.15, lead_secs=10.0, coverage=0.7),
            timing=_mock_timing(lat_ms=2.0),
            model_size_bytes=20000,
            peak_memory_mb=12.0,
        )

        # Model 2 passes all gates, higher score
        runner.results["Model2"] = ModelBenchmarkResult(
            model_name="Model2",
            multistep_metrics={1: _mock_eval_metrics(f1=0.85, acc=0.90)},
            lead_time_results=_mock_lead_time(fpr=0.08, lead_secs=25.0, coverage=0.95),
            timing=_mock_timing(lat_ms=1.2),
            model_size_bytes=30000,
            peak_memory_mb=15.0,
        )

        best = runner._apply_selection_rule()
        assert best == "Model2"
        assert runner.results["Model2"].composite_score > runner.results["Model1"].composite_score

    def test_generate_report_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test_report.md")
            runner = BenchmarkRunner(BenchmarkConfig(output_path=out_path))
            runner.results["Model1"] = ModelBenchmarkResult(
                model_name="Model1",
                multistep_metrics={
                    1: _mock_eval_metrics(f1=0.75, acc=0.80),
                    2: _mock_eval_metrics(f1=0.70, acc=0.75),
                    3: _mock_eval_metrics(f1=0.65, acc=0.70),
                },
                lead_time_results=_mock_lead_time(fpr=0.10, lead_secs=20.0, coverage=0.85),
                timing=_mock_timing(lat_ms=1.5),
                model_size_bytes=25000,
                peak_memory_mb=14.0,
            )

            report = runner._generate_report(selected_model="Model1", duration=4.5)
            assert "# TurboSH V4 — Model Competition Benchmark Report" in report
            assert "Model1" in report
            assert "Wilcoxon" in report or "Benchmark Configuration" in report
            assert os.path.exists(out_path)
