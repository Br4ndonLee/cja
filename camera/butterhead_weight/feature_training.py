from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .auto_train import maybe_auto_train_feature_model
from .config import load_runtime_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the butterhead feature regressor from labeled weights CSV.")
    parser.add_argument("--planting-date", default=None, help="Fallback planting date in YYYY-MM-DD.")
    parser.add_argument("--force", action="store_true", help="Ignore auto-train thresholds and retrain now.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config()
    result = maybe_auto_train_feature_model(
        config=config,
        default_planting_date=args.planting_date,
        force=args.force,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True, ensure_ascii=False))
    return 0
