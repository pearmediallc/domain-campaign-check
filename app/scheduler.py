from __future__ import annotations

import time

from apscheduler.schedulers.background import BackgroundScheduler

from .checker import run_full_check
from .redtrack import RedTrackClient
from .storage import load_config, save_config, should_run_now
from .config import TIMEZONE
from .telegram import send_message, send_many
from .log import log
from .config import MAX_TELEGRAM_MESSAGES_PER_RUN, TELEGRAM_VERBOSE
from .results_store import append_run


def _job():
    cfg = load_config()
    if not should_run_now(cfg, tz_name=TIMEZONE):
        log(
            "job.skip",
            reason="not_due",
            schedule_mode=cfg.schedule_mode,
            last_run_epoch=cfg.last_run_epoch,
            last_run_local_date=cfg.last_run_local_date,
            interval_minutes=cfg.interval_minutes,
            run_at_hhmm=cfg.run_at_hhmm,
        )
        return

    # Always update last_run_epoch even on failure, otherwise it will retry every minute forever.
    import datetime as dt

    now_epoch = int(time.time())
    cfg.last_run_epoch = now_epoch
    # record local date for daily schedule guard
    try:
        from zoneinfo import ZoneInfo

        today_local = dt.datetime.now(tz=ZoneInfo(TIMEZONE)).date().isoformat()
    except Exception:
        today_local = dt.datetime.now().date().isoformat()
    cfg.last_run_local_date = today_local
    save_config(cfg)

    try:
        log("job.start", date_from=cfg.date_from, date_to=cfg.date_to, days_lookback=cfg.days_lookback)
        redtrack = RedTrackClient()
        results = run_full_check(
            redtrack,
            date_from=cfg.date_from,
            date_to=cfg.date_to,
            days_lookback=cfg.days_lookback,
        )

        total = len(results)
        failing = sum(1 for r in results if any(not ch.get("ok") for ch in r.get("checks", [])))
        log("job.results", total=total, failing=failing)

        run_record = {
            "kind": "scheduled",
            "ts": int(time.time()),
            "date_from": cfg.date_from,
            "date_to": cfg.date_to,
            "days_lookback": cfg.days_lookback,
            "total_checked": total,
            "failing": failing,
            "results": results,
        }
        log("cache.write", path="results.json", runs_cached="append")
        append_run(run_record)

        # Telegram notifications: ONLY send failing campaigns. If no failures, send nothing.
        if failing:
            try:
                lines: list[str] = [f"🚨 {failing} failing campaign(s) (checked {total} campaigns with activity)"]
                for r in results:
                    c = r.get("campaign", {})
                    failed = [ch for ch in r.get("checks", []) if not ch.get("ok")]
                    if not failed:
                        continue
                    lines.append(f"FAIL | {c.get('title') or 'Campaign'} | {c.get('id')} | {c.get('domain_name') or ''}")
                    if c.get("trackback_url"):
                        lines.append(f"  url: {c.get('trackback_url')}")
                    for ch in failed[:8]:
                        lines.append(f"  - {ch.get('kind')}: {ch.get('failure_type')} {ch.get('message')} {ch.get('tested_url')}")
                    lines.append("")

                send_many(lines, max_messages=MAX_TELEGRAM_MESSAGES_PER_RUN)
            except Exception as e:
                log("telegram.error", error=str(e))
                print(f"[scheduler] telegram failed: {e}")

    except Exception as e:
        # Single failure message (at most once per interval due to last_run_epoch)
        log("job.error", error=str(e), error_type=type(e).__name__)
        print(f"[scheduler] job failed: {e}")
        try:
            send_message(f"⚠️ Domain check job failed: {e}")
        except Exception:
            pass


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    # run every minute; internal guard uses interval_minutes
    sched.add_job(_job, "interval", minutes=1, id="domain_campaign_check")
    sched.start()
    return sched
