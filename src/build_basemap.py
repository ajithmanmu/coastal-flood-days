"""Build a small, self-contained CONUS outline for the map page.

The page cannot reach a tile server -- it is hosted as static files and must also work
where external requests are blocked. So the basemap ships as coordinates the page
projects itself, using the same projection as the station dots.

Source is the US Census cartographic boundary file for states, via a widely mirrored
GeoJSON copy. Census boundary data is public domain.

    .venv/bin/python src/build_basemap.py
"""

import json
import urllib.request
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json"
OUT = Path(__file__).resolve().parents[1] / "web" / "us-states.json"

# Drawn as a recessive backdrop behind the dots, so detail below roughly a pixel is
# wasted bytes. Tuned by eye against the rendered map, not guessed.
TOLERANCE = 0.06
DECIMALS = 2

# Not in CONUS. Hawaii's stations are real but sit 40 degrees west; drawing them in the
# same frame would shrink the mainland to a smear. They get their own treatment.
SKIP = {"Alaska", "Hawaii", "Puerto Rico"}


def perpendicular_distance(point, start, end):
    (x, y), (x1, y1), (x2, y2) = point, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def simplify(points, tolerance):
    """Ramer-Douglas-Peucker. Iterative, because state outlines are deep enough to
    blow a recursive implementation's stack."""
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        worst_distance, worst_index = 0.0, None
        for i in range(first + 1, last):
            d = perpendicular_distance(points[i], points[first], points[last])
            if d > worst_distance:
                worst_distance, worst_index = d, i
        if worst_index is not None and worst_distance > tolerance:
            keep[worst_index] = True
            stack.extend([(first, worst_index), (worst_index, last)])

    return [p for p, k in zip(points, keep) if k]


def rings_of(geometry):
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    return [ring for polygon in geometry["coordinates"] for ring in polygon]


def main() -> None:
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        source = json.load(response)

    shapes, kept_points, source_points = [], 0, 0
    for feature in source["features"]:
        name = feature["properties"].get("name", "")
        if name in SKIP:
            continue
        for ring in rings_of(feature["geometry"]):
            source_points += len(ring)
            simplified = simplify([(round(x, 4), round(y, 4)) for x, y in ring], TOLERANCE)
            # A ring reduced to a sliver is noise, not coastline.
            if len(simplified) < 4:
                continue
            kept_points += len(simplified)
            shapes.append([[round(x, DECIMALS), round(y, DECIMALS)] for x, y in simplified])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"rings": shapes}, separators=(",", ":")))

    print(f"rings   : {len(shapes)}")
    print(f"points  : {source_points} -> {kept_points} ({kept_points / source_points:.0%})")
    print(f"written : {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
