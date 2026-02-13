from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from .config import REDTRACK_API_BASE, REDTRACK_API_KEY, TIMEZONE
from .log import debug


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

    @staticmethod
    def _normalize_list_payload(data: Any, *, label: str) -> list[dict[str, Any]]:
        """Normalize list responses.

        RedTrack sometimes returns:
        - a raw list: [ ... ]
        - an envelope: {items:[...], total:{...}}
        - an envelope: {data:[...]}
        """
        if isinstance(data, list):
            # Filter to dict elements only (defensive)
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            if data.get("error"):
                raise RedTrackError(f"RedTrack error in {label}: {data.get('error')}")
            for k in ("items", "data", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
        raise RedTrackError(f"Unexpected {label} response shape: {type(data)}")

    def _get(self, path: str, params: dict[str, Any] | None = None, *, retries: int = 3) -> Any:
        if not self.api_key:
            raise RedTrackError("Missing api key (REDTRACK_API_KEY)")
        # Many RedTrack endpoints accept/require format=json
        p = {"api_key": self.api_key, "format": "json"}
        if params:
            p.update({k: v for k, v in params.items() if v is not None})

        last_err: str | None = None
        for attempt in range(retries + 1):
            debug("redtrack.request", path=path, attempt=attempt, params=p)
            r = self.client.get(path, params=p, headers={"Accept": "application/json"})
            debug("redtrack.response", path=path, status=r.status_code, text_snippet=r.text[:200])

            # Try to parse JSON for nicer errors
            data = None
            try:
                data = r.json()
            except Exception:
                data = None

            # If response isn't JSON at all, treat as error (we rely on JSON shapes downstream)
            if data is None:
                last_err = f"{r.status_code} non-json response: {r.text[:200]}"
                break

            # Some RedTrack errors come back as JSON with 200 or 4xx
            if isinstance(data, dict) and data.get("error"):
                last_err = f"{r.status_code} {data.get('error')}"
                # don't retry auth/validation errors
                if r.status_code < 500:
                    break

            if r.status_code < 400 and not (isinstance(data, dict) and data.get("error")):
                return data

            # retry only on 5xx
            last_err = last_err or f"{r.status_code} {r.text[:500]}"
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
                # NOTE: Some RedTrack setups return 500 when using status filter.
                # So we fetch without status and filter locally.
                raw = self._get(
                    path,
                    params={
                        "page": page,
                        "per": per,
                        "timezone": TIMEZONE,
                    },
                )
                data = self._normalize_list_payload(raw, label=f"campaigns list {path}")
                out.extend(data)
                if len(data) < per:
                    break
                page += 1
            return out

        def _is_active(c: dict[str, Any]) -> bool:
            v = c.get("status")
            if v is None:
                return False
            s = str(v).lower()
            return s in ("active", "enabled", "1", "true")

        try:
            all_ = _list("/campaigns/v2")
        except RedTrackError as e:
            if any(code in str(e) for code in ("500", "502", "503")):
                all_ = _list("/campaigns")
            else:
                raise

        return [c for c in all_ if _is_active(c)]

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self._get(f"/campaigns/{campaign_id}")

    def get_domain(self, domain_id: str) -> dict[str, Any]:
        return self._get(f"/domains/{domain_id}")

    def get_landing(self, landing_id: str) -> dict[str, Any]:
        return self._get(f"/landings/{landing_id}")

    def report_by_campaign(self, date_from: dt.date, date_to: dt.date) -> list[dict[str, Any]]:
        # group=campaign is the common grouping in RedTrack.
        raw = self._get(
            "/report",
            params={
                "group": "campaign",
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "timezone": TIMEZONE,
                "per": 5000,
                "page": 1,
                "total": "1",
                # some deployments support this; harmless otherwise
                "include_zero_rows": 0,
            },
        )
        return self._normalize_list_payload(raw, label="report")
