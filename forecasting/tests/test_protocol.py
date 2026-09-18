"""
Unit tests for ForecastModel protocol and adapters (forecasting/models/protocol.py).
"""

import os
import tempfile
import numpy as np
import pytest
import torch

from forecasting.config import FEATURE_NAMES, FORECAST_HORIZON, STAGE_NAMES
from forecasting.models.protocol import (
    ForecastModel,
    HMMAdapter,
    InferenceTimingResult,
    LSTMAdapter,
    MarkovChainAdapter,
    TransformerAdapter,
    measure_inference_latency,
)
from forecasting.models.markov_chain import MarkovChain
from forecasting.models.hmm_model import HMMForecaster
from forecasting.models.lstm_model import LSTMForecaster
from forecasting.models.transformer_model import TransformerForecaster


class TestProtocolAndAdapters:
    """Test suite ensuring all adapters satisfy ForecastModel and produce valid outputs."""

    def test_protocol_isinstance(self):
        mc_adapter = MarkovChainAdapter()
        hmm_adapter = HMMAdapter()
        lstm_adapter = LSTMAdapter()
        tx_adapter = TransformerAdapter()

        assert isinstance(mc_adapter, ForecastModel)
        assert isinstance(hmm_adapter, ForecastModel)
        assert isinstance(lstm_adapter, ForecastModel)
        assert isinstance(tx_adapter, ForecastModel)

    def test_lstm_adapter_inference(self):
        model = LSTMForecaster(input_size=6, hidden_size=32, num_layers=1, forecast_horizon=3)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "lstm.pt")
            model.save(path)

            adapter = LSTMAdapter(forecast_horizon=3)
            adapter.load(path)

            assert adapter.model_name == "LSTM World Model"
            assert adapter.get_model_size_bytes() > 0

            seq = np.random.randn(10, 6).astype(np.float32)
            preds = adapter.predict(seq)
            assert preds.shape == (3,)
            assert np.all((preds >= 0) & (preds < 5))

            probs = adapter.predict_proba(seq)
            assert probs.shape == (3, 5)
            np.testing.assert_allclose(probs.sum(axis=-1), np.ones(3), atol=1e-5)

            batch_seq = np.random.randn(4, 10, 6).astype(np.float32)
            batch_preds = adapter.predict_batch(batch_seq)
            assert batch_preds.shape == (4, 3)

            batch_probs = adapter.predict_proba_batch(batch_seq)
            assert batch_probs.shape == (4, 3, 5)

    def test_transformer_adapter_inference(self):
        model = TransformerForecaster(
            input_size=6, d_model=32, nhead=2, num_layers=1, forecast_horizon=3
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "transformer.pt")
            model.save(path)

            adapter = TransformerAdapter(forecast_horizon=3)
            adapter.load(path)

            assert adapter.model_name == "Transformer"
            assert adapter.get_model_size_bytes() > 0

            seq = np.random.randn(10, 6).astype(np.float32)
            preds = adapter.predict(seq)
            assert preds.shape == (3,)

            probs = adapter.predict_proba(seq)
            assert probs.shape == (3, 5)
            np.testing.assert_allclose(probs.sum(axis=-1), np.ones(3), atol=1e-5)

            batch_seq = np.random.randn(4, 10, 6).astype(np.float32)
            batch_preds = adapter.predict_batch(batch_seq)
            assert batch_preds.shape == (4, 3)

            batch_probs = adapter.predict_proba_batch(batch_seq)
            assert batch_probs.shape == (4, 3, 5)

    def test_markov_adapter_inference(self):
        # Create a trained MarkovChain
        mc = MarkovChain(n_states=5)
        # Add transitions
        sequences = [[0, 1, 2, 3, 4], [0, 1, 2, 3, 4]]
        mc.fit(sequences)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "mc.json")
            mc.save(path)

            adapter = MarkovChainAdapter(n_states=5, forecast_horizon=3)
            adapter.load(path)
            assert adapter.model_name == "Markov Chain"
            assert adapter.get_model_size_bytes() > 0

            seq = np.random.randn(10, 6).astype(np.float32)
            preds = adapter.predict(seq)
            assert preds.shape == (3,)

            probs = adapter.predict_proba(seq)
            assert probs.shape == (3, 5)
            np.testing.assert_allclose(probs.sum(axis=-1), np.ones(3), atol=1e-5)

    def test_hmm_adapter_inference(self):
        hmm = HMMForecaster(n_hidden_states=5, n_features=6)
        obs_seqs = [
            np.random.randn(5, 6).tolist(),
            np.random.randn(5, 6).tolist(),
        ]
        st_seqs = [
            [0, 1, 2, 3, 4],
            [0, 1, 2, 3, 4],
        ]
        hmm.fit(obs_seqs, st_seqs)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "hmm.json")
            hmm.save(path)

            adapter = HMMAdapter(n_states=5, forecast_horizon=3)
            adapter.load(path)
            assert adapter.model_name == "Gaussian HMM"
            assert adapter.get_model_size_bytes() > 0

            seq = np.random.randn(10, 6).astype(np.float32)
            preds = adapter.predict(seq)
            assert preds.shape == (3,)

            probs = adapter.predict_proba(seq)
            assert probs.shape == (3, 5)
            np.testing.assert_allclose(probs.sum(axis=-1), np.ones(3), atol=1e-4)

    def test_measure_inference_latency(self):
        model = TransformerForecaster(
            input_size=6, d_model=32, nhead=2, num_layers=1, forecast_horizon=3
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "model.pt")
            model.save(path)

            adapter = TransformerAdapter(forecast_horizon=3)
            adapter.load(path)

            sample_input = np.random.randn(10, 6).astype(np.float32)
            timing = measure_inference_latency(
                adapter, sample_input, num_runs=10, warmup_runs=2
            )

            assert isinstance(timing, InferenceTimingResult)
            assert timing.num_runs == 10
            assert timing.warmup_runs == 2
            assert timing.median_ms > 0
            assert timing.min_ms <= timing.median_ms <= timing.max_ms
