"""Count flood days for a single NOAA CO-OPS station.

Milestone one: one station, one year, one number.

Verified working against station 8518750 (The Battery, NY):

    import noaa_coops as nc
    s = nc.Station("8518750")
    s.datums                  # -> available datums for this station
    s.get_data(
        begin_date="20240101",
        end_date="20241231",
        product="hourly_height",
        datum="NAVD",         # API code; station lists it as NAVD88
        units="metric",
        time_zone="gmt",
    )                         # -> DataFrame indexed by 't', value in column 'v'

Rules that apply to what goes below (from the project note):

  1. Daily maximum, binary count. max(level) per calendar day >= threshold -> 1 day.
     Never count individual hourly exceedances.
  4. One timezone throughout. GMT or Local Standard Time, never local daylight time.
  5. Completeness filter. Drop or flag any year under ~90% valid hourly records.
     A gap is not a dry year.
  6. Fixed vertical reference. NAVD88 or STND, not a moving tidal datum.

Thresholds (rules 2, 3) are a separate fetch and are deliberately out of scope today.
Use a hardcoded placeholder to get the pipeline end to end, and label it as a
placeholder so it can't leak into a real number later.
"""


def fetch_hourly_heights(station_id: str, year: int):
    """Return a year of hourly water levels for one station."""
    raise NotImplementedError


def count_flood_days(heights, threshold: float) -> int:
    """Return the number of calendar days whose maximum level meets the threshold."""
    raise NotImplementedError
