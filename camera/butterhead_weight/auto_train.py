from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2

from .config import RuntimeConfig
from .dataset import load_label_rows
from .feature_regressor import (
    FeatureTrainingSample,
    ensure_bootstrap_model,
    fit_feature_regressor,
    save_feature_regressor,
)
from .features import extract_feature_bundle
from .metadata import (
    parse_optional_date,
    parse_optional_datetime,
    read_capture_metadata,
    resolve_camera_capture_settings,
)


@dataclass(frozen=True)
class AutoTrainResult:
    status: str
    model_path: str | None
    model_source: str
    label_count: int
    message: str


@dataclass(frozen=True)
class PreparedModel:
    model_path: Path
    model_source: str
    auto_train_status: str


def _resolve_captured_at(row: dict[str, str], image_path: Path, file_metadata: dict[str, object]) -> datetime:
    captured_at = file_metadata.get("captured_at")
    if isinstance(captured_at, datetime):
        if captured_at.tzinfo is None:
            return captured_at.astimezone()
        return captured_at

    parsed_captured_at = parse_optional_datetime(row.get("captured_at"))
    if parsed_captured_at is not None:
        return parsed_captured_at

    return datetime.fromtimestamp(image_path.stat().st_mtime).astimezone()


def _build_training_samples(
    config: RuntimeConfig,
    label_rows: list[dict[str, str]],
    default_planting_date: str | None,
) -> list[FeatureTrainingSample]:
    samples: list[FeatureTrainingSample] = []
    default_date = parse_optional_date(default_planting_date)

    for row in label_rows:
        image_path = Path(row["image_path"]).expanduser()
        if not image_path.exists():
            continue

        image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image_bgr is None:
            continue

        file_metadata = read_capture_metadata(image_path)
        captured_at = _resolve_captured_at(row=row, image_path=image_path, file_metadata=file_metadata)
        planting_date = parse_optional_date(row.get("planting_date")) or default_date
        camera_distance_cm, camera_fov_deg, camera_fov_axis = resolve_camera_capture_settings(
            metadata=file_metadata,
            default_distance_cm=config.camera_distance_cm,
            default_fov_deg=config.camera_fov_deg,
            default_fov_axis=config.camera_fov_axis,
        )
        feature_bundle = extract_feature_bundle(
            image_bgr=image_bgr,
            captured_at=captured_at,
            planting_date=planting_date,
            camera_distance_cm=camera_distance_cm,
            camera_fov_deg=camera_fov_deg,
            camera_fov_axis=camera_fov_axis,
        )
        samples.append(
            FeatureTrainingSample(
                image_path=str(image_path),
                weight_g=float(row["weight_g"]),
                raw_features=feature_bundle.raw_features,
            )
        )

    return samples


def _load_auto_train_state(state_path: Path) -> dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text())
    except json.JSONDecodeError:
        return {}


