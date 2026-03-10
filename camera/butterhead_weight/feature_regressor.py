from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from math import pi
from pathlib import Path
from typing import Any

import numpy as np


MODEL_KIND_BOOTSTRAP = "bootstrap_linear_v1"
MODEL_KIND_FEATURE_REGRESSOR = "feature_ridge_regressor_v1"
BASIS_FEATURE_NAMES = (
    "plant_height_cm",
    "plant_width_cm",
    "ellipse_area_cm2",
    "canopy_fill_ratio",
    "excess_green_mean",
    "days_since_planting",
    "leaf_color_score",
    "green_area_ratio",
)


@dataclass(frozen=True)
class FeatureTrainingSample:
    image_path: str
    weight_g: float
    raw_features: dict[str, float]


def _coerce_vector(values: list[float] | tuple[float, ...] | np.ndarray) -> list[float]:
    return [float(value) for value in values]


def compute_canopy_fill_ratio(raw_features: dict[str, float]) -> float:
    bbox_ratio = float(raw_features.get("canopy_bbox_ratio", 0.0))
    if bbox_ratio <= 0.0:
        return 0.0
    fill_ratio = float(raw_features.get("green_area_ratio", 0.0)) / bbox_ratio
    return float(min(max(fill_ratio, 0.0), 1.0))


def build_basis_vector(raw_features: dict[str, float]) -> np.ndarray:
    plant_height_cm = float(raw_features.get("plant_height_cm", 0.0))
    plant_width_cm = float(raw_features.get("plant_width_cm", 0.0))
    ellipse_area_cm2 = float(pi * max(plant_height_cm, 0.0) * max(plant_width_cm, 0.0) / 4.0)
    canopy_fill_ratio = compute_canopy_fill_ratio(raw_features)
    excess_green_mean = float(raw_features.get("excess_green_mean", 0.0))
    days_since_planting = float(raw_features.get("days_since_planting", 0.0))
    leaf_color_score = float(raw_features.get("leaf_color_score", 0.0))
    green_area_ratio = float(raw_features.get("green_area_ratio", 0.0))
    return np.array(
        [
            plant_height_cm,
            plant_width_cm,
            ellipse_area_cm2,
            canopy_fill_ratio,
            excess_green_mean,
            days_since_planting,
            leaf_color_score,
            green_area_ratio,
        ],
        dtype=np.float64,
    )


def build_bootstrap_model_payload() -> dict[str, Any]:
    return {
        "model_kind": MODEL_KIND_BOOTSTRAP,
        "basis_feature_names": list(BASIS_FEATURE_NAMES),
        "intercept": -42.0,
        "coefficients": [
            2.4,
            2.4,
            0.45,
            18.0,
            10.0,
            0.55,
            20.0,
            12.0,
        ],
        "feature_means": None,
        "feature_scales": None,
        "alpha": None,
        "min_weight_g": 8.0,
        "max_weight_g": 450.0,
        "trained_at": datetime.now().astimezone().isoformat(),
        "training_source": "heuristic bootstrap based on canopy size, color, and planting age",
    }


def ensure_bootstrap_model(model_path: Path) -> Path:
    if model_path.exists():
        return model_path
    save_feature_regressor(model_path, build_bootstrap_model_payload())
    return model_path


def load_feature_regressor(model_path: Path) -> dict[str, Any]:
    payload = json.loads(model_path.read_text())
    coefficients = payload.get("coefficients")
    basis_feature_names = payload.get("basis_feature_names")
    if not isinstance(coefficients, list) or not isinstance(basis_feature_names, list):
        raise ValueError(f"Invalid feature regressor payload: {model_path}")
    if len(coefficients) != len(basis_feature_names):
        raise ValueError(f"Coefficient length mismatch in model payload: {model_path}")
    return payload


def save_feature_regressor(model_path: Path, payload: dict[str, Any]) -> None:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def predict_with_feature_regressor(raw_features: dict[str, float], payload: dict[str, Any]) -> float:
    prediction = predict_with_feature_regressor_raw(raw_features=raw_features, payload=payload)
    min_weight_g = float(payload.get("min_weight_g", 0.0))
    max_weight_g = float(payload.get("max_weight_g", max(min_weight_g, prediction)))
    return float(min(max(prediction, min_weight_g), max_weight_g))


