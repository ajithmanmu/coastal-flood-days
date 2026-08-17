"""Walk one station's full hourly record, year by year, and report days and hours.

Usage:  .venv/bin/python src/station_history.py 8518750 [start_year]

Fetching and caching live in storage.py -- this file only summarises.
"""

import sys
import time

from flood_days import fetch_threshold, summarise_year
from storage import is_cached, load_year

POLITE_SECONDS = 0.5


def walk(station_id: str, start: int = 1920, end: int = 2025):
    threshold = fetch_threshold(station_id)
    print(f"station {station_id} · nos_minor = {threshold:.2f} ft above station datum\n")
    print(f"{'year':6} {'days':>5} {'hours':>7} {'hrs/day':>8} {'complete':>9}")

    results = []
    for year in range(start, end + 1):
        was_cached = is_cached(station_id, year)
        heights = load_year(station_id, year)
        if not was_cached:
            time.sleep(POLITE_SECONDS)  # only pause when we actually called NOAA

        if heights.empty:
            continue

        summary = summarise_year(heights, threshold, year)
        results.append(summary)
        hpd = summary.hours_per_flood_day
        flag = "" if summary.usable else "  <- excluded, under 90%"
        print(
            f"{summary.year:6} {summary.flood_days:5} {summary.flood_hours:7.0f} "
            f"{(f'{hpd:.1f}' if hpd else '-'):>8} {summary.completeness:8.0%}{flag}"
        )
    return results


def decade_summary(results):
    """Averages over usable years only -- rule 5 applies to every derived number."""
    usable = [r for r in results if r.usable]
    if not usable:
        return
    print(f"\n{'decade':8} {'yrs':>4} {'days/yr':>8} {'hours/yr':>9} {'hrs/day':>8}")
    for decade in range(min(r.year for r in usable) // 10 * 10,
                        max(r.year for r in usable) // 10 * 10 + 10, 10):
        block = [r for r in usable if decade <= r.year < decade + 10]
        if not block:
            continue
        days = sum(r.flood_days for r in block) / len(block)
        hours = sum(r.flood_hours for r in block) / len(block)
        print(f"{decade}s{'':3} {len(block):4} {days:8.1f} {hours:9.1f} "
              f"{(hours / days if days else 0):8.1f}")


if __name__ == "__main__":
    station = sys.argv[1] if len(sys.argv) > 1 else "8518750"
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 1920
    decade_summary(walk(station, start=start))
