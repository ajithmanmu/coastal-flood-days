"""Local cache of raw water levels, one Parquet file per station-year.

    data/raw/station=8518750/year=1996.parquet

The layout matches what will sit in S3, so moving there later is a path change and
nothing else. `station=`/`year=` is Hive-style partitioning -- DuckDB and Athena read
those directory names as real columns and skip whole folders without opening files.

Two things this buys us beyond speed:

  * The backfill becomes resumable. It walks ~4,000 station-years against an API with
    no published rate limit; dying at station 80 and starting again from zero is not
    an option.
  * Station-years that genuinely have no data are remembered as empty rather than
    re-requested forever. Most of the 137 stations do not go back to 1920, so without
    this the backfill spends most of its life asking for data that has never existed.
"""

from pathlib import Path

import noaa_coops as nc
import pandas as pd

from flood_days import DATUM, TIME_ZONE, UNITS

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def path_for(station_id: str, year: int) -> Path:
    return RAW / f"station={station_id}" / f"year={year}.parquet"


def _station(station_id: str, _cache: dict = {}) -> nc.Station:
    """One Station object per id -- constructing it hits the metadata endpoint."""
    if station_id not in _cache:
        _cache[station_id] = nc.Station(station_id)
    return _cache[station_id]


def _fetch(station_id: str, year: int) -> pd.DataFrame:
    """Pull one year from NOAA. Returns an empty frame if the year has no data.

    'No data was found' is a normal answer, not a failure -- most stations simply did
    not exist for most of the century. It is cached like any other result.
    """
    try:
        df = _station(station_id).get_data(
            begin_date=f"{year}0101",
            end_date=f"{year}1231",
            product="hourly_height",
            datum=DATUM,
            units=UNITS,
            time_zone=TIME_ZONE,
        )
    except Exception as exc:
        if "No data was found" in str(exc):
            return pd.DataFrame({"v": pd.Series(dtype="float64")})
        raise

    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    return df[["v"]]


def load_year(station_id: str, year: int, refresh: bool = False) -> pd.DataFrame:
    """Return one station-year, from disk if we have it and from NOAA if we don't.

    An empty frame means 'NOAA has no data for this station-year' -- a cached fact,
    not a cache miss.
    """
    path = path_for(station_id, year)

    if path.exists() and not refresh:
        return pd.read_parquet(path)

    df = _fetch(station_id, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def is_cached(station_id: str, year: int) -> bool:
    return path_for(station_id, year).exists()


def cached_years(station_id: str) -> list[int]:
    """Years already on disk for a station, empty ones included."""
    folder = RAW / f"station={station_id}"
    if not folder.exists():
        return []
    return sorted(int(p.stem.split("=")[1]) for p in folder.glob("year=*.parquet"))
