from __future__ import annotations

import datetime as dt
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import CHECK_RETRIES, CHECK_TIMEOUT_SECONDS, TIMEZONE
from .redtrack import RedTrackClient
from .log import log, debug
from .url_utils import add_sub5_test


@dataclass
class UrlCheck:
    ok: bool
    failure_type: str | None = None
    message: str | None = None
    tested_url: str | None = None
    final_url: str | None = None
    http_status: int | None = None
    elapsed_ms: int | None = None


def _pick_number(d: dict[str, Any], keys: list[str]) -> float | None:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def _pick_str(d: dict[str, Any], keys: list[str]) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def dns_check(hostname: str) -> tuple[bool, str | None]:
    try:
        socket.getaddrinfo(hostname, 80)
        return True, None
    except socket.gaierror as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def http_check(url: str, timeout_s: int = CHECK_TIMEOUT_SECONDS) -> UrlCheck:
    # Add sub5=test to bypass cloaking, use mobile UA to simulate real user
    check_url = add_sub5_test(url) or url
    tested = url
    start = time.time()
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout_s, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 16; SM-A156U Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/145.0.7632.104 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/549.0.0.61.62;IABMV/1;]"}) as client:
            r = client.get(check_url)
        elapsed_ms = int((time.time() - start) * 1000)
        ok = 200 <= r.status_code < 400

        # basic "loaded" heuristic: HTML should have some body.
        content_ok = True
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" in ctype:
            txt = r.text or ""
            if len(txt.strip()) < 200:
                content_ok = False

        if ok and content_ok:
            return UrlCheck(ok=True, tested_url=tested, final_url=str(r.url), http_status=r.status_code, elapsed_ms=elapsed_ms)

        msg = f"HTTP {r.status_code}" + ("; content too small" if ok and not content_ok else "")
        return UrlCheck(ok=False, failure_type="http", message=msg, tested_url=tested, final_url=str(r.url), http_status=r.status_code, elapsed_ms=elapsed_ms)

    except httpx.TimeoutException:
        elapsed_ms = int((time.time() - start) * 1000)
        return UrlCheck(ok=False, failure_type="timeout", message="timeout", tested_url=tested, elapsed_ms=elapsed_ms)
    except httpx.RequestError as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return UrlCheck(ok=False, failure_type="http", message=str(e), tested_url=tested, elapsed_ms=elapsed_ms)
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return UrlCheck(ok=False, failure_type="other", message=str(e), tested_url=tested, elapsed_ms=elapsed_ms)


def extract_urls_from_campaign(c: dict[str, Any]) -> dict[str, Any]:
    """Best-effort URL extraction.

    RedTrack campaign schema varies by configuration; we use the most common fields.
    """
    tracking_url = _pick_str(c, ["trackback_url", "impression_url", "campaign_url", "url", "tracking_url"])
    domain_id = _pick_str(c, ["domain_id"])

    landing_ids: set[str] = set()
    for cs in (c.get("streams") or []):
        stream = (cs or {}).get("stream") or {}
        for l in (stream.get("landings") or []):
            lid = (l or {}).get("id")
            if lid:
                landing_ids.add(str(lid))
        for l in (stream.get("prelandings") or []):
            lid = (l or {}).get("id")
            if lid:
                landing_ids.add(str(lid))

    return {
        "tracking_url": tracking_url,
        "domain_id": domain_id,
        "landing_ids": sorted(landing_ids),
    }


def compute_lookback_window(days_lookback: int) -> tuple[dt.date, dt.date]:
    # Use UTC dates; RedTrack also accepts timezone param.
    # We keep logic simple: last N calendar days.
    today = dt.datetime.now(dt.timezone.utc).date()
    date_from = today - dt.timedelta(days=days_lookback)
    date_to = today
    return date_from, date_to


