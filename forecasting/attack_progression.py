"""
Attack progression modeling for tracking threat evolution across stages.
"""

from typing import Dict, List, Optional, Tuple
import numpy as np

from forecasting.config import AttackStage, STAGE_NAMES
from forecasting.models.markov_chain import MarkovChain
from forecasting.state_store import StateStore


class AttackProgressionModel:
    """
    Analyzes attack evolution across stages:
    NORMAL (0) -> RECON (1) -> ESCALATION (2) -> SURGE (3) -> SUSTAINED (4).
    Quantifies escalation risk, de-escalation tendencies, and trajectory confidences.
    """

    def __init__(self, markov_model: MarkovChain):
        self.markov = markov_model
        self.n_states = markov_model.n_states

    @classmethod
    def from_state_store(
        cls, store: StateStore, smoothing_alpha: float = 1.0
    ) -> "AttackProgressionModel":
        """Fit Markov transitions from labeled state sequences in StateStore."""
        sequences = store.get_all_sequences(window_size=4, min_length=2)
        state_seqs: List[List[int]] = []
        for seq in sequences:
            # Extract assigned labels if present, or fallback to NORMAL
            labels = [s.label if s.label is not None else int(AttackStage.NORMAL) for s in seq]
            state_seqs.append(labels)

        mc = MarkovChain(n_states=5)
        if state_seqs:
            mc.fit(state_seqs, smoothing_alpha=smoothing_alpha)

        return cls(markov_model=mc)

    def get_escalation_probability(self, current_stage: int) -> float:
        """
        Compute the probability that the next time step transitions to a higher attack stage:
        P(S_{t+1} > current_stage | S_t = current_stage).
        """
        if not (0 <= current_stage < self.n_states):
            return 0.0
        if current_stage == self.n_states - 1:
            # Already at maximum stage (SUSTAINED)
            return 0.0

        probs = self.markov.transition_matrix[current_stage]
        # Sum probabilities of all strictly higher stages
        return float(np.sum(probs[current_stage + 1 :]))

    def get_deescalation_probability(self, current_stage: int) -> float:
        """
        Compute the probability that the next time step transitions to a lower attack stage:
        P(S_{t+1} < current_stage | S_t = current_stage).
        """
        if not (0 <= current_stage < self.n_states):
            return 0.0
        if current_stage == 0:
            return 0.0

        probs = self.markov.transition_matrix[current_stage]
        return float(np.sum(probs[:current_stage]))

    def get_stability_probability(self, current_stage: int) -> float:
        """Probability of remaining in the current stage: P(S_{t+1} = current_stage | S_t = current_stage)."""
        if not (0 <= current_stage < self.n_states):
            return 1.0
        return float(self.markov.transition_matrix[current_stage, current_stage])

    def get_likely_trajectory(
        self, current_stage: int, horizon: int = 3
    ) -> List[Tuple[int, float]]:
        """
        Predict future attack stages with confidence values:
        Returns [(predicted_stage_t1, confidence_t1), (predicted_stage_t2, confidence_t2), ...]
        """
        trajectory_probs = self.markov.predict_trajectory_proba(current_stage, steps=horizon)
        trajectory: List[Tuple[int, float]] = []

        for prob_dist in trajectory_probs:
            best_stage = max(prob_dist.keys(), key=lambda s: prob_dist[s])
            confidence = prob_dist[best_stage]
            trajectory.append((best_stage, confidence))

        return trajectory

    def is_escalating(self, recent_stages: List[int]) -> bool:
        """
        Detect whether a recent history of stages reflects an active escalation trend.
        Returns True if stages are non-decreasing and the final stage is higher than the starting stage.
        """
        if not recent_stages or len(recent_stages) < 2:
            return False

        # Filter to valid stage values
        stages = [s for s in recent_stages if 0 <= s < self.n_states]
        if len(stages) < 2:
            return False

        # Check for monotonic or net upward movement with no sharp drop
        net_change = stages[-1] - stages[0]
        recent_max = max(stages)
        return net_change > 0 and stages[-1] >= recent_max - 1
