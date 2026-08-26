"""Turn thousands of raw station-year files into the two artifacts everything else reads.

    results/flood_days.parquet   the dataset -- every station-year, nothing hidden
    results/map_summary.json     ~137 rows, what the map loads on first paint

The split is deliberate. The Parquet file is the contribution: the bulk duration record
that does not exist anywhere else. The JSON is a viewer convenience -- small enough that
the map draws immediately instead of waiting on the full dataset.

Nothing here calls NOAA for water levels. It reads what the backfill already cached, so
it can be re-run freely as thresholds or rules change.
"""

import json
from pathlib import Path

import pandas as pd

from flood_days import SESSION, fetch_threshold, summarise_year
from storage import (cached_years, load_year, results_exists, results_read_parquet,
                     results_write_parquet, results_write_text)

HTF_ANNUAL = "https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/htf/htf_annual.json"
RESULTS = Path(__file__).resolve().parents[1] / "data" / "results"

# Rule 8. A trend needs two full 18.6-year lunar nodal cycles, or the cycle itself can
# masquerade as one. Stations below this get published in the dataset but must not carry
# a trend claim.
MIN_YEARS_FOR_TREND = 37


def station_index(refresh: bool = False) -> pd.DataFrame:
    """Station id, name and position for every station NOAA publishes flood counts for.

    Cached, because it is also the definitive list of which stations matter -- and it
    doubles as NOAA's own answer for validation.
    """
    if results_exists("station_index.parquet") and not refresh:
        return results_read_parquet("station_index.parquet")

    rows = SESSION.get(HTF_ANNUAL, timeout=60).json()["AnnualFloodCount"]
    frame = pd.DataFrame(rows)
    index = (
        frame.groupby("stnId")
        .agg(name=("stnName", "first"), lat=("lat", "first"), lon=("lon", "first"))
        .reset_index()
        .rename(columns={"stnId": "station"})
    )
    index[["lat", "lon"]] = index[["lat", "lon"]].astype(float)

    noaa_counts = frame.rename(columns={"stnId": "station", "minCount": "noaa_days"})
    results_write_parquet("station_index.parquet", index)
    results_write_parquet("noaa_counts.parquet", noaa_counts[["station", "year", "noaa_days"]])
    return index


def station_years(station_id: str, threshold: float) -> list[dict]:
    """Summarise every cached year for one station. Empty years are skipped, not zeroed --
    rule 5: an absent year is unknown, not a year without floods."""
    rows = []
    for year in cached_years(station_id):
        heights = load_year(station_id, year)
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


def build(stations: list[str] | None = None) -> pd.DataFrame:
    index = station_index()
    targets = stations or index["station"].tolist()

    rows = []
    for station_id in targets:
        if not cached_years(station_id):
            continue
        try:
            threshold = fetch_threshold(station_id)
        except Exception:
            continue  # no published threshold means the station cannot be counted
        rows.extend(station_years(station_id, threshold))

    if not rows:
        return pd.DataFrame()

    results = pd.DataFrame(rows).merge(index, on="station", how="left")
    return results.sort_values(["station", "year"]).reset_index(drop=True)


def summarise_stations(results: pd.DataFrame) -> pd.DataFrame:
    """One row per station -- what the map needs, and only what it needs.

    Every figure here is computed from usable years only. A station with six missing
    years must not look calmer than one with none.
    """
    usable = results[results["usable"]]
    if usable.empty:
        return pd.DataFrame()

    recent = usable[usable["year"] >= usable["year"].max() - 9]

    per_station = recent.groupby("station").agg(
        days_per_year=("flood_days", "mean"),
        hours_per_year=("flood_hours", "mean"),
    )
    # Computed from the totals, not as a mean of ratios -- averaging ratios lets a
    # single quiet year with one short flood dominate the number.
    totals = recent.groupby("station").agg(
        total_days=("flood_days", "sum"), total_hours=("flood_hours", "sum")
    )
    per_station["hours_per_flood_day"] = (
        totals["total_hours"] / totals["total_days"].replace(0, pd.NA)
    )

    span = usable.groupby("station")["year"].agg(
        first_year="min", last_year="max", usable_years="count"
    )
    per_station = per_station.join(span)
    per_station["trend_supported"] = per_station["usable_years"] >= MIN_YEARS_FOR_TREND

    meta = results.groupby("station")[["name", "lat", "lon"]].first()
    return per_station.join(meta).reset_index().round(3)


