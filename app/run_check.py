from __future__ import annotations

import datetime as dt

from sqlalchemy import desc

from .checker import run_full_check
from .db import get_session
from .migrate import migrate
from .models import Campaign, CheckResult
from .redtrack import RedTrackClient
from .telegram import send_message


def _fmt_campaign_line(c: dict, failed_checks: list[dict]) -> str:
    parts = [f"• {c.get('title') or 'Campaign'} (id {c.get('id')})"]
    if c.get("domain_name"):
        parts.append(f"  domain: {c['domain_name']}")
    if c.get("trackback_url"):
        parts.append(f"  url: {c['trackback_url']}")
    for ch in failed_checks[:5]:
        kind = ch.get("kind")
        msg = ch.get("message")
        status = ch.get("http_status")
        tested = ch.get("tested_url")
        parts.append(f"  - {kind}: {msg or 'failed'}" + (f" (HTTP {status})" if status else "") + (f" → {tested}" if tested else ""))
    if len(failed_checks) > 5:
        parts.append(f"  - (+{len(failed_checks)-5} more)")
    return "\n".join(parts)


def main():
    migrate()

    redtrack = RedTrackClient()
    results = run_full_check(redtrack)

    now = dt.datetime.now(dt.timezone.utc)

    total = len(results)
    failing = 0

    with get_session() as s:
        for r in results:
            c = r["campaign"]
            stats = r["stats"]
            checks = r["checks"]

            ok = all(ch.get("ok") for ch in checks) if checks else False

            db_c = s.get(Campaign, c["id"]) or Campaign(id=c["id"])
            db_c.title = c.get("title")
            db_c.status = str(c.get("status")) if c.get("status") is not None else None
            db_c.domain_id = c.get("domain_id")
            db_c.domain_name = c.get("domain_name")
            db_c.impression_url = None
            db_c.trackback_url = c.get("trackback_url")
            db_c.cost_30d = stats.get("cost_30d")
            db_c.revenue_30d = stats.get("revenue_30d")
            db_c.updated_at = now
            s.add(db_c)

            # store one consolidated check result per campaign run (plus message)
            failed_checks = [ch for ch in checks if not ch.get("ok")]
            if failed_checks:
                failing += 1

            first = failed_checks[0] if failed_checks else (checks[0] if checks else {})
            cr = CheckResult(
                campaign_id=db_c.id,
                ok=ok,
                failure_type=(first.get("failure_type") if not ok else None),
                message=(first.get("message") if not ok else "ok"),
                tested_url=first.get("tested_url"),
                final_url=first.get("final_url"),
                http_status=first.get("http_status"),
                elapsed_ms=first.get("elapsed_ms"),
            )
            s.add(cr)

        s.commit()

    # Telegram notification
    summary = f"RedTrack domain check finished. Checked {total} active campaigns with spend/rev in last 30d. Failing: {failing}."
    try:
        send_message(summary)
    except Exception:
        # If telegram not configured, still succeed.
        pass

    if failing:
        # Send details for failing campaigns (batched)
        chunks: list[str] = []
        current = "🚨 Failing campaigns:\n"
        for r in results:
            c = r["campaign"]
            failed_checks = [ch for ch in r["checks"] if not ch.get("ok")]
            if not failed_checks:
                continue
            line = _fmt_campaign_line(c, failed_checks)
            if len(current) + len(line) + 2 > 3800:
                chunks.append(current)
                current = "🚨 Failing campaigns (cont.):\n"
            current += line + "\n\n"
        if current.strip():
            chunks.append(current)

        for text in chunks:
            try:
                send_message(text)
            except Exception:
                break


if __name__ == "__main__":
    main()
