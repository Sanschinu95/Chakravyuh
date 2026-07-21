"""GDELT DOC 2.0 news feed, with a June-2025 replay archive behind it.

GDELT's public API is frequently rate-limited, slow, or blocked outright from
corporate/lab networks, so this module is written fetch-first / replay-always:

* A successful DOC 2.0 call this session is LIVE.
* Everything served from `data_replay/june2025_gdelt.jsonl` is REPLAY. It is
  never relabelled, not even partially.

About the replay corpus -- read this before quoting it anywhere. It is a
*reconstruction* of the June 2025 US/Israel-Iran escalation news flow, built
for deterministic replay of the Strait of Hormuz storyline. The dates and the
sequence of events track the real crisis; the individual headline strings are
paraphrases written for this archive, not verbatim wire copy. For that reason
every record carries `corpus: "reconstructed"`, sources are generic channel
labels rather than named outlets, and URLs use a `replay://` scheme so nothing
can be mistaken for a live citation.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from backend.config import Provenance, REPLAY_DIR

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
REPLAY_PATH = REPLAY_DIR / "june2025_gdelt.jsonl"

_TIMEOUT_S = 6.0

REPLAY_WINDOW = (date(2025, 6, 1), date(2025, 6, 30))

CORPUS_DISCLOSURE = (
    "Reconstructed archival corpus of the June 2025 Hormuz escalation. "
    "Event sequence and dates track the real crisis; headline text is "
    "paraphrase written for replay, not verbatim wire copy. REPLAY only."
)


# --------------------------------------------------------------------------
# The replay corpus. (day, title, channel, tone)
# --------------------------------------------------------------------------
# Tone follows the GDELT convention: negative = negative coverage, roughly
# bounded at +/- 20. Escalation drives tone down and volume up.
_CORPUS: list[tuple[str, str, str, float]] = [
    # -- background: talks alive, risk premium dormant --------------------
    ("2025-06-01", "Fifth round of US-Iran nuclear talks ends in Muscat without a text", "wire-agency", -2.4),
    ("2025-06-01", "Gulf tanker rates soften as June loading programme completes", "shipping-press", 1.2),
    ("2025-06-02", "Tehran signals it will reject any deal that bars domestic enrichment", "wire-agency", -3.6),
    ("2025-06-02", "Asian refiners book incremental Basrah barrels for July arrival", "energy-trade-press", 0.8),
    ("2025-06-03", "Omani mediators say gaps on enrichment remain wide", "regional-daily", -3.1),
    ("2025-06-04", "IAEA inspectors report undeclared material questions unresolved at two sites", "official-statement", -4.7),
    ("2025-06-04", "War risk premium for Gulf transits unchanged at 0.06 percent of hull value", "shipping-press", -1.1),
    ("2025-06-05", "US carrier strike group extends deployment in the Arabian Sea", "wire-agency", -3.9),
    ("2025-06-06", "Iranian officials warn of a response to any censure at the IAEA board", "regional-daily", -5.2),
    ("2025-06-06", "Brent holds a narrow range as physical differentials stay soft", "energy-trade-press", 0.4),

    # -- build-up: censure motion, drawdowns, explicit threats ------------
    ("2025-06-07", "European powers circulate draft resolution finding Iran in non-compliance", "official-statement", -5.6),
    ("2025-06-07", "Shipowners association reviews Gulf routing guidance for members", "shipping-press", -3.2),
    ("2025-06-08", "Iran says it will unveil a third enrichment site if censured", "wire-agency", -6.4),
    ("2025-06-08", "Insurers quietly widen the Gulf breach-of-warranty quote range", "shipping-press", -3.8),
    ("2025-06-09", "IAEA board opens session with the non-compliance motion on the agenda", "official-statement", -5.1),
    ("2025-06-09", "Freight indications for VLCCs on Gulf-West Coast India firm sharply", "energy-trade-press", -2.6),
    ("2025-06-10", "Washington authorises voluntary departure of dependants from regional posts", "wire-agency", -6.9),
    ("2025-06-10", "Iranian defence ministry says all regional US bases are within range", "regional-daily", -7.8),
    ("2025-06-10", "Tanker owners begin declining Gulf fixtures for prompt loading", "shipping-press", -5.3),
    ("2025-06-11", "US embassy in Baghdad ordered to reduce staffing", "wire-agency", -7.4),
    ("2025-06-11", "Two VLCCs reported waiting outside Hormuz rather than transiting", "shipping-press", -6.1),
    ("2025-06-11", "Brent front-month settles higher as the geopolitical bid returns", "energy-trade-press", -3.4),
    ("2025-06-12", "IAEA board formally finds Iran in breach of safeguards obligations", "official-statement", -7.1),
    ("2025-06-12", "Iran announces a new enrichment facility in response to the censure", "wire-agency", -7.6),
    ("2025-06-12", "Regional airlines begin rerouting away from Iranian airspace", "regional-daily", -6.8),
    ("2025-06-12", "Gulf war risk quotes double week on week, brokers report", "shipping-press", -6.6),

    # -- 13 June: the strike, and the price gap ---------------------------
    ("2025-06-13", "Israel strikes Iranian nuclear and missile sites in overnight operation", "wire-agency", -11.4),
    ("2025-06-13", "Iran vows severe retaliation as air defences engage over Tehran", "regional-daily", -10.8),
    ("2025-06-13", "Brent gaps up at the open on the largest one-day move in three years", "energy-trade-press", -7.2),
    ("2025-06-13", "Hormuz transit advisories issued to merchant shipping", "shipping-press", -9.1),
    ("2025-06-13", "Gulf states close airspace intermittently through the morning", "official-statement", -8.4),

    # -- retaliation cycle and shipping disruption ------------------------
    ("2025-06-14", "Iranian missile and drone salvoes target Israeli cities", "wire-agency", -11.1),
    ("2025-06-14", "Electronic interference degrades AIS and GPS across the Gulf", "shipping-press", -8.7),
    ("2025-06-15", "Two tankers collide near Hormuz amid navigation signal disruption", "shipping-press", -9.4),
    ("2025-06-15", "Charterers invoke war clauses on Gulf voyages", "energy-trade-press", -7.3),
    ("2025-06-16", "Iranian parliament debates authorising closure of the Strait of Hormuz", "regional-daily", -10.2),
    ("2025-06-16", "Indian refiners say crude cover is adequate for several weeks", "official-statement", -2.8),
    ("2025-06-17", "War risk premium for Gulf transits rises roughly tenfold from May", "shipping-press", -8.9),
    ("2025-06-17", "Strikes continue on Iranian energy infrastructure including a gas plant", "wire-agency", -10.6),
    ("2025-06-18", "Tanker owners suspend new Gulf fixtures pending clarity", "shipping-press", -8.1),
    ("2025-06-18", "Freight on Gulf-India voyages more than doubles in a week", "energy-trade-press", -6.4),
    ("2025-06-19", "Brent extends gains as traders price a tail risk of closure", "energy-trade-press", -6.9),
    ("2025-06-19", "Several VLCCs turn away from the strait mid-voyage", "shipping-press", -8.6),
    ("2025-06-20", "Diplomatic contacts in Geneva end without a pause in hostilities", "wire-agency", -7.9),
    ("2025-06-20", "Number of tankers signalling dark near Hormuz rises sharply", "shipping-press", -8.2),
    ("2025-06-21", "Gulf producers reroute volumes to Red Sea and pipeline outlets", "energy-trade-press", -5.7),
    ("2025-06-21", "Anchorage congestion builds off Fujairah as transits slow", "shipping-press", -7.4),

    # -- 22-23 June: US strikes, Al Udeid, the closure vote ---------------
    ("2025-06-22", "United States strikes three Iranian nuclear facilities", "wire-agency", -12.1),
    ("2025-06-22", "Shipping industry warns of a step change in Gulf transit risk", "shipping-press", -9.8),
    ("2025-06-23", "Iran fires missiles at a US air base in Qatar", "wire-agency", -11.6),
    ("2025-06-23", "Iranian parliament votes to back closing the Strait of Hormuz", "regional-daily", -11.9),
    ("2025-06-23", "Qatar closes airspace temporarily as interceptors engage", "official-statement", -9.2),
    ("2025-06-23", "Brent spikes intraday then fades as no tanker is hit", "energy-trade-press", -5.4),

    # -- 24 June onwards: ceasefire and unwind ----------------------------
    ("2025-06-24", "Ceasefire announced between Israel and Iran", "wire-agency", 2.6),
    ("2025-06-24", "Brent falls sharply as the closure premium unwinds", "energy-trade-press", 1.9),
    ("2025-06-24", "Hormuz transits resume at near-normal counts", "shipping-press", 2.2),
    ("2025-06-25", "Ceasefire holds through a second day despite mutual accusations", "wire-agency", 0.9),
    ("2025-06-25", "War risk quotes begin easing from the peak", "shipping-press", 1.4),
    ("2025-06-26", "IAEA seeks access to assess damage at struck facilities", "official-statement", -3.2),
    ("2025-06-26", "Gulf freight retraces about half of the June spike", "energy-trade-press", 1.1),
    ("2025-06-27", "Iran suspends cooperation with IAEA inspectors", "wire-agency", -6.3),
    ("2025-06-28", "Dark-signalling tanker count near Hormuz returns to the May baseline", "shipping-press", 1.6),
    ("2025-06-29", "Indian refiners resume normal Gulf lifting programmes", "official-statement", 2.1),
    ("2025-06-29", "Brent settles the month roughly where it started", "energy-trade-press", 0.7),
    ("2025-06-30", "Talks on resuming negotiations reported to be under discussion", "wire-agency", -1.4),
    ("2025-06-30", "Shipowners keep enhanced Gulf watchkeeping in place", "shipping-press", -2.7),
]


def build_replay_corpus() -> list[dict[str, Any]]:
    """Materialise the corpus as records. Deterministic -- no randomness."""
    return [
        {
            "date": d,
            "title": title,
            "source": channel,
            "url": f"replay://chakravyuh/june2025_gdelt/{i:03d}",
            "tone": tone,
            "corpus": "reconstructed",
            "provenance": Provenance.REPLAY,
        }
        for i, (d, title, channel, tone) in enumerate(_CORPUS)
    ]


def ensure_replay_file() -> None:
    """Write the replay JSONL if it is missing. Self-healing, idempotent."""
    if REPLAY_PATH.exists():
        return
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    with REPLAY_PATH.open("w", encoding="utf-8") as fh:
        for rec in build_replay_corpus():
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_replay(start: str | None = None,
                end: str | None = None) -> list[dict[str, Any]]:
    """Replay records, optionally bounded by inclusive ISO date strings."""
    ensure_replay_file()
    out: list[dict[str, Any]] = []
    try:
        with REPLAY_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if start and rec["date"] < start:
                    continue
                if end and rec["date"] > end:
                    continue
                out.append(rec)
    except Exception as exc:  # noqa: BLE001
        print(f"[gdelt] replay read failed: {type(exc).__name__}: {exc}")
        out = [r for r in build_replay_corpus()
               if (not start or r["date"] >= start) and (not end or r["date"] <= end)]
    out.sort(key=lambda r: r["date"])
    return out


# --------------------------------------------------------------------------
# Live fetch
# --------------------------------------------------------------------------
def _normalise_live(raw: dict[str, Any]) -> list[dict[str, Any]]:
    arts = raw.get("articles") or []
    out: list[dict[str, Any]] = []
    for a in arts:
        stamp = str(a.get("seendate") or "")
        iso = f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 else ""
        out.append({
            "date": iso,
            "title": (a.get("title") or "").strip(),
            "source": a.get("domain") or "unknown",
            "url": a.get("url") or "",
            # DOC 2.0 artlist does not return tone; absent means absent.
            "tone": None,
            "corpus": "live",
            "provenance": Provenance.LIVE,
        })
    return [r for r in out if r["title"]]


async def fetch_events(query: str = "Strait of Hormuz",
                       days: int = 7,
                       max_records: int = 75) -> dict[str, Any]:
    """Try GDELT DOC 2.0; fall back to the June 2025 replay archive.

    Never raises. The returned `provenance` is the single source of truth for
    which path was taken -- callers must not assume LIVE.
    """
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max_records),
        "timespan": f"{max(1, int(days))}d",
        "sort": "datedesc",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            r = await client.get(GDELT_URL, params=params)
            r.raise_for_status()
            events = _normalise_live(r.json())
        if not events:
            raise RuntimeError("GDELT returned no usable articles")
        return {
            "query": query,
            "days": days,
            "count": len(events),
            "events": events,
            "source": "gdelt-doc-2.0",
            "note": "Fetched from the GDELT DOC 2.0 API this session.",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provenance": Provenance.LIVE,
        }
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        reason = f"{type(exc).__name__}: {exc}"[:160]
        print(f"[gdelt] live fetch failed, replaying archive: {reason}")

    end = REPLAY_WINDOW[1]
    start = max(REPLAY_WINDOW[0], end - timedelta(days=max(1, int(days)) - 1))
    events = load_replay(start.isoformat(), end.isoformat())
    return {
        "query": query,
        "days": days,
        "count": len(events),
        "events": events,
        "source": REPLAY_PATH.name,
        "note": f"GDELT unavailable ({reason}). Replaying the June 2025 "
                f"archive instead. {CORPUS_DISCLOSURE}",
        "replay_window": [start.isoformat(), end.isoformat()],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": Provenance.REPLAY,
    }
