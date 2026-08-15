# Coastal Flood Days

Count how many days a year each NOAA coastal water-level station floods, and show the
multi-decade trend per station.

**Status:** early. Milestone one — pull one station, one year, produce one number.

> ⚠️ **The numbers this currently produces are not valid.** The flood threshold is a
> placeholder (station MHHW plus a flat 0.55 m), not NOAA's published per-station
> threshold. Real thresholds come next. Don't cite anything from this yet.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Layout

```
src/flood_days.py    fetch water levels, count flood days
data/                local scratch output (gitignored)
```

## Methods

*To be written — this section is a deliverable, not an afterthought. It documents the
eight methodology rules the counting logic encodes, and states explicitly what is and
isn't claimed.*

## Data source

NOAA CO-OPS — <https://api.tidesandcurrents.noaa.gov/api/prod/>

Water levels via the `hourly_height` product (1-year max per request; `noaa_coops`
chunks automatically). Flood thresholds are separate and are not in this product.
