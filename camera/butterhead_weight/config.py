from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
CAMERA_DIR = PACKAGE_DIR.parent
PROJECT_DIR = CAMERA_DIR.parent


def _default_camera_device() -> str:
    preferred = os.environ.get(
        "BUTTERHEAD_CAMERA_DEVICE",
        "/dev/v4l/by-id/usb-046d_C270_HD_WEBCAM_200901010001-video-index0",
    )
    if Path(preferred).exists():
        return preferred

    for candidate in ("/dev/video0", "/dev/video1"):
        if Path(candidate).exists():
            return candidate

    return preferred


@dataclass(frozen=True)
class RuntimeConfig:
    camera_dir: Path
    project_dir: Path
    capture_dir: Path
    preview_dir: Path
    model_dir: Path
    label_dir: Path
    log_dir: Path
    prediction_log_csv: Path
    db_path: Path
    default_label_csv: Path
    bootstrap_model_path: Path
    auto_feature_model_path: Path
    auto_train_state_path: Path
    camera_device: str
    camera_model: str
    camera_distance_cm: float
    camera_fov_deg: float
    camera_fov_axis: str
    camera_max_fps: float
    capture_width: int
    capture_height: int
    image_size: int
    monitor_hour: int
    monitor_minute: int
    auto_train_enabled: bool
    auto_train_min_labels: int
    auto_train_min_new_labels: int


def load_runtime_config() -> RuntimeConfig:
    capture_width = int(os.environ.get("BUTTERHEAD_CAPTURE_WIDTH", "1280"))
    capture_height = int(os.environ.get("BUTTERHEAD_CAPTURE_HEIGHT", "720"))
    image_size = int(os.environ.get("BUTTERHEAD_IMAGE_SIZE", "224"))
    camera_model = os.environ.get("BUTTERHEAD_CAMERA_MODEL", "Logitech C270")
    camera_distance_cm = float(os.environ.get("BUTTERHEAD_CAMERA_DISTANCE_CM", "26.0"))
    camera_fov_deg = float(os.environ.get("BUTTERHEAD_CAMERA_FOV_DEG", "55.0"))
    camera_fov_axis = os.environ.get("BUTTERHEAD_CAMERA_FOV_AXIS", "diagonal").strip().lower() or "diagonal"
    camera_max_fps = float(os.environ.get("BUTTERHEAD_CAMERA_MAX_FPS", "30.0"))
    monitor_hour = int(os.environ.get("BUTTERHEAD_MONITOR_HOUR", "9"))
    monitor_minute = int(os.environ.get("BUTTERHEAD_MONITOR_MINUTE", "0"))
    auto_train_enabled = os.environ.get("BUTTERHEAD_AUTO_TRAIN_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    auto_train_min_labels = int(os.environ.get("BUTTERHEAD_AUTO_TRAIN_MIN_LABELS", "10"))
    auto_train_min_new_labels = int(os.environ.get("BUTTERHEAD_AUTO_TRAIN_MIN_NEW_LABELS", "3"))

    config = RuntimeConfig(
        camera_dir=CAMERA_DIR,
        project_dir=PROJECT_DIR,
        capture_dir=CAMERA_DIR / "data" / "captures",
        preview_dir=CAMERA_DIR / "data" / "previews",
        model_dir=CAMERA_DIR / "data" / "models",
        label_dir=CAMERA_DIR / "data" / "labels",
        log_dir=CAMERA_DIR / "logs",
        prediction_log_csv=CAMERA_DIR / "logs" / "butterhead_weight_predictions.csv",
        db_path=PROJECT_DIR / "data" / "data.db",
        default_label_csv=CAMERA_DIR / "data" / "labels" / "butterhead_weights.csv",
        bootstrap_model_path=CAMERA_DIR / "data" / "models" / "butterhead_weight_bootstrap.json",
        auto_feature_model_path=CAMERA_DIR / "data" / "models" / "butterhead_weight_feature_regressor.json",
        auto_train_state_path=CAMERA_DIR / "data" / "models" / "butterhead_weight_auto_train_state.json",
        camera_device=_default_camera_device(),
        camera_model=camera_model,
        camera_distance_cm=camera_distance_cm,
        camera_fov_deg=camera_fov_deg,
        camera_fov_axis=camera_fov_axis,
        camera_max_fps=camera_max_fps,
        capture_width=capture_width,
        capture_height=capture_height,
        image_size=image_size,
        monitor_hour=monitor_hour,
        monitor_minute=monitor_minute,
        auto_train_enabled=auto_train_enabled,
        auto_train_min_labels=auto_train_min_labels,
        auto_train_min_new_labels=auto_train_min_new_labels,
    )
    ensure_runtime_dirs(config)
    return config


def ensure_runtime_dirs(config: RuntimeConfig) -> None:
    for directory in (
        config.capture_dir,
        config.preview_dir,
        config.model_dir,
        config.label_dir,
        config.log_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
