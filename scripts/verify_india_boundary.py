"""Point-in-polygon check that the shipped outline uses the Indian depiction.

The test that matters is not "did a file download" but "does the polygon
actually contain the territory the OSM basemap places outside India". These
probe points sit in Aksai Chin, Gilgit-Baltistan and the Kashmir valley --
inside India on an Indian map, outside it on an international one.
"""
import json
from pathlib import Path

P = Path(r"C:\Users\ASUS\Desktop\Projects\Energy Engine\frontend\public\india-boundary.geojson")
fc = json.loads(P.read_text(encoding="utf-8"))
geom = fc["features"][0]["geometry"]

polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]


def in_ring(pt, ring):
    x, y = pt
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def contains(pt):
    for poly in polys:
        if not poly:
            continue
        if in_ring(pt, poly[0]) and not any(in_ring(pt, h) for h in poly[1:]):
            return True
    return False


PROBES = [
    ("Aksai Chin (China-administered)",      (79.10, 35.10), True),
    ("Gilgit-Baltistan (Pak-administered)",  (75.00, 35.90), True),
    ("Muzaffarabad, PoK",                    (73.47, 34.36), True),
    ("Srinagar, Kashmir valley",             (74.80, 34.08), True),
    ("Leh, Ladakh",                          (77.58, 34.15), True),
    ("New Delhi",                            (77.21, 28.61), True),
    ("Jamnagar refinery",                    (70.05, 22.35), True),
    # Controls: these must be OUTSIDE
    ("Lahore, Pakistan",                     (74.34, 31.55), False),
    ("Kathmandu, Nepal",                     (85.32, 27.71), False),
    ("Colombo, Sri Lanka",                   (79.86,  6.93), False),
]

print(f"{'location':<38} {'expect':>7} {'actual':>7}   result")
fails = 0
for name, pt, expect in PROBES:
    got = contains(pt)
    ok = got == expect
    fails += 0 if ok else 1
    print(f"{name:<38} {'IN' if expect else 'OUT':>7} {'IN' if got else 'OUT':>7}   "
          f"{'ok' if ok else 'FAIL'}")

size_kb = P.stat().st_size / 1024
print(f"\nfile {size_kb:.0f} KB, {len(polys)} polygon(s)")
print("PASS - shipped outline uses the Indian depiction" if not fails
      else f"{fails} FAILURES - do not ship this file")
raise SystemExit(1 if fails else 0)
