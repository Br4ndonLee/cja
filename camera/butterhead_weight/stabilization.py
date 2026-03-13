from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .config import RuntimeConfig
from .logging_utils import PREDICTION_TABLE


@dataclass(frozen=True)
class RecentPrediction:
    captured_at_iso: str
    predicted_weight_g: float
    plant_height_cm: float
    plant_width_cm: float


def load_recent_prediction(
    config: RuntimeConfig,
    plant_id: str,
    batch_id: str,
    before_iso: str,
) -> RecentPrediction | None:
    connection = sqlite3.connect(config.db_path, timeout=5.0)
    try:
        row = connection.execute(
            f"""
            SELECT "Date", "PredictedWeightG", "PlantHeightCm", "PlantWidthCm"
            FROM "{PREDICTION_TABLE}"
            WHERE "PlantId" = ?
              AND "BatchId" = ?
              AND "PredictedWeightG" IS NOT NULL
              AND "Date" < ?
            ORDER BY "Date" DESC
            LIMIT 1;
            """,
            (plant_id, batch_id, before_iso),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None

    return RecentPrediction(
        captured_at_iso=str(row[0]),
        predicted_weight_g=float(row[1]),
        plant_height_cm=float(row[2]),
        plant_width_cm=float(row[3]),
    )


def stabilize_bootstrap_prediction(
    config: RuntimeConfig,
    plant_id: str,
    batch_id: str,
    captured_at_iso: str,
    predicted_weight_g: float | None,
    plant_height_cm: float,
    plant_width_cm: float,
) -> float | None:
    previous = load_recent_prediction(
        config=config,
        plant_id=plant_id,
        batch_id=batch_id,
        before_iso=captured_at_iso,
    )
    return stabilize_bootstrap_prediction_against_previous(
        previous=previous,
        captured_at_iso=captured_at_iso,
        predicted_weight_g=predicted_weight_g,
        plant_height_cm=plant_height_cm,
        plant_width_cm=plant_width_cm,
    )


def stabilize_bootstrap_prediction_against_previous(
    previous: RecentPrediction | None,
    captured_at_iso: str,
    predicted_weight_g: float | None,
    plant_height_cm: float,
    plant_width_cm: float,
) -> float | None:
    if predicted_weight_g is None:
        return None
    if previous is None:
        return predicted_weight_g

    current_dt = datetime.fromisoformat(captured_at_iso)
    previous_dt = datetime.fromisoformat(previous.captured_at_iso)
    elapsed_days = max((current_dt - previous_dt).total_seconds() / 86400.0, 0.0)
    same_day = current_dt.date() == previous_dt.date()

    lower_bound_ratio = 0.9 if same_day else 0.75
    lower_bound = previous.predicted_weight_g * lower_bound_ratio

    height_delta_ratio = abs(plant_height_cm - previous.plant_height_cm) / max(previous.plant_height_cm, 1e-6)
    width_delta_ratio = abs(plant_width_cm - previous.plant_width_cm) / max(previous.plant_width_cm, 1e-6)
    abrupt_drop = predicted_weight_g < lower_bound
    framing_shift = height_delta_ratio < 0.08 and width_delta_ratio > 0.08

    if abrupt_drop or (same_day and framing_shift):
        blend_ratio = 0.2 if same_day else 0.35
        blended = ((1.0 - blend_ratio) * previous.predicted_weight_g) + (blend_ratio * predicted_weight_g)
        return float(max(blended, lower_bound))

    if elapsed_days <= 2.0 and framing_shift and predicted_weight_g < previous.predicted_weight_g:
        return float(((0.7 * previous.predicted_weight_g) + (0.3 * predicted_weight_g)))

    return predicted_weight_g
