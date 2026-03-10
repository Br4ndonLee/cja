from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.optim import AdamW
from tqdm import tqdm

from .config import load_runtime_config
from .dataset import create_dataloaders
from .features import MODEL_FEATURE_NAMES
from .model import EXTRA_FEATURE_DIM, EfficientNetB0Regressor, save_checkpoint


@dataclass(frozen=True)
class EpochMetrics:
    epoch: int
    train_loss: float
    val_mae: float
    val_rmse: float


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def train_one_epoch(
    model: EfficientNetB0Regressor,
    loader,
    optimizer: AdamW,
    loss_fn: nn.Module,
    device: torch.device,
) -> float:
    model.train()
    total_loss = 0.0

    for images, features, targets in tqdm(loader, desc="train", leave=False):
        images = images.to(device, non_blocking=True)
        features = features.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        predictions = model(images, features)
        loss = loss_fn(predictions, targets)
        loss.backward()
        optimizer.step()

        total_loss += float(loss.item()) * images.size(0)

    return total_loss / len(loader.dataset)


@torch.no_grad()
def evaluate(model: EfficientNetB0Regressor, loader, device: torch.device) -> tuple[float, float]:
    model.eval()
    total_abs_error = 0.0
    total_squared_error = 0.0
    count = 0

    for images, features, targets in tqdm(loader, desc="val", leave=False):
        images = images.to(device, non_blocking=True)
        features = features.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)

        predictions = model(images, features)
        errors = predictions - targets
        total_abs_error += float(errors.abs().sum().item())
        total_squared_error += float((errors ** 2).sum().item())
        count += int(images.size(0))

    mae = total_abs_error / max(count, 1)
    rmse = math.sqrt(total_squared_error / max(count, 1))
    return mae, rmse


def export_onnx_model(
    model: EfficientNetB0Regressor,
    onnx_path: Path,
    image_size: int,
    device: torch.device,
) -> None:
    model.eval()
    onnx_path.parent.mkdir(parents=True, exist_ok=True)

    dummy_image = torch.randn(1, 3, image_size, image_size, device=device)
    dummy_features = torch.randn(1, EXTRA_FEATURE_DIM, device=device)

    torch.onnx.export(
        model,
        (dummy_image, dummy_features),
        onnx_path,
        input_names=["image", "features"],
        output_names=["weight_g"],
        dynamic_axes={
            "image": {0: "batch"},
            "features": {0: "batch"},
            "weight_g": {0: "batch"},
        },
        opset_version=17,
    )


def parse_args() -> argparse.Namespace:
    config = load_runtime_config()
    parser = argparse.ArgumentParser(description="Train the butterhead weight regressor.")
    parser.add_argument(
        "--labels-csv",
        type=Path,
        default=config.label_dir / "butterhead_weights.csv",
        help="CSV with image paths and manual weights in grams.",
    )
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--image-size", type=int, default=config.image_size)
    parser.add_argument("--planting-date", default=None, help="Fallback planting date in YYYY-MM-DD.")
    parser.add_argument("--disable-pretrained", action="store_true", help="Train without ImageNet initialization.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.labels_csv.exists():
        raise SystemExit(f"Label CSV not found: {args.labels_csv}")

    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_loader, val_loader = create_dataloaders(
        label_csv_path=args.labels_csv,
        image_size=args.image_size,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        val_ratio=args.val_ratio,
        seed=args.seed,
        default_planting_date=args.planting_date,
    )

    model = EfficientNetB0Regressor(pretrained=not args.disable_pretrained).to(device)
    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    loss_fn = nn.SmoothL1Loss(beta=5.0)

    config = load_runtime_config()
    checkpoint_path = config.model_dir / "butterhead_weight_efficientnet_b0.pt"
    onnx_path = config.model_dir / "butterhead_weight_efficientnet_b0.onnx"
    metadata_path = onnx_path.with_suffix(".json")

    best_val_mae = float("inf")
    history: list[EpochMetrics] = []

    for epoch in range(1, args.epochs + 1):
        train_loss = train_one_epoch(
            model=model,
            loader=train_loader,
            optimizer=optimizer,
            loss_fn=loss_fn,
            device=device,
        )
        val_mae, val_rmse = evaluate(model=model, loader=val_loader, device=device)
        history.append(
            EpochMetrics(
                epoch=epoch,
                train_loss=train_loss,
                val_mae=val_mae,
                val_rmse=val_rmse,
            )
        )
        print(
            json.dumps(
                {
                    "epoch": epoch,
                    "train_loss": round(train_loss, 4),
                    "val_mae_g": round(val_mae, 4),
                    "val_rmse_g": round(val_rmse, 4),
                },
                sort_keys=True,
            )
        )

        if val_mae < best_val_mae:
            best_val_mae = val_mae
            save_checkpoint(model, checkpoint_path)
            export_onnx_model(model, onnx_path, image_size=args.image_size, device=device)
            metadata_path.write_text(
                json.dumps(
                    {
                        "backbone": "torchvision.models.efficientnet_b0",
                        "image_size": args.image_size,
                        "feature_names": list(MODEL_FEATURE_NAMES),
                        "label_csv": str(args.labels_csv),
                        "planting_date": args.planting_date,
                        "best_val_mae_g": val_mae,
                        "best_val_rmse_g": val_rmse,
                        "trained_at": datetime.now().astimezone().isoformat(),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )

    summary = {
        "best_val_mae_g": best_val_mae,
        "checkpoint_path": str(checkpoint_path),
        "onnx_path": str(onnx_path),
        "history": [asdict(item) for item in history],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0
