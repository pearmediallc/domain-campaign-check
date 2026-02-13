from __future__ import annotations

import json
import os
import time
from typing import Any

DEBUG = (os.getenv("DEBUG", "false") or "false").lower() in ("1", "true", "yes")


def log(event: str, **fields: Any) -> None:
    rec = {
        "ts": int(time.time()),
        "event": event,
        **fields,
    }
    print(json.dumps(rec, default=str))


def debug(event: str, **fields: Any) -> None:
    if DEBUG:
        log(event, **fields)
