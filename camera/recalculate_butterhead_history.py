#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from butterhead_weight.config import load_runtime_config
from butterhead_weight.logging_utils import (
    PREDICTION_CSV_COLUMNS,
    PREDICTION_TABLE,
    SUMMARY_TABLE,
    ensure_prediction_db,
)
from butterhead_weight.metadata import read_capture_metadata, resolve_camera_capture_settings
from butterhead_weight.predict import predict_image
from butterhead_weight.stabilization import (
    RecentPrediction,
    stabilize_bootstrap_prediction_against_previous,
)


@dataclass(frozen=True)
class RecalculatedRow:
    csv_row: dict[str, object]
    summary_row: tuple[object, ...]


@dataclass(frozen=True)
class RecalculationResult:
    source_row_count: int
    recalculated_row_count: int
    dropped_missing_image_count: int
    dropped_missing_images: list[str]
    csv_backup_path: str
    db_backup_path: str


def parse_args() -> argparse.Namespace:
    config = load_runtime_config()
    parser = argparse.ArgumentParser(description="Recalculate historical butterhead predictions from saved images.")
    parser.add_argument(
        "--csv",
        type=Path,
        default=config.prediction_log_csv,
        help="Prediction CSV to rebuild.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=config.db_path,
        help="SQLite database to update.",
    )
    parser.add_argument(
        "--planting-date",
        default=None,
        help="Planting date in YYYY-MM-DD used when recalculating features.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=config.log_dir / "history_recalc_backups",
        help="Directory for CSV/DB backups.",
    )
    return parser.parse_args()


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", newline="") as handle:
        return list(csv.DictReader(handle))


def backup_csv(csv_path: Path, backup_dir: Path, stamp: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{csv_path.stem}.{stamp}{csv_path.suffix}.bak"
    shutil.copy2(csv_path, backup_path)
    return backup_path


def backup_db(db_path: Path, backup_dir: Path, stamp: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}.{stamp}{db_path.suffix}.bak"
    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return backup_path


def resolve_model_path(raw_model_path: str, config) -> Path:
    if raw_model_path:
        requested = Path(raw_model_path).expanduser()
        if requested.exists():
            return requested
        if requested.name == config.bootstrap_model_path.name and config.bootstrap_model_path.exists():
            return config.bootstrap_model_path
        if requested.name == config.auto_feature_model_path.name and config.auto_feature_model_path.exists():
            return config.auto_feature_model_path

    if config.bootstrap_model_path.exists():
        return config.bootstrap_model_path
    if config.auto_feature_model_path.exists():
        return config.auto_feature_model_path
    return Path(raw_model_path).expanduser()


def is_bootstrap_model(model_path: Path) -> bool:
    return model_path.name == "butterhead_weight_bootstrap.json"


def build_recalculated_rows(
    source_rows: list[dict[str, str]],
    planting_date: str | None,
) -> tuple[list[RecalculatedRow], list[str]]:
    config = load_runtime_config()
    recalculated_rows: list[RecalculatedRow] = []
    dropped_missing_images: list[str] = []
    previous_prediction: RecentPrediction | None = None

    sorted_rows = sorted(source_rows, key=lambda row: row["Date"])
    for row in sorted_rows:
        image_path = Path(row["ImagePath"]).expanduser()
        if not image_path.exists():
            dropped_missing_images.append(str(image_path))
            continue

        model_path = resolve_model_path(row.get("ModelPath", ""), config)
        prediction = predict_image(
            image_path=image_path,
            model_path=model_path,
            planting_date=planting_date,
        )
        predicted_weight_g = prediction.predicted_weight_g
        if is_bootstrap_model(model_path):
            predicted_weight_g = stabilize_bootstrap_prediction_against_previous(
                previous=previous_prediction,
                captured_at_iso=row["Date"],
                predicted_weight_g=predicted_weight_g,
                plant_height_cm=prediction.plant_height_cm,
                plant_width_cm=prediction.plant_width_cm,
            )

        capture_metadata = read_capture_metadata(image_path)
        camera_distance_cm, camera_fov_deg, camera_fov_axis = resolve_camera_capture_settings(
            metadata=capture_metadata,
            default_distance_cm=config.camera_distance_cm,
            default_fov_deg=config.camera_fov_deg,
            default_fov_axis=config.camera_fov_axis,
        )
        camera_model = str(capture_metadata.get("camera_model") or row.get("CameraModel") or config.camera_model)

        csv_row = {
            "Date": row["Date"],
            "PlantId": row["PlantId"],
            "BatchId": row["BatchId"],
            "ImagePath": str(image_path),
            "PredictedWeightG": float(predicted_weight_g) if predicted_weight_g is not None else None,
            "GreenAreaRatio": float(prediction.raw_features["green_area_ratio"]),
            "CanopyBBoxRatio": float(prediction.raw_features["canopy_bbox_ratio"]),
            "ExcessGreenMean": float(prediction.raw_features["excess_green_mean"]),
            "DaysSincePlanting": float(prediction.raw_features["days_since_planting"]),
            "PlantHeightRatio": float(prediction.raw_features["plant_height_ratio"]),
            "PlantWidthRatio": float(prediction.raw_features["plant_width_ratio"]),
            "PlantHeightCm": float(prediction.raw_features["plant_height_cm"]),
            "PlantWidthCm": float(prediction.raw_features["plant_width_cm"]),
            "LeafColor": prediction.leaf_color,
            "LeafColorScore": float(prediction.raw_features["leaf_color_score"]),
            "CameraDistanceCm": float(camera_distance_cm),
            "CameraFovDeg": float(camera_fov_deg),
            "CameraFovAxis": str(camera_fov_axis),
            "CameraModel": camera_model,
            "ModelPath": str(model_path),
        }
        summary_row = (
            csv_row["Date"],
            csv_row["PlantId"],
            csv_row["BatchId"],
            csv_row["ImagePath"],
            csv_row["PredictedWeightG"],
            csv_row["PlantHeightCm"],
            csv_row["PlantWidthCm"],
            csv_row["LeafColor"],
            csv_row["LeafColorScore"],
            csv_row["CameraDistanceCm"],
            csv_row["CameraFovDeg"],
            csv_row["CameraFovAxis"],
            csv_row["CameraModel"],
        )
        recalculated_rows.append(RecalculatedRow(csv_row=csv_row, summary_row=summary_row))

        if predicted_weight_g is not None:
            previous_prediction = RecentPrediction(
                captured_at_iso=row["Date"],
                predicted_weight_g=float(predicted_weight_g),
                plant_height_cm=float(prediction.plant_height_cm),
                plant_width_cm=float(prediction.plant_width_cm),
            )

    return recalculated_rows, dropped_missing_images


def write_csv(csv_path: Path, recalculated_rows: list[RecalculatedRow]) -> None:
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREDICTION_CSV_COLUMNS)
        writer.writeheader()
        for recalculated in recalculated_rows:
            writer.writerow(recalculated.csv_row)


