"""Count flood days for a single NOAA CO-OPS station.

Milestone one: one station, one year, one number.

Rules encoded here (from the project note):

  1. Daily maximum, binary count. One day whose max level meets the threshold is
     one flood day, no matter how many times it crossed.
  4. One timezone throughout. We use Local Standard Time, never local daylight time.
  5. Completeness filter. A year under 90% valid hourly records is flagged, not
     silently reported as a low-flood year.
  6. Fixed vertical reference. NAVD88 where the station supports it.

Rules 2 and 3 (real NOS thresholds) are NOT encoded yet. See PROVISIONAL_OFFSET_M.
"""

import calendar
from dataclasses import dataclass

import noaa_coops as nc
import pandas as pd

# Rule 4: local standard time, so a calendar day matches the day people lived through.
# GMT would work equally well but splits US nights across two dates; either is valid,
# mixing them is not.
TIME_ZONE = "lst"
UNITS = "metric"
DATUM = "NAVD"  # API code for NAVD88

# The datums endpoint reports in FEET regardless of what units the water-level product
# is requested in. Conversion is not optional.
FEET_TO_METRES = 0.3048

# NOT a real NOAA threshold. Sweet et al. 2018 puts the minor high-tide-flooding
# threshold roughly 0.5-0.65 m above MHHW, varying by station. This midpoint stands in
# until the real per-station thresholds are fetched. Any number produced with it is a
# pipeline test, not a finding.
PROVISIONAL_OFFSET_M = 0.55


@dataclass
class FloodYear:
    """One station-year. Carries completeness so rule 5 can't be dropped by accident."""

    year: int
    flood_days: int
    days_observed: int
    completeness: float

    @property
    def usable(self) -> bool:
        return self.completeness >= 0.90


def fetch_hourly_heights(station_id: str, year: int, datum: str = "NAVD") -> pd.DataFrame:
    """Return one year of hourly water levels for a station.

    Rule 6: datum is explicit and required. Not every station supports NAVD88, so
    this is a parameter rather than a constant.
    """
    station = nc.Station(station_id)
    df = station.get_data(
        begin_date=f"{year}0101",
        end_date=f"{year}1231",
        product="hourly_height",
        datum=datum,
        units=UNITS,
        time_zone=TIME_ZONE,
    )
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    return df


def count_flood_days(heights: pd.DataFrame, threshold: float, year: int) -> FloodYear:
    """Count calendar days whose maximum water level reaches the threshold.

    Rule 1: one day, one count. We reduce to a daily maximum first, so a day with two
    exceeding high tides still counts once.

    Rule 5: days with no observations are absent from the daily max, so they are never
    counted as dry. Completeness is reported alongside rather than folded into the
    count.
    """
    observed = heights["v"].dropna()
    daily_max = observed.groupby(observed.index.date).max()

    expected_hours = (366 if calendar.isleap(year) else 365) * 24

    return FloodYear(
        year=year,
        flood_days=int((daily_max >= threshold).sum()),
        days_observed=len(daily_max),
        completeness=len(observed) / expected_hours,
    )


def provisional_threshold(station_id: str) -> tuple[float, str]:
    """Stand-in threshold in metres above NAVD88, plus the datum epoch it came from.

    Rule 3 is the reason this is not just MHHW. MHHW is the average of daily higher
    high tides and is exceeded about half the days of the year by definition; using it
    directly would invalidate every number downstream.

    Rule 6 is the reason for the arithmetic. The datums endpoint returns every value in
    FEET and relative to STND, the station's own zero. Water levels here are requested
    in METRES relative to NAVD88. Two different units and two different reference
    frames, so MHHW has to be re-expressed against NAVD88 and converted before it can
    be compared to anything. Skipping either step is a silent 6-foot error.

    This is still not a real threshold. Replace with the NOS per-station values.
    """
    response = nc.Station(station_id).datums
    datums = {d["name"]: float(d["value"]) for d in response["datums"]}

    mhhw_above_navd88_ft = datums["MHHW"] - datums["NAVD88"]
    threshold_m = mhhw_above_navd88_ft * FEET_TO_METRES + PROVISIONAL_OFFSET_M

    return threshold_m, response["epoch"]


if __name__ == "__main__":
    STATION = "8518750"  # The Battery, NY
    YEAR = 2024

    threshold, epoch = provisional_threshold(STATION)
    heights = fetch_hourly_heights(STATION, YEAR, datum=DATUM)
    result = count_flood_days(heights, threshold, YEAR)

    print(f"station {STATION}, {result.year}")
    print(f"  threshold      {threshold:.3f} m above NAVD88  <- PROVISIONAL, not a NOAA value")
    print(f"  datum epoch    {epoch}")
    print(f"  flood days     {result.flood_days}")
    print(f"  days observed  {result.days_observed}")
    print(f"  completeness   {result.completeness:.1%}{'' if result.usable else '  <- below 90%, do not report'}")
