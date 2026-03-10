#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


CRON_TAG = "skyfarms-butterhead-daily-capture"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install or update the daily butterhead capture cron job.")
    parser.add_argument("--hour", type=int, default=9, help="Cron hour in 24h format.")
    parser.add_argument("--minute", type=int, default=0, help="Cron minute.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not (0 <= args.hour <= 23):
        raise SystemExit("--hour must be between 0 and 23.")
    if not (0 <= args.minute <= 59):
        raise SystemExit("--minute must be between 0 and 59.")

    script_dir = Path(__file__).resolve().parent
    job_script = script_dir / "run_daily_butterhead_job.sh"
    cron_line = f"{args.minute} {args.hour} * * * {job_script} # {CRON_TAG}"

    current = subprocess.run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
        check=False,
    )
    existing_lines = []
    if current.returncode == 0:
        existing_lines = [line for line in current.stdout.splitlines() if CRON_TAG not in line]

    existing_lines.append(cron_line)
    payload = "\n".join(existing_lines).strip() + "\n"

    subprocess.run(
        ["crontab", "-"],
        input=payload,
        text=True,
        check=True,
    )

    print(f"Installed cron job: {cron_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
