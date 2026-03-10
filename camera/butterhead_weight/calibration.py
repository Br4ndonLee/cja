from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import RuntimeConfig
from .feature_regressor import (
    calibrate_feature_regressor_to_reference,
    ensure_bootstrap_model,
    load_feature_regressor,
    predict_with_feature_regressor,
    save_feature_regressor,
)
from .predict import extract_prediction_inputs


@dataclass(frozen=True)
class BootstrapCalibrationResult:
    model_path: str
    target_weight_g: float
    predicted_weight_g: float
    image_path: str


def calibrate_bootstrap_model_to_image(
    config: RuntimeConfig,
    image_path: Path,
    target_weight_g: float,
    planting_date: str | None,
) -> BootstrapCalibrationResult:
    bootstrap_model_path = ensure_bootstrap_model(config.bootstrap_model_path)
    payload = load_feature_regressor(bootstrap_model_path)
    _, _, feature_bundle = extract_prediction_inputs(
        image_path=image_path,
        model_metadata={},
        planting_date=planting_date,
    )
    calibrated_payload = calibrate_feature_regressor_to_reference(
        payload=payload,
        raw_features=feature_bundle.raw_features,
        target_weight_g=target_weight_g,
        reference_image_path=str(image_path),
    )
    save_feature_regressor(bootstrap_model_path, calibrated_payload)
    predicted_weight_g = predict_with_feature_regressor(
        raw_features=feature_bundle.raw_features,
        payload=calibrated_payload,
    )
    return BootstrapCalibrationResult(
        model_path=str(bootstrap_model_path),
        target_weight_g=float(target_weight_g),
        predicted_weight_g=float(predicted_weight_g),
        image_path=str(image_path),
    )