def predict_with_feature_regressor_raw(raw_features: dict[str, float], payload: dict[str, Any]) -> float:
    basis_vector = build_basis_vector(raw_features)
    coefficients = np.asarray(payload["coefficients"], dtype=np.float64)
    means_raw = payload.get("feature_means")
    scales_raw = payload.get("feature_scales")

    if means_raw is not None and scales_raw is not None:
        means = np.asarray(means_raw, dtype=np.float64)
        scales = np.asarray(scales_raw, dtype=np.float64)
        safe_scales = np.where(scales == 0.0, 1.0, scales)
        basis_vector = (basis_vector - means) / safe_scales

    return float(payload.get("intercept", 0.0)) + float(np.dot(basis_vector, coefficients))


def calibrate_feature_regressor_to_reference(
    payload: dict[str, Any],
    raw_features: dict[str, float],
    target_weight_g: float,
    reference_image_path: str | None = None,
) -> dict[str, Any]:
    calibrated_payload = dict(payload)
    current_prediction = predict_with_feature_regressor_raw(raw_features=raw_features, payload=payload)
    calibrated_payload["intercept"] = float(payload.get("intercept", 0.0)) + (float(target_weight_g) - current_prediction)
    calibrated_payload["min_weight_g"] = float(min(calibrated_payload.get("min_weight_g", target_weight_g), target_weight_g))
    calibrated_payload["max_weight_g"] = float(max(calibrated_payload.get("max_weight_g", target_weight_g), target_weight_g))
    calibrated_payload["calibrated_at"] = datetime.now().astimezone().isoformat()
    calibrated_payload["calibration_target_weight_g"] = float(target_weight_g)
    calibrated_payload["calibration_prediction_before_g"] = float(current_prediction)
    if reference_image_path is not None:
        calibrated_payload["calibration_reference_image_path"] = reference_image_path
    return calibrated_payload


def fit_feature_regressor(
    samples: list[FeatureTrainingSample],
    alpha: float = 2.0,
) -> dict[str, Any]:
    if len(samples) < 2:
        raise ValueError("At least 2 labeled samples are required to fit the feature regressor.")

    design_matrix = np.vstack([build_basis_vector(sample.raw_features) for sample in samples])
    targets = np.asarray([float(sample.weight_g) for sample in samples], dtype=np.float64)
    feature_means = design_matrix.mean(axis=0)
    feature_scales = design_matrix.std(axis=0)
    feature_scales = np.where(feature_scales < 1e-6, 1.0, feature_scales)
    standardized = (design_matrix - feature_means) / feature_scales

    centered_targets = targets - targets.mean()
    reg_matrix = (standardized.T @ standardized) + (alpha * np.eye(standardized.shape[1], dtype=np.float64))
    reg_rhs = standardized.T @ centered_targets
    try:
        coefficients = np.linalg.solve(reg_matrix, reg_rhs)
    except np.linalg.LinAlgError:
        coefficients = np.linalg.pinv(reg_matrix) @ reg_rhs

    predictions = float(targets.mean()) + standardized @ coefficients
    residuals = predictions - targets
    mae_g = float(np.abs(residuals).mean())
    rmse_g = float(np.sqrt(np.mean(residuals ** 2)))
    r2_denominator = float(np.sum((targets - targets.mean()) ** 2))
    r2_score = 0.0 if r2_denominator <= 0.0 else float(1.0 - (np.sum(residuals ** 2) / r2_denominator))

    return {
        "model_kind": MODEL_KIND_FEATURE_REGRESSOR,
        "basis_feature_names": list(BASIS_FEATURE_NAMES),
        "intercept": float(targets.mean()),
        "coefficients": _coerce_vector(coefficients),
        "feature_means": _coerce_vector(feature_means),
        "feature_scales": _coerce_vector(feature_scales),
        "alpha": float(alpha),
        "min_weight_g": float(max(0.0, targets.min() * 0.5)),
        "max_weight_g": float(max(targets.max() * 1.5, 450.0)),
        "trained_at": datetime.now().astimezone().isoformat(),
        "training_source": "manual labeled weights CSV",
        "training_sample_count": len(samples),
        "fit_mae_g": mae_g,
        "fit_rmse_g": rmse_g,
        "fit_r2": r2_score,
    }
