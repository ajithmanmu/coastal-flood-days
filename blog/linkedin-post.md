# LinkedIn draft

Post Tuesday or Wednesday, ~8am ET. Put the link in the first comment rather than the
post body — LinkedIn throttles reach on posts with outbound links. Pin that comment.

---

Boston and Galveston flood about the same number of days a year.

A flood in Boston lasts about 90 minutes. A flood in Galveston lasts about seven and a half hours.

NOAA's published counts score both as one flood day.

That gap bothered me enough to go and measure it. I pulled a century of hourly water levels from NOAA's tide gauges, worked out how long the water actually sits above each station's flood threshold, and put the whole thing online as a dataset anyone can download.

137 gauges. 7,743 station-years. 59.5 million hourly readings, back to 1920.

Two things came out of it:

Floods got far more frequent. At 73 of the 86 gauges with long enough records, they happen more often now than when the station opened. Galveston went from under one flood day a year in the mid-century to sixteen.

They did not get longer. The typical flood ran 1.95 hours in a gauge's first decade and 1.97 hours in its most recent. A century apart, essentially unchanged.

More floods, same shape. How long a flood lasts turns out to be a property of the place rather than the year.

The part I'd defend hardest is the boring part: my flood-day counts agree with NOAA's own published numbers 95.75% exactly, 99.61% within a single day. Getting there meant finding two places where their documentation and their data disagree, and following the data.

Full write-up, methods and the dataset in the comments.

---

## Shorter variant, if the above runs long on mobile

Boston and Galveston flood about the same number of days a year.

A flood in Boston lasts 90 minutes. In Galveston, seven and a half hours. NOAA counts both as one flood day.

So I measured the difference: a century of hourly readings from 137 NOAA tide gauges, 59.5 million of them, turned into a dataset of how long coastal floods actually last.

Floods have got far more frequent — more often now at 73 of 86 long-record gauges. They have not got longer: 1.95 hours in a gauge's first decade, 1.97 in its most recent.

More floods, same shape.

The counts agree with NOAA's own published figures 95.75% exactly, which took finding two places where their docs and their data disagree.

Write-up and dataset in the comments.

---

## First comment

Write-up: https://dev.to/aws-builders/noaa-counts-flood-days-i-counted-the-hours-5017
Live site and dataset: https://floodhours.ajithmanmadhan.com
Code and methods: https://github.com/ajithmanmu/coastal-flood-days
