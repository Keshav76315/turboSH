"""
Training CLI and Benchmark Pipeline for TurboSH Transformer Forecaster — V4 Model Competition.

Usage:
    python -m forecasting.train_transformer [--epochs 30] [--batch-size 32] [--lr 0.0005]

This script:
  1. Loads sequence data and prepares PyTorch sliding-window DataLoaders (identical pipeline to LSTM).
  2. Trains the TransformerForecaster with early stopping and cosine annealing LR.
  3. Evaluates multi-step forecasting accuracy (t+1, t+2, t+3) on unseen test sequences.
  4. Saves trained model checkpoint.
"""

import argparse
import copy
from datetime import datetime, timezone
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

# Ensure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from forecasting.config import (
    FEATURE_NAMES,
    FORECAST_HORIZON,
    STAGE_NAMES,
)
from forecasting.evaluation.evaluator import ForecastEvaluator
from forecasting.models.data_loader import (
    FeatureScaler,
    StateSequenceDataset,
    create_dataloaders,
)
from forecasting.models.transformer_model import TransformerForecaster


def set_seed(seed: int = 42) -> None:
    """Set random seeds for full reproducibility."""
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def train_transformer_forecaster(
    train_loader: torch.utils.data.DataLoader,
    val_loader: torch.utils.data.DataLoader,
    input_size: int = len(FEATURE_NAMES),
    d_model: int = 128,
    nhead: int = 4,
    num_layers: int = 3,
    dim_feedforward: int = 256,
    num_classes: int = len(STAGE_NAMES),
    forecast_horizon: int = FORECAST_HORIZON,
    epochs: int = 30,
    lr: float = 5e-4,
    patience: int = 8,
    dropout: float = 0.1,
    pooling: str = "last",
    device: Optional[torch.device] = None,
) -> Tuple[TransformerForecaster, Dict[str, List[float]]]:
    """Train TransformerForecaster with early stopping and cosine annealing LR."""
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = TransformerForecaster(
        input_size=input_size,
        d_model=d_model,
        nhead=nhead,
        num_layers=num_layers,
        dim_feedforward=dim_feedforward,
        num_classes=num_classes,
        forecast_horizon=forecast_horizon,
        dropout=dropout,
        pooling=pooling,
    ).to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=epochs, eta_min=1e-6
    )

    history: Dict[str, List[float]] = {
        "train_loss": [],
        "val_loss": [],
        "val_acc_t1": [],
    }

    best_val_loss = float("inf")
    best_weights = None
    epochs_no_improve = 0

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"       Training on device: {device}")
    print(f"       Total parameters: {total_params:,} ({trainable_params:,} trainable)")
    print(f"       Pooling strategy: {pooling}")
    print(f"       Total training batches: {len(train_loader)}, validation batches: {len(val_loader)}")

    for epoch in range(1, epochs + 1):
        # ── Training Phase ───────────────────────────────────────────────
        model.train()
        train_loss = 0.0
        train_count = 0

        for x_b, y_b in train_loader:
            x_b = x_b.to(device)
            y_b = y_b.to(device)

            optimizer.zero_grad()
            logits = model(x_b)  # (batch, forecast_horizon, num_classes)

            loss = 0.0
            for h in range(forecast_horizon):
                loss += criterion(logits[:, h, :], y_b[:, h])
            loss = loss / forecast_horizon

            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            train_loss += loss.item() * x_b.size(0)
            train_count += x_b.size(0)

        epoch_train_loss = train_loss / max(1, train_count)

        # ── Validation Phase ─────────────────────────────────────────────
        model.eval()
        val_loss = 0.0
        val_count = 0
        correct_t1 = 0

        with torch.no_grad():
            for x_v, y_v in val_loader:
                x_v = x_v.to(device)
                y_v = y_v.to(device)

                logits = model(x_v)
                loss = 0.0
                for h in range(forecast_horizon):
                    loss += criterion(logits[:, h, :], y_v[:, h])
                loss = loss / forecast_horizon

                val_loss += loss.item() * x_v.size(0)
                val_count += x_v.size(0)

                preds_t1 = torch.argmax(logits[:, 0, :], dim=-1)
                correct_t1 += (preds_t1 == y_v[:, 0]).sum().item()

        epoch_val_loss = val_loss / max(1, val_count)
        epoch_val_acc_t1 = correct_t1 / max(1, val_count)

        scheduler.step()

        history["train_loss"].append(epoch_train_loss)
        history["val_loss"].append(epoch_val_loss)
        history["val_acc_t1"].append(epoch_val_acc_t1)

        print(
            f"       Epoch {epoch:02d}/{epochs:02d} — "
            f"Train Loss: {epoch_train_loss:.4f} | "
            f"Val Loss: {epoch_val_loss:.4f} | "
            f"Val Acc (t+1): {epoch_val_acc_t1 * 100:.2f}%"
        )

        if epoch_val_loss < best_val_loss:
            best_val_loss = epoch_val_loss
            best_weights = copy.deepcopy(model.state_dict())
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= patience:
                print(f"       Early stopping triggered at epoch {epoch} (no improvement for {patience} epochs).")
                break

    if best_weights is not None:
        model.load_state_dict(best_weights)

    return model, history


