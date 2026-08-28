# Architecture

Mermaid source for the project's diagrams. These render on GitHub and in Obsidian.

**dev.to does not render Mermaid** — its editor supports dozens of embeds and KaTeX, but no
diagram syntax. The two diagrams used in the blog post are therefore checked in as PNGs
alongside their `.mmd` source:

    blog/diagram-pipeline.png   +  diagram-pipeline.mmd
    blog/diagram-basemap.png    +  diagram-basemap.mmd

Regenerate with:

```bash
npx @mermaid-js/mermaid-cli -i blog/diagram-pipeline.mmd -o blog/diagram-pipeline.png \
  -c blog/mermaid-theme.json -b "#0d0d0d" -w 1400 --scale 2
```

## The whole system

```mermaid
flowchart TB
    subgraph noaa["NOAA CO-OPS"]
        api["Water levels · thresholds<br/>published flood-day counts"]
    end

    subgraph once["Runs once"]
        backfill["backfill.py<br/><i>Fargate</i><br/>a century, 137 stations"]
    end

    subgraph daily["Runs daily · 10:00 UTC"]
        refresh["daily.py<br/><i>Lambda</i><br/>refetch the current year"]
    end

    subgraph s3["S3 · one bucket"]
        raw[("raw/<br/>14,659 Parquet files · 744 MB<br/><b>private</b>")]
        results[("results/<br/>769 KB<br/>public")]
        basemap[("basemap/<br/>382 MB PMTiles<br/>public")]
    end

    agg["aggregate.py<br/>count · summarise · publish"]
    cf["CloudFront"]
    page["floodhours.ajithmanmadhan.com<br/>one HTML file"]

    api -->|"one-time walk"| backfill
    api -->|"current year, every morning"| refresh
    backfill --> raw
    refresh --> raw
    raw --> agg
    agg --> results
    results --> cf
    basemap -->|"HTTP range requests"| cf
    cf --> page

    style raw fill:#8c2d04,color:#fff
    style results fill:#f16913,color:#fff
    style basemap fill:#f16913,color:#fff
    style page fill:#1a1a19,color:#fff
```

**The split that matters:** the century is fetched once and kept. Everything after that
recomputes from the cache, so a change to a counting rule costs nothing at NOAA.

## What one station-year costs

```mermaid
sequenceDiagram
    participant J as daily.py
    participant N as NOAA
    participant S as S3

    J->>N: threshold for station 8518750
    N-->>J: 10.19 ft above station datum
    J->>N: hourly_height, whole year, STND/english/GMT
    N-->>J: 8,761 readings
    Note over J: daily max ≥ 10.19 → flood days<br/>readings ≥ 10.19 → flood hours
    J->>S: write raw/station=8518750/year=2026.parquet
    J->>S: rewrite results/
```

Two calls per station. A whole year costs the same single request as one day, which is why
the job refetches the year rather than guessing how far back NOAA's revisions reach.

## The basemap, and why it is one file

```mermaid
flowchart LR
    planet[("Protomaps planet<br/>137 GB")]
    region["basemap/region.geojson<br/>8 rectangles"]
    extract["pmtiles extract"]
    ours[("our copy<br/>382 MB")]
    browser["browser"]

    region --> extract
    planet -->|"80 range requests<br/>35 seconds"| extract
    extract --> ours
    ours -->|"Range: bytes=40112880-40169999<br/>206 Partial Content"| browser

    style planet fill:#2c2c2a,color:#fff
    style ours fill:#f16913,color:#fff
```

The planet file is never downloaded — not when cutting our copy, and not by any reader. Both
steps read an index and ask for byte ranges.

## Publishing

```mermaid
flowchart LR
    push["git push to main"]
    gh["GitHub Actions"]
    sts["AWS STS"]
    s3["S3"]
    check{"raw/ → 403 ?"}

    push --> gh
    gh -->|"OIDC token, no stored keys"| sts
    sts -->|"temporary credentials<br/>index.html + vendor/ only"| gh
    gh --> s3
    s3 --> check
    check -->|"yes"| done["deployed"]
    check -->|"no"| fail["fail the build"]

    style fail fill:#8c2d04,color:#fff
    style done fill:#f16913,color:#fff
```

The deploy role can write the page and its assets and nothing else. It cannot touch
`results/`, which belongs to the daily Lambda, and it cannot read `raw/` at all.

Every deploy asserts the negative case: the raw archive must return 403. A wildcard in the
bucket policy once made all 744 MB publicly downloadable while every positive test still
passed.
