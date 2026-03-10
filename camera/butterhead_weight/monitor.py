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
    parser.add_argument("--hour", type=int, default=config.monitor_hour, help="Daily capture hour in 24h format.")
    parser.add_argument("--minute", type=int, default=config.monitor_minute, help="Daily capture minute.")
    parser.add_argument("--poll-seconds", type=float, default=20.0, help="Sleep interval while waiting for next run.")
    parser.add_argument("--skip-initial-run", action="store_true", help="Wait until the first scheduled time.")
    parser.add_argument("--max-runs", type=int, default=0, help="Optional run limit for testing.")
    return parser.parse_args()


def compute_next_run(now: datetime, hour: int, minute: int, last_run_date: str | None) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    if last_run_date == candidate.date().isoformat():
        candidate += timedelta(days=1)
    return candidate


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

    completed_runs = 0
    last_run_date: str | None = None

    if not args.skip_initial_run:
        payload = run_once(args)
        completed_runs += 1
        last_run_date = str(payload["captured_at_iso"])[:10]
        if args.max_runs and completed_runs >= args.max_runs:
            return 0

    while True:
        now = datetime.now().astimezone()
        next_run = compute_next_run(now, args.hour, args.minute, last_run_date)
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
            last_run_date = str(payload["captured_at_iso"])[:10]
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
