"""
Unit tests for Lead-Time Evaluation module (forecasting/evaluation/lead_time.py).
"""

import numpy as np
import pytest

from forecasting.config import AttackStage
from forecasting.evaluation.lead_time import (
    AttackEpisode,
    DetectionResult,
    FalseAlarmMetrics,
    LeadTimeConfig,
    LeadTimeEvaluator,
    LeadTimeResults,
    StatTestResult,
)


class TestLeadTimeEvaluator:
    """Test suite for attack event detection, lead-time measurement, and false alarms."""

    def test_detect_episodes(self):
        # Sequence with 2 attack episodes (stage >= SURGE=3)
        # 0: normal, 1: recon, 2: escalation, 3: surge, 4: exfil
        true_stages = np.array([
            [0, 0, 0],  # 0
            [1, 1, 1],  # 1
            [2, 2, 2],  # 2
            [3, 3, 3],  # 3: onset episode 1
            [4, 4, 4],  # 4: peak episode 1
            [3, 3, 3],  # 5: resolution episode 1
            [1, 1, 1],  # 6: back to recon
            [0, 0, 0],  # 7: normal
            [3, 3, 3],  # 8: episode 2 onset, peak, res
            [0, 0, 0],  # 9
        ])

        evaluator = LeadTimeEvaluator()
        episodes = evaluator.detect_episodes(true_stages)

        assert len(episodes) == 2
        # Episode 1
        assert episodes[0].onset_idx == 3
        assert episodes[0].peak_idx == 4
        assert episodes[0].resolution_idx == 5
        assert episodes[0].peak_stage == 4

        # Episode 2
        assert episodes[1].onset_idx == 8
        assert episodes[1].peak_idx == 8
        assert episodes[1].resolution_idx == 8
        assert episodes[1].peak_stage == 3

    def test_evaluate_detections_lead_time(self):
        # Episode onset at index 5
        true_stages = np.zeros((10, 3), dtype=int)
        true_stages[5:8, :] = AttackStage.SURGE  # indices 5, 6, 7

        # Model predicted attack at index 3 (2 steps before onset)
        pred_stages = np.zeros((10, 3), dtype=int)
        pred_stages[3, 0] = AttackStage.SURGE
        pred_stages[4, 0] = AttackStage.SURGE

        evaluator = LeadTimeEvaluator(LeadTimeConfig(step_seconds=10, min_consecutive_correct=1))
        detections = evaluator.evaluate_detections(true_stages, pred_stages)

        assert len(detections) == 1
        d = detections[0]
        assert d.detected is True
        assert d.lead_time_steps == 2  # 5 - 3 = 2 steps before onset
        assert d.lead_time_seconds == 20.0

    def test_min_confidence_filter(self):
        true_stages = np.zeros((10, 3), dtype=int)
        true_stages[5:8, :] = AttackStage.SURGE

        pred_stages = np.zeros((10, 3), dtype=int)
        pred_stages[4, 0] = AttackStage.SURGE

        # Low confidence probabilities: max is 0.4
        pred_proba = np.zeros((10, 3, 5), dtype=float)
        pred_proba[4, 0, AttackStage.SURGE] = 0.4
        pred_proba[4, 0, AttackStage.NORMAL] = 0.6

        # Requiring min_confidence = 0.7 should reject detection
        evaluator_strict = LeadTimeEvaluator(LeadTimeConfig(min_confidence=0.7))
        detections_strict = evaluator_strict.evaluate_detections(true_stages, pred_stages, pred_proba)
        assert detections_strict[0].detected is False

        # Lenient min_confidence should accept detection
        evaluator_lenient = LeadTimeEvaluator(LeadTimeConfig(min_confidence=0.3))
        detections_lenient = evaluator_lenient.evaluate_detections(true_stages, pred_stages, pred_proba)
        assert detections_lenient[0].detected is True

    def test_false_alarms(self):
        # 10 timesteps, indices 0..6 non-attack, 7..9 attack
        true_stages = np.zeros((10, 3), dtype=int)
        true_stages[7:10, :] = AttackStage.SURGE

        # Model gives 2 false alarms at non-attack steps 1 and 2
        pred_stages = np.zeros((10, 3), dtype=int)
        pred_stages[1, 0] = AttackStage.SURGE
        pred_stages[2, 0] = AttackStage.SUSTAINED

        evaluator = LeadTimeEvaluator()
        fa = evaluator.compute_false_alarms(true_stages, pred_stages)

        assert fa.total_non_attack_windows == 7
        assert fa.false_alarms == 2
        np.testing.assert_allclose(fa.false_alarm_rate, 2 / 7, atol=1e-5)
        assert fa.false_alarm_by_stage[AttackStage.SURGE] == 1
        assert fa.false_alarm_by_stage[AttackStage.SUSTAINED] == 1

    def test_compute_lead_times_summary(self):
        true_stages = np.zeros((20, 3), dtype=int)
        true_stages[10:13, :] = AttackStage.SURGE

        pred_stages = np.zeros((20, 3), dtype=int)
        pred_stages[8, 0] = AttackStage.SURGE

        evaluator = LeadTimeEvaluator(LeadTimeConfig(step_seconds=10))
        results = evaluator.compute_lead_times(true_stages, pred_stages, model_name="TestModel")

        assert isinstance(results, LeadTimeResults)
        assert results.model_name == "TestModel"
        assert results.total_episodes == 1
        assert results.detected_episodes == 1
        assert results.detection_coverage == 1.0
        assert results.mean_lead_time_steps == 2.0
        assert results.mean_lead_time_seconds == 20.0

    def test_statistical_comparison(self):
        times_a = [3.0, 4.0, 5.0, 6.0, 5.0, 4.0, 5.0, 6.0, 4.0, 5.0]
        times_b = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 2.0, 1.0]

        res = LeadTimeEvaluator.statistical_comparison(times_a, times_b, "ModelA", "ModelB")
        assert isinstance(res, StatTestResult)
        assert res.model_a_mean > res.model_b_mean
        assert res.is_significant is True
        assert res.p_value < 0.05
