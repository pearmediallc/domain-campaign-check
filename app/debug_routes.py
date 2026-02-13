from __future__ import annotations

from fastapi import APIRouter

from .redtrack import RedTrackClient
from .log import log

router = APIRouter()


@router.get("/debug/redtrack")
def debug_redtrack():
    """Returns a small summary of what RedTrack returns.

    This helps debug response shapes without exposing the API key.
    """
    rt = RedTrackClient()
    raw = rt._get("/campaigns/v2", params={"page": 1, "per": 1, "timezone": "UTC"}, retries=0)
    kind = type(raw).__name__
    keys = list(raw.keys()) if isinstance(raw, dict) else None
    sample = None
    if isinstance(raw, dict) and isinstance(raw.get("items"), list) and raw["items"]:
        sample = {
            "id": raw["items"][0].get("id"),
            "title": raw["items"][0].get("title"),
            "status": raw["items"][0].get("status"),
        }
    log("debug.redtrack", kind=kind, keys=keys, sample=sample)
    return {"type": kind, "keys": keys, "sample": sample}
