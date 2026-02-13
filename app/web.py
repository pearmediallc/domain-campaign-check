from __future__ import annotations

import datetime as dt
import threading

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .checker import run_full_check
from .redtrack import RedTrackClient
from .scheduler import start_scheduler
from .storage import AppConfig, load_config, save_config
from .telegram import send_message
from .debug_routes import router as debug_router
from .results_store import load_results, append_run
from .config import MAX_TELEGRAM_MESSAGES_PER_RUN, TELEGRAM_VERBOSE

app = FastAPI(title="Domain Campaign Check")
app.include_router(debug_router)
templates = Jinja2Templates(directory="app/templates")

_sched = None
_lock = threading.Lock()
_last_run: dict[str, str] = {}
_is_running = False


@app.on_event("startup")
def _startup():
    global _sched
    _sched = start_scheduler()


def _run_once(cfg: AppConfig):
    global _last_run, _is_running
    try:
        from .log import log

        _is_running = True
        log("manual.start", date_from=cfg.date_from, date_to=cfg.date_to, days_lookback=cfg.days_lookback)
        redtrack = RedTrackClient()
        results = run_full_check(
            redtrack,
            date_from=cfg.date_from,
            date_to=cfg.date_to,
            days_lookback=cfg.days_lookback,
        )
        total = len(results)
        failing = sum(1 for r in results if any(not ch.get("ok") for ch in r.get("checks", [])))
        _last_run = {
            "time": dt.datetime.now(dt.timezone.utc).isoformat(),
            "summary": f"Checked {total} campaigns. Failing: {failing}.",
        }
        log("manual.results", total=total, failing=failing)

        append_run(
            {
                "kind": "manual",
                "ts": int(dt.datetime.now(dt.timezone.utc).timestamp()),
                "date_from": cfg.date_from,
                "date_to": cfg.date_to,
                "days_lookback": cfg.days_lookback,
                "total_checked": total,
                "failing": failing,
                "results": results,
            }
        )

        # Telegram: ONLY send failing campaigns. If no failures, send nothing.
        try:
            if failing:
                from .telegram import send_many

                lines: list[str] = [f"🚨 Manual run: {failing} failing campaign(s) (checked {total})"]
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
    except Exception as e:
        from .log import log

        log("manual.error", error=str(e), error_type=type(e).__name__)
        _last_run = {
            "time": dt.datetime.now(dt.timezone.utc).isoformat(),
            "summary": f"Run failed: {e}",
        }
    finally:
        _is_running = False


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()
    cached = load_results()
    runs = cached.get("runs") if isinstance(cached, dict) else []
    latest = runs[0] if isinstance(runs, list) and runs else None

    failing_campaigns = []
    if isinstance(latest, dict):
        for r in latest.get("results") or []:
            if not isinstance(r, dict):
                continue
            checks = r.get("checks") or []
            failed = [ch for ch in checks if isinstance(ch, dict) and not ch.get("ok", True)]
            if failed:
                failing_campaigns.append({"campaign": r.get("campaign") or {}, "failed": failed})

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "cfg": cfg,
            "now": dt.datetime.now(dt.timezone.utc),
            "last_run": _last_run or None,
            "latest": latest,
            "failing_campaigns": failing_campaigns,
        },
    )


@app.post("/config")
def update_config(
    schedule_mode: str = Form("daily_at"),
    run_at_hhmm: str = Form("17:00"),
    interval_minutes: int = Form(1440),
    days_lookback: int = Form(...),
    date_from: str = Form(""),
    date_to: str = Form(""),
    alert_on_first_failure: str = Form("false"),
):
    cfg = load_config()
    cfg.schedule_mode = (schedule_mode or "interval").strip()
    cfg.run_at_hhmm = (run_at_hhmm or "17:00").strip()
    cfg.interval_minutes = max(1, int(interval_minutes))
    cfg.days_lookback = max(1, int(days_lookback))
    cfg.date_from = date_from.strip() or None
    cfg.date_to = date_to.strip() or None
    cfg.alert_on_first_failure = (alert_on_first_failure or "false").lower() in ("1", "true", "yes", "on")
    save_config(cfg)
    return RedirectResponse(url="/", status_code=303)


@app.post("/run")
def run_now():
    # Trigger a manual run in a background thread so the request returns quickly.
    global _is_running
    with _lock:
        if _is_running:
            # already running
            return RedirectResponse(url="/?running=1", status_code=303)
        cfg = load_config()
        t = threading.Thread(target=_run_once, args=(cfg,), daemon=True)
        t.start()
    return RedirectResponse(url="/", status_code=303)
