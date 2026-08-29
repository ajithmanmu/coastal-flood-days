# Blog

Draft and assets for the dev.to post.

```
noaa-counts-days-i-counted-hours.md   the post
diagram-pipeline.{mmd,png}            how the data moves
diagram-basemap.{mmd,png}             the byte-range basemap
site-{chart,map,station}.png          screenshots of the live site
mermaid-theme.json                    dark theme matching the site
```

dev.to renders no Mermaid, so the diagrams ship as PNGs with their source beside
them. Regenerate after editing a `.mmd`:

```bash
npx @mermaid-js/mermaid-cli -i blog/diagram-pipeline.mmd -o blog/diagram-pipeline.png \
  -c blog/mermaid-theme.json -b "#0d0d0d" -w 1400 --scale 2
```

Screenshots are captured from the live site at a viewport sized to each panel, so
nothing is clipped mid-chart.
