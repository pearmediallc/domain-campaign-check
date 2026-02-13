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

    def _get(self, path: str, params: dict[str, Any] | None = None, *, retries: int = 3) -> Any:
        if not self.api_key:
            raise RedTrackError("Missing api key")
        p = {"api_key": self.api_key}
        if params:
            p.update({k: v for k, v in params.items() if v is not None})

        last_err: str | None = None
        for attempt in range(retries + 1):
            r = self.client.get(path, params=p)
            if r.status_code < 400:
                return r.json()

            # retry only on 5xx
            last_err = f"{r.status_code} {r.text[:500]}"
            if 500 <= r.status_code < 600 and attempt < retries:
                import time

                time.sleep(1.5 * (attempt + 1))
                continue
            break

        raise RedTrackError(f"RedTrack GET {path} failed: {last_err}")

    def list_active_campaigns(self, per: int = 200) -> list[dict[str, Any]]:
        """Return active campaigns.

        Some RedTrack accounts intermittently return 500 on /campaigns/v2.
        We fall back to /campaigns in that case.
        """

        def _list(path: str) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            page = 1
            while True:
                data = self._get(
                    path,
                    params={
                        "status": "active",
                        "page": page,
                        "per": per,
                        "timezone": TIMEZONE,
                    },
                )
                if not isinstance(data, list):
                    raise RedTrackError(f"Unexpected campaigns response from {path}: {type(data)}")
                out.extend(data)
                if len(data) < per:
                    break
                page += 1
            return out

        try:
            return _list("/campaigns/v2")
        except RedTrackError as e:
            # only fallback on server errors
            if "500" in str(e) or "502" in str(e) or "503" in str(e):
                return _list("/campaigns")
            raise

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
