"""Fetch and simplify India's national boundary as depicted on Indian maps.

Source: DataMeet (https://github.com/datameet/maps), an Indian civic-data
community whose India boundary follows the official depiction -- the full
extent of Jammu & Kashmir and Ladakh, including Aksai Chin and
Pakistan-administered Kashmir.

This matters because the OpenStreetMap-derived basemap draws those areas with
dashed "disputed" lines outside India, which is not the boundary recognised in
India.

The raw file is ~10 MB, far too heavy to ship to a browser on every load, so
it is simplified with Ramer-Douglas-Peucker before being written to
frontend/public/. The script validates the northern extent before writing:
the official depiction reaches roughly 37.1 N, whereas a truncated
international rendering stops near 35.5 N. If that check fails we refuse to
write the file rather than ship a boundary that is quietly wrong.

Run:  python scripts/fetch_india_boundary.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "india-boundary.geojson"

SOURCE = (
    "https://raw.githubusercontent.com/datameet/maps/master/"
    "Country/india-composite.geojson"
)

# The official depiction extends to ~37.1 N (Gilgit-Baltistan). Anything that
# stops short of this is the truncated international rendering.
MIN_EXPECTED_NORTH = 36.5
# Simplification tolerance in degrees. ~0.01 deg is roughly 1 km, invisible at
# the zoom levels this map uses.
TOLERANCE = 0.01


def rdp(points: list[list[float]], eps: float) -> list[list[float]]:
    """Ramer-Douglas-Peucker line simplification."""
    if len(points) < 3:
        return points

    def perp(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        px, py = x1 + t * dx, y1 + t * dy
        return ((x - px) ** 2 + (y - py) ** 2) ** 0.5

    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perp(points[i], points[0], points[-1])
        if d > dmax:
            dmax, idx = d, i

    if dmax <= eps:
        return [points[0], points[-1]]
    return rdp(points[: idx + 1], eps)[:-1] + rdp(points[idx:], eps)


def simplify_ring(ring: list, eps: float) -> list:
    pts = [[round(float(x), 4), round(float(y), 4)] for x, y in ring]
    out = rdp(pts, eps)
    # A ring must stay closed and needs at least 4 positions to be valid.
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else pts


def walk(geom: dict, eps: float) -> dict:
    t = geom["type"]
    if t == "Polygon":
        rings = [simplify_ring(r, eps) for r in geom["coordinates"]]
        return {"type": t, "coordinates": [r for r in rings if len(r) >= 4]}
    if t == "MultiPolygon":
        polys = []
        for poly in geom["coordinates"]:
            rings = [simplify_ring(r, eps) for r in poly]
            rings = [r for r in rings if len(r) >= 4]
            if rings:
                polys.append(rings)
        return {"type": t, "coordinates": polys}
    if t == "GeometryCollection":
        return {"type": t, "geometries": [walk(g, eps) for g in geom["geometries"]]}
    return geom


def bbox(geom: dict) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []

    def rec(c):
        if isinstance(c[0], (int, float)):
            xs.append(float(c[0]))
            ys.append(float(c[1]))
        else:
            for i in c:
                rec(i)

    if geom["type"] == "GeometryCollection":
        for g in geom["geometries"]:
            b = bbox(g)
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
    else:
        rec(geom["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    print("Fetching India boundary (DataMeet, official depiction)...")
    try:
        r = httpx.get(SOURCE, timeout=120.0, follow_redirects=True)
        r.raise_for_status()
        fc = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        print("  The map falls back to drawing no boundary, which is safe.")
        return 1

    raw_kb = len(r.content) / 1024
    feats = fc.get("features", [])
    print(f"  downloaded {raw_kb:,.0f} KB, {len(feats)} feature(s)")

    # --- validate before trusting it -------------------------------------
    minx, miny, maxx, maxy = bbox(feats[0]["geometry"])
    print(f"  bbox  lon {minx:.2f}..{maxx:.2f}   lat {miny:.2f}..{maxy:.2f}")
    if maxy < MIN_EXPECTED_NORTH:
        print(f"  REFUSING TO WRITE: northern extent {maxy:.2f} N is below "
              f"{MIN_EXPECTED_NORTH} N, so this looks like the truncated "
              f"international depiction, not the Indian one.")
        return 2
    print(f"  northern extent {maxy:.2f} N -- includes full J&K / Ladakh")

    # --- simplify ---------------------------------------------------------
    out = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "India",
                    "depiction": "Government of India official boundary",
                    "source": "DataMeet india-composite",
                },
                "geometry": walk(feats[0]["geometry"], TOLERANCE),
            }
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    new_kb = OUT.stat().st_size / 1024
    print(f"  simplified {raw_kb:,.0f} KB -> {new_kb:,.0f} KB "
          f"({100 * new_kb / raw_kb:.1f}%)")
    print(f"  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
