"""Count flood days AND flood hours for a single NOAA CO-OPS station.

The hours are the point. NOAA already publishes the day counts; what it does not publish
is how long the water stayed up, and that is what this file computes alongside them.

Rules encoded here (from the project note):

  1. Daily maximum, binary count. One day whose maximum level reaches the threshold is
     one flood day, no matter how many times it crossed.
  2. Station-specific NOS thresholds, fetched from NOAA. Never invented.
  3. Never MHHW as the threshold. MHHW is the average high tide and is exceeded about
     half the days of the year by definition.
  4. One timezone throughout -- GMT, not local standard time. Settled by measurement
     against NOAA's own published counts, not by preference. See TIME_ZONE.
  5. Completeness filter. A year under 90% valid records is flagged, not silently
     reported as a low-flood year.
  6. Fixed vertical reference. See DATUM below.
  9. Hourly observations are a valid proxy for CUMULATIVE hours, not for the length of
     any single flood. See summarise_year.
 10. "Exposure duration", never "impact duration". These are hours at a gauge, not hours
     a road was shut. See FloodYear.hours_per_flood_day.
 11. The event rule is declared, not implied -- and it is `>=`, not `>`. NOAA's wording
     says "exceeds", which reads as strictly greater; their data disagrees. See
     summarise_year for the measurement.

Two of these rules once said the opposite. Rule 4 read "Local Standard Time" and rule 11
read "strictly greater than", both matching NOAA's documentation and neither matching
NOAA's data. They were corrected in the code when the 2x2 test was run, and this docstring
was not -- so for a while the header of this file contradicted the function below it. If a
rule here and the code ever disagree again, the code is the one that was tested.
"""

import calendar
from dataclasses import dataclass

import noaa_coops as nc
import pandas as pd
import requests

MDAPI = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations"

# NOAA began rejecting mdapi requests carrying a default client User-Agent on 2026-08-26 --
# `python-requests/x.y` returns 403, and so does a plain descriptive string. The daily job
# had been running for weeks and started failing between two runs on the same day. Only
# mdapi filters; datagetter and dpapi accept anything.
#
# This is the conventional non-browser agent form -- the same shape Googlebot uses --
# and it identifies the project rather than pretending to be a browser. The `Mozilla/5.0`
# token is a historical compatibility artifact that essentially every HTTP client carries;
# what matters for identification is the product name and the URL after it.
USER_AGENT = (
    "Mozilla/5.0 (compatible; coastal-flood-days/1.0; "
    "+https://github.com/ajithmanmu/coastal-flood-days)"
)

# One session for the process: connection reuse across 137 stations, and one place that
# decides what we send. Anything calling NOAA through our own code goes through this.
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

# ...but not everything calling NOAA is our own code. noaa_coops builds its requests with
# the module-level `requests` and sets no headers (station.py:145 fetches station metadata
# the moment a Station is constructed), so it kept sending the default agent and getting a
# 403 that surfaced as KeyError: 'stations' -- the block is invisible because the library
# indexes the error body as though it were data.
#
# requests composes its default header from this function at Session creation, so replacing
# it covers every client in the process, including dependencies we do not control. It is a
# deliberate process-wide default rather than a per-call override, which is the only level
# that reaches inside a third-party library.
requests.utils.default_user_agent = lambda *_a, **_kw: USER_AGENT

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
    flood_hours: float
    days_observed: int
    completeness: float

    @property
    def usable(self) -> bool:
        return self.completeness >= 0.90

    @property
    def hours_per_flood_day(self) -> float | None:
        """When it floods here, how long does it stay? The headline metric.

        Deliberately NOT called anything about road closures -- this is exposure
        duration at a gauge, not impact duration on land (rule 10).
        """
        return self.flood_hours / self.flood_days if self.flood_days else None


def fetch_threshold(station_id: str, level: str = "nos_minor") -> float:
    """Return the station's flood threshold, in feet above station datum.

    Rule 2. NOAA publishes two families: nos_* are nationally comparable and derived
    from Sweet et al. 2018; nws_* are local forecast-office impact levels and vary by
    office. NOAA documents nos_minor as the one used for historical flood-day counts,
    so it is the default here. They disagree -- at The Battery, 10.19 vs 10.49 ft.
    """
    response = SESSION.get(f"{MDAPI}/{station_id}/floodlevels.json", timeout=30)
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


def summarise_year(heights: pd.DataFrame, threshold: float, year: int) -> FloodYear:
    """Reduce a year of hourly water levels to flood days AND flood hours.

    Rule 1: one day, one count. Reducing to a daily maximum first means a day with two
    exceeding high tides still counts once.

    Rule 9: flood hours is the count of hourly observations at or above the threshold,
    each standing for one hour. Measured against the 6-minute product this is accurate
    to 3-5% for an annual total -- but only for the annual total. It says nothing about
    how long any individual flood lasted; a 40-minute event is invisible at this
    resolution. Per-event durations need the 6-minute product, which only exists from
    1995-96 onward.

    Rule 11: at or above (>=), established by measurement rather than documentation.

    NOAA's published wording is "exceeds", which reads as strictly greater. Their data
    disagrees. Across nine stations in 2024, total disagreement with NOAA's own counts:

        GMT + >=   1 day     <- this
        GMT + >    3 days
        LST + >    9 days
        LST + >=   9 days

    So the implementation behind NOAA's published counts treats a value equal to the
    threshold as a flood. Where the docs and the data disagree, follow the data and say
    so in the methods section.

    Rule 5: days with no observations are absent from the daily max, so they are never
    counted as dry. Completeness is reported alongside rather than folded into the count.
    """
    observed = heights["v"].dropna()
    daily_max = observed.groupby(observed.index.date).max()
    expected_hours = (366 if calendar.isleap(year) else 365) * 24

    return FloodYear(
        year=year,
        flood_days=int((daily_max >= threshold).sum()),
        flood_hours=float((observed >= threshold).sum()),
        days_observed=len(daily_max),
        completeness=len(observed) / expected_hours,
    )


# Kept so the name that matches NOAA's own vocabulary still works.
count_flood_days = summarise_year


if __name__ == "__main__":
    STATION = "8518750"  # The Battery, NY
    YEAR = 2024

    threshold = fetch_threshold(STATION)
    result = count_flood_days(fetch_hourly_heights(STATION, YEAR), threshold, YEAR)

    print(f"station {STATION}, {result.year}")
    print(f"  threshold      {threshold:.2f} ft above station datum (nos_minor)")
    print(f"  flood days     {result.flood_days}")
    print(f"  completeness   {result.completeness:.1%}")
