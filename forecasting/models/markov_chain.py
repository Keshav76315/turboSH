"""
Discrete-time first-order Markov Chain model for attack-stage forecasting.
"""

import json
import os
from typing import Dict, List, Optional
import numpy as np

from forecasting.config import AttackStage


class MarkovChain:
    """
    First-order Markov Chain model representing transitions between attack stages:
    NORMAL (0), RECON (1), ESCALATION (2), SURGE (3), SUSTAINED (4).
    """

    def __init__(self, n_states: int = 5):
        self.n_states = n_states
        # Default initialization: uniform transition matrix
        self.transition_matrix = np.full(
            (n_states, n_states), 1.0 / n_states, dtype=np.float64
        )
        self.is_fitted = False

    def fit(
        self,
        state_sequences: List[List[int]],
        smoothing_alpha: float = 1.0,
    ) -> "MarkovChain":
        """
        Fit transition probability matrix from observed state sequences.
        Applies Laplace (additive) smoothing to prevent zero probabilities.
        """
        counts = np.zeros((self.n_states, self.n_states), dtype=np.float64)

        for seq in state_sequences:
            if not seq or len(seq) < 2:
                continue
            for t in range(len(seq) - 1):
                from_state = int(seq[t])
                to_state = int(seq[t + 1])
                if 0 <= from_state < self.n_states and 0 <= to_state < self.n_states:
                    counts[from_state, to_state] += 1.0

        # Apply smoothing and normalize
        smoothed = counts + smoothing_alpha
        row_sums = smoothed.sum(axis=1, keepdims=True)
        self.transition_matrix = smoothed / row_sums
        self.is_fitted = True
        return self

    def predict(self, current_state: int) -> int:
        """Predict the most likely next state (t+1)."""
        if not (0 <= current_state < self.n_states):
            return int(AttackStage.NORMAL)
        return int(np.argmax(self.transition_matrix[current_state]))

    def predict_proba(self, current_state: int) -> Dict[int, float]:
        """Return probability distribution over next states P(S_{t+1} = j | S_t = current_state)."""
        if not (0 <= current_state < self.n_states):
            probs = np.full(self.n_states, 1.0 / self.n_states)
        else:
            probs = self.transition_matrix[current_state]

        return {s: float(probs[s]) for s in range(self.n_states)}

    def predict_trajectory(self, current_state: int, steps: int = 3) -> List[int]:
        """
        Multi-step forecasting for t+1, t+2, ..., t+steps.
        Returns the argmax state at each horizon step computed via matrix powers.
        """
        trajectory: List[int] = []
        if not (0 <= current_state < self.n_states):
            return [int(AttackStage.NORMAL)] * steps

        # Initial state distribution vector (one-hot)
        state_vec = np.zeros(self.n_states, dtype=np.float64)
        state_vec[current_state] = 1.0

        for _ in range(steps):
            state_vec = state_vec @ self.transition_matrix
            trajectory.append(int(np.argmax(state_vec)))

        return trajectory

    def predict_trajectory_proba(
        self, current_state: int, steps: int = 3
    ) -> List[Dict[int, float]]:
        """Return full probability distributions for future steps t+1, ..., t+steps."""
        distributions: List[Dict[int, float]] = []
        if not (0 <= current_state < self.n_states):
            uniform = {s: 1.0 / self.n_states for s in range(self.n_states)}
            return [uniform] * steps

        state_vec = np.zeros(self.n_states, dtype=np.float64)
        state_vec[current_state] = 1.0

        for _ in range(steps):
            state_vec = state_vec @ self.transition_matrix
            distributions.append({s: float(state_vec[s]) for s in range(self.n_states)})

        return distributions

    def save(self, file_path: str) -> None:
        """Serialize model to JSON file."""
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        data = {
            "n_states": self.n_states,
            "transition_matrix": self.transition_matrix.tolist(),
            "is_fitted": self.is_fitted,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, file_path: str) -> "MarkovChain":
        """Load serialized model from JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        mc = cls(n_states=data.get("n_states", 5))
        mc.transition_matrix = np.array(data["transition_matrix"], dtype=np.float64)
        mc.is_fitted = data.get("is_fitted", True)
        return mc
