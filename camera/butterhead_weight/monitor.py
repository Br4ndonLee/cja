from __future__ import annotations

import argparse
import json
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .config import load_runtime_config
from .pipeline import run_capture_pipeline


def parse_args() -> argparse.Namespace:
    config = load_runtime_config()
    parser = argparse.ArgumentParser(description="Run the butterhead camera monitor continuously.")
    parser.add_argument("--plant-id", default="butterhead-01", help="Logical plant identifier.")
    parser.add_argument("--batch-id", default="default-batch", help="Logical batch or tray identifier.")
    parser.add_argument("--planting-date", default=None, help="Planting date in YYYY-MM-DD.")
    parser.add_argument("--model", type=Path, default=None, help="ONNX model path for prediction.")
    parser.add_argument("--device", default=None, help="Camera device path.")
    parser.add_argument("--width", type=int, default=None, help="Capture width.")
    parser.add_argument("--height", type=int, default=None, help="Capture height.")
    parser.add_argument(
        "--times",
        default=",".join(config.monitor_times),
        help="Comma-separated capture times in HH:MM 24h format, for example 06:00,18:00.",
    )
    parser.add_argument("--hour", type=int, default=config.monitor_hour, help="Daily capture hour in 24h format.")
    parser.add_argument("--minute", type=int, default=config.monitor_minute, help="Daily capture minute.")
    parser.add_argument("--poll-seconds", type=float, default=20.0, help="Sleep interval while waiting for next run.")
    parser.add_argument("--skip-initial-run", action="store_true", help="Wait until the first scheduled time.")
    parser.add_argument("--max-runs", type=int, default=0, help="Optional run limit for testing.")
    return parser.parse_args()


def parse_schedule_times(raw_times: str | None, fallback_hour: int, fallback_minute: int) -> tuple[tuple[int, int], ...]:
    if raw_times is None or not raw_times.strip():
        return ((fallback_hour, fallback_minute),)

    parsed: list[tuple[int, int]] = []
    for raw_token in raw_times.split(","):
        token = raw_token.strip()
        if not token:
            continue
        parts = token.split(":")
        if len(parts) != 2:
            raise SystemExit(f"Invalid --times value '{token}'. Use HH:MM,HH:MM.")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise SystemExit(f"Invalid --times value '{token}'. Use HH:MM,HH:MM.") from exc
        if not (0 <= hour <= 23):
            raise SystemExit(f"Invalid hour '{hour}' in --times.")
        if not (0 <= minute <= 59):
            raise SystemExit(f"Invalid minute '{minute}' in --times.")
        parsed.append((hour, minute))

    if not parsed:
        return ((fallback_hour, fallback_minute),)

    return tuple(sorted(set(parsed)))


def compute_next_run(now: datetime, schedule_times: tuple[tuple[int, int], ...]) -> datetime:
    candidates: list[datetime] = []
    for day_offset in (0, 1):
        candidate_day = now + timedelta(days=day_offset)
        for hour, minute in schedule_times:
            candidate = candidate_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                candidates.append(candidate)

    if not candidates:
        raise RuntimeError("No valid next capture time could be computed.")

    return min(candidates)


def run_once(args: argparse.Namespace) -> dict[str, object]:
    result = run_capture_pipeline(
        plant_id=args.plant_id,
        batch_id=args.batch_id,
        planting_date=args.planting_date,
        model_path=args.model,
        device=args.device,
        width=args.width,
        height=args.height,
    )
    payload = asdict(result)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return payload


def main() -> int:
    args = parse_args()
    if not (0 <= args.hour <= 23):
        raise SystemExit("--hour must be between 0 and 23.")
    if not (0 <= args.minute <= 59):
        raise SystemExit("--minute must be between 0 and 59.")
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be > 0.")

    schedule_times = parse_schedule_times(
        raw_times=args.times,
        fallback_hour=args.hour,
        fallback_minute=args.minute,
    )
    completed_runs = 0

    if not args.skip_initial_run:
        payload = run_once(args)
        completed_runs += 1
        if args.max_runs and completed_runs >= args.max_runs:
            return 0

    while True:
        now = datetime.now().astimezone()
        next_run = compute_next_run(now, schedule_times)
        print(json.dumps({"event": "waiting", "next_run_iso": next_run.isoformat()}, ensure_ascii=False, sort_keys=True))

        while True:
            now = datetime.now().astimezone()
            remaining = (next_run - now).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(args.poll_seconds, remaining))

        try:
            payload = run_once(args)
            completed_runs += 1
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "run_failed",
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

        if args.max_runs and completed_runs >= args.max_runs:
            return 0
