from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .auto_train import maybe_auto_train_feature_model
from .calibration import calibrate_bootstrap_model_to_image
from .config import load_runtime_config


LABEL_COLUMNS = ("image_path", "weight_g", "planting_date", "split")


@dataclass(frozen=True)
class LabelUpdateResult:
    action: str
    image_path: str
    weight_g: float
    label_csv: str
    auto_train_status: str
    auto_train_message: str
    bootstrap_calibration_status: str
    bootstrap_calibration_message: str


def ensure_label_csv(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        return
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(LABEL_COLUMNS)


def upsert_weight_label(
    csv_path: Path,
    image_path: Path,
    weight_g: float,
    planting_date: str | None,
    split: str | None,
) -> str:
    if not image_path.expanduser().exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    ensure_label_csv(csv_path)
    normalized_image_path = str(image_path.expanduser().resolve())
    rows: list[dict[str, str]] = []
    action = "inserted"

    with csv_path.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized_row = {column: row.get(column, "") for column in LABEL_COLUMNS}
            if normalized_row["image_path"] == normalized_image_path:
                normalized_row["weight_g"] = f"{float(weight_g):.4f}".rstrip("0").rstrip(".")
                normalized_row["planting_date"] = planting_date or normalized_row["planting_date"]
                normalized_row["split"] = split or normalized_row["split"] or "train"
                action = "updated"
            rows.append(normalized_row)

    if action == "inserted":
        rows.append(
            {
                "image_path": normalized_image_path,
                "weight_g": f"{float(weight_g):.4f}".rstrip("0").rstrip("."),
                "planting_date": planting_date or "",
                "split": split or "train",
            }
        )

    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return action


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append or update a manual butterhead weight label.")
    parser.add_argument("--image", required=True, type=Path, help="Captured image path to label.")
    parser.add_argument("--weight-g", required=True, type=float, help="Measured fresh weight in grams.")
    parser.add_argument("--planting-date", default=None, help="Optional planting date in YYYY-MM-DD.")
    parser.add_argument("--split", default="train", help="Optional train/val split value.")
    parser.add_argument("--force-train", action="store_true", help="Retrain immediately after writing the label.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config()
    action = upsert_weight_label(
        csv_path=config.default_label_csv,
        image_path=args.image,
        weight_g=args.weight_g,
        planting_date=args.planting_date,
        split=args.split,
    )
    auto_train_result = maybe_auto_train_feature_model(
        config=config,
        default_planting_date=args.planting_date,
        force=args.force_train,
    )
    calibration_status = "skipped"
    calibration_message = "Auto-trained model exists or calibration not required."
    if not config.auto_feature_model_path.exists():
        calibration_result = calibrate_bootstrap_model_to_image(
            config=config,
            image_path=args.image.expanduser().resolve(),
            target_weight_g=float(args.weight_g),
            planting_date=args.planting_date,
        )
        calibration_status = "calibrated"
        calibration_message = (
            f"Bootstrap model recalibrated to {calibration_result.predicted_weight_g:.2f} g "
            f"for {calibration_result.image_path}."
        )
    print(
        json.dumps(
            asdict(
                LabelUpdateResult(
                    action=action,
                    image_path=str(args.image.expanduser().resolve()),
                    weight_g=float(args.weight_g),
                    label_csv=str(config.default_label_csv),
                    auto_train_status=auto_train_result.status,
                    auto_train_message=auto_train_result.message,
                    bootstrap_calibration_status=calibration_status,
                    bootstrap_calibration_message=calibration_message,
                )
            ),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    return 0
