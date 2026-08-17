"""Cache of raw water levels, one Parquet file per station-year.

    station=8518750/year=1996.parquet

Writes locally by default and to S3 when RAW_URI points at a bucket:

    export RAW_URI=s3://coastal-flood-days-data-412602263780/raw

Same layout either way, which is the point -- the Fargate task and a laptop produce an
identical tree, so a run can start in one place and finish in the other. `station=` /
`year=` is Hive-style partitioning, so DuckDB and Athena read those directory names as
real columns and skip whole folders without opening files.

Two things this buys beyond speed:

  * The backfill becomes resumable. It walks ~14,000 station-years against an API with
    no published rate limit; dying partway and restarting from zero is not an option.
  * Station-years that genuinely have no data are remembered as empty rather than
    re-requested forever. Most of the 137 stations do not reach 1920, so without this
    the backfill spends most of its life asking for data that has never existed.
"""

import io
import os
from functools import lru_cache
from pathlib import Path

import noaa_coops as nc
import pandas as pd

from flood_days import DATUM, TIME_ZONE, UNITS

DEFAULT_LOCAL = Path(__file__).resolve().parents[1] / "data" / "raw"
RAW_URI = os.environ.get("RAW_URI", str(DEFAULT_LOCAL))


def _key(station_id: str, year: int) -> str:
    return f"station={station_id}/year={year}.parquet"


def _is_s3() -> bool:
    return RAW_URI.startswith("s3://")


def _bucket_and_prefix() -> tuple[str, str]:
    bucket, _, prefix = RAW_URI[len("s3://"):].partition("/")
    return bucket, prefix.strip("/")


@lru_cache(maxsize=1)
def _s3():
    import boto3

    return boto3.client("s3")


def _s3_key(station_id: str, year: int) -> str:
    _, prefix = _bucket_and_prefix()
    return f"{prefix}/{_key(station_id, year)}" if prefix else _key(station_id, year)


def path_for(station_id: str, year: int) -> str:
    """Where this station-year lives, as a URI or a local path."""
    if _is_s3():
        bucket, _ = _bucket_and_prefix()
        return f"s3://{bucket}/{_s3_key(station_id, year)}"
    return str(Path(RAW_URI) / _key(station_id, year))


def is_cached(station_id: str, year: int) -> bool:
    if not _is_s3():
        return Path(path_for(station_id, year)).exists()

    bucket, _ = _bucket_and_prefix()
    try:
        _s3().head_object(Bucket=bucket, Key=_s3_key(station_id, year))
        return True
    except Exception:
        return False


def _read(station_id: str, year: int) -> pd.DataFrame:
    if not _is_s3():
        return pd.read_parquet(path_for(station_id, year))

    bucket, _ = _bucket_and_prefix()
    body = _s3().get_object(Bucket=bucket, Key=_s3_key(station_id, year))["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def _write(station_id: str, year: int, frame: pd.DataFrame) -> None:
    if not _is_s3():
        target = Path(path_for(station_id, year))
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(target)
        return

    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    bucket, _ = _bucket_and_prefix()
    _s3().put_object(
        Bucket=bucket, Key=_s3_key(station_id, year), Body=buffer.getvalue()
    )


@lru_cache(maxsize=None)
def _station(station_id: str) -> nc.Station:
    """One Station object per id -- constructing it hits the metadata endpoint, and
    doing that once per year of a 14,000-year backfill is what makes NOAA refuse."""
    return nc.Station(station_id)


def _fetch(station_id: str, year: int) -> pd.DataFrame:
    """Pull one year from NOAA. Returns an empty frame if the year has no data.

    'No data was found' is a normal answer, not a failure -- most stations simply did
    not exist for most of the century. It gets cached like any other result.
    """
    try:
        frame = _station(station_id).get_data(
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

    frame["v"] = pd.to_numeric(frame["v"], errors="coerce")
    return frame[["v"]]


def load_year(station_id: str, year: int, refresh: bool = False) -> pd.DataFrame:
    """Return one station-year, from cache if we have it and from NOAA if we don't.

    An empty frame means 'NOAA has no data for this station-year' -- a cached fact,
    not a cache miss.
    """
    if is_cached(station_id, year) and not refresh:
        return _read(station_id, year)

    frame = _fetch(station_id, year)
    _write(station_id, year, frame)
    return frame


def cached_years(station_id: str) -> list[int]:
    """Years already cached for a station, empty ones included."""
    if not _is_s3():
        folder = Path(RAW_URI) / f"station={station_id}"
        if not folder.exists():
            return []
        return sorted(int(p.stem.split("=")[1]) for p in folder.glob("year=*.parquet"))

    bucket, _ = _bucket_and_prefix()
    prefix = _s3_key(station_id, 0).rsplit("/", 1)[0] + "/"
    paginator = _s3().get_paginator("list_objects_v2")
    years = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            stem = item["Key"].rsplit("/", 1)[-1].removesuffix(".parquet")
            years.append(int(stem.split("=")[1]))
    return sorted(years)
