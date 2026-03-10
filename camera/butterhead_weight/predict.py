from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import onnxruntime as ort

from .config import load_runtime_config
from .feature_regressor import load_feature_regressor, predict_with_feature_regressor
from .features import MODEL_FEATURE_NAMES, build_model_feature_vector, extract_feature_bundle
from .metadata import parse_optional_date, read_capture_metadata, resolve_camera_capture_settings
from .preprocess import load_image_bgr, preprocess_for_onnx


@dataclass(frozen=True)
class PredictionResult:
    image_path: str
    model_path: str
    predicted_weight_g: float
    captured_at_iso: str
    plant_height_cm: float
    plant_width_cm: float
    leaf_color: str
    leaf_color_score: float
    raw_features: dict[str, float]


def load_model_metadata(model_path: Path) -> dict[str, Any]:
    metadata_path = model_path.with_suffix(".json")
    if metadata_path.exists():
        return json.loads(metadata_path.read_text())
    return {}


def resolve_captured_at(image_path: Path) -> datetime:
    metadata = read_capture_metadata(image_path)
    captured_at = metadata.get("captured_at")
    if isinstance(captured_at, datetime):
        if captured_at.tzinfo is None:
            return captured_at.astimezone()
        return captured_at
    return datetime.fromtimestamp(image_path.stat().st_mtime).astimezone()


def extract_prediction_inputs(
    image_path: Path,
    model_metadata: dict[str, Any],
    planting_date: str | None,
):
    runtime_config = load_runtime_config()
    resolved_planting_date = parse_optional_date(planting_date or model_metadata.get("planting_date"))
    image_bgr = load_image_bgr(image_path)
    capture_metadata = read_capture_metadata(image_path)
    captured_at = resolve_captured_at(image_path)
    camera_distance_cm, camera_fov_deg, camera_fov_axis = resolve_camera_capture_settings(
        metadata=capture_metadata,
        default_distance_cm=float(model_metadata.get("camera_distance_cm", runtime_config.camera_distance_cm)),
        default_fov_deg=float(model_metadata.get("camera_fov_deg", runtime_config.camera_fov_deg)),
        default_fov_axis=str(model_metadata.get("camera_fov_axis", runtime_config.camera_fov_axis)),
    )
    feature_bundle = extract_feature_bundle(
        image_bgr=image_bgr,
        captured_at=captured_at,
        planting_date=resolved_planting_date,
        camera_distance_cm=camera_distance_cm,
        camera_fov_deg=camera_fov_deg,
        camera_fov_axis=camera_fov_axis,
    )
    return image_bgr, captured_at, feature_bundle


def predict_image(image_path: Path, model_path: Path, planting_date: str | None = None) -> PredictionResult:
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    model_metadata = load_model_metadata(model_path)
    image_bgr, captured_at, feature_bundle = extract_prediction_inputs(
        image_path=image_path,
        model_metadata=model_metadata,
        planting_date=planting_date,
    )

    if model_path.suffix.lower() == ".json":
        regressor_payload = load_feature_regressor(model_path)
        predicted_weight = predict_with_feature_regressor(feature_bundle.raw_features, regressor_payload)
    else:
        image_size = int(model_metadata.get("image_size", 224))
        feature_names = tuple(model_metadata.get("feature_names", list(MODEL_FEATURE_NAMES)))
        session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        output_name = session.get_outputs()[0].name
        inputs = {
            "image": preprocess_for_onnx(image_bgr=image_bgr, image_size=image_size),
            "features": build_model_feature_vector(feature_bundle.raw_features, feature_names).reshape(1, -1),
        }
        prediction = session.run([output_name], inputs)[0]
        predicted_weight = float(prediction.reshape(-1)[0])

    return PredictionResult(
        image_path=str(image_path),
        model_path=str(model_path),
        predicted_weight_g=predicted_weight,
        captured_at_iso=captured_at.isoformat(),
        plant_height_cm=float(feature_bundle.raw_features["plant_height_cm"]),
        plant_width_cm=float(feature_bundle.raw_features["plant_width_cm"]),
        leaf_color=str(feature_bundle.metadata_fields["leaf_color"]),
        leaf_color_score=float(feature_bundle.raw_features["leaf_color_score"]),
        raw_features=feature_bundle.raw_features,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict butterhead weight from a single image.")
    parser.add_argument("--image", required=True, type=Path, help="Path to the captured JPEG image.")
    parser.add_argument("--model", required=True, type=Path, help="Path to the ONNX or JSON model.")
    parser.add_argument("--planting-date", default=None, help="Optional planting date in YYYY-MM-DD.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = predict_image(image_path=args.image, model_path=args.model, planting_date=args.planting_date)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0