def rebuild_db(db_path: Path, source_rows: list[dict[str, str]], recalculated_rows: list[RecalculatedRow]) -> None:
    ensure_prediction_db(db_path)
    target_pairs = sorted({(row.get("PlantId", ""), row.get("BatchId", "")) for row in source_rows})
    connection = sqlite3.connect(db_path, timeout=5.0)
    try:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")
        for plant_id, batch_id in target_pairs:
            connection.execute(
                f'DELETE FROM "{PREDICTION_TABLE}" WHERE "PlantId" = ? AND "BatchId" = ?;',
                (plant_id, batch_id),
            )
            connection.execute(
                f'DELETE FROM "{SUMMARY_TABLE}" WHERE "PlantId" = ? AND "BatchId" = ?;',
                (plant_id, batch_id),
            )

        prediction_rows = [
            tuple(recalculated.csv_row[column] for column in PREDICTION_CSV_COLUMNS)
            for recalculated in recalculated_rows
        ]
        summary_rows = [recalculated.summary_row for recalculated in recalculated_rows]

        connection.executemany(
            f"""
            INSERT INTO "{PREDICTION_TABLE}"
            ("Date", "PlantId", "BatchId", "ImagePath", "PredictedWeightG", "GreenAreaRatio",
             "CanopyBBoxRatio", "ExcessGreenMean", "DaysSincePlanting",
             "PlantHeightRatio", "PlantWidthRatio", "PlantHeightCm", "PlantWidthCm",
             "LeafColor", "LeafColorScore", "CameraDistanceCm", "CameraFovDeg",
             "CameraFovAxis", "CameraModel", "ModelPath")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            prediction_rows,
        )
        connection.executemany(
            f"""
            INSERT INTO "{SUMMARY_TABLE}"
            ("Date", "PlantId", "BatchId", "ImagePath", "PredictedWeightG",
             "PlantHeightCm", "PlantWidthCm", "LeafColor", "LeafColorScore",
             "CameraDistanceCm", "CameraFovDeg", "CameraFovAxis", "CameraModel")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            summary_rows,
        )
        connection.commit()
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    csv_path = args.csv.expanduser().resolve()
    db_path = args.db.expanduser().resolve()
    source_rows = load_csv_rows(csv_path)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    csv_backup_path = backup_csv(csv_path=csv_path, backup_dir=args.backup_dir, stamp=stamp)
    db_backup_path = backup_db(db_path=db_path, backup_dir=args.backup_dir, stamp=stamp)
    recalculated_rows, dropped_missing_images = build_recalculated_rows(
        source_rows=source_rows,
        planting_date=args.planting_date,
    )
    write_csv(csv_path=csv_path, recalculated_rows=recalculated_rows)
    rebuild_db(db_path=db_path, source_rows=source_rows, recalculated_rows=recalculated_rows)

    print(
        json.dumps(
            asdict(
                RecalculationResult(
                    source_row_count=len(source_rows),
                    recalculated_row_count=len(recalculated_rows),
                    dropped_missing_image_count=len(dropped_missing_images),
                    dropped_missing_images=dropped_missing_images,
                    csv_backup_path=str(csv_backup_path),
                    db_backup_path=str(db_backup_path),
                )
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
