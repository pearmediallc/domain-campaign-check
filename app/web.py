from __future__ import annotations

import datetime as dt

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from .db import get_session
from .migrate import migrate
from .models import Campaign, CheckResult

app = FastAPI(title="Domain Campaign Check")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def _startup():
    migrate()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, only_failing: bool = False, q: str | None = None):
    with get_session() as s:
        # subquery for latest check per campaign
        sub = (
            select(CheckResult.campaign_id, func.max(CheckResult.created_at).label("max_created"))
            .group_by(CheckResult.campaign_id)
            .subquery()
        )

        stmt = (
            select(Campaign, CheckResult)
            .join(sub, sub.c.campaign_id == Campaign.id, isouter=True)
            .join(
                CheckResult,
                (CheckResult.campaign_id == sub.c.campaign_id) & (CheckResult.created_at == sub.c.max_created),
                isouter=True,
            )
            .order_by(Campaign.title.asc().nulls_last())
        )

        if q:
            like = f"%{q}%"
            stmt = stmt.where(Campaign.title.ilike(like))

        rows = s.execute(stmt).all()

    items = []
    for camp, chk in rows:
        if only_failing and (chk is None or chk.ok):
            continue
        items.append({"campaign": camp, "check": chk})

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "items": items,
            "only_failing": only_failing,
            "q": q or "",
            "now": dt.datetime.now(dt.timezone.utc),
        },
    )


@app.get("/campaign/{campaign_id}", response_class=HTMLResponse)
def campaign_detail(request: Request, campaign_id: str):
    with get_session() as s:
        camp = s.get(Campaign, campaign_id)
        checks = (
            s.query(CheckResult)
            .filter(CheckResult.campaign_id == campaign_id)
            .order_by(CheckResult.created_at.desc())
            .limit(50)
            .all()
        )

    return templates.TemplateResponse(
        "campaign.html",
        {"request": request, "campaign": camp, "checks": checks},
    )
