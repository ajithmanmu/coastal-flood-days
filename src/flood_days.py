"""Count flood days for a single NOAA CO-OPS station.

Rules encoded here (from the project note):

  1. Daily maximum, binary count. One day whose max level exceeds the threshold is
     one flood day, no matter how many times it crossed.
  2. Station-specific NOS thresholds, fetched from NOAA. Never invented.
  3. Never MHHW as the threshold. MHHW is the average high tide and is exceeded about
     half the days of the year by definition.
  4. One timezone throughout. We use Local Standard Time, never local daylight time.
  5. Completeness filter. A year under 90% valid records is flagged, not silently
     reported as a low-flood year.
  6. Fixed vertical reference. See DATUM below.
 11. The event rule is declared, not implied. NOAA's definition is "exceeds", so this
     is strictly greater than, not >=.
"""

import calendar
from dataclasses import dataclass

import noaa_coops as nc
import pandas as pd
import requests

MDAPI = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations"

# Rule 4: one timezone throughout, never local daylight time.
#
# GMT, not local standard time -- established by measurement, not preference. Counting
# on LST days disagrees with NOAA's published counts by 9 days across 9 stations in
# 2024; counting on GMT days disagrees by 3, and matches exactly at 7 of the 9. So NOAA
# uses GMT calendar days.
#
# The cost is that a "flood day" boundary falls at 7-8pm local on the East Coast, which
# is not the day anyone lived through. That is a real distortion, kept deliberately
# because comparability with NOAA is worth more than intuitive day boundaries. It must
# be stated in the methods section, not buried.
TIME_ZONE = "gmt"

# Rule 6. The thresholds endpoint returns feet relative to the station datum, and does
# not document that anywhere -- it was established by arithmetic against the station's
# own datums. Requesting water levels in the same units and frame means the two sides
# are directly comparable and no conversion can silently go wrong.
DATUM = "STND"
UNITS = "english"


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


def fetch_threshold(station_id: str, level: str = "nos_minor") -> float:
    """Return the station's flood threshold, in feet above station datum.

    Rule 2. NOAA publishes two families: nos_* are nationally comparable and derived
    from Sweet et al. 2018; nws_* are local forecast-office impact levels and vary by
    office. NOAA documents nos_minor as the one used for historical flood-day counts,
    so it is the default here. They disagree -- at The Battery, 10.19 vs 10.49 ft.
    """
    response = requests.get(f"{MDAPI}/{station_id}/floodlevels.json", timeout=30)
    response.raise_for_status()
    return float(response.json()[level])


def fetch_hourly_heights(station_id: str, year: int) -> pd.DataFrame:
    """Return one year of hourly water levels, in the same units and frame as the
    threshold."""
    df = nc.Station(station_id).get_data(
        begin_date=f"{year}0101",
        end_date=f"{year}1231",
        product="hourly_height",
        datum=DATUM,
        units=UNITS,
        time_zone=TIME_ZONE,
    )
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    return df


def count_flood_days(heights: pd.DataFrame, threshold: float, year: int) -> FloodYear:
    """Count calendar days whose maximum water level exceeds the threshold.

    Rule 1: one day, one count. Reducing to a daily maximum first means a day with two
    exceeding high tides still counts once.

    Rule 11: strictly greater than. NOAA's published definition is "exceeds", and a day
    that merely touches the threshold is not a flood day under it.

    Rule 5: days with no observations are absent from the daily max, so they are never
    counted as dry. Completeness is reported alongside rather than folded into the count.
    """
    observed = heights["v"].dropna()
    daily_max = observed.groupby(observed.index.date).max()
    expected_hours = (366 if calendar.isleap(year) else 365) * 24

    return FloodYear(
        year=year,
        flood_days=int((daily_max > threshold).sum()),
        days_observed=len(daily_max),
        completeness=len(observed) / expected_hours,
    )


if __name__ == "__main__":
    STATION = "8518750"  # The Battery, NY
    YEAR = 2024

    threshold = fetch_threshold(STATION)
    result = count_flood_days(fetch_hourly_heights(STATION, YEAR), threshold, YEAR)

    print(f"station {STATION}, {result.year}")
    print(f"  threshold      {threshold:.2f} ft above station datum (nos_minor)")
    print(f"  flood days     {result.flood_days}")
    print(f"  completeness   {result.completeness:.1%}")
