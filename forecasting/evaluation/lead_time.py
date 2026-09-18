"""
Lead-Time Evaluation Module for TurboSH Forecasting Engine (V4).

Provides precise attack event definitions and lead-time analysis with:
- Attack onset, peak, and resolution boundary detection
- Minimum confidence threshold filtering
- Consecutive correct prediction requirements
- False alarm rate computation
- Wilcoxon signed-rank statistical comparison between models

These definitions ensure lead-time results are consistent and reproducible
across different benchmark runs and model comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from forecasting.config import AttackStage, STAGE_NAMES, TIME_STEP_SECONDS


@dataclass
class LeadTimeConfig:
    """
    Precise attack event definitions for consistent lead-time measurement.

    Defines how attack episodes are detected, what counts as a valid
    early warning, and the quality thresholds for filtering predictions.
    """

    surge_threshold: int = AttackStage.SURGE
    """Minimum attack stage index that constitutes an "attack event"."""

    min_confidence: float = 0.0
    """Minimum prediction confidence to count as a valid early warning.
    Set to 0.0 to accept any prediction above random chance."""

    min_consecutive_correct: int = 1
    """Required number of consecutive correct predictions before the
    attack onset to qualify as a valid detection."""

    max_false_alarm_rate: float = 0.30
    """Maximum tolerable false alarm rate. Models exceeding this
    threshold are flagged in the benchmark report."""

    step_seconds: int = TIME_STEP_SECONDS
    """Duration of each timestep in seconds (for converting steps to time)."""


@dataclass
class AttackEpisode:
    """A detected attack episode within a test sequence."""

    sequence_idx: int
    onset_idx: int       # First timestep where true stage >= surge_threshold
    peak_idx: int        # Timestep with highest true stage value
    resolution_idx: int  # Last timestep where true stage >= surge_threshold
    peak_stage: int      # The highest stage value observed


@dataclass
class DetectionResult:
    """Result of early warning detection for a single attack episode."""

    episode: AttackEpisode
    detected: bool
    lead_time_steps: int  # Steps before onset that first correct prediction occurred
    lead_time_seconds: float
    first_correct_idx: int  # Absolute index of first correct prediction
    consecutive_correct: int  # Length of consecutive correct prediction streak


@dataclass
class FalseAlarmMetrics:
    """False alarm analysis for a model's predictions."""

    total_non_attack_windows: int
    false_alarms: int
    false_alarm_rate: float
    false_alarm_by_stage: Dict[int, int]  # Stage → count of false predictions for that stage


@dataclass
class StatTestResult:
    """Result of statistical comparison between two models' lead times."""

    test_name: str
    statistic: float
    p_value: float
    model_a_mean: float
    model_b_mean: float
    is_significant: bool  # p_value < 0.05
    conclusion: str


@dataclass
class LeadTimeResults:
    """Comprehensive lead-time evaluation results for a single model."""

    model_name: str
    config: LeadTimeConfig
    episodes: List[AttackEpisode]
    detections: List[DetectionResult]
    false_alarms: FalseAlarmMetrics
    mean_lead_time_steps: float
    mean_lead_time_seconds: float
    median_lead_time_steps: float
    detection_coverage: float  # Fraction of episodes detected before onset
    total_episodes: int
    detected_episodes: int


