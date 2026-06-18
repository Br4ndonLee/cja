"""
Automatic transplant detection via camera.

Detects when a seedling appears in the frame by monitoring
green_area_ratio across captures. Transitions from pre-transplant
(photo-only) to post-transplant (full analysis) automatically.

Detection criteria:
  1. green_area_ratio > DETECTION_THRESHOLD in current capture
  2. Previous capture also exceeded the threshold (2 consecutive = confirmed)
  3. On confirmation, the first detection date becomes the planting date
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import RuntimeConfig

STATE_FILENAME = "transplant_state.json"

# Minimum green coverage to consider "a plant is present"
# Empty tray / rockwool / growing medium is typically < 0.02
# A freshly transplanted seedling: 0.03 ~ 0.15
DETECTION_THRESHOLD = 0.03

# Require this many consecutive detections before confirming
REQUIRED_CONSECUTIVE = 2


@dataclass(frozen=True)
class TransplantState:
    status: str  # "waiting", "candidate", "confirmed"
    plant_id: str
    batch_id: str
    consecutive_detections: int
    first_detected_at: str | None  # ISO datetime
    confirmed_at: str | None  # ISO datetime
    planting_date: str | None  # YYYY-MM-DD (the date to use as Day 0)


def _state_path(config: RuntimeConfig) -> Path:
    return config.model_dir / STATE_FILENAME


def load_transplant_state(
    config: RuntimeConfig,
    plant_id: str,
    batch_id: str,
) -> TransplantState:
    path = _state_path(config)
    if path.exists():
        raw = json.loads(path.read_text())
        # Only return if it matches the current plant/batch
        if raw.get("plant_id") == plant_id and raw.get("batch_id") == batch_id:
            return TransplantState(
                status=raw.get("status", "waiting"),
                plant_id=raw["plant_id"],
                batch_id=raw["batch_id"],
                consecutive_detections=raw.get("consecutive_detections", 0),
                first_detected_at=raw.get("first_detected_at"),
                confirmed_at=raw.get("confirmed_at"),
                planting_date=raw.get("planting_date"),
            )

    return TransplantState(
        status="waiting",
        plant_id=plant_id,
        batch_id=batch_id,
        consecutive_detections=0,
        first_detected_at=None,
        confirmed_at=None,
        planting_date=None,
    )


def save_transplant_state(config: RuntimeConfig, state: TransplantState) -> None:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "status": state.status,
        "plant_id": state.plant_id,
        "batch_id": state.batch_id,
        "consecutive_detections": state.consecutive_detections,
        "first_detected_at": state.first_detected_at,
        "confirmed_at": state.confirmed_at,
        "planting_date": state.planting_date,
    }, indent=2, ensure_ascii=False))


def update_detection(
    config: RuntimeConfig,
    plant_id: str,
    batch_id: str,
    green_area_ratio: float,
    captured_at: datetime,
) -> TransplantState:
    """
    Update transplant detection state based on the current capture.

    Returns the updated state. If status becomes "confirmed",
    the planting_date field contains the date to use as Day 0.
    """
    state = load_transplant_state(config, plant_id, batch_id)

    if state.status == "confirmed":
        return state

    plant_detected = green_area_ratio >= DETECTION_THRESHOLD

    if plant_detected:
        new_consecutive = state.consecutive_detections + 1
        first_detected = state.first_detected_at or captured_at.isoformat()

        if new_consecutive >= REQUIRED_CONSECUTIVE:
            # Confirmed! Use the first detection date as planting date
            first_dt = datetime.fromisoformat(first_detected)
            new_state = TransplantState(
                status="confirmed",
                plant_id=plant_id,
                batch_id=batch_id,
                consecutive_detections=new_consecutive,
                first_detected_at=first_detected,
                confirmed_at=captured_at.isoformat(),
                planting_date=first_dt.strftime("%Y-%m-%d"),
            )
        else:
            new_state = TransplantState(
                status="candidate",
                plant_id=plant_id,
                batch_id=batch_id,
                consecutive_detections=new_consecutive,
                first_detected_at=first_detected,
                confirmed_at=None,
                planting_date=None,
            )
    else:
        # No green detected → reset counter
        new_state = TransplantState(
            status="waiting",
            plant_id=plant_id,
            batch_id=batch_id,
            consecutive_detections=0,
            first_detected_at=None,
            confirmed_at=None,
            planting_date=None,
        )

    save_transplant_state(config, new_state)
    return new_state


def get_effective_planting_date(
    config: RuntimeConfig,
    plant_id: str,
    batch_id: str,
    env_planting_date: str | None,
) -> str | None:
    """
    Resolve the effective planting date.

    Priority:
      1. .env BUTTERHEAD_PLANTING_DATE (if set and in the past → user override)
      2. Auto-detected planting date from transplant_state.json
      3. None (no planting date → pre-transplant mode)
    """
    # If user explicitly set a past planting date in .env, respect it
    if env_planting_date:
        try:
            env_date = date.fromisoformat(env_planting_date)
            if env_date <= date.today():
                return env_planting_date
        except ValueError:
            pass

    # Check auto-detected state
    state = load_transplant_state(config, plant_id, batch_id)
    if state.status == "confirmed" and state.planting_date:
        return state.planting_date

    return None
