from __future__ import annotations

import time

from apscheduler.schedulers.background import BackgroundScheduler

from .checker import run_full_check
from .redtrack import RedTrackClient
from .storage import load_config, save_config, should_run_now
from .telegram import send_message


def _job():
    cfg = load_config()
    if not should_run_now(cfg):
        return

    redtrack = RedTrackClient()
    results = run_full_check(redtrack, date_from=cfg.date_from, date_to=cfg.date_to, days_lookback=cfg.days_lookback)

    total = len(results)
    failing = sum(1 for r in results if any(not ch.get("ok") for ch in r.get("checks", [])))

    cfg.last_run_epoch = int(time.time())
    save_config(cfg)

    # Telegram notifications
    try:
        send_message(
            f"RedTrack domain check finished. Checked {total} active campaigns with spend/rev in window. Failing: {failing}."
        )
    except Exception as e:
        print(f"[scheduler] telegram failed: {e}")

    if failing:
        # batch details (reuse minimal formatting)
        lines = ["🚨 Failing campaigns:"]
        for r in results:
            failed = [ch for ch in r.get("checks", []) if not ch.get("ok")]
            if not failed:
                continue
            c = r.get("campaign", {})
            lines.append(f"• {c.get('title') or 'Campaign'} (id {c.get('id')})")
            if c.get("domain_name"):
                lines.append(f"  domain: {c['domain_name']}")
            if c.get("trackback_url"):
                lines.append(f"  url: {c['trackback_url']}")
            for ch in failed[:3]:
                lines.append(f"  - {ch.get('kind')}: {ch.get('failure_type')} {ch.get('message')} {ch.get('tested_url')}")
            lines.append("")
        msg = "\n".join(lines)[:3800]
        try:
            send_message(msg)
        except Exception as e:
            print(f"[scheduler] telegram details failed: {e}")


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    # run every minute; internal guard uses interval_minutes
    sched.add_job(_job, "interval", minutes=1, id="domain_campaign_check")
    sched.start()
    return sched
