from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from .config import REDTRACK_API_BASE, REDTRACK_API_KEY, TIMEZONE


class RedTrackError(RuntimeError):
    pass


def _require_key():
    if not REDTRACK_API_KEY:
        raise RedTrackError("REDTRACK_API_KEY is not set")


class RedTrackClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout_s: int = 30):
        self.base_url = (base_url or REDTRACK_API_BASE).rstrip("/")
        self.api_key = api_key or REDTRACK_API_KEY
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout_s)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise RedTrackError("Missing api key")
        p = {"api_key": self.api_key}
        if params:
            p.update({k: v for k, v in params.items() if v is not None})
        r = self.client.get(path, params=p)
        if r.status_code >= 400:
            raise RedTrackError(f"RedTrack GET {path} failed: {r.status_code} {r.text[:500]}")
        return r.json()

    def list_active_campaigns(self, per: int = 200) -> list[dict[str, Any]]:
        # /campaigns/v2 supports status filter
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._get(
                "/campaigns/v2",
                params={
                    "status": "active",
                    "page": page,
                    "per": per,
                },
            )
            if not isinstance(data, list):
                raise RedTrackError("Unexpected campaigns response")
            out.extend(data)
            if len(data) < per:
                break
            page += 1
        return out

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self._get(f"/campaigns/{campaign_id}")

    def get_domain(self, domain_id: str) -> dict[str, Any]:
        return self._get(f"/domains/{domain_id}")

    def get_landing(self, landing_id: str) -> dict[str, Any]:
        return self._get(f"/landings/{landing_id}")

    def report_by_campaign(self, date_from: dt.date, date_to: dt.date) -> list[dict[str, Any]]:
        # group=campaign is the common grouping in RedTrack.
        # Response is an array of free-form objects.
        return self._get(
            "/report",
            params={
                "group": "campaign",
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "timezone": TIMEZONE,
                "per": 5000,
                "page": 1,
                "total": "1",
            },
        )
