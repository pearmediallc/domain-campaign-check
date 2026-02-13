from __future__ import annotations

import json
import os
import time
from typing import Any

from .config import MAX_CACHED_RUNS, RESULTS_PATH


def load_results() -> dict[str, Any]:
    if not os.path.exists(RESULTS_PATH):
        return {"runs": []}
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_results(doc: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(RESULTS_PATH) or ".", exist_ok=True)
    tmp = RESULTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    os.replace(tmp, RESULTS_PATH)


def append_run(run: dict[str, Any]) -> None:
    doc = load_results()
    runs = doc.get("runs")
    if not isinstance(runs, list):
        runs = []
    runs.insert(0, run)
    runs = runs[:MAX_CACHED_RUNS]
    doc["runs"] = runs
    doc["updated_at_epoch"] = int(time.time())
    save_results(doc)
