"""OFAC SDN list -> a maritime sanctions-pressure signal.

We care about one slice of the SDN list: designations that touch shipping.
A wave of tanker designations moves freight, insurance and shadow-fleet
behaviour on specific corridors well before it moves the flat price, which is
exactly the kind of early signal the Corridor Risk Index is built to catch.

Honesty contract:

* A successful download this session is LIVE.
* Anything served from `data_replay/ofac_cache.json` is REPLAY.
* If the list is unreachable and no cache exists, `available` is false and the
  CRI drops the sanctions component and renormalises its weights rather than
  scoring a zero it cannot justify.

This module never raises. The SDN export is ~5-6 MB of headerless CSV; we parse
it defensively because OFAC has changed the column layout before.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.config import Provenance, REPLAY_DIR

SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
CACHE_PATH = REPLAY_DIR / "ofac_cache.json"

_TIMEOUT_S = 10.0

# Columns of the SDN export (headerless, positional).
_COL_ENT, _COL_NAME, _COL_TYPE, _COL_PROGRAM = 0, 1, 2, 3
_COL_VESS_TYPE, _COL_VESS_FLAG, _COL_REMARKS = 6, 9, 11

_SHIPPING_RE = re.compile(
    r"\bvessel\b|\btanker\b|\bshipping\b|\bmaritime\b|\bvlcc\b|\bimo\s*\d|"
    r"\bship management\b|\bshipmanagement\b|\bcrude oil\b.{0,20}\bcarrier\b|"
    r"\bfleet\b|\bmarine\b",
    re.I,
)

# Programmes whose maritime designations bear on the corridors we model.
_PROGRAMS_OF_INTEREST = ("IRAN", "IFSR", "SDGT", "NPWMD", "RUSSIA", "UKRAINE",
                         "VENEZUELA", "SYRIA", "HOUTHI")

# Saturation anchors for the 0-100 score. Stated here so they can be argued
# with: 400 in-scope maritime designations, or 40 new ones since the last
# snapshot, each saturate their half of the signal.
_LEVEL_ANCHOR = 400.0
_DELTA_ANCHOR = 40.0


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _count(text: str) -> dict[str, Any]:
    total = vessels = shipping = in_scope = 0
    flags: dict[str, int] = {}
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 4:
            continue
        total += 1
        sdn_type = (row[_COL_TYPE] or "").strip().lower()
        program = (row[_COL_PROGRAM] or "").strip().upper()
        vess_type = (row[_COL_VESS_TYPE] or "").strip() if len(row) > _COL_VESS_TYPE else ""
        remarks = (row[_COL_REMARKS] or "") if len(row) > _COL_REMARKS else ""
        flag = (row[_COL_VESS_FLAG] or "").strip() if len(row) > _COL_VESS_FLAG else ""

        is_vessel = sdn_type == "vessel"
        is_shipping = bool(
            is_vessel
            or (vess_type and vess_type != "-0-")
            or _SHIPPING_RE.search(remarks or "")
        )
        if is_vessel:
            vessels += 1
            if flag and flag != "-0-":
                flags[flag] = flags.get(flag, 0) + 1
        if is_shipping:
            shipping += 1
            if any(p in program for p in _PROGRAMS_OF_INTEREST):
                in_scope += 1

    return {
        "total_entries": total,
        "vessel_entries": vessels,
        "shipping_linked_entries": shipping,
        "in_scope_maritime_entries": in_scope,
        "top_vessel_flags": dict(sorted(flags.items(), key=lambda kv: -kv[1])[:8]),
    }


# --------------------------------------------------------------------------
# Cache I/O
# --------------------------------------------------------------------------
def _read_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[sanctions] cache read failed: {type(exc).__name__}: {exc}")
        return None


def _write_cache(counts: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    history = list((previous or {}).get("history", []))[-11:]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    history.append({"fetched_at": stamp,
                    "vessel_entries": counts["vessel_entries"],
                    "in_scope_maritime_entries": counts["in_scope_maritime_entries"]})
    doc = {**counts, "fetched_at": stamp, "source": SDN_URL, "history": history}
    try:
        REPLAY_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[sanctions] cache write failed: {type(exc).__name__}: {exc}")
    return doc


def _delta(doc: dict[str, Any]) -> dict[str, int]:
    hist = doc.get("history") or []
    if len(hist) < 2:
        return {"vessel_entries": 0, "in_scope_maritime_entries": 0}
    prev, last = hist[-2], hist[-1]
    return {
        "vessel_entries": int(last.get("vessel_entries", 0))
                          - int(prev.get("vessel_entries", 0)),
        "in_scope_maritime_entries": int(last.get("in_scope_maritime_entries", 0))
                                     - int(prev.get("in_scope_maritime_entries", 0)),
    }


def _score(doc: dict[str, Any], delta: dict[str, int]) -> float:
    """0-100 maritime sanctions pressure.

    score = 100 * clip( 0.6 * in_scope/400  +  0.4 * |delta_in_scope|/40 )

    Level captures how much of the shadow fleet is already designated; delta
    captures whether Treasury is actively moving right now.
    """
    level = min(1.0, float(doc.get("in_scope_maritime_entries", 0)) / _LEVEL_ANCHOR)
    activity = min(1.0, abs(delta.get("in_scope_maritime_entries", 0)) / _DELTA_ANCHOR)
    return round(100.0 * max(0.0, min(1.0, 0.6 * level + 0.4 * activity)), 2)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _blocking_fetch() -> str:
    with httpx.Client(timeout=_TIMEOUT_S, follow_redirects=True) as client:
        r = client.get(SDN_URL)
        r.raise_for_status()
        if len(r.content) < 100_000:
            raise RuntimeError(f"SDN export suspiciously small: {len(r.content)} bytes")
        return r.text


async def sdn_delta() -> dict[str, Any]:
    """Maritime slice of the OFAC SDN list, plus its change since last snapshot.

    Never raises. Returns `available: False` with an explicit note when the
    feed is unreachable and no cache exists.
    """
    previous = _read_cache()
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_blocking_fetch), timeout=_TIMEOUT_S + 5.0
        )
        counts = await asyncio.to_thread(_count, text)
        doc = _write_cache(counts, previous)
        delta = _delta(doc)
        return {
            "available": True,
            **counts,
            "delta": delta,
            "score": _score(doc, delta),
            "as_of": doc["fetched_at"],
            "source": "ofac-sdn-csv",
            "note": "Downloaded from the OFAC SDN export this session. Delta is "
                    "measured against the previously cached snapshot.",
            "provenance": Provenance.LIVE,
        }
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        reason = f"{type(exc).__name__}: {exc}"[:160]
        print(f"[sanctions] SDN fetch failed, falling back to cache: {reason}")

    if previous:
        delta = _delta(previous)
        return {
            "available": True,
            **{k: v for k, v in previous.items() if k not in ("history", "source")},
            "delta": delta,
            "score": _score(previous, delta),
            "as_of": previous.get("fetched_at"),
            "source": CACHE_PATH.name,
            "note": f"OFAC feed unavailable ({reason}); replaying the last cached "
                    f"snapshot. Counts are as of {previous.get('fetched_at')}, "
                    f"not today.",
            "provenance": Provenance.REPLAY,
        }

    return {
        "available": False,
        "total_entries": 0,
        "vessel_entries": 0,
        "shipping_linked_entries": 0,
        "in_scope_maritime_entries": 0,
        "top_vessel_flags": {},
        "delta": {"vessel_entries": 0, "in_scope_maritime_entries": 0},
        "score": 0.0,
        "as_of": None,
        "source": "none",
        "note": f"OFAC SDN list unreachable ({reason}) and no cached snapshot "
                f"exists. The sanctions component is dropped from the CRI and "
                f"its weight redistributed, rather than scored as zero risk.",
        "provenance": Provenance.REPLAY,
    }
