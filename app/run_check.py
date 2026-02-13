from __future__ import annotations

import argparse

from .checker import run_full_check
from .redtrack import RedTrackClient
from .telegram import send_message


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date-from", dest="date_from")
    p.add_argument("--date-to", dest="date_to")
    p.add_argument("--days-lookback", dest="days_lookback", type=int, default=30)
    args = p.parse_args()

    redtrack = RedTrackClient()
    results = run_full_check(redtrack, date_from=args.date_from, date_to=args.date_to, days_lookback=args.days_lookback)

    total = len(results)
    failing = sum(1 for r in results if any(not ch.get("ok") for ch in r.get("checks", [])))

    send_message(f"RedTrack domain check finished. Checked {total} campaigns. Failing: {failing}.")


if __name__ == "__main__":
    main()
