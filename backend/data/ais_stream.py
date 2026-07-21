"""Vessel positions and behavioural anomalies near the chokepoints we model.

There is no AISSTREAM_API_KEY on this deployment, so there is no live AIS.
Rather than pretend otherwise, this module runs a *replay* feed: a fixed
snapshot of tanker positions around the June 2025 Hormuz escalation, stored at
`data_replay/june2025_ais_snapshots/vessels.json`, tagged REPLAY everywhere.

`vessel_snapshot()` will only ever return LIVE if `backend.config.AIS_ENABLED`
is true, i.e. a key exists AND a live stream was actually read. With no key the
payload says so in plain text and the UI colours it blue, not green.

Anomaly rules (all deterministic, all explainable in one sentence to a judge):

  dark_near_chokepoint  a tanker whose transponder has gone dark within 60 nm
                        of a modelled chokepoint
  loitering             speed over ground below 2.0 kn within 80 nm of a
                        chokepoint, i.e. stopped or drifting in a transit lane
  anchorage_cluster     4 or more effectively stationary tankers (< 1.0 kn)
                        within 25 nm of each other -- queueing rather than
                        transiting

Each anomaly carries a weight used by the Corridor Risk Index; the weights are
in ANOMALY_WEIGHTS below and are exposed in the payload.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.config import AIS_ENABLED, Provenance, REPLAY_DIR

SNAPSHOT_DIR = REPLAY_DIR / "june2025_ais_snapshots"
SNAPSHOT_PATH = SNAPSHOT_DIR / "vessels.json"

# Snapshot epoch: the middle of the June 2025 escalation, when dark-signalling
# and anchorage queueing near Hormuz were both elevated.
SNAPSHOT_EPOCH = datetime(2025, 6, 20, 12, 0, tzinfo=timezone.utc)

# chokepoint_id -> (lat, lon, corridor)
CHOKEPOINT_ANCHORS: dict[str, tuple[float, float, str]] = {
    "HORMUZ": (26.57, 56.25, "Hormuz"),
    "BAB": (12.58, 43.33, "RedSea_Suez"),
    "MALACCA": (2.50, 101.30, "Malacca"),
    "CAPE": (-34.36, 18.47, "Cape"),
}

ANOMALY_WEIGHTS: dict[str, float] = {
    "dark_near_chokepoint": 1.0,
    "loitering": 0.6,
    "anchorage_cluster": 0.8,
}

DARK_RADIUS_NM = 60.0
LOITER_RADIUS_NM = 80.0
LOITER_SPEED_KN = 2.0
CLUSTER_RADIUS_NM = 25.0
CLUSTER_SPEED_KN = 1.0
CLUSTER_MIN_VESSELS = 4

# Saturation anchor for the 0-100 AIS component: a weighted anomaly load of 6
# on one corridor is a fully stressed picture.
ANOMALY_SATURATION = 6.0


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_nm * math.asin(min(1.0, math.sqrt(a)))


def nearest_chokepoint(lat: float, lon: float) -> tuple[str, float, str]:
    best_id, best_d, best_corr = "", float("inf"), "none"
    for cid, (clat, clon, corridor) in CHOKEPOINT_ANCHORS.items():
        d = haversine_nm(lat, lon, clat, clon)
        if d < best_d:
            best_id, best_d, best_corr = cid, d, corridor
    return best_id, round(best_d, 1), best_corr


# --------------------------------------------------------------------------
# Replay snapshot generation
# --------------------------------------------------------------------------
_HULL_NAMES = [
    "Front Meridian", "Nissos Rhenia", "Maran Centaurus", "Delta Kanaris",
    "New Vision", "Olympic Trophy", "Nave Buena Suerte", "Sea Pearl",
    "Kriti Future", "Yasa Golden Sun", "Astro Perseus", "Minerva Vera",
    "Devon Star", "Aegean Sapphire", "Gulf Coral", "Silver Ray",
    "Desh Vaibhav", "Swarna Kamal", "Jag Lokesh", "Bahri Trader",
    "Kalamos Wave", "Hafnia Andromeda", "Pacific Sentinel", "Ocean Lily",
    "Ardmore Sealion", "Nordic Freedom", "Elandra Denali", "Trikwon Spirit",
    "Blue Marlin V", "Cap Diamant", "Selene Trader", "Grand Ace",
    "Karvouno Bay", "Everest Peak", "Torm Signe", "Marlin Aventurine",
    "Sakura Princess", "Baltic Sun", "Cape Cormorant", "Naxos Trader",
    "Serena Star", "Anafi Voyager",
]

_FLAG_MID = {
    "Liberia": "636", "Panama": "357", "Marshall Islands": "538",
    "Malta": "249", "Greece": "240", "Singapore": "565",
    "India": "419", "Bahamas": "311", "Cyprus": "212",
}

_VESSEL_CLASSES = ["VLCC", "Suezmax", "Aframax", "LR2"]

# (chokepoint, count, dark_probability, stopped_probability)
_REGION_PLAN = [
    ("HORMUZ", 16, 0.38, 0.30),
    ("BAB", 10, 0.25, 0.20),
    ("MALACCA", 10, 0.08, 0.15),
    ("CAPE", 5, 0.05, 0.05),
]


def build_snapshot() -> dict[str, Any]:
    """Deterministically construct the replay snapshot (seeded, reproducible)."""
    rng = random.Random(20250620)
    vessels: list[dict[str, Any]] = []
    name_i = 0

    for cid, count, p_dark, p_stopped in _REGION_PLAN:
        clat, clon, _corr = CHOKEPOINT_ANCHORS[cid]
        for k in range(count):
            # Most traffic sits within ~100 nm of the chokepoint; a handful of
            # queueing vessels sit tight against a nearby anchorage.
            if k < CLUSTER_MIN_VESSELS and cid in ("HORMUZ", "BAB"):
                # Anchorage cluster: Fujairah-style holding area.
                dlat = 0.35 + rng.uniform(-0.08, 0.08)
                dlon = 0.55 + rng.uniform(-0.08, 0.08)
                sog = round(rng.uniform(0.0, 0.8), 1)
            else:
                dlat = rng.uniform(-1.6, 1.6)
                dlon = rng.uniform(-1.9, 1.9)
                sog = (round(rng.uniform(0.0, 1.8), 1)
                       if rng.random() < p_stopped
                       else round(rng.uniform(7.5, 14.5), 1))

            name = _HULL_NAMES[name_i % len(_HULL_NAMES)]
            name_i += 1
            flag = rng.choice(list(_FLAG_MID))
            vessels.append({
                "mmsi": f"{_FLAG_MID[flag]}{rng.randint(100000, 999999)}",
                "name": name,
                "flag": flag,
                "vessel_class": rng.choice(_VESSEL_CLASSES),
                "lat": round(clat + dlat, 4),
                "lon": round(clon + dlon, 4),
                "sog": sog,
                "course": round(rng.uniform(0, 359), 1),
                "dark": rng.random() < p_dark,
                "last_seen": (
                    SNAPSHOT_EPOCH - timedelta(minutes=rng.randint(2, 900))
                ).isoformat(timespec="seconds"),
                "provenance": Provenance.REPLAY,
            })

    return {
        "snapshot_epoch": SNAPSHOT_EPOCH.isoformat(timespec="seconds"),
        "vessel_count": len(vessels),
        "disclosure": (
            "Reconstructed AIS replay snapshot for the June 2025 Hormuz "
            "escalation. Positions, names and MMSIs are plausible but "
            "synthetic; no live AIS feed is configured on this deployment. "
            "REPLAY only -- never to be presented as live."
        ),
        "vessels": vessels,
    }


def ensure_snapshot_file() -> None:
    """Write the replay snapshot if missing. Self-healing, idempotent."""
    if SNAPSHOT_PATH.exists():
        return
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(build_snapshot(), indent=1), encoding="utf-8"
    )


def load_snapshot() -> dict[str, Any]:
    ensure_snapshot_file()
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[ais] snapshot read failed: {type(exc).__name__}: {exc}")
        return build_snapshot()


# --------------------------------------------------------------------------
# Anomaly detection
# --------------------------------------------------------------------------
def detect_anomalies(vessels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the three rules. Pure function of the vessel list."""
    out: list[dict[str, Any]] = []

    for v in vessels:
        cid, dist, corridor = nearest_chokepoint(v["lat"], v["lon"])
        if v.get("dark") and dist <= DARK_RADIUS_NM:
            out.append({
                "kind": "dark_near_chokepoint",
                "weight": ANOMALY_WEIGHTS["dark_near_chokepoint"],
                "corridor": corridor,
                "chokepoint": cid,
                "distance_nm": dist,
                "vessels": [v["name"]],
                "mmsi": [v["mmsi"]],
                "detail": (f"{v['name']} ({v['vessel_class']}, {v['flag']}) went "
                           f"dark {dist} nm from {cid}"),
                "provenance": Provenance.REPLAY,
            })
        if v.get("sog", 99.0) < LOITER_SPEED_KN and dist <= LOITER_RADIUS_NM:
            out.append({
                "kind": "loitering",
                "weight": ANOMALY_WEIGHTS["loitering"],
                "corridor": corridor,
                "chokepoint": cid,
                "distance_nm": dist,
                "vessels": [v["name"]],
                "mmsi": [v["mmsi"]],
                "detail": (f"{v['name']} at {v['sog']} kn, {dist} nm from {cid} "
                           f"-- stopped or drifting in the approach"),
                "provenance": Provenance.REPLAY,
            })

    # Anchorage clustering: greedy grouping of effectively stationary vessels.
    stationary = [v for v in vessels if v.get("sog", 99.0) < CLUSTER_SPEED_KN]
    used: set[str] = set()
    for seed in stationary:
        if seed["mmsi"] in used:
            continue
        group = [
            v for v in stationary
            if v["mmsi"] not in used
            and haversine_nm(seed["lat"], seed["lon"], v["lat"], v["lon"])
            <= CLUSTER_RADIUS_NM
        ]
        if len(group) >= CLUSTER_MIN_VESSELS:
            used.update(v["mmsi"] for v in group)
            clat = sum(v["lat"] for v in group) / len(group)
            clon = sum(v["lon"] for v in group) / len(group)
            cid, dist, corridor = nearest_chokepoint(clat, clon)
            out.append({
                "kind": "anchorage_cluster",
                "weight": ANOMALY_WEIGHTS["anchorage_cluster"],
                "corridor": corridor,
                "chokepoint": cid,
                "distance_nm": dist,
                "vessels": [v["name"] for v in group],
                "mmsi": [v["mmsi"] for v in group],
                "detail": (f"{len(group)} tankers stationary within "
                           f"{CLUSTER_RADIUS_NM:.0f} nm, {dist} nm from {cid} "
                           f"-- queueing rather than transiting"),
                "provenance": Provenance.REPLAY,
            })

    out.sort(key=lambda a: (-a["weight"], a["corridor"]))
    return out


