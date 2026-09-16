"""
Hidden Markov Model (Gaussian HMM) for attack intent modeling and multi-step forecasting.
"""

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple
# pyrefly: ignore [missing-import]
import numpy as np
    
from forecasting.config import AttackStage, FEATURE_NAMES


class HMMForecaster:
    """
    Hidden Markov Model with Gaussian emissions.
    Hidden States: AttackStage (0=NORMAL, 1=RECON, 2=ESCALATION, 3=SURGE, 4=SUSTAINED)
    Observations: D-dimensional continuous network telemetry feature vectors.
    """

    def __init__(self, n_hidden_states: int = 5, n_features: int = len(FEATURE_NAMES)):
        self.n_states = n_hidden_states
        self.n_features = n_features

        # Initial state distribution pi
        self.start_prob = np.full(self.n_states, 1.0 / self.n_states, dtype=np.float64)

        # Transition probability matrix A: P(S_{t+1}=j | S_t=i)
        self.transition_matrix = np.full(
            (self.n_states, self.n_states), 1.0 / self.n_states, dtype=np.float64
        )

        # Gaussian emission parameters per hidden state: mean and diagonal variance
        # Default sensible priors for normalized features
        self.means = np.zeros((self.n_states, self.n_features), dtype=np.float64)
        # Add baseline differences across stages for prior
        for s in range(self.n_states):
            self.means[s, :] = float(s) * 0.2
        self.vars = np.ones((self.n_states, self.n_features), dtype=np.float64)

        self.is_fitted = False

    def fit(
        self,
        observation_sequences: List[List[List[float]]],
        state_sequences: List[List[int]],
        smoothing_alpha: float = 1.0,
        variance_floor: float = 1e-4,
    ) -> "HMMForecaster":
        """
        Fit HMM parameters from paired observations and labeled state sequences via MLE.
        """
        if not state_sequences or not observation_sequences:
            return self

        # 1. Estimate initial state distribution pi and transition matrix A
        start_counts = np.zeros(self.n_states, dtype=np.float64)
        trans_counts = np.zeros((self.n_states, self.n_states), dtype=np.float64)

        # Buckets for Gaussian emission estimation per state
        state_observations: Dict[int, List[List[float]]] = {
            s: [] for s in range(self.n_states)
        }

        for obs_seq, st_seq in zip(observation_sequences, state_sequences):
            if not st_seq or len(st_seq) != len(obs_seq):
                continue

            first_state = int(st_seq[0])
            if 0 <= first_state < self.n_states:
                start_counts[first_state] += 1.0

            for t in range(len(st_seq)):
                s = int(st_seq[t])
                if 0 <= s < self.n_states:
                    state_observations[s].append(obs_seq[t])

                if t < len(st_seq) - 1:
                    s_next = int(st_seq[t + 1])
                    if 0 <= s < self.n_states and 0 <= s_next < self.n_states:
                        trans_counts[s, s_next] += 1.0

        # Normalize start probabilities with smoothing
        smoothed_start = start_counts + smoothing_alpha
        self.start_prob = smoothed_start / smoothed_start.sum()

        # Normalize transitions with smoothing
        smoothed_trans = trans_counts + smoothing_alpha
        self.transition_matrix = smoothed_trans / smoothed_trans.sum(axis=1, keepdims=True)

        # 2. Estimate Gaussian emission parameters (mean & diagonal variance) per state
        for s in range(self.n_states):
            obs_list = state_observations[s]
            if obs_list:
                obs_arr = np.array(obs_list, dtype=np.float64)
                self.means[s] = np.mean(obs_arr, axis=0)
                variances = np.var(obs_arr, axis=0)
                self.vars[s] = np.maximum(variances, variance_floor)
            else:
                # Fallback: retain default prior
                self.vars[s] = np.maximum(self.vars[s], variance_floor)

        self.is_fitted = True
        return self

    def _log_gaussian_pdf(self, obs: np.ndarray, s: int) -> float:
        """Compute log Gaussian emission probability log P(obs | state=s)."""
        diff = obs - self.means[s]
        var = self.vars[s]
        # Sum of log 1D Gaussians under diagonal covariance assumption
        log_prob = -0.5 * np.sum(np.log(2.0 * np.pi * var) + (diff ** 2) / var)
        return float(log_prob)

    def viterbi(self, observations: List[List[float]]) -> List[int]:
        """
        Viterbi decoding algorithm to find the most probable sequence of hidden states.
        Uses numerically stable log-domain computations.
        """
        if not observations:
            return []

        T = len(observations)
        obs_arr = np.array(observations, dtype=np.float64)

        log_start = np.log(np.maximum(self.start_prob, 1e-12))
        log_trans = np.log(np.maximum(self.transition_matrix, 1e-12))

        # Viterbi DP tables
        viterbi_table = np.zeros((T, self.n_states), dtype=np.float64)
        backpointer = np.zeros((T, self.n_states), dtype=np.int64)

        # Initialization (t = 0)
        for s in range(self.n_states):
            log_emit = self._log_gaussian_pdf(obs_arr[0], s)
            viterbi_table[0, s] = log_start[s] + log_emit

        # Recursion (t = 1 .. T-1)
        for t in range(1, T):
            for s in range(self.n_states):
                log_emit = self._log_gaussian_pdf(obs_arr[t], s)
                # max over previous state s_prev: viterbi_table[t-1, s_prev] + log_trans[s_prev, s]
                prev_scores = viterbi_table[t - 1] + log_trans[:, s]
                best_prev = int(np.argmax(prev_scores))
                viterbi_table[t, s] = prev_scores[best_prev] + log_emit
                backpointer[t, s] = best_prev

        # Backtracking
        best_path = [0] * T
        best_path[-1] = int(np.argmax(viterbi_table[-1]))
        for t in range(T - 2, -1, -1):
            best_path[t] = int(backpointer[t + 1, best_path[t + 1]])

        return best_path

    def predict(self, observations: List[List[float]]) -> int:
        """Decode the most likely current hidden state S_t for the given sequence of observations."""
        path = self.viterbi(observations)
        if not path:
            return int(AttackStage.NORMAL)
        return path[-1]

    def forecast(self, observations: List[List[float]], steps: int = 3) -> List[int]:
        """
        Forecast future attack stages for t+1, t+2, ..., t+steps given historical observations.
        First decodes the current hidden state, then projects forward using transition dynamics.
        """
        current_state = self.predict(observations)
        state_vec = np.zeros(self.n_states, dtype=np.float64)
        state_vec[current_state] = 1.0

        forecasts: List[int] = []
        for _ in range(steps):
            state_vec = state_vec @ self.transition_matrix
            forecasts.append(int(np.argmax(state_vec)))

        return forecasts

    def forecast_proba(
        self, observations: List[List[float]], steps: int = 3
    ) -> List[Dict[int, float]]:
        """Return probability distributions over future states for each horizon step."""
        current_state = self.predict(observations)
        state_vec = np.zeros(self.n_states, dtype=np.float64)
        state_vec[current_state] = 1.0

        distributions: List[Dict[int, float]] = []
        for _ in range(steps):
            state_vec = state_vec @ self.transition_matrix
            distributions.append({s: float(state_vec[s]) for s in range(self.n_states)})

        return distributions

    def save(self, file_path: str) -> None:
        """Serialize model parameters to JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        data = {
            "n_states": self.n_states,
            "n_features": self.n_features,
            "start_prob": self.start_prob.tolist(),
            "transition_matrix": self.transition_matrix.tolist(),
            "means": self.means.tolist(),
            "vars": self.vars.tolist(),
            "is_fitted": self.is_fitted,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, file_path: str) -> "HMMForecaster":
        """Load serialized model from JSON."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        hmm = cls(
            n_hidden_states=data.get("n_states", 5),
            n_features=data.get("n_features", len(FEATURE_NAMES)),
        )
        hmm.start_prob = np.array(data["start_prob"], dtype=np.float64)
        hmm.transition_matrix = np.array(data["transition_matrix"], dtype=np.float64)
        hmm.means = np.array(data["means"], dtype=np.float64)
        hmm.vars = np.array(data["vars"], dtype=np.float64)
        hmm.is_fitted = data.get("is_fitted", True)
        return hmm
