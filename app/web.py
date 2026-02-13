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

app = FastAPI(title="Domain Campaign Check")
app.include_router(debug_router)
templates = Jinja2Templates(directory="app/templates")

_sched = None
_lock = threading.Lock()
_last_run: dict[str, str] = {}


@app.on_event("startup")
def _startup():
    global _sched
    _sched = start_scheduler()


def _run_once(cfg: AppConfig):
    global _last_run
    try:
        from .log import log

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
        # Optional: send a summary when manually run
        try:
            send_message(f"Manual run finished. {_last_run['summary']}")
        except Exception:
            pass
    except Exception as e:
        from .log import log

        log("manual.error", error=str(e), error_type=type(e).__name__)
        _last_run = {
            "time": dt.datetime.now(dt.timezone.utc).isoformat(),
            "summary": f"Run failed: {e}",
        }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "cfg": cfg,
            "now": dt.datetime.now(dt.timezone.utc),
            "last_run": _last_run or None,
        },
    )


@app.post("/config")
def update_config(
    interval_minutes: int = Form(...),
    days_lookback: int = Form(...),
    date_from: str = Form(""),
    date_to: str = Form(""),
    alert_on_first_failure: str = Form("false"),
):
    cfg = load_config()
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
    with _lock:
        cfg = load_config()
        t = threading.Thread(target=_run_once, args=(cfg,), daemon=True)
        t.start()
    return RedirectResponse(url="/", status_code=303)