def _save_auto_train_state(state_path: Path, payload: dict[str, object]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def maybe_auto_train_feature_model(
    config: RuntimeConfig,
    default_planting_date: str | None = None,
    force: bool = False,
) -> AutoTrainResult:
    label_csv_path = config.default_label_csv
    if not config.auto_train_enabled and not force:
        return AutoTrainResult(
            status="disabled",
            model_path=None,
            model_source="none",
            label_count=0,
            message="Auto training is disabled.",
        )

    if not label_csv_path.exists():
        return AutoTrainResult(
            status="missing_labels",
            model_path=None,
            model_source="none",
            label_count=0,
            message=f"Label CSV not found: {label_csv_path}",
        )

    try:
        label_rows = load_label_rows(label_csv_path)
    except ValueError as exc:
        if "No rows found" in str(exc):
            return AutoTrainResult(
                status="insufficient_labels",
                model_path=None,
                model_source="bootstrap_default",
                label_count=0,
                message="No labeled weights are available yet.",
            )
        return AutoTrainResult(
            status="invalid_labels",
            model_path=None,
            model_source="bootstrap_default",
            label_count=0,
            message=f"Unable to parse label CSV: {exc}",
        )
    except Exception as exc:
        return AutoTrainResult(
            status="invalid_labels",
            model_path=None,
            model_source="bootstrap_default",
            label_count=0,
            message=f"Unable to parse label CSV: {exc}",
        )
    label_count = len(label_rows)
    if label_count < config.auto_train_min_labels and not force:
        return AutoTrainResult(
            status="insufficient_labels",
            model_path=None,
            model_source="bootstrap_default",
            label_count=label_count,
            message=(
                f"Need at least {config.auto_train_min_labels} labeled weights before auto training "
                f"(currently {label_count})."
            ),
        )

    state = _load_auto_train_state(config.auto_train_state_path)
    previous_count = int(state.get("label_count", 0) or 0)
    labels_mtime_ns = label_csv_path.stat().st_mtime_ns
    previous_mtime_ns = int(state.get("labels_mtime_ns", 0) or 0)

    if (
        not force
        and config.auto_feature_model_path.exists()
        and label_count < previous_count + config.auto_train_min_new_labels
        and labels_mtime_ns <= previous_mtime_ns
    ):
        return AutoTrainResult(
            status="up_to_date",
            model_path=str(config.auto_feature_model_path),
            model_source="auto_trained_feature_regressor",
            label_count=label_count,
            message="Auto-trained feature model is already up to date.",
        )

    try:
        samples = _build_training_samples(
            config=config,
            label_rows=label_rows,
            default_planting_date=default_planting_date,
        )
    except Exception as exc:
        return AutoTrainResult(
            status="feature_extraction_failed",
            model_path=None,
            model_source="bootstrap_default",
            label_count=label_count,
            message=f"Unable to build training samples: {exc}",
        )
    if len(samples) < config.auto_train_min_labels and not force:
        return AutoTrainResult(
            status="insufficient_valid_labels",
            model_path=None,
            model_source="bootstrap_default",
            label_count=len(samples),
            message=(
                f"Need at least {config.auto_train_min_labels} valid label rows with readable images "
                f"(currently {len(samples)})."
            ),
        )

    try:
        payload = fit_feature_regressor(samples=samples)
    except Exception as exc:
        return AutoTrainResult(
            status="training_failed",
            model_path=None,
            model_source="bootstrap_default",
            label_count=label_count,
            message=f"Auto training failed: {exc}",
        )
    payload["label_csv"] = str(label_csv_path)
    payload["trained_image_count"] = len(samples)
    save_feature_regressor(config.auto_feature_model_path, payload)
    _save_auto_train_state(
        config.auto_train_state_path,
        {
            "label_count": label_count,
            "labels_mtime_ns": labels_mtime_ns,
            "model_path": str(config.auto_feature_model_path),
            "trained_at": payload["trained_at"],
            "trained_image_count": len(samples),
            "fit_mae_g": payload["fit_mae_g"],
            "fit_rmse_g": payload["fit_rmse_g"],
            "fit_r2": payload["fit_r2"],
        },
    )
    return AutoTrainResult(
        status="trained",
        model_path=str(config.auto_feature_model_path),
        model_source="auto_trained_feature_regressor",
        label_count=label_count,
        message=(
            f"Trained feature regressor with {len(samples)} labeled images "
            f"(fit MAE {payload['fit_mae_g']:.2f} g)."
        ),
    )


def prepare_prediction_model(
    config: RuntimeConfig,
    requested_model_path: Path | None,
    default_planting_date: str | None = None,
) -> PreparedModel:
    auto_train_result = AutoTrainResult(
        status="not_checked",
        model_path=None,
        model_source="none",
        label_count=0,
        message="Auto training was not checked.",
    )

    if requested_model_path is not None and requested_model_path.exists():
        return PreparedModel(
            model_path=requested_model_path,
            model_source="requested_model",
            auto_train_status=auto_train_result.status,
        )

    if requested_model_path is None or not requested_model_path.exists():
        auto_train_result = maybe_auto_train_feature_model(
            config=config,
            default_planting_date=default_planting_date,
        )

    if config.auto_feature_model_path.exists():
        return PreparedModel(
            model_path=config.auto_feature_model_path,
            model_source="auto_trained_feature_regressor",
            auto_train_status=auto_train_result.status,
        )

    efficientnet_onnx_path = config.model_dir / "butterhead_weight_efficientnet_b0.onnx"
    if efficientnet_onnx_path.exists():
        return PreparedModel(
            model_path=efficientnet_onnx_path,
            model_source="efficientnet_onnx_default",
            auto_train_status=auto_train_result.status,
        )

    bootstrap_path = ensure_bootstrap_model(config.bootstrap_model_path)
    fallback_source = "bootstrap_default"
    if requested_model_path is not None and not requested_model_path.exists():
        fallback_source = "bootstrap_default_missing_requested"
    return PreparedModel(
        model_path=bootstrap_path,
        model_source=fallback_source,
        auto_train_status=auto_train_result.status,
    )
