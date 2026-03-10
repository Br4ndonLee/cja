from __future__ import annotations

import json
import math
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import piexif
import piexif.helper
from PIL import Image


def format_exif_datetime(value: datetime) -> str:
    return value.strftime("%Y:%m:%d %H:%M:%S")


def parse_optional_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def resolve_camera_capture_settings(
    metadata: dict[str, Any],
    default_distance_cm: float,
    default_fov_deg: float,
    default_fov_axis: str,
) -> tuple[float, float, str]:
    distance_cm = parse_optional_float(metadata.get("camera_distance_cm")) or default_distance_cm
    fov_deg = parse_optional_float(metadata.get("camera_fov_deg")) or default_fov_deg
    fov_axis = str(metadata.get("camera_fov_axis") or default_fov_axis or "diagonal").strip().lower()
    if fov_axis not in {"horizontal", "vertical", "diagonal"}:
        fov_axis = "diagonal"
    return distance_cm, fov_deg, fov_axis


def read_capture_metadata(image_path: Path) -> dict[str, Any]:
    with Image.open(image_path) as image:
        exif_bytes = image.info.get("exif")
    if not exif_bytes:
        return {}

    exif = piexif.load(exif_bytes)
    metadata: dict[str, Any] = {}

    original = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
    if original:
        if isinstance(original, bytes):
            original = original.decode("utf-8", errors="ignore")
        try:
            metadata["captured_at"] = datetime.strptime(original, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass

    comment = exif.get("Exif", {}).get(piexif.ExifIFD.UserComment)
    if comment:
        if isinstance(comment, bytes):
            try:
                comment = piexif.helper.UserComment.load(comment)
            except ValueError:
                comment = comment.decode("utf-8", errors="ignore")
        try:
            parsed_comment = json.loads(comment)
            metadata.update(parsed_comment)
            captured_at_iso = parsed_comment.get("captured_at_iso")
            parsed_datetime = parse_optional_datetime(captured_at_iso)
            if parsed_datetime is not None:
                metadata["captured_at"] = parsed_datetime
        except json.JSONDecodeError:
            metadata["user_comment_raw"] = comment

    return metadata


def build_capture_metadata(
    captured_at: datetime,
    plant_id: str,
    batch_id: str,
    device: str,
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    return {
        "captured_at_iso": captured_at.isoformat(),
        "plant_id": plant_id,
        "batch_id": batch_id,
        "camera_device": device,
        "image_width": image_width,
        "image_height": image_height,
    }


def update_capture_metadata(image_path: Path, extra_metadata: dict[str, Any]) -> None:
    with Image.open(image_path) as image:
        exif_bytes = image.info.get("exif")
        image_format = image.format or "JPEG"
        image_copy = image.copy()

    exif = piexif.load(exif_bytes) if exif_bytes else {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    current_metadata = read_capture_metadata(image_path)
    current_metadata.pop("captured_at", None)
    current_metadata.update(extra_metadata)
    exif.setdefault("Exif", {})
    exif["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(
        json.dumps(current_metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="unicode",
    )

    with tempfile.NamedTemporaryFile(dir=image_path.parent, suffix=image_path.suffix, delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        image_copy.save(temp_path, format=image_format, quality=95, exif=piexif.dump(exif))
        temp_path.replace(image_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
