from __future__ import annotations

import csv
import random
from datetime import datetime
from pathlib import Path

import cv2
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from .config import load_runtime_config
from .features import FeatureBundle, extract_feature_bundle
from .metadata import (
    parse_optional_date,
    parse_optional_datetime,
    read_capture_metadata,
    resolve_camera_capture_settings,
)
from .preprocess import build_eval_transform, build_train_transform


def load_label_rows(label_csv_path: Path) -> list[dict[str, str]]:
    with label_csv_path.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]

    if not rows:
        raise ValueError(f"No rows found in label CSV: {label_csv_path}")

    required_columns = {"image_path", "weight_g"}
    missing_columns = required_columns.difference(rows[0].keys())
    if missing_columns:
        raise ValueError(f"Label CSV is missing required columns: {sorted(missing_columns)}")

    return rows


def split_rows(rows: list[dict[str, str]], val_ratio: float, seed: int) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if all(row.get("split") for row in rows):
        train_rows = [row for row in rows if row.get("split", "").strip().lower() == "train"]
        val_rows = [row for row in rows if row.get("split", "").strip().lower() == "val"]
        if not train_rows or not val_rows:
            raise ValueError("When using the split column, both train and val rows must exist.")
        return train_rows, val_rows

    shuffled_rows = rows[:]
    random.Random(seed).shuffle(shuffled_rows)
    val_count = max(1, int(len(shuffled_rows) * val_ratio))
    val_rows = shuffled_rows[:val_count]
    train_rows = shuffled_rows[val_count:]
    if not train_rows:
        raise ValueError("Training split is empty. Add more labeled images or lower val_ratio.")
    return train_rows, val_rows


class ButterheadWeightDataset(Dataset):
    def __init__(
        self,
        rows: list[dict[str, str]],
        image_size: int,
        training: bool,
        default_planting_date: str | None = None,
    ) -> None:
        self.rows = rows
        self.training = training
        self.default_planting_date = parse_optional_date(default_planting_date)
        runtime_config = load_runtime_config()
        self.default_camera_distance_cm = runtime_config.camera_distance_cm
        self.default_camera_fov_deg = runtime_config.camera_fov_deg
        self.default_camera_fov_axis = runtime_config.camera_fov_axis
        self.transform = build_train_transform(image_size) if training else build_eval_transform(image_size)

    def __len__(self) -> int:
        return len(self.rows)

    def _resolve_captured_at(self, row: dict[str, str], image_path: Path, file_metadata: dict[str, object]) -> datetime:
        if isinstance(file_metadata.get("captured_at"), datetime):
            return file_metadata["captured_at"]

        row_value = parse_optional_datetime(row.get("captured_at"))
        if row_value is not None:
            return row_value

        return datetime.fromtimestamp(image_path.stat().st_mtime).astimezone()

    def _resolve_feature_bundle(
        self,
        row: dict[str, str],
        image_bgr,
        captured_at: datetime,
        file_metadata: dict[str, object],
    ) -> FeatureBundle:
        planting_date = parse_optional_date(row.get("planting_date")) or self.default_planting_date
        camera_distance_cm, camera_fov_deg, camera_fov_axis = resolve_camera_capture_settings(
            metadata=file_metadata,
            default_distance_cm=self.default_camera_distance_cm,
            default_fov_deg=self.default_camera_fov_deg,
            default_fov_axis=self.default_camera_fov_axis,
        )
        return extract_feature_bundle(
            image_bgr=image_bgr,
            captured_at=captured_at,
            planting_date=planting_date,
            camera_distance_cm=camera_distance_cm,
            camera_fov_deg=camera_fov_deg,
            camera_fov_axis=camera_fov_axis,
        )

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        row = self.rows[index]
        image_path = Path(row["image_path"]).expanduser()
        image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise FileNotFoundError(f"Unable to load image: {image_path}")

        file_metadata = read_capture_metadata(image_path)
        captured_at = self._resolve_captured_at(row=row, image_path=image_path, file_metadata=file_metadata)
        feature_bundle = self._resolve_feature_bundle(
            row=row,
            image_bgr=image_bgr,
            captured_at=captured_at,
            file_metadata=file_metadata,
        )

        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        image_tensor = self.transform(Image.fromarray(image_rgb))
        feature_tensor = torch.from_numpy(feature_bundle.model_features)
        target = torch.tensor(float(row["weight_g"]), dtype=torch.float32)
        return image_tensor, feature_tensor, target


def create_dataloaders(
    label_csv_path: Path,
    image_size: int,
    batch_size: int,
    num_workers: int,
    val_ratio: float,
    seed: int,
    default_planting_date: str | None,
) -> tuple[DataLoader, DataLoader]:
    rows = load_label_rows(label_csv_path)
    train_rows, val_rows = split_rows(rows=rows, val_ratio=val_ratio, seed=seed)

    train_dataset = ButterheadWeightDataset(
        rows=train_rows,
        image_size=image_size,
        training=True,
        default_planting_date=default_planting_date,
    )
    val_dataset = ButterheadWeightDataset(
        rows=val_rows,
        image_size=image_size,
        training=False,
        default_planting_date=default_planting_date,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=True,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
    )
    return train_loader, val_loader
