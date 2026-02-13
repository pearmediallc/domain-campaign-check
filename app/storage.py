from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_PATH = os.getenv("CONFIG_PATH", "./data/config.json")


@dataclass
class AppConfig:
    # How often to run the automatic check
    interval_minutes: int = 24 * 60

    # Default lookback window if user doesn't specify exact dates
    days_lookback: int = 30

    # Optional fixed dates (YYYY-MM-DD). If set, checker uses these.
    date_from: str | None = None
    date_to: str | None = None

    # Alerting
    alert_on_first_failure: bool = False

    # Internal bookkeeping
    last_run_epoch: int | None = None


def load_config(path: str = DEFAULT_PATH) -> AppConfig:
    if not os.path.exists(path):
        return AppConfig()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return AppConfig(**data)


def save_config(cfg: AppConfig, path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def should_run_now(cfg: AppConfig) -> bool:
    if cfg.last_run_epoch is None:
        return True
    return (int(time.time()) - int(cfg.last_run_epoch)) >= int(cfg.interval_minutes) * 60