def headline_stats(results: pd.DataFrame) -> dict:
    """The two figures the page leads with, computed across every long record.

    Both compare a station's first decade of record against its last, so each gauge is its
    own control -- the set of reporting stations changes enormously over a century, and a
    cross-sectional average would track that churn instead of the climate.

    Frequency and duration use different populations, deliberately. Any gauge with a long
    enough record can be asked whether it floods more often. Only a gauge that actually
    flooded can be asked how long its floods lasted, so the duration figure is restricted
    to records with at least one flood day -- a necessity, not a filter.
    """
    usable = results[results["usable"]]
    counts = usable.groupby("station")["year"].count()
    long_records = counts[counts >= MIN_YEARS_FOR_TREND].index

    def ends(frame):
        """First and last decade of one station's record."""
        first, last = frame["year"].min(), frame["year"].max()
        return frame[frame["year"] <= first + 9], frame[frame["year"] >= last - 9]

    rose = total = 0
    for _, block in usable[usable["station"].isin(long_records)].groupby("station"):
        early, late = ends(block)
        total += 1
        rose += late["flood_days"].mean() > early["flood_days"].mean()

    # Ratios from decade totals, never a mean of per-year ratios: one quiet year with a
    # single short flood would otherwise dominate the station's number.
    flooded = usable[usable["flood_days"] > 0]
    then, now = [], []
    for _, block in flooded[flooded["station"].isin(long_records)].groupby("station"):
        if block["year"].nunique() < MIN_YEARS_FOR_TREND:
            continue
        early, late = ends(block)
        if early["flood_days"].sum() > 0:
            then.append(early["flood_hours"].sum() / early["flood_days"].sum())
        if late["flood_days"].sum() > 0:
            now.append(late["flood_hours"].sum() / late["flood_days"].sum())

    return {
        "gauges_more_frequent": int(rose),
        "gauges_compared": int(total),
        "hours_per_flood_then": round(float(pd.Series(then).median()), 2),
        "hours_per_flood_now": round(float(pd.Series(now).median()), 2),
        "duration_records": len(now),
        "station_years": int(len(usable)),
    }


def write(results: pd.DataFrame, summary: pd.DataFrame) -> None:
    """Three artifacts, sized for three different jobs.

    The Parquet file is the dataset. The map summary is ~137 rows so the page draws on
    first paint. Per-station files are fetched only when someone clicks -- putting every
    station's full century into the summary would make the map wait on data most
    visitors never look at.
    """
    results_write_parquet("flood_days.parquet", results)

    results_write_text("map_summary.json",
        json.dumps(
            {
                "generated": pd.Timestamp.utcnow().isoformat(),
                "note": "hours above NOS minor threshold at the gauge; not road-closure time",
                "headline": headline_stats(results),
                "stations": json.loads(summary.to_json(orient="records")),
            },
            indent=1,
        ))

    for station_id, block in results.groupby("station"):
        series = block[["year", "flood_days", "flood_hours", "completeness", "usable"]]
        results_write_text(f"stations/{station_id}.json",
            json.dumps(
                {
                    "station": station_id,
                    "name": block["name"].iloc[0],
                    "years": json.loads(series.to_json(orient="records")),
                },
                separators=(",", ":"),
            ))


if __name__ == "__main__":
    import sys

    wanted = sys.argv[1:] or None
    results = build(wanted)
    if results.empty:
        print("nothing cached yet")
        raise SystemExit(1)

    summary = summarise_stations(results)
    write(results, summary)

    print(f"station-years : {len(results)}")
    print(f"usable        : {int(results['usable'].sum())}")
    print(f"stations      : {results['station'].nunique()}")
    print(f"trend-capable : {int(summary['trend_supported'].sum())}\n")
    print(summary[["station", "name", "days_per_year", "hours_per_year",
                   "hours_per_flood_day", "usable_years", "trend_supported"]].to_string(index=False))
