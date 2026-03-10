from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .config import RuntimeConfig


PREDICTION_TABLE = "camera_butterhead_weight_log"
SUMMARY_TABLE = "camera_butterhead_growth_log"
PREDICTION_CSV_COLUMNS = [
    "Date",
    "PlantId",
    "BatchId",
    "ImagePath",
    "PredictedWeightG",
    "GreenAreaRatio",
    "CanopyBBoxRatio",
    "ExcessGreenMean",
    "DaysSincePlanting",
    "PlantHeightRatio",
    "PlantWidthRatio",
    "PlantHeightCm",
    "PlantWidthCm",
    "LeafColor",
    "LeafColorScore",
    "CameraDistanceCm",
    "CameraFovDeg",
    "CameraFovAxis",
    "CameraModel",
    "ModelPath",
]
PREDICTION_DB_COLUMNS = {
    "Date": "TEXT",
    "PlantId": "TEXT",
    "BatchId": "TEXT",
    "ImagePath": "TEXT",
    "PredictedWeightG": "REAL",
    "GreenAreaRatio": "REAL",
    "CanopyBBoxRatio": "REAL",
    "ExcessGreenMean": "REAL",
    "DaysSincePlanting": "REAL",
    "PlantHeightRatio": "REAL",
    "PlantWidthRatio": "REAL",
    "PlantHeightCm": "REAL",
    "PlantWidthCm": "REAL",
    "LeafColor": "TEXT",
    "LeafColorScore": "REAL",
    "CameraDistanceCm": "REAL",
    "CameraFovDeg": "REAL",
    "CameraFovAxis": "TEXT",
    "CameraModel": "TEXT",
    "ModelPath": "TEXT",
}
SUMMARY_DB_COLUMNS = {
    "Date": "TEXT",
    "PlantId": "TEXT",
    "BatchId": "TEXT",
    "ImagePath": "TEXT",
    "PredictedWeightG": "REAL",
    "PlantHeightCm": "REAL",
    "PlantWidthCm": "REAL",
    "LeafColor": "TEXT",
    "LeafColorScore": "REAL",
    "CameraDistanceCm": "REAL",
    "CameraFovDeg": "REAL",
    "CameraFovAxis": "TEXT",
    "CameraModel": "TEXT",
}


def ensure_prediction_csv(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists() and csv_path.stat().st_size > 0:
        with csv_path.open("r", newline="") as handle:
            reader = csv.DictReader(handle)
            current_columns = reader.fieldnames or []
            if current_columns == PREDICTION_CSV_COLUMNS:
                return
            rows = [dict(row) for row in reader]

        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=PREDICTION_CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                normalized = {column: row.get(column, "") for column in PREDICTION_CSV_COLUMNS}
                writer.writerow(normalized)
        return

    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PREDICTION_CSV_COLUMNS)


def ensure_prediction_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5.0)
    try:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{PREDICTION_TABLE}" (
                "Date" TEXT,
                "PlantId" TEXT,
                "BatchId" TEXT,
                "ImagePath" TEXT,
                "PredictedWeightG" REAL,
                "GreenAreaRatio" REAL,
                "CanopyBBoxRatio" REAL,
                "ExcessGreenMean" REAL,
                "DaysSincePlanting" REAL,
                "PlantHeightRatio" REAL,
                "PlantWidthRatio" REAL,
                "PlantHeightCm" REAL,
                "PlantWidthCm" REAL,
                "LeafColor" TEXT,
                "LeafColorScore" REAL,
                "CameraDistanceCm" REAL,
                "CameraFovDeg" REAL,
                "CameraFovAxis" TEXT,
                "CameraModel" TEXT,
                "ModelPath" TEXT
            );
            """
        )
        existing_columns = {
            row[1]
            for row in connection.execute(f'PRAGMA table_info("{PREDICTION_TABLE}");').fetchall()
        }
        for column_name, column_type in PREDICTION_DB_COLUMNS.items():
            if column_name in existing_columns:
                continue
            connection.execute(
                f'ALTER TABLE "{PREDICTION_TABLE}" ADD COLUMN "{column_name}" {column_type};'
            )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{SUMMARY_TABLE}" (
                "Date" TEXT,
                "PlantId" TEXT,
                "BatchId" TEXT,
                "ImagePath" TEXT,
                "PredictedWeightG" REAL,
                "PlantHeightCm" REAL,
                "PlantWidthCm" REAL,
                "LeafColor" TEXT,
                "LeafColorScore" REAL,
                "CameraDistanceCm" REAL,
                "CameraFovDeg" REAL,
                "CameraFovAxis" TEXT,
                "CameraModel" TEXT
            );
            """
        )
        existing_summary_columns = {
            row[1]
            for row in connection.execute(f'PRAGMA table_info("{SUMMARY_TABLE}");').fetchall()
        }
        for column_name, column_type in SUMMARY_DB_COLUMNS.items():
            if column_name in existing_summary_columns:
                continue
            connection.execute(
                f'ALTER TABLE "{SUMMARY_TABLE}" ADD COLUMN "{column_name}" {column_type};'
            )
        connection.commit()
    finally:
        connection.close()


