from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import atan, radians, sqrt, tan
from typing import Any

import cv2
import numpy as np


MODEL_FEATURE_NAMES = (
    "green_area_ratio",
    "canopy_bbox_ratio",
    "excess_green_mean",
    "days_since_planting",
    "plant_height_cm",
    "plant_width_cm",
    "leaf_color_score",
)
ROBUST_HEIGHT_LOWER_QUANTILE = 0.22
ROBUST_HEIGHT_UPPER_QUANTILE = 0.78
ROBUST_WIDTH_LOWER_QUANTILE = 0.08
ROBUST_WIDTH_UPPER_QUANTILE = 0.92


@dataclass(frozen=True)
class FeatureBundle:
    model_features: np.ndarray
    raw_features: dict[str, float]
    metadata_fields: dict[str, Any]
    mask: np.ndarray


def compute_days_since_planting(captured_at: datetime, planting_date: date | None) -> float:
    if planting_date is None:
        return 0.0
    if captured_at.tzinfo is not None:
        captured_on = captured_at.date()
    else:
        captured_on = captured_at.date()
    return float(max((captured_on - planting_date).days, 0))


def extract_canopy_mask(image_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lower = np.array([25, 35, 30], dtype=np.uint8)
    upper = np.array([95, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)

    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        refined = np.zeros_like(mask)
        cv2.drawContours(refined, [largest], contourIdx=-1, color=255, thickness=cv2.FILLED)
        return refined
    return mask


def extract_feature_bundle(
    image_bgr: np.ndarray,
    captured_at: datetime,
    planting_date: date | None,
    camera_distance_cm: float = 26.0,
    camera_fov_deg: float = 55.0,
    camera_fov_axis: str = "diagonal",
) -> FeatureBundle:
    mask = extract_canopy_mask(image_bgr)
    image_area = float(mask.size)
    area_ratio = float(np.count_nonzero(mask)) / image_area

    bbox_ratio = 0.0
    excess_green_mean = 0.0
    plant_height_ratio = 0.0
    plant_width_ratio = 0.0
    plant_height_cm = 0.0
    plant_width_cm = 0.0
    plant_height_mode = "bbox"
    plant_width_mode = "bbox"
    leaf_color_score = 0.0
    leaf_color = "unknown"
    scene_width_cm, scene_height_cm = compute_scene_dimensions_cm(
        image_width_px=image_bgr.shape[1],
        image_height_px=image_bgr.shape[0],
        camera_distance_cm=camera_distance_cm,
        camera_fov_deg=camera_fov_deg,
        camera_fov_axis=camera_fov_axis,
    )

    if area_ratio > 0.0:
        ys, xs = np.where(mask > 0)
        full_height_px = float(ys.max() - ys.min() + 1)
        full_width_px = float(xs.max() - xs.min() + 1)
        plant_height_px = full_height_px
        if ys.min() == 0 or ys.max() == image_bgr.shape[0] - 1:
            plant_height_px = compute_trimmed_span_px(
                coordinates=ys,
                lower_quantile=ROBUST_HEIGHT_LOWER_QUANTILE,
                upper_quantile=ROBUST_HEIGHT_UPPER_QUANTILE,
            )
            plant_height_mode = "trimmed_quantile"
        plant_width_px = full_width_px
        if xs.min() == 0 or xs.max() == image_bgr.shape[1] - 1:
            plant_width_px = compute_trimmed_span_px(
                coordinates=xs,
                lower_quantile=ROBUST_WIDTH_LOWER_QUANTILE,
                upper_quantile=ROBUST_WIDTH_UPPER_QUANTILE,
            )
            plant_width_mode = "trimmed_quantile"
        bbox_area = float(full_width_px * full_height_px)
        bbox_ratio = bbox_area / image_area
        plant_height_ratio = float(plant_height_px / image_bgr.shape[0])
        plant_width_ratio = float(plant_width_px / image_bgr.shape[1])
        plant_height_cm = float(plant_height_ratio * scene_height_cm)
        plant_width_cm = float(plant_width_ratio * scene_width_cm)

        b_channel, g_channel, r_channel = cv2.split(image_bgr.astype(np.float32))
        excess_green = np.clip((2.0 * g_channel) - r_channel - b_channel, a_min=0.0, a_max=None)
        excess_green_mean = float(excess_green[mask > 0].mean() / 255.0)

        hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        saturation_mean = float((hsv[:, :, 1][mask > 0] / 255.0).mean())
        value_mean = float((hsv[:, :, 2][mask > 0] / 255.0).mean())
        leaf_color_score = max(0.0, min(1.0, (0.65 * excess_green_mean) + (0.35 * saturation_mean)))
        leaf_color = classify_leaf_color(leaf_color_score=leaf_color_score, value_mean=value_mean)

    days_since_planting = compute_days_since_planting(captured_at, planting_date)
    raw_features = {
        "green_area_ratio": area_ratio,
        "canopy_bbox_ratio": bbox_ratio,
        "excess_green_mean": excess_green_mean,
        "days_since_planting": days_since_planting,
        "plant_height_ratio": plant_height_ratio,
        "plant_width_ratio": plant_width_ratio,
        "plant_height_cm": plant_height_cm,
        "plant_width_cm": plant_width_cm,
        "leaf_color_score": leaf_color_score,
    }
    metadata_fields = {
        "plant_height_ratio": plant_height_ratio,
        "plant_width_ratio": plant_width_ratio,
        "plant_height_cm": plant_height_cm,
        "plant_width_cm": plant_width_cm,
        "leaf_color": leaf_color,
        "leaf_color_score": leaf_color_score,
        "plant_height_mode": plant_height_mode,
        "plant_width_mode": plant_width_mode,
        "camera_distance_cm": camera_distance_cm,
        "camera_fov_deg": camera_fov_deg,
        "camera_fov_axis": camera_fov_axis,
        "scene_width_cm": scene_width_cm,
        "scene_height_cm": scene_height_cm,
        "초장_비율": plant_height_ratio,
        "초폭_비율": plant_width_ratio,
        "초장_cm": plant_height_cm,
        "초폭_cm": plant_width_cm,
        "초장": plant_height_cm,
        "초폭": plant_width_cm,
        "엽색": leaf_color,
    }
    model_features = build_model_feature_vector(raw_features)
    return FeatureBundle(
        model_features=model_features,
        raw_features=raw_features,
        metadata_fields=metadata_fields,
        mask=mask,
    )


def classify_leaf_color(leaf_color_score: float, value_mean: float) -> str:
    if leaf_color_score <= 0.0:
        return "unknown"
    if value_mean >= 0.72 and leaf_color_score < 0.28:
        return "light_green"
    if leaf_color_score < 0.24:
        return "yellow_green"
    if value_mean < 0.35 or leaf_color_score >= 0.52:
        return "deep_green"
    return "green"


def build_model_feature_vector(
    raw_features: dict[str, float],
    feature_names: tuple[str, ...] = MODEL_FEATURE_NAMES,
) -> np.ndarray:
    return np.array([float(raw_features[name]) for name in feature_names], dtype=np.float32)


def compute_trimmed_span_px(
    coordinates: np.ndarray,
    lower_quantile: float,
    upper_quantile: float,
) -> float:
    if coordinates.size == 0:
        return 0.0
    low = float(np.quantile(coordinates, lower_quantile))
    high = float(np.quantile(coordinates, upper_quantile))
    return float(max(high - low + 1.0, 1.0))


def compute_scene_dimensions_cm(
    image_width_px: int,
    image_height_px: int,
    camera_distance_cm: float,
    camera_fov_deg: float,
    camera_fov_axis: str,
) -> tuple[float, float]:
    aspect_width = float(image_width_px)
    aspect_height = float(image_height_px)
    if aspect_width <= 0 or aspect_height <= 0:
        return 0.0, 0.0

    axis = camera_fov_axis.strip().lower()
    base_half_angle = radians(max(camera_fov_deg, 1e-6) / 2.0)

    if axis == "horizontal":
        horizontal_half_angle = base_half_angle
        vertical_half_angle = atan(tan(horizontal_half_angle) * (aspect_height / aspect_width))
    elif axis == "vertical":
        vertical_half_angle = base_half_angle
        horizontal_half_angle = atan(tan(vertical_half_angle) * (aspect_width / aspect_height))
    else:
        diagonal_length = sqrt((aspect_width ** 2) + (aspect_height ** 2))
        horizontal_half_angle = atan(tan(base_half_angle) * (aspect_width / diagonal_length))
        vertical_half_angle = atan(tan(base_half_angle) * (aspect_height / diagonal_length))

    scene_width_cm = float(2.0 * camera_distance_cm * tan(horizontal_half_angle))
    scene_height_cm = float(2.0 * camera_distance_cm * tan(vertical_half_angle))
    return scene_width_cm, scene_height_cm


def render_mask_overlay(image_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    overlay = image_bgr.copy()
    green_layer = np.zeros_like(image_bgr)
    green_layer[:, :, 1] = 255
    highlight = cv2.addWeighted(overlay, 0.7, green_layer, 0.3, 0.0)
    overlay[mask > 0] = highlight[mask > 0]
    return overlay
