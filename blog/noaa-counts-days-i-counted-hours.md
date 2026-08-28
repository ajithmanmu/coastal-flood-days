---
title: "NOAA Counts Flood Days. I Counted the Hours."
published: false
tags: aws, python, data, serverless
---

NOAA will tell you that Galveston Pier 21 flooded 26 days last year. It won't tell you that a flood there lasts about seven and a half hours, while the same "flood day" at Monterey means about one.

Both count as 1. That's the whole problem.

A flood day is a binary: did the water cross the local threshold at any point? A puddle that drains in forty minutes and water sitting over a road for most of a working day score identically. NOAA publishes those counts for 137 US tide gauges going back a century, and they're the numbers everyone cites. The duration isn't published anywhere as a dataset.

So I computed it. 137 gauges, 7,743 station-years, 59.5 million hourly readings, 1920 to today. The result is live at [floodhours.ajithmanmadhan.com](https://floodhours.ajithmanmadhan.com) and the Parquet file is there to download.

**Stack:** Python (pandas, requests), AWS Fargate for the one-time backfill, Lambda + EventBridge for the daily refresh, S3, CloudFront, Terraform, MapLibre GL, PMTiles.

## What The Data Says

Two findings, and the second one surprised me.

**Floods got much more frequent.** Of the 86 gauges with records long enough to compare their first decade against their most recent, 73 flood more often now. Galveston went from 0.7 flood days a year across 1920–1999 to 15.9 in the last ten.

**They didn't get longer.** Across the 41 longest records, the typical flood ran 1.95 hours in a gauge's first decade and 1.97 hours in its last. That's a century apart. Galveston's floods were 8.2 hours each back then and 7.5 hours now.

More floods. Same shape. How long a flood lasts turns out to be a property of place, not time: it's set by tidal regime and basin geometry, and it barely moves.

## The Two Rules That Decide Everything

Here's where it got interesting, and where I nearly shipped wrong numbers.

To count a flood day you need two definitions that sound trivial. What counts as a "day," and what counts as "crossing" the threshold. Both have an obvious answer. Both obvious answers are wrong.

**The day boundary.** Local time is the intuitive choice, since that's the day people lived through. I tested both against NOAA's own published counts for nine stations in 2024. Local time disagreed by 9 days. GMT disagreed by 1.

**The comparison.** NOAA's documentation says a flood day is one where the water *"exceeds"* the threshold. In English and in code that means strictly greater than. Their data says otherwise: `>=` matches their counts better, so whatever produces NOAA's published numbers treats water sitting exactly at the threshold as a flood.

They interact, so I had to test all four combinations:

| | Disagreement with NOAA |
|---|---|
| GMT + `>=` | **1 day** |
| GMT + `>` | 3 days |
| LST + `>` | 9 days |
| LST + `>=` | 9 days |

I spent longer than I'd like to admit getting there. My first attempt changed the operator on its own, and the error didn't move at all. I assumed the operator wasn't the problem. It was, but timezone was the dominant factor and was masking it completely. Only running the full matrix showed which mattered.

Where the docs and the data disagree, follow the data and say so in your methods section. Both choices are stated on the page rather than buried.

Final agreement across all 6,848 usable station-years: **95.75% exact, 99.61% within one day**, worst case 3 days off.

## The 137 GB File I Never Downloaded

The site needs a map. The default answer is Mapbox or Google: an API key, per-request billing, and your site breaking when theirs does.

I didn't want a runtime dependency on anyone else for a page that displays a static coastline. Coastlines don't move.

PMTiles solves this. It's a map chopped into thousands of small tiles, packed into one file, with an index at the front saying where each tile starts and how long it is. Protomaps publishes a daily build of the entire planet that way. It's 137 GB.

You never download it. You read the index over the network, work out which tiles you want, and ask for those byte ranges:

```bash
pmtiles extract https://build.protomaps.com/20260820.pmtiles \
  web/basemap/protomaps-20260820.pmtiles \
  --region=basemap/region.geojson --maxzoom=10
```

`region.geojson` is eight rectangles: one around the mainland US, seven around Hawaii, Puerto Rico, Guam, Wake, Kwajalein, Midway and Samoa. Everything else gets skipped.

**382 MB out of 137 GB. Eighty HTTP requests. Thirty-five seconds.**

The browser then does the same trick against my copy in S3:

```
Range: bytes=40112880-40169999
→ HTTP/2 206 Partial Content
```

That's plain HTTP, the same mechanism that resumes a paused download. S3 and CloudFront both support it with no configuration. So a reader never downloads 382 MB; they pull a few kilobytes for whatever is on screen.

If you've worked with GRIB2 weather files you've seen this before: the `.idx` sidecar does exactly this, and Kerchunk generalises it. One immutable blob in object storage plus an index, and byte ranges turn it into something you query instead of something you download.

Storage cost for the basemap: about a cent a month.

## The Feature I Built And Deleted

The map plots 137 dots. A reviewer looked at it and said, reasonably, that dots don't show you where the problem is.

So I shaded the coastline itself, colouring each stretch by its nearest gauge. It looked good. The Gulf lit up as a continuous pale band running into orange down Florida's Atlantic side.

Then he zoomed into Puerto Rico. Two gauges, and the whole island's coast was coloured from them. He asked whether that meant the shoreline flooded at that level, or only that spot.

Only that spot. Everything else was inference wearing the same colours as measurement — which is the exact objection I'd raised against his original idea of shaded polygons, and I'd gone and committed it on a line instead of an area.

The honest move was to test how far the inference actually holds. Comparing every pair of gauges:

| Gap between gauges | Pairs differing by >50% |
|---|---|
| 0–25 km | 10% |
| 25–50 km | 14% |
| 50–100 km | **35%** |
| 100–200 km | 37% |

Flood duration is spatially coherent to about 50 km and not much past it. My shading radius was 120 km, which meant roughly a third of the coloured coast carried a value the nearest real gauge would have contradicted by more than half.

I deleted the feature. The map is dots, and the legend now says so directly: *nothing here is interpolated between them.*

The measurement was worth more than the feature. It's a real result about the data, and it's the reason the honest map is points.

## Gotchas

**NOAA started blocking us mid-project.** On a Wednesday the daily job ran fine at 10:04 UTC and every request failed by 13:45. NOAA had begun rejecting default client User-Agents on their metadata endpoint. Nothing in my code had changed.

It hid in two disguises. My own call raised a clean 403. But `noaa_coops`, the library I use for water levels, raised `KeyError: 'stations'` — it builds requests with the bare `requests` module, sets no headers, then indexes the error body as though it were data. An HTTP block surfaced as a missing dictionary key. Fixing my own call left the library still broken, which cost me a second rebuild.

Neither the block nor the disguise is documented anywhere obvious.

**Retrying made the failure mode worse.** I added backoff, which is right, and immediately created a new problem: 137 stations each burning three attempts against a dead endpoint overran the Lambda's ceiling and died as a timeout instead of a clean failure. It now stops after 8 consecutive failures, because one shared upstream problem doesn't need proving 137 times.

**The guard that mattered.** Through both broken runs the published dataset was never touched. `daily.py` refuses to publish if too few stations refreshed, so a failed run leaves yesterday's data live rather than replacing 137 stations with nothing. That check was written months earlier for exactly this and it earned its place in an afternoon.

## What The Pipeline Looks Like

Two jobs, not one.

The backfill walks a century once, on Fargate, and caches every station-year as Parquet in S3. It has a kill switch in SSM and caps on requests, hours and consecutive failures. Fetching a century from someone else's free API is the kind of thing you want to be able to stop instantly.

The daily job refetches the current year for every station. Not yesterday, the whole year, because NOAA revises recent readings for weeks and a trailing window is a guess about how far back to look. `hourly_height` returns up to a year per request, so a whole year costs the same single call as one day. The guess disappears.

Everything downstream recomputes from the cache. A change to a counting rule costs nothing at NOAA.

```
raw/station=8518750/year=2024.parquet    14,659 files, 744 MB, private
results/flood_days.parquet               the dataset, 51 KB, public
```

Two-thirds of the bucket is the raw archive, and it's the only part that isn't public. Which brings me to the bug I'm least proud of.

## The Security Bug Every Test Passed

The bucket policy granted CloudFront `s3:GetObject` on `/*`. Direct S3 access was correctly denied. Every check I ran came back green.

The 744 MB raw archive was publicly downloadable through the CDN by anyone who guessed a key.

I found it by testing the negative case instead of the positive one. The policy now enumerates exactly the paths the page needs, and every deploy asserts it:

```
raw/ -> 403
```

If that ever returns 200, the build fails. The only assertion that would have caught the original bug is the one about what *isn't* reachable.

## What I'd Tell You To Take From This

- **Test the negative case.** "Is the site up" passes whether or not your private data is exposed. Assert what should be unreachable, on every deploy.
- **Where the docs and the data disagree, follow the data.** NOAA says "exceeds"; NOAA's numbers say `>=`. Test it, pick the one that matches, and state the choice in your methods.
- **Change one variable at a time, or run the whole matrix.** I changed the operator alone, saw no improvement, and drew the wrong conclusion because a second variable was masking it.
- **Byte ranges turn big files into queries.** A 137 GB archive you can read 16 bytes out of is a different kind of object than a 137 GB file you have to download. Same trick as `.idx` and Kerchunk.
- **If a pattern only appears after interpolating, it isn't evidence.** Points, not surfaces. Measure how far your inference holds before you draw it.
- **Guard the publish step, not just the fetch.** Two runs failed completely and the live dataset never wobbled, because the job refuses to publish a mostly-empty refresh.

## Is It Worth Building?

For the dataset, yes. Duration made comparable across thousands of station-years didn't exist in queryable form, and now it does. The science isn't new — the metric is standard and the geographic pattern is published — but the artifact wasn't there.

For the engineering, the parts I'd reuse tomorrow are the byte-range basemap and the refuse-to-publish guard. Both are small, both solved a real problem, and neither took long.

The part I'd skip is the ribbon. I built it because the map looked sparse, not because the data supported it, and it took a reviewer asking the same question three times before I stopped explaining and started measuring.

Code, methods and the full dataset: [github.com/ajithmanmu/coastal-flood-days](https://github.com/ajithmanmu/coastal-flood-days)

*Ajith builds data infrastructure for large-scale scientific and geospatial data.*