class LeadTimeEvaluator:
    """
    Specialized lead-time analysis for attack forecast evaluation.

    Precisely defines attack events (onset, peak, resolution) and measures
    how far in advance each model correctly predicts upcoming attacks.
    """

    def __init__(self, config: Optional[LeadTimeConfig] = None):
        self.config = config or LeadTimeConfig()

    def detect_episodes(
        self,
        true_stages: np.ndarray,
    ) -> List[AttackEpisode]:
        """
        Detect attack episodes from ground truth stage sequences.

        An episode is a contiguous run of timesteps where the true stage
        is >= surge_threshold.

        Args:
            true_stages: Array of shape (N, forecast_horizon) with true stage labels.

        Returns:
            List of AttackEpisode objects.
        """
        episodes: List[AttackEpisode] = []
        n_samples = len(true_stages)
        threshold = self.config.surge_threshold

        # Look at t+1 predictions (column 0) for episode detection
        t1_true = true_stages[:, 0] if true_stages.ndim == 2 else true_stages

        i = 0
        while i < n_samples:
            if t1_true[i] >= threshold:
                onset = i
                peak = i
                peak_stage = int(t1_true[i])

                # Scan forward to find peak and resolution
                j = i + 1
                while j < n_samples and t1_true[j] >= threshold:
                    if t1_true[j] > peak_stage:
                        peak_stage = int(t1_true[j])
                        peak = j
                    j += 1

                resolution = j - 1

                episodes.append(AttackEpisode(
                    sequence_idx=0,  # Flat array; sequence tracking is external
                    onset_idx=onset,
                    peak_idx=peak,
                    resolution_idx=resolution,
                    peak_stage=peak_stage,
                ))
                i = j  # Skip past this episode
            else:
                i += 1

        return episodes

    def evaluate_detections(
        self,
        true_stages: np.ndarray,
        pred_stages: np.ndarray,
        pred_proba: Optional[np.ndarray] = None,
    ) -> List[DetectionResult]:
        """
        For each attack episode, determine if and when the model first
        correctly predicted the attack before onset.

        Args:
            true_stages: (N, horizon) ground truth.
            pred_stages: (N, horizon) model predictions.
            pred_proba: (N, horizon, n_classes) optional probabilities for confidence filtering.

        Returns:
            List of DetectionResult, one per episode.
        """
        episodes = self.detect_episodes(true_stages)
        results: List[DetectionResult] = []
        threshold = self.config.surge_threshold
        min_conf = self.config.min_confidence
        min_consec = self.config.min_consecutive_correct

        t1_true = true_stages[:, 0] if true_stages.ndim == 2 else true_stages
        t1_pred = pred_stages[:, 0] if pred_stages.ndim == 2 else pred_stages

        for episode in episodes:
            onset = episode.onset_idx

            # Look backwards from onset to find earliest correct prediction
            best_lead = 0
            first_correct_idx = -1
            consecutive = 0
            best_consecutive = 0

            # Scan the window before onset
            search_start = max(0, onset - 20)  # Look back up to 20 steps
            for idx in range(onset - 1, search_start - 1, -1):
                if idx < 0:
                    break

                predicted_attack = t1_pred[idx] >= threshold

                # Check confidence threshold if probabilities are available
                if predicted_attack and pred_proba is not None:
                    proba = pred_proba[idx, 0] if pred_proba.ndim == 3 else pred_proba[idx]
                    predicted_stage = int(t1_pred[idx])
                    stage_conf = float(proba[predicted_stage]) if 0 <= predicted_stage < len(proba) else float(np.max(proba))
                    if stage_conf < min_conf:
                        predicted_attack = False

                if predicted_attack:
                    consecutive += 1
                    if consecutive >= min_consec:
                        lead = onset - idx
                        if lead > best_lead:
                            best_lead = lead
                            first_correct_idx = idx
                            best_consecutive = consecutive
                else:
                    consecutive = 0

            results.append(DetectionResult(
                episode=episode,
                detected=best_lead > 0,
                lead_time_steps=best_lead,
                lead_time_seconds=best_lead * self.config.step_seconds,
                first_correct_idx=first_correct_idx,
                consecutive_correct=best_consecutive,
            ))

        return results

    def compute_false_alarms(
        self,
        true_stages: np.ndarray,
        pred_stages: np.ndarray,
        valid_detections: Optional[List[DetectionResult]] = None,
    ) -> FalseAlarmMetrics:
        """
        Compute false alarm rate: fraction of non-attack windows where the
        model incorrectly predicts an attack outside of valid early detection windows.

        Args:
            true_stages: (N, horizon) ground truth.
            pred_stages: (N, horizon) model predictions.
            valid_detections: Optional list of DetectionResult from evaluate_detections.
                             If provided, predictions that qualify as valid early
                             detections are excluded from false alarms.

        Returns:
            FalseAlarmMetrics with rate and per-stage breakdown.
        """
        threshold = self.config.surge_threshold
        t1_true = true_stages[:, 0] if true_stages.ndim == 2 else true_stages
        t1_pred = pred_stages[:, 0] if pred_stages.ndim == 2 else pred_stages

        non_attack_mask = t1_true < threshold
        total_non_attack = int(np.sum(non_attack_mask))

        if total_non_attack == 0:
            return FalseAlarmMetrics(
                total_non_attack_windows=0,
                false_alarms=0,
                false_alarm_rate=0.0,
                false_alarm_by_stage={},
            )

        # Exclude predictions that qualify as valid early detections in evaluate_detections
        valid_indices = set()
        if valid_detections is not None:
            for d in valid_detections:
                if d.detected and d.first_correct_idx is not None:
                    # Valid early detection window: from first_correct_idx to episode onset
                    for idx in range(d.first_correct_idx, d.episode.onset_idx):
                        valid_indices.add(idx)

        false_alarm_mask = np.zeros(len(t1_pred), dtype=bool)
        for i in range(len(t1_pred)):
            if non_attack_mask[i] and t1_pred[i] >= threshold and i not in valid_indices:
                false_alarm_mask[i] = True

        false_alarms = int(np.sum(false_alarm_mask))

        # Per-stage breakdown
        fa_by_stage: Dict[int, int] = {}
        for stage in range(len(STAGE_NAMES)):
            if stage >= threshold:
                fa_by_stage[stage] = int(np.sum(
                    false_alarm_mask & (t1_pred == stage)
                ))

        return FalseAlarmMetrics(
            total_non_attack_windows=total_non_attack,
            false_alarms=false_alarms,
            false_alarm_rate=float(false_alarms / total_non_attack),
            false_alarm_by_stage=fa_by_stage,
        )

    def compute_lead_times(
        self,
        true_stages: np.ndarray,
        pred_stages: np.ndarray,
        pred_proba: Optional[np.ndarray] = None,
        model_name: str = "Model",
    ) -> LeadTimeResults:
        """
        Full lead-time evaluation for a single model.

        Args:
            true_stages: (N, horizon) ground truth.
            pred_stages: (N, horizon) model predictions.
            pred_proba: Optional (N, horizon, n_classes) probabilities.
            model_name: Human-readable model name.

        Returns:
            LeadTimeResults with all metrics.
        """
        episodes = self.detect_episodes(true_stages)
        detections = self.evaluate_detections(true_stages, pred_stages, pred_proba)
        false_alarms = self.compute_false_alarms(true_stages, pred_stages, valid_detections=detections)

        detected_leads = [d.lead_time_steps for d in detections if d.detected]
        detected_count = len(detected_leads)
        total_episodes = len(episodes)

        mean_lt_steps = float(np.mean(detected_leads)) if detected_leads else 0.0
        median_lt_steps = float(np.median(detected_leads)) if detected_leads else 0.0
        coverage = detected_count / total_episodes if total_episodes > 0 else 0.0

        return LeadTimeResults(
            model_name=model_name,
            config=self.config,
            episodes=episodes,
            detections=detections,
            false_alarms=false_alarms,
            mean_lead_time_steps=round(mean_lt_steps, 2),
            mean_lead_time_seconds=round(mean_lt_steps * self.config.step_seconds, 1),
            median_lead_time_steps=round(median_lt_steps, 2),
            detection_coverage=round(coverage, 4),
            total_episodes=total_episodes,
            detected_episodes=detected_count,
        )

    def cumulative_detection_curve(
        self,
        lead_times: List[int],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute cumulative detection curve: what fraction of attacks are
        detected by each lead-time horizon.

        Args:
            lead_times: List of lead-time steps for detected episodes.

        Returns:
            (x_steps, y_fraction) where x is lead time in steps and
            y is cumulative fraction of attacks detected.
        """
        if not lead_times:
            return np.array([0]), np.array([0.0])

        max_lead = max(lead_times)
        x = np.arange(0, max_lead + 1)
        y = np.array([sum(1 for lt in lead_times if lt >= l) / len(lead_times) for l in x])

        return x, y

    @staticmethod
    def statistical_comparison(
        times_a: List[float],
        times_b: List[float],
        model_a_name: str = "Model A",
        model_b_name: str = "Model B",
    ) -> StatTestResult:
        """
        Wilcoxon signed-rank test: is one model's lead time significantly
        better than another's?

        Requires paired observations (same attack episodes evaluated by both
        models). If fewer than 10 paired observations, the test is unreliable.

        Args:
            times_a: Lead times from model A for shared episodes.
            times_b: Lead times from model B for shared episodes.
            model_a_name: Name of model A.
            model_b_name: Name of model B.

        Returns:
            StatTestResult with test statistic, p-value, and conclusion.
        """
        from scipy import stats

        n = min(len(times_a), len(times_b))
        if n < 5:
            return StatTestResult(
                test_name="Wilcoxon Signed-Rank",
                statistic=0.0,
                p_value=1.0,
                model_a_mean=float(np.mean(times_a)) if times_a else 0.0,
                model_b_mean=float(np.mean(times_b)) if times_b else 0.0,
                is_significant=False,
                conclusion=f"Insufficient paired observations (n={n}, need ≥5) for statistical test.",
            )

        a = np.array(times_a[:n], dtype=np.float64)
        b = np.array(times_b[:n], dtype=np.float64)

        # Check if all differences are zero (Wilcoxon can't handle this)
        diffs = a - b
        if np.all(diffs == 0):
            return StatTestResult(
                test_name="Wilcoxon Signed-Rank",
                statistic=0.0,
                p_value=1.0,
                model_a_mean=float(np.mean(a)),
                model_b_mean=float(np.mean(b)),
                is_significant=False,
                conclusion=f"No difference between {model_a_name} and {model_b_name} lead times.",
            )

        try:
            stat, p_value = stats.wilcoxon(a, b, alternative="two-sided")
        except ValueError:
            return StatTestResult(
                test_name="Wilcoxon Signed-Rank",
                statistic=0.0,
                p_value=1.0,
                model_a_mean=float(np.mean(a)),
                model_b_mean=float(np.mean(b)),
                is_significant=False,
                conclusion="Wilcoxon test could not be computed (possible tied ranks).",
            )

        is_sig = bool(p_value < 0.05)
        mean_a = float(np.mean(a))
        mean_b = float(np.mean(b))

        if is_sig:
            better = model_a_name if mean_a > mean_b else model_b_name
            conclusion = (
                f"{better} provides significantly earlier detection "
                f"(p={p_value:.4f}, {model_a_name} mean={mean_a:.1f}s, "
                f"{model_b_name} mean={mean_b:.1f}s)."
            )
        else:
            conclusion = (
                f"No statistically significant difference between {model_a_name} "
                f"and {model_b_name} lead times (p={p_value:.4f})."
            )

        return StatTestResult(
            test_name="Wilcoxon Signed-Rank",
            statistic=float(stat),
            p_value=float(p_value),
            model_a_mean=mean_a,
            model_b_mean=mean_b,
            is_significant=is_sig,
            conclusion=conclusion,
        )
