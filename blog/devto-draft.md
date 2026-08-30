---
title: "NOAA Counts Flood Days. I Counted the Hours."
published: false
tags: aws, python, data, serverless
---

**What this is:** a dataset and a site measuring how long US coastal floods last, not just how often they happen. 137 NOAA tide gauges, every year since 1920, computed from 59.5 million raw hourly readings. Live at [floodhours.ajithmanmadhan.com](https://floodhours.ajithmanmadhan.com).

---

Boston and Galveston flood about the same number of days a year. Thirteen and sixteen.

Their flood days are nothing alike. A flood in Boston lasts about ninety minutes. A flood in Galveston lasts about seven and a half hours.

The published counts score them the same.

A flood day is a binary: did the water cross the local threshold at any point? Water that drains inside an hour and water sitting over a road for most of a working day come out identical. NOAA has kept those counts for 137 US tide gauges for a century.

The hours behind those counts aren't published anywhere. NOAA has a [tool](https://tidesandcurrents.noaa.gov/inundationanalysis/) that works them out for one station over a limited date range, but nobody had run it across every gauge and put the answers in a single file.

So I computed it, from the raw readings rather than from anyone's published counts. The result is one row per station per year — 7,743 of them — carrying flood days, flood hours, and how long a typical flood lasted there.

**Stack:** Python (pandas, requests), AWS Fargate for the one-time backfill, Lambda + EventBridge for the daily refresh, S3, CloudFront, Terraform, MapLibre GL, PMTiles.

## What The Data Says

**Floods got much more frequent.** Of the 86 gauges with records long enough to compare their first decade against their most recent, 73 flood more often now. Galveston went from 0.7 flood days a year across 1920–1999 to 15.9 in the last ten.

**They didn't get longer.** Across the 41 longest records, the typical flood ran 1.95 hours in a gauge's first decade and 1.97 hours in its last. That's a century apart. Galveston's floods were 8.2 hours each back then and 7.5 hours now.

More floods. Same shape. I expected the second number to climb with the first and it doesn't move at all. How long a flood lasts is set by tidal regime and basin geometry, which is a fact about the place rather than about the year.

## What The Pipeline Looks Like

NOAA holds a century of hourly water levels and I need all of them. I'd rather ask once.

The first job downloads everything: 137 stations, every year back to 1920, saved into S3 as one Parquet file per station-year. It ran once on Fargate and hasn't needed to run since. It reads a flag in SSM between stations, so a long run can be stopped without killing the container mid-write.

The second job runs every morning on Lambda and downloads the current year again for all 137 stations. NOAA revises recent readings for weeks after publishing them, so fetching only the last few days means guessing how far back the corrections reach. A whole year costs one API call, the same as a single day, so it fetches the year.

Counting is a separate step that reads those saved files rather than calling NOAA. So changing how a flood day is defined means recounting 59.5 million readings locally, with no requests to their servers at all.

The saved readings stay private in S3 and only the counted results are public. Every deploy checks that, by requesting a raw file through the CDN and failing the build if it returns anything but a 403.

<!-- IMAGE 1: upload blog/diagram-pipeline.png here, then replace the line below -->
![The pipeline: one backfill, one daily refresh, and counting that never calls NOAA](IMAGE_1_diagram-pipeline.png)

## Checking The Count Against NOAA

I'm counting flood days from raw readings, and NOAA already publishes its own count for the same stations and years. If my numbers match theirs, the flood *hours* I'm adding are probably right too. If they don't, nothing else in this post is worth reading.

First, the line itself. Every station has its own flood threshold, published by NOAA. The Battery's is 10.19 feet, measured from that station's own zero mark on the pier rather than from sea level. The water levels have to be requested against the same mark, or you're comparing two different starting points and you're off by about six feet.

With that right, my counts still didn't match. Two reasons:

- **Day boundaries.** I used local time. NOAA uses GMT. Switching cut my disagreement from 9 days to 1.
- **The comparison.** NOAA's docs say the water must *"exceed"* the threshold, which reads as `>`. Their numbers behave as `>=` — water sitting exactly on the line counts as a flood.

I found the second one late. I'd changed the operator on its own first, seen no improvement, and moved on. The timezone was wrong at the same time and hid the effect. Testing all four combinations together was what showed it.

One more rule before the numbers mean anything: a year missing more than 10% of its readings gets dropped rather than counted, because a gauge that was offline for two months looks calm and isn't. That removes 895 of 7,743 station-years.

Across the remaining 6,848 my counts match NOAA's exactly **95.75%** of the time, and within one day **99.61%**.

## The 137 GB File I Never Downloaded

The site needs a map. The usual answer is Mapbox or Google, which means an API key, a bill that grows with traffic, and one more service that has to be up for your page to work.

None of that felt right for a page showing a coastline. Coastlines don't move.

PMTiles is the alternative. A map gets chopped into thousands of small tiles, and all of them are packed into a single file with an index at the front recording where each tile sits and how long it is. Protomaps publishes the entire planet in that format every day. It's 137 GB.

You never download it. You read the index over the network, work out which tiles you want, and ask for those byte ranges:

```bash
pmtiles extract https://build.protomaps.com/20260820.pmtiles \
  web/basemap/protomaps-20260820.pmtiles \
  --region=basemap/region.geojson --maxzoom=10
```

`region.geojson` is eight rectangles: one around the mainland US, seven around Hawaii, Puerto Rico, Guam, Wake, Kwajalein, Midway and Samoa. Everything outside them is skipped.

**382 MB out of 137 GB. Eighty HTTP requests. Thirty-five seconds.**

That runs once. The result is a smaller file in the same format, with its own index, and I upload it to S3 as a single object.

Which means the browser can do exactly what the extract did, one level down. It reads the index off the front of my file, works out which tiles are on screen, and asks for those bytes:

```
Range: bytes=40112880-40169999
→ 206 Partial Content
```

A client asks for a byte range, S3 streams back that slice and answers `206 Partial Content` instead of `200`. It's a standard HTTP feature and neither S3 nor CloudFront needs anything switched on for it. Nobody downloads 382 MB; they pull a few kilobytes for whatever is on screen.

Strip out the maps and what's left is a general trick: one large file that doesn't change, an index saying what's inside it, and byte ranges that turn it into something you query instead of something you download.

Weather data does this already. A GRIB2 file holds hundreds of forecast layers, and a small `.idx` file beside it lists where each layer starts, so you can pull the one you need without reading the rest. Kerchunk extends the idea to scientific archives, building an index over files that were never designed to be read that way.

<!-- IMAGE 2: upload blog/diagram-basemap.png here, then replace the line below -->
![Cutting 382 MB out of a 137 GB file with byte-range requests, then serving it the same way](IMAGE_2_diagram-basemap.png)

Storage cost for the basemap: about a cent a month.

## What The Site Shows

<!-- IMAGE 3: upload blog/site-chart.png here, then replace the line below -->
![The slope chart: every long-record station, first ten years against most recent](IMAGE_3_site-chart.png)

Each line is a station: left end its first ten years of record, right end its most recent. 73 rise, 13 stay flat. It's the same 73-of-86 figure from the cards, in a form you can check by looking.

<!-- IMAGE 4: upload blog/site-map.png here, then replace the line below -->
![The map and the frequency-versus-duration scatter](IMAGE_4_site-map.png)

The map is where, and the scatter is how the two numbers relate: across is how often a station floods, up is total hours a year. High and left means rare but long. Low and right means often but brief.

<!-- IMAGE 5: upload blog/site-station.png here, then replace the line below -->
![One station's full record, flood days above and flood hours below](IMAGE_5_site-station.png)

Clicking any station opens its century underneath. Galveston is a good one to look at — both panels have the same shape, which is what "more floods, same length" looks like when you draw it.

There is no API and no database. The daily job precomputes everything into static files, so the site is one HTML page reading JSON from the same bucket. Nothing runs at request time.

## The Day NOAA Started Blocking Me

The daily job ran fine at 10:04 one Wednesday and every request failed by 13:45. NOAA had started rejecting requests that don't identify themselves, and mine didn't. Nothing in my code had changed.

The library I use for water levels hit the same block, but read the error page as data and raised `KeyError: 'stations'`, so the 403 showed up as a missing dictionary key.

The fix was a one-line User-Agent. I also added a short pause between stations, three retries with backoff, and a stop after 8 consecutive failures, so a dead endpoint fails in seconds rather than grinding through all 137 stations.

The published data never moved through any of this. The job refuses to publish when too few stations refresh, so both failed runs left yesterday's numbers live instead of overwriting 137 stations with nothing. That check was the one piece of the pipeline I'd recommend to anyone building something similar.

## What I'd Keep

The dataset was worth making. None of the science is new — the metric is standard and the geographic pattern is already published. What was missing was the numbers themselves, for every station and every year, in one file anyone can download.

Two pieces of the build I'd use again. The basemap read by byte range, because it removed a paid service and a runtime dependency for the cost of one file in S3. And the check that stops the daily job publishing when too few stations come back, which is what kept the site correct while NOAA was blocking me.

Code, methods and the full dataset: [github.com/ajithmanmu/coastal-flood-days](https://github.com/ajithmanmu/coastal-flood-days)

*Ajith builds data infrastructure for large-scale scientific and geospatial data.*
