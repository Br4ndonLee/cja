from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import cv2

from .auto_train import prepare_prediction_model
from .capture import build_capture_path, capture_image_to_path
from .config import load_runtime_config
from .features import extract_feature_bundle, render_mask_overlay
from .logging_utils import log_prediction
from .metadata import parse_optional_date, update_capture_metadata
from .predict import predict_image
from .preprocess import load_image_bgr
from .stabilization import stabilize_bootstrap_prediction


@dataclass(frozen=True)
class PipelineResult:
    captured_at_iso: str
    image_path: str
    preview_path: str
    metadata_written: bool
    analysis_logged: bool
    model_path: str | None
    model_source: str
    auto_train_status: str
    predicted_weight_g: float | None
    plant_height_cm: float
    plant_width_cm: float
    leaf_color: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture one butterhead image and predict its weight.")
    parser.add_argument("--plant-id", default="butterhead-01", help="Logical plant identifier.")
    parser.add_argument("--batch-id", default="default-batch", help="Logical batch or tray identifier.")
    parser.add_argument("--planting-date", default=None, help="Planting date in YYYY-MM-DD.")
    parser.add_argument("--model", type=Path, default=None, help="Optional ONNX or JSON model path for prediction.")
    parser.add_argument("--device", default=None, help="Camera device path.")
    parser.add_argument("--width", type=int, default=None, help="Capture width.")
    parser.add_argument("--height", type=int, default=None, help="Capture height.")
    return parser.parse_args()


def run_capture_pipeline(
    plant_id: str,
    batch_id: str,
    planting_date: str | None,
    model_path: Path | None,
    device: str | None,
    width: int | None,
    height: int | None,
) -> PipelineResult:
    config = load_runtime_config()
    resolved_device = device or config.camera_device
    resolved_width = width or config.capture_width
    resolved_height = height or config.capture_height
    captured_at = datetime.now().astimezone()
    image_path = build_capture_path(config.capture_dir, plant_id=plant_id, captured_at=captured_at)

    capture_image_to_path(
        device=resolved_device,
        output_path=image_path,
        width=resolved_width,
        height=resolved_height,
        plant_id=plant_id,
        batch_id=batch_id,
        captured_at=captured_at,
    )

    image_bgr = load_image_bgr(image_path)
    feature_bundle = extract_feature_bundle(
        image_bgr=image_bgr,
        captured_at=captured_at,
        planting_date=parse_optional_date(planting_date),
        camera_distance_cm=config.camera_distance_cm,
        camera_fov_deg=config.camera_fov_deg,
        camera_fov_axis=config.camera_fov_axis,
    )
    update_capture_metadata(
        image_path,
        {
            "camera_model": config.camera_model,
            "camera_distance_cm": config.camera_distance_cm,
            "camera_fov_deg": config.camera_fov_deg,
            "camera_fov_axis": config.camera_fov_axis,
            "camera_max_fps": config.camera_max_fps,
            "capture_width_px": resolved_width,
            "capture_height_px": resolved_height,
            **feature_bundle.metadata_fields,
        },
    )
    preview = render_mask_overlay(image_bgr=image_bgr, mask=feature_bundle.mask)
    preview_path = config.preview_dir / image_path.relative_to(config.capture_dir)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(preview_path), preview)

    prepared_model = prepare_prediction_model(
        config=config,
        requested_model_path=model_path,
        default_planting_date=planting_date,
    )
    predicted_weight = None
    if prepared_model.model_path is not None:
        result = predict_image(image_path=image_path, model_path=prepared_model.model_path, planting_date=planting_date)
        predicted_weight = result.predicted_weight_g
        if prepared_model.model_source.startswith("bootstrap"):
            predicted_weight = stabilize_bootstrap_prediction(
                config=config,
                plant_id=plant_id,
                batch_id=batch_id,
                captured_at_iso=captured_at.isoformat(),
                predicted_weight_g=predicted_weight,
                plant_height_cm=float(feature_bundle.raw_features["plant_height_cm"]),
                plant_width_cm=float(feature_bundle.raw_features["plant_width_cm"]),
            )
    log_prediction(
        config=config,
        captured_at_iso=captured_at.isoformat(),
        image_path=image_path,
        predicted_weight_g=predicted_weight,
        raw_features=feature_bundle.raw_features,
        metadata_fields={
            **feature_bundle.metadata_fields,
            "camera_model": config.camera_model,
        },
        model_path=prepared_model.model_path,
        plant_id=plant_id,
        batch_id=batch_id,
    )

    return PipelineResult(
        captured_at_iso=captured_at.isoformat(),
        image_path=str(image_path),
        preview_path=str(preview_path),
        metadata_written=True,
        analysis_logged=True,
        model_path=str(prepared_model.model_path) if prepared_model.model_path is not None else None,
        model_source=prepared_model.model_source,
        auto_train_status=prepared_model.auto_train_status,
        predicted_weight_g=predicted_weight,
        plant_height_cm=float(feature_bundle.raw_features["plant_height_cm"]),
        plant_width_cm=float(feature_bundle.raw_features["plant_width_cm"]),
        leaf_color=str(feature_bundle.metadata_fields["leaf_color"]),
    )


def main() -> int:
    args = parse_args()
    payload = run_capture_pipeline(
        plant_id=args.plant_id,
        batch_id=args.batch_id,
        planting_date=args.planting_date,
        model_path=args.model,
        device=args.device,
        width=args.width,
        height=args.height,
    )
    print(json.dumps(asdict(payload), indent=2, sort_keys=True))
    return 0
