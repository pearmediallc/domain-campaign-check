from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_PATH = os.getenv("CONFIG_PATH", "./data/config.json")

# EDT operating window: only run scheduled checks between these hours (EDT)
EDT_RUN_WINDOW_START = (7, 30)   # 7:30 AM EDT
EDT_RUN_WINDOW_END = (12, 0)     # 12:00 PM EDT


@dataclass
class AppConfig:
    # Scheduling
    # - "interval": run every interval_minutes
    # - "daily_at": run once per day at run_at_hhmm (TIMEZONE)
    schedule_mode: str = "interval"
    interval_minutes: int = 60
    run_at_hhmm: str = "17:00"

    # Default lookback window if user doesn't specify exact dates
    days_lookback: int = 7

    # Optional fixed dates (YYYY-MM-DD). If set, checker uses these.
    date_from: str | None = None
    date_to: str | None = None

    # Alerting
    alert_on_first_failure: bool = False

    # Internal bookkeeping
    last_run_epoch: int | None = None
    last_run_local_date: str | None = None  # YYYY-MM-DD (TIMEZONE)


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


def _in_edt_window() -> bool:
    """Return True if current time in America/New_York is within the operating window."""
    import datetime as dt

    try:
        from zoneinfo import ZoneInfo
        edt = ZoneInfo("America/New_York")
    except Exception:
        # Fallback: UTC-4 as fixed offset for EDT
        edt = dt.timezone(dt.timedelta(hours=-4))

    now = dt.datetime.now(tz=edt)
    start = now.replace(hour=EDT_RUN_WINDOW_START[0], minute=EDT_RUN_WINDOW_START[1], second=0, microsecond=0)
    end = now.replace(hour=EDT_RUN_WINDOW_END[0], minute=EDT_RUN_WINDOW_END[1], second=0, microsecond=0)
    return start <= now <= end


def should_run_now(cfg: AppConfig, *, tz_name: str) -> bool:
    """Return True if a scheduled run should trigger now.

    We keep an always-on scheduler tick (every minute) and decide here whether to actually run.
    Scheduled runs only execute within the EDT operating window (7:30 AM - 12:00 PM EDT).
    """

    # Gate: scheduled runs only within EDT operating window
    if not _in_edt_window():
        return False

    mode = (cfg.schedule_mode or "interval").lower()
    now_epoch = int(time.time())

    if mode == "interval":
        if cfg.last_run_epoch is None:
            return True
        return (now_epoch - int(cfg.last_run_epoch)) >= int(cfg.interval_minutes) * 60

    # daily_at
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = None

    import datetime as dt

    now = dt.datetime.now(tz=tz) if tz else dt.datetime.now()
    today = now.date().isoformat()

    # already ran today?
    if cfg.last_run_local_date == today:
        return False

    # parse HH:MM
    hhmm = (cfg.run_at_hhmm or "17:00").strip()
    try:
        hh, mm = [int(x) for x in hhmm.split(":", 1)]
    except Exception:
        hh, mm = 17, 0

    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now >= target