def anomaly_score_by_corridor(anomalies: list[dict[str, Any]]) -> dict[str, float]:
    """Weighted anomaly load per corridor, mapped to 0-100.

    score = 100 * min(1, sum(weight) / ANOMALY_SATURATION)
    """
    load: dict[str, float] = {}
    for a in anomalies:
        load[a["corridor"]] = load.get(a["corridor"], 0.0) + float(a["weight"])
    return {
        corridor: round(100.0 * min(1.0, total / ANOMALY_SATURATION), 2)
        for corridor, total in load.items()
    }


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
async def vessel_snapshot() -> dict[str, Any]:
    """Vessels + detected anomalies. REPLAY unless a live AIS key exists.

    Never raises.
    """
    snap = load_snapshot()
    vessels = snap.get("vessels", [])
    anomalies = detect_anomalies(vessels)

    if AIS_ENABLED:
        # A key exists, but this build has no live AISSTREAM reader wired in,
        # so we still serve replay and say so rather than upgrading the label.
        note = ("AISSTREAM_API_KEY is present but no live stream reader is "
                "wired into this build; still serving the replay snapshot.")
    else:
        note = ("No AISSTREAM_API_KEY configured, so live AIS is unavailable. "
                "Serving the June 2025 replay snapshot. "
                + str(snap.get("disclosure", "")))

    return {
        "available": True,
        "live_ais_configured": AIS_ENABLED,
        "snapshot_epoch": snap.get("snapshot_epoch"),
        "vessel_count": len(vessels),
        "vessels": vessels,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "anomaly_weights": ANOMALY_WEIGHTS,
        "scores_by_corridor": anomaly_score_by_corridor(anomalies),
        "rules": {
            "dark_near_chokepoint": f"dark transponder within {DARK_RADIUS_NM:.0f} nm of a chokepoint",
            "loitering": f"sog < {LOITER_SPEED_KN} kn within {LOITER_RADIUS_NM:.0f} nm of a chokepoint",
            "anchorage_cluster": f">= {CLUSTER_MIN_VESSELS} vessels under {CLUSTER_SPEED_KN} kn within {CLUSTER_RADIUS_NM:.0f} nm",
        },
        "source": str(SNAPSHOT_PATH.name),
        "note": note,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": Provenance.REPLAY,
    }
