# Coastal Flood Days

**How many hours a year is the US coast actually underwater?**

NOAA publishes how many *days* each coastal station floods. A puddle that drains in forty
minutes and water sitting over a road for six hours both count as one day. This project
measures the hours.

**Status:** early — the method is validated, the dataset isn't built yet.

> ⚠️ **Numbers produced by the current code are not valid.** The threshold is a
> placeholder, not NOAA's published per-station value. Don't cite anything from this yet.

## Why it exists

NOAA computes inundation duration in their [Inundation Analysis Tool](https://tidesandcurrents.noaa.gov/inundationanalysis/)
and in a [public notebook](https://github.com/NOAA-CO-OPS/Coastal_Hazards_Example_Notebooks) —
but one station at a time, capped at 10 years of 6-minute data, emitting images rather
than data. Nobody publishes the result as a dataset.

This is that dataset, plus the pipeline that produces it.

**It is not new science.** The metric is standard in the literature and the geographic
pattern is already published. The contribution is a reproducible, validated, bulk
station-year record that didn't previously exist in queryable form.

## Early result

Nine stations, 2024, computed from raw hourly observations:

| station | flood days | hours underwater | hrs/day |
|---|---|---|---|
| Grand Isle, LA | 16 | 75 | 4.7 |
| Sewells Point, VA | 20 | 66 | 3.3 |
| Honolulu, HI | 23 | 43 | 1.9 |
| The Battery, NY | 26 | 45 | 1.7 |
| Boston, MA | 25 | 38 | 1.5 |

Boston floods 56% more often than Grand Isle and spends half as long submerged.

## Validation

Flood-day counts are computed independently and checked against NOAA's published
`htf_annual` counts. Currently exact at 3 of 9 stations and within 1–3 days elsewhere;
closing that gap is the next milestone.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tests/test_count_flood_days.py
```

## Methods

*To be written — a deliverable, not an afterthought. Will document the counting rules,
the datum handling, the event definition, and what is and isn't claimed.*

Two things it will say up front:

- These are **exposure durations** — hours the water was above a station threshold. Not
  road-closure times. A gauge measures one point in the water, not the street.
- Tide gauges systematically undercount street flooding
  ([Nature Comms, 2025](https://www.nature.com/articles/s43247-025-02326-w)).

## Data sources

All NOAA CO-OPS, all public, no key required.

| | |
|---|---|
| water levels | `api.tidesandcurrents.noaa.gov/api/prod/datagetter` |
| flood thresholds | `.../mdapi/prod/webapi/stations/{id}/floodlevels.json` |
| NOAA's own counts | `.../dpapi/prod/webapi/htf/htf_annual.json` |