def filter_campaigns_with_activity(campaigns: list[dict[str, Any]], report_rows: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    """Return map campaign_id -> {cost_7d, revenue_7d} for campaigns with cost>0 or revenue>0."""

    # Build id set for robustness.
    ids = {str(c.get("id")) for c in campaigns if c.get("id") is not None}

    out: dict[str, dict[str, float | None]] = {}
    for row in report_rows or []:
        # campaign id can appear under different keys depending on grouping
        cid = None
        for k in ["campaign_id", "id", "campaign", "campaignId"]:
            if row.get(k) is not None:
                cid = str(row.get(k))
                break
        if not cid or cid not in ids:
            continue

        cost = _pick_number(row, ["cost", "spend", "total_cost", "totalCost"]) or 0.0
        rev = _pick_number(row, ["revenue", "rev", "total_revenue", "totalRevenue"]) or 0.0
        if cost > 0 or rev > 0:
            out[cid] = {"cost_7d": float(cost), "revenue_7d": float(rev)}

    return out


def _is_after_9am_edt() -> bool:
    """Return True if current time is after 9:00 AM EDT."""
    try:
        from zoneinfo import ZoneInfo
        edt = ZoneInfo("America/New_York")
    except Exception:
        edt = dt.timezone(dt.timedelta(hours=-4))

    now = dt.datetime.now(tz=edt)
    return now.hour >= 9


def _get_campaigns_with_today_clicks(
    redtrack: RedTrackClient,
    campaign_ids: set[str],
) -> set[str]:
    """Fetch today's report and return campaign IDs that have clicks > 0 today."""
    try:
        from zoneinfo import ZoneInfo
        edt = ZoneInfo("America/New_York")
    except Exception:
        edt = dt.timezone(dt.timedelta(hours=-4))

    today = dt.datetime.now(tz=edt).date()

    log("checker.today_clicks.fetch", date=today.isoformat())
    today_rows = redtrack.report_by_campaign(today, today)
    log("checker.today_clicks.fetched", rows=len(today_rows))

    clicked: set[str] = set()
    for row in today_rows or []:
        cid = None
        for k in ["campaign_id", "id", "campaign", "campaignId"]:
            if row.get(k) is not None:
                cid = str(row.get(k))
                break
        if not cid or cid not in campaign_ids:
            continue

        clicks = _pick_number(row, [
            "clicks", "total_clicks", "totalClicks",
            "lp_clicks", "lpClicks", "lp_views", "lpViews",
            "ts_clicks", "click",
        ]) or 0.0

        if clicks > 0:
            clicked.add(cid)

    return clicked


def run_full_check(
    redtrack: RedTrackClient,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    days_lookback: int = 7,
    stop_flag: Any = None,
) -> list[dict[str, Any]]:
    """Runs the check.

    Returns a list of result dicts:
    {campaign, stats, domain, urls, checks:[UrlCheck...]}
    """
    if date_from and date_to:
        df = dt.date.fromisoformat(date_from)
        dt_ = dt.date.fromisoformat(date_to)
    else:
        df, dt_ = compute_lookback_window(days_lookback)


    log("checker.window", date_from=str(df), date_to=str(dt_), timezone=TIMEZONE)

    campaigns = redtrack.list_active_campaigns()
    log("checker.campaigns.fetched", count=len(campaigns))

    report_rows = redtrack.report_by_campaign(df, dt_)
    log("checker.report.fetched", rows=len(report_rows))

    active_map = filter_campaigns_with_activity(campaigns, report_rows)
    log("checker.active_with_activity", count=len(active_map))

    # After 9 AM EDT: narrow down to campaigns that received clicks TODAY
    after_9am = _is_after_9am_edt()
    if after_9am:
        today_clicked = _get_campaigns_with_today_clicks(redtrack, set(active_map.keys()))
        log("checker.today_clicks.filter", after_9am=True, total_active=len(active_map), with_clicks_today=len(today_clicked))
        # Only keep campaigns that have clicks today
        active_map = {cid: stats for cid, stats in active_map.items() if cid in today_clicked}
        log("checker.after_filter", remaining=len(active_map))
    else:
        log("checker.today_clicks.filter", after_9am=False, note="before 9 AM EDT, checking all active campaigns")

    results: list[dict[str, Any]] = []
    domain_cache: dict[str, dict[str, Any]] = {}
    landing_cache: dict[str, dict[str, Any]] = {}

    processed = 0
    target = len(active_map)

    for c in campaigns:
        # Check if stop was requested
        if stop_flag and callable(stop_flag) and stop_flag():
            log("checker.stopped", processed=processed, target=target)
            break

        cid = str(c.get("id"))
        if cid not in active_map:
            continue

        processed += 1
        if processed == 1 or processed % 25 == 0 or processed == target:
            log("checker.progress", processed=processed, target=target)

        debug("checker.campaign.start", campaign_id=cid, title=c.get("title"), status=c.get("status"))

        # full campaign object (contains streams etc.)
        full = redtrack.get_campaign(cid)
        meta = extract_urls_from_campaign(full)

        # domain name lookup
        domain_name = None
        if meta.get("domain_id"):
            did = str(meta["domain_id"])
            if did not in domain_cache:
                try:
                    domain_cache[did] = redtrack.get_domain(did)
                except Exception:
                    domain_cache[did] = {}
            domain_name = _pick_str(domain_cache[did], ["name", "domain", "title", "hostname"]) or domain_cache[did].get("domain")

        urls_to_check: list[tuple[str, str]] = []  # (kind, url)
        if meta.get("tracking_url"):
            urls_to_check.append(("tracking", meta["tracking_url"]))

        if domain_name:
            # check both https and http quickly
            urls_to_check.append(("domain_https", f"https://{domain_name}"))
            urls_to_check.append(("domain_http", f"http://{domain_name}"))

        # landing urls
        landing_urls: list[str] = []
        for lid in meta.get("landing_ids") or []:
            if lid not in landing_cache:
                try:
                    landing_cache[lid] = redtrack.get_landing(lid)
                except Exception:
                    landing_cache[lid] = {}
            u = _pick_str(landing_cache[lid], ["url"])
            if u:
                landing_urls.append(u)

        for u in landing_urls:
            urls_to_check.append(("landing", u))

        checks: list[dict[str, Any]] = []
        for kind, url in urls_to_check:
            # DNS precheck if url has host
            try:
                host = urlparse(url).hostname
            except Exception:
                host = None
            if host:
                ok_dns, dns_msg = dns_check(host)
                if not ok_dns:
                    checks.append({"kind": kind, **UrlCheck(ok=False, failure_type="dns", message=dns_msg, tested_url=url).__dict__})
                    continue

            best: UrlCheck | None = None
            for attempt in range(CHECK_RETRIES + 1):
                res = http_check(url)
                best = res
                if res.ok:
                    break
            checks.append({"kind": kind, **(best.__dict__ if best else UrlCheck(ok=False, failure_type="other", message="unknown").__dict__)})

        results.append(
            {
                "campaign": {
                    "id": cid,
                    "title": full.get("title"),
                    "status": full.get("status"),
                    "domain_id": meta.get("domain_id"),
                    "domain_name": domain_name,
                    "trackback_url": meta.get("tracking_url"),
                },
                "stats": active_map[cid],
                "checks": checks,
            }
        )

    log("checker.done", checked=len(results), processed=processed, target=target)
    return results