def main():
    parser = argparse.ArgumentParser(
        description="Train and evaluate TurboSH Transformer Forecaster."
    )
    parser.add_argument("--data", type=str, default="datasets/labeled_states.csv")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--d-model", type=int, default=128)
    parser.add_argument("--nhead", type=int, default=4)
    parser.add_argument("--num-layers", type=int, default=3)
    parser.add_argument("--dim-feedforward", type=int, default=256)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--pooling", type=str, default="last", choices=["last", "avg"])
    parser.add_argument("--output-dir", type=str, default="models/forecasting")
    parser.add_argument(
        "--evaluate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run multi-horizon test evaluation",
    )
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    print("=" * 70)
    print("  TurboSH V4 — Transformer Forecaster Training Pipeline")
    print("=" * 70)

    set_seed(args.seed)
    t_start = time.time()

    # ── 1. Data Loading ──────────────────────────────────────────────────────
    print("\n[1/4] Loading sequence data and fitting FeatureScaler...")
    train_loader, val_loader, test_loader, scaler = create_dataloaders(
        csv_path=args.data,
        seq_len=10,
        forecast_horizon=FORECAST_HORIZON,
        batch_size=args.batch_size,
        train_ratio=0.70,
        val_ratio=0.15,
        test_ratio=0.15,
        random_seed=args.seed,
    )
    print(f"       Training windows: {len(train_loader.dataset)}")
    print(f"       Validation windows: {len(val_loader.dataset)}")
    print(f"       Test windows: {len(test_loader.dataset)}")

    # ── 2. Train Transformer ─────────────────────────────────────────────────
    print(f"\n[2/4] Training TransformerForecaster ({args.epochs} max epochs, patience {args.patience})...")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, history = train_transformer_forecaster(
        train_loader=train_loader,
        val_loader=val_loader,
        d_model=args.d_model,
        nhead=args.nhead,
        num_layers=args.num_layers,
        dim_feedforward=args.dim_feedforward,
        epochs=args.epochs,
        lr=args.lr,
        patience=args.patience,
        dropout=args.dropout,
        pooling=args.pooling,
        device=device,
    )

    # Save model checkpoint
    os.makedirs(args.output_dir, exist_ok=True)
    model_pt_path = os.path.join(args.output_dir, "transformer_model.pt")
    model.save_weights(model_pt_path)
    print(f"       Saved Transformer weights to: {model_pt_path}")

    # ── 3. Evaluate on Test Set ──────────────────────────────────────────────
    if args.evaluate:
        print("\n[3/4] Running multi-step evaluation on test set...")
        evaluator = ForecastEvaluator(n_states=len(STAGE_NAMES))
        test_dataset = test_loader.dataset

        all_x_scaled = test_dataset.samples_x
        all_y_true = test_dataset.samples_y

        transformer_preds = model.predict(all_x_scaled)
        metrics = evaluator.evaluate_multistep(all_y_true, transformer_preds)

        for h in [1, 2, 3]:
            m = metrics[h]
            print(f"       t+{h}: Accuracy={m.accuracy * 100:.2f}%, F1={m.f1_macro:.4f}")

    # ── 4. Summary ───────────────────────────────────────────────────────────
    t_end = time.time()
    duration = t_end - t_start
    print(f"\n[4/4] Training complete in {duration:.2f}s")

    print("\n" + "=" * 70)
    print(f"  V4 Transformer Training Finished in {duration:.2f}s!")
    print("=" * 70)


if __name__ == "__main__":
    main()
