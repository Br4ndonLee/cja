from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import piexif
import piexif.helper
from PIL import Image

from .metadata import build_capture_metadata, format_exif_datetime


def _candidate_devices(device: str) -> list[str]:
    candidates = [device]
    if Path(device).exists():
        resolved = str(Path(device).resolve())
        if resolved not in candidates:
            candidates.append(resolved)
    for fallback in ("/dev/video0", "/dev/video1"):
        if Path(fallback).exists() and fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _capture_from_device(device: str, width: int, height: int, warmup_frames: int) -> np.ndarray | None:
    capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not capture.isOpened():
        capture = cv2.VideoCapture(device)
    if not capture.isOpened():
        return None

    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FPS, 5)

    frame = None
    try:
        for _ in range(max(3, warmup_frames)):
            ok, next_frame = capture.read()
            if ok:
                frame = next_frame
            time.sleep(0.12)

        if frame is None:
            ok, next_frame = capture.read()
            if ok:
                frame = next_frame

        return frame
    finally:
        capture.release()


def _resolve_usb_id(device: str) -> str | None:
    try:
        resolved_device = Path(device).resolve()
    except FileNotFoundError:
        return None

    sysfs_dir = Path("/sys/class/video4linux") / resolved_device.name / "device"
    if not sysfs_dir.exists():
        return None

    for candidate in (sysfs_dir.resolve(), *sysfs_dir.resolve().parents):
        vendor_path = candidate / "idVendor"
        product_path = candidate / "idProduct"
        if not vendor_path.exists() or not product_path.exists():
            continue
        vendor_id = vendor_path.read_text().strip().lower()
        product_id = product_path.read_text().strip().lower()
        if vendor_id and product_id:
            return f"{vendor_id}:{product_id}"
    return None


def _reset_usb_camera(device: str) -> bool:
    usb_id = _resolve_usb_id(device)
    if not usb_id:
        return False

    try:
        completed = subprocess.run(
            ["sudo", "usbreset", usb_id],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    if completed.returncode != 0:
        return False

    time.sleep(3.0)
    return True


def capture_frame(device: str, width: int, height: int, warmup_frames: int = 8) -> np.ndarray:
    for candidate in _candidate_devices(device):
        frame = _capture_from_device(device=candidate, width=width, height=height, warmup_frames=warmup_frames)
        if frame is not None:
            return frame

    reset_attempted = _reset_usb_camera(device)
    if reset_attempted:
        for candidate in _candidate_devices(device):
            frame = _capture_from_device(device=candidate, width=width, height=height, warmup_frames=warmup_frames)
            if frame is not None:
                return frame

    raise RuntimeError(
        "Unable to capture a frame from the camera device via OpenCV direct capture. "
        f"device={device} usb_reset_attempted={reset_attempted}"
    )


def overlay_capture_timestamp(frame_bgr: np.ndarray, captured_at: datetime) -> np.ndarray:
    annotated = frame_bgr.copy()
    timestamp_text = captured_at.astimezone().strftime("%Y-%m-%d %H:%M")
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.6, min(1.0, annotated.shape[1] / 1600.0))
    thickness = max(2, int(round(font_scale * 2)))
    margin = max(14, int(round(font_scale * 18)))
    (text_width, text_height), baseline = cv2.getTextSize(timestamp_text, font, font_scale, thickness)

    x1 = margin
    y2 = annotated.shape[0] - margin
    x2 = x1 + text_width + (margin // 2)
    y1 = y2 - text_height - baseline - (margin // 2)

    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 0), thickness=-1)
    cv2.putText(
        annotated,
        timestamp_text,
        (x1 + (margin // 4), y2 - baseline - (margin // 4)),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        lineType=cv2.LINE_AA,
    )
    return annotated


def save_frame_with_exif(
    frame_bgr: np.ndarray,
    output_path: Path,
    captured_at: datetime,
    plant_id: str,
    batch_id: str,
    device: str,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_with_timestamp = overlay_capture_timestamp(frame_bgr=frame_bgr, captured_at=captured_at)
    height, width = frame_with_timestamp.shape[:2]
    metadata = build_capture_metadata(
        captured_at=captured_at,
        plant_id=plant_id,
        batch_id=batch_id,
        device=device,
        image_width=width,
        image_height=height,
    )

    image_rgb = cv2.cvtColor(frame_with_timestamp, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(image_rgb)

    exif_dict = {
        "0th": {
            piexif.ImageIFD.Software: "cja-skyfarms-camera",
            piexif.ImageIFD.ImageDescription: f"butterhead_capture:{plant_id}",
            piexif.ImageIFD.DateTime: format_exif_datetime(captured_at),
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: format_exif_datetime(captured_at),
            piexif.ExifIFD.DateTimeDigitized: format_exif_datetime(captured_at),
            piexif.ExifIFD.UserComment: piexif.helper.UserComment.dump(
                json_dumps(metadata),
                encoding="unicode",
            ),
        },
    }

    image.save(output_path, format="JPEG", quality=95, exif=piexif.dump(exif_dict))
    return metadata


def capture_image_to_path(
    device: str,
    output_path: Path,
    width: int,
    height: int,
    plant_id: str,
    batch_id: str,
    captured_at: datetime | None = None,
) -> tuple[Path, dict[str, object]]:
    captured_at = captured_at or datetime.now().astimezone()
    frame = capture_frame(device=device, width=width, height=height)
    metadata = save_frame_with_exif(
        frame_bgr=frame,
        output_path=output_path,
        captured_at=captured_at,
        plant_id=plant_id,
        batch_id=batch_id,
        device=device,
    )
    return output_path, metadata


def build_capture_path(base_dir: Path, plant_id: str, captured_at: datetime) -> Path:
    dated_dir = base_dir / captured_at.strftime("%Y") / captured_at.strftime("%m")
    file_name = f"{plant_id}__{captured_at.strftime('%Y%m%d_%H%M%S')}.jpg"
    return dated_dir / file_name


def json_dumps(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