def log_prediction(
    config: RuntimeConfig,
    captured_at_iso: str,
    image_path: Path,
    predicted_weight_g: float | None,
    raw_features: dict[str, float],
    metadata_fields: dict[str, object],
    model_path: Path | None,
    plant_id: str,
    batch_id: str,
) -> None:
    ensure_prediction_csv(config.prediction_log_csv)
    ensure_prediction_db(config.db_path)

    row = [
        captured_at_iso,
        plant_id,
        batch_id,
        str(image_path),
        float(predicted_weight_g) if predicted_weight_g is not None else None,
        float(raw_features["green_area_ratio"]),
        float(raw_features["canopy_bbox_ratio"]),
        float(raw_features["excess_green_mean"]),
        float(raw_features["days_since_planting"]),
        float(raw_features["plant_height_ratio"]),
        float(raw_features["plant_width_ratio"]),
        float(raw_features["plant_height_cm"]),
        float(raw_features["plant_width_cm"]),
        str(metadata_fields["leaf_color"]),
        float(raw_features["leaf_color_score"]),
        float(metadata_fields["camera_distance_cm"]),
        float(metadata_fields["camera_fov_deg"]),
        str(metadata_fields["camera_fov_axis"]),
        str(metadata_fields.get("camera_model", config.camera_model)),
        str(model_path) if model_path is not None else "",
    ]
    summary_row = [
        captured_at_iso,
        plant_id,
        batch_id,
        str(image_path),
        float(predicted_weight_g) if predicted_weight_g is not None else None,
        float(raw_features["plant_height_cm"]),
        float(raw_features["plant_width_cm"]),
        str(metadata_fields["leaf_color"]),
        float(raw_features["leaf_color_score"]),
        float(metadata_fields["camera_distance_cm"]),
        float(metadata_fields["camera_fov_deg"]),
        str(metadata_fields["camera_fov_axis"]),
        str(metadata_fields.get("camera_model", config.camera_model)),
    ]

    with config.prediction_log_csv.open("a", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(row)

    connection = sqlite3.connect(config.db_path, timeout=5.0)
    try:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")
        connection.execute(
            f"""
            INSERT INTO "{PREDICTION_TABLE}"
            ("Date", "PlantId", "BatchId", "ImagePath", "PredictedWeightG", "GreenAreaRatio",
             "CanopyBBoxRatio", "ExcessGreenMean", "DaysSincePlanting",
             "PlantHeightRatio", "PlantWidthRatio", "PlantHeightCm", "PlantWidthCm",
             "LeafColor", "LeafColorScore", "CameraDistanceCm", "CameraFovDeg",
             "CameraFovAxis", "CameraModel", "ModelPath")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            row,
        )
        connection.execute(
            f"""
            INSERT INTO "{SUMMARY_TABLE}"
            ("Date", "PlantId", "BatchId", "ImagePath", "PredictedWeightG",
             "PlantHeightCm", "PlantWidthCm", "LeafColor", "LeafColorScore",
             "CameraDistanceCm", "CameraFovDeg", "CameraFovAxis", "CameraModel")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            summary_row,
        )
        connection.commit()
    finally:
        connection.close()
