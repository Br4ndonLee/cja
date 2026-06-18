"""
Butterhead lettuce logistic growth model.

Estimates plant dimensions and weight beyond camera frame overflow
using logistic growth curves fitted to visible-period observations
and optional manual calibration points.

Growth follows: y(t) = y_max / (1 + exp(-k * (t - t_mid)))
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from math import exp, inf
from pathlib import Path
from typing import Any

import numpy as np

from .config import RuntimeConfig
from .logging_utils import PREDICTION_TABLE


# --------------------------------------------------------------------------- #
# Logistic growth primitives
# --------------------------------------------------------------------------- #

def logistic(t: float, y_max: float, k: float, t_mid: float) -> float:
    arg = -k * (t - t_mid)
    if arg > 500:
        return 0.0
    return y_max / (1.0 + exp(arg))


def fit_logistic(
    data_points: list[tuple[float, float]],
    k_range: tuple[float, float] = (0.04, 0.30),
    t_mid_range: tuple[float, float] = (3.0, 40.0),
    k_step: float = 0.01,
    t_mid_step: float = 1.0,
) -> tuple[float, float, float]:
    """Grid-search fit for (y_max, k, t_mid). Returns best parameters."""
    if not data_points:
        raise ValueError("No data points to fit")

    best_error = inf
    best_params = (0.0, 0.1, 20.0)

    for k_int in range(int(k_range[0] * 100), int(k_range[1] * 100) + 1, int(k_step * 100)):
        k = k_int / 100.0
        for t_mid_int in range(int(t_mid_range[0]), int(t_mid_range[1]) + 1, int(t_mid_step)):
            t_mid = float(t_mid_int)

            # Solve y_max analytically for each point, take median
            y_max_estimates = []
            for t, y in data_points:
                denom_factor = 1.0 + exp(-k * (t - t_mid))
                y_max_est = y * denom_factor
                if 0 < y_max_est < 1e6:
                    y_max_estimates.append(y_max_est)

            if not y_max_estimates:
                continue

            y_max = float(np.median(y_max_estimates))

            error = sum((logistic(t, y_max, k, t_mid) - y) ** 2 for t, y in data_points)
            if error < best_error:
                best_error = error
                best_params = (y_max, k, t_mid)

    return best_params


# --------------------------------------------------------------------------- #
# Growth estimate result
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GrowthEstimate:
    days_since_planting: float
    weight_g: float
    height_cm: float
    width_cm: float
    method: str  # "growth_curve"
    curve_params: dict[str, Any]


# --------------------------------------------------------------------------- #
# Calibration persistence
# --------------------------------------------------------------------------- #

CALIBRATION_FILENAME = "growth_calibration.json"


def _calibration_path(config: RuntimeConfig) -> Path:
    return config.model_dir / CALIBRATION_FILENAME


def load_calibration(config: RuntimeConfig) -> dict[str, Any] | None:
    path = _calibration_path(config)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_calibration(config: RuntimeConfig, payload: dict[str, Any]) -> None:
    path = _calibration_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Historical data loading
# --------------------------------------------------------------------------- #

OVERFLOW_RATIO = 0.95


@dataclass(frozen=True)
class HistoricalPoint:
    days: float
    height_cm: float
    width_cm: float
    green_area_ratio: float

    @property
    def is_overflow(self) -> bool:
        return self.green_area_ratio >= OVERFLOW_RATIO


def load_visible_history(
    config: RuntimeConfig,
    plant_id: str,
    batch_id: str,
) -> list[HistoricalPoint]:
    """Load non-overflow measurements from the prediction DB."""
    if not config.db_path.exists():
        return []

    connection = sqlite3.connect(config.db_path, timeout=5.0)
    try:
        rows = connection.execute(
            f"""
            SELECT "DaysSincePlanting", "PlantHeightCm", "PlantWidthCm", "GreenAreaRatio"
            FROM "{PREDICTION_TABLE}"
            WHERE "PlantId" = ?
              AND "BatchId" = ?
              AND "GreenAreaRatio" < ?
              AND "PlantHeightCm" > 0
              AND "PlantWidthCm" > 0
            ORDER BY "DaysSincePlanting"
            """,
            (plant_id, batch_id, OVERFLOW_RATIO),
        ).fetchall()
    finally:
        connection.close()

    return [
        HistoricalPoint(
            days=float(r[0]),
            height_cm=float(r[1]),
            width_cm=float(r[2]),
            green_area_ratio=float(r[3]),
        )
        for r in rows
    ]


def _aggregate_daily(points: list[HistoricalPoint]) -> list[tuple[float, float, float]]:
    """Average per-day: returns [(day, mean_height, mean_width), ...]."""
    from collections import defaultdict
    buckets: dict[int, list[HistoricalPoint]] = defaultdict(list)
    for p in points:
        buckets[int(p.days)].append(p)

    result = []
    for day in sorted(buckets):
        pts = buckets[day]
        mean_h = sum(p.height_cm for p in pts) / len(pts)
        mean_w = sum(p.width_cm for p in pts) / len(pts)
        result.append((float(day), mean_h, mean_w))
    return result


# --------------------------------------------------------------------------- #
# Growth model fitting & prediction
# --------------------------------------------------------------------------- #

# Literature priors for butterhead lettuce (greenhouse/hydroponic)
DEFAULT_PARAMS = {
    "height": {"y_max": 18.0, "k": 0.10, "t_mid": 12.0},
    "width": {"y_max": 26.0, "k": 0.10, "t_mid": 10.0},
    "weight": {"y_max": 250.0, "k": 0.13, "t_mid": 28.0},
}


def build_growth_model(
    config: RuntimeConfig,
    plant_id: str,
    batch_id: str,
    manual_calibrations: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """
    Fit growth curves from visible-period history + manual calibrations.

    manual_calibrations: [{"days": 33, "weight_g": 162, "height_cm": 15, "width_cm": 21}]
    """
    visible = load_visible_history(config, plant_id, batch_id)
    daily = _aggregate_daily(visible)
    manual = manual_calibrations or []

    # Build data points for each metric
    # Anchor at transplanting day (typical butterhead transplant seedling)
    height_points: list[tuple[float, float]] = [(1.0, 2.5)]
    width_points: list[tuple[float, float]] = [(1.0, 3.0)]
    weight_points: list[tuple[float, float]] = [(1.0, 3.0)]

    # Add visible-period observations
    height_points.extend((d, h) for d, h, _ in daily)
    width_points.extend((d, w) for d, _, w in daily)

    for cal in manual:
        if "height_cm" in cal and "days" in cal:
            height_points.append((float(cal["days"]), float(cal["height_cm"])))
        if "width_cm" in cal and "days" in cal:
            width_points.append((float(cal["days"]), float(cal["width_cm"])))
        if "weight_g" in cal and "days" in cal:
            weight_points.append((float(cal["days"]), float(cal["weight_g"])))

    # Fit each curve
    fitted = {}

    if height_points:
        y_max, k, t_mid = fit_logistic(height_points, k_range=(0.04, 0.25), t_mid_range=(3, 30))
        fitted["height"] = {"y_max": y_max, "k": k, "t_mid": t_mid}
    else:
        fitted["height"] = dict(DEFAULT_PARAMS["height"])

    if width_points:
        y_max, k, t_mid = fit_logistic(width_points, k_range=(0.04, 0.25), t_mid_range=(3, 30))
        fitted["width"] = {"y_max": y_max, "k": k, "t_mid": t_mid}
    else:
        fitted["width"] = dict(DEFAULT_PARAMS["width"])

    if weight_points:
        y_max, k, t_mid = fit_logistic(weight_points, k_range=(0.04, 0.25), t_mid_range=(15, 40))
        fitted["weight"] = {"y_max": y_max, "k": k, "t_mid": t_mid}
    else:
        fitted["weight"] = dict(DEFAULT_PARAMS["weight"])

    # Determine overflow start day
    overflow_start_day = None
    if daily:
        last_visible_day = max(d for d, _, _ in daily)
        overflow_start_day = last_visible_day + 1

    payload = {
        "plant_id": plant_id,
        "batch_id": batch_id,
        "fitted_params": fitted,
        "manual_calibrations": manual,
        "visible_period_points": len(daily),
        "overflow_start_day": overflow_start_day,
        "calibrated_at": datetime.now().astimezone().isoformat(),
    }

    save_calibration(config, payload)
    return payload


def predict_growth(
    calibration: dict[str, Any],
    days_since_planting: float,
) -> GrowthEstimate:
    """Predict height, width, weight at a given day using fitted growth curves."""
    params = calibration["fitted_params"]

    h_p = params["height"]
    w_p = params["width"]
    wt_p = params["weight"]

    height = logistic(days_since_planting, h_p["y_max"], h_p["k"], h_p["t_mid"])
    width = logistic(days_since_planting, w_p["y_max"], w_p["k"], w_p["t_mid"])
    weight = logistic(days_since_planting, wt_p["y_max"], wt_p["k"], wt_p["t_mid"])

    return GrowthEstimate(
        days_since_planting=days_since_planting,
        weight_g=weight,
        height_cm=height,
        width_cm=width,
        method="growth_curve",
        curve_params=params,
    )


def get_or_build_growth_model(
    config: RuntimeConfig,
    plant_id: str,
    batch_id: str,
    manual_calibrations: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Load existing calibration or build a new one."""
    existing = load_calibration(config)

    # Rebuild if: no calibration, different plant, or new manual calibrations provided
    if (
        existing is None
        or existing.get("plant_id") != plant_id
        or existing.get("batch_id") != batch_id
        or manual_calibrations is not None
    ):
        return build_growth_model(config, plant_id, batch_id, manual_calibrations)

    return existing
