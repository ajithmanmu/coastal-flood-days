"""Daily refresh: keep the published dataset current.

Runs once a day. A day's flood count is not final until the day ends, so running more
often only recomputes a partial answer.

**Why it refreshes whole years rather than appending yesterday.**

NOAA serves recent observations as `preliminary` and replaces them with quality-controlled
`verified` values weeks later, so days already counted can change and days skipped for
missing data can become usable. An append-only job would never see those corrections.

The obvious fix is to re-count a trailing window -- but the window length is a guess
(NOAA says "weeks"), and a wrong guess silently misses the tail. Refetching the current
year sidesteps it entirely: `hourly_height` returns up to a year per request, so a whole
year costs exactly one call, the same as asking for a single day. The guess disappears
and every revision is picked up by construction.

Early in the year, revisions can still reach back into December, so the previous year is
refreshed too for the first REVISION_REACH_DAYS days.

    .venv/bin/python src/daily.py --dry-run --stations 3
"""

import argparse
import json
import logging
import sys
from datetime import date, timedelta

import pandas as pd

from aggregate import station_index, summarise_stations, write
from flood_days import fetch_threshold, summarise_year
from storage import load_year, results_read_parquet, results_write_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("daily")

# How long into a new year revisions can still land on the previous one.
REVISION_REACH_DAYS = 90

# The job must fail loudly if it produces implausibly little. A green run that wrote
# nothing is the failure mode that goes unnoticed for weeks -- the same gap as MAR-886.
MIN_STATIONS_EXPECTED = 100


def years_to_refresh(today: date) -> list[int]:
    years = [today.year]
    if today.timetuple().tm_yday <= REVISION_REACH_DAYS:
        years.append(today.year - 1)
    return years


def refresh_station(station_id: str, years: list[int]) -> list[dict]:
    """Refetch and recount the given years for one station. Returns replacement rows."""
    threshold = fetch_threshold(station_id)
    rows = []
    for year in years:
        heights = load_year(station_id, year, refresh=True)
        if heights.empty:
            continue
        summary = summarise_year(heights, threshold, year)
        rows.append(
            {
                "station": station_id,
                "year": summary.year,
                "flood_days": summary.flood_days,
                "flood_hours": summary.flood_hours,
                "hours_per_flood_day": summary.hours_per_flood_day,
                "completeness": round(summary.completeness, 4),
                "usable": summary.usable,
            }
        )
    return rows


def run(stations: list[str] | None = None, today: date | None = None, dry_run: bool = False) -> int:
    today = today or date.today()
    years = years_to_refresh(today)
    log.info("daily refresh · years %s · %s", years, "DRY RUN" if dry_run else "live")

    existing = results_read_parquet("flood_days.parquet")
    index = station_index()
    targets = stations or index["station"].tolist()

    fresh, failed = [], []
    for n, station_id in enumerate(targets, 1):
        try:
            fresh.extend(refresh_station(station_id, years))
        except Exception as exc:
            failed.append(station_id)
            log.warning("%s failed: %s", station_id, str(exc)[:80])
        if n % 25 == 0:
            log.info("  %s/%s stations", n, len(targets))

    if not fresh:
        log.error("no rows produced -- refusing to publish")
        return 1

    updated = pd.DataFrame(fresh)
    log.info("refreshed %s station-years across %s stations (%s failed)",
             len(updated), updated["station"].nunique(), len(failed))

    # Replace rather than append: these station-years already exist and their values
    # may have been revised underneath us.
    keys = set(zip(updated["station"], updated["year"]))
    kept = existing[~existing.set_index(["station", "year"]).index.isin(keys)]
    merged = pd.concat([kept.drop(columns=["name", "lat", "lon"], errors="ignore"), updated])
    merged = merged.merge(index, on="station", how="left").sort_values(["station", "year"])

    changed = compare(existing, merged)
    if changed:
        log.info("value changes vs the published dataset: %s", changed)

    summary = summarise_stations(merged)
    if len(summary) < MIN_STATIONS_EXPECTED:
        log.error("only %s stations in summary, expected >= %s -- refusing to publish",
                  len(summary), MIN_STATIONS_EXPECTED)
        return 1

    if dry_run:
        log.info("dry run: would publish %s station-years, %s stations", len(merged), len(summary))
        return 0

    write(merged, summary)
    results_write_text("last_updated.json", json.dumps({
        "updated": pd.Timestamp.utcnow().isoformat(),
        "years_refreshed": years,
        "stations": int(summary.shape[0]),
        "station_years": int(len(merged)),
        "failed_stations": failed,
    }, indent=1))
    log.info("published %s station-years, %s stations", len(merged), len(summary))
    return 0


def handler(event, context):
    """Lambda entry point.

    Raises on failure rather than returning an error code, so Lambda records an
    invocation error and the alarm fires. A job that fails quietly and returns 200 is
    indistinguishable from a healthy one.
    """
    code = run()
    if code != 0:
        raise RuntimeError("daily refresh failed -- see logs")
    return {"ok": True}


def compare(before: pd.DataFrame, after: pd.DataFrame) -> str:
    """Report how many published counts NOAA revised under us. This is the number worth
    watching -- if it is always zero the refresh is pointless; if it is large the trailing
    reach is too short."""
    a = before.set_index(["station", "year"])["flood_days"]
    b = after.set_index(["station", "year"])["flood_days"]
    common = a.index.intersection(b.index)
    diff = (a.loc[common] != b.loc[common]).sum()
    return f"{diff} station-years changed" if diff else ""


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stations", type=int, default=0, help="limit, 0 = all")
    args = p.parse_args()

    idx = station_index()
    subset = idx["station"].tolist()[: args.stations] if args.stations else None
    sys.exit(run(stations=subset, dry_run=args.dry_run))
