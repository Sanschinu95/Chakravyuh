"""Backtest: replay June 2025 and ask whether the CRI would have led the price.

The claim this module exists to test, and to be able to fail: *the Corridor
Risk Index crosses its alert threshold before Brent gaps.* We replay the
US/Israel-Iran escalation day by day, recompute the index from only the
information available up to that day, and measure two things.

1. **Lead time.** Hours between the first day the Hormuz CRI closes at or above
   `CRI_ALERT_THRESHOLD` and the first day Brent posts a single-day rise of
   `SPIKE_PCT` or more. If the index never crosses, we say so and report a null
   lead time. We do not move the threshold to manufacture a crossing.

2. **Brier score** on the daily alert probabilities, against the binary outcome
   "Brent closes at least SPIKE_PCT above today's close at some point in the
   next 72 hours". Brier is reported alongside the climatological reference
   (always predicting the period's base rate) and the resulting skill score,
   because a raw Brier with no reference is not interpretable.

Signal availability during the backtest is deliberately narrow and is stated in
the payload: we replay **news and Brent only**. There is no historical AIS
archive and no historical OFAC snapshot for June 2025 on this deployment, so
those two components are marked unavailable and the CRI renormalises its
weights over the two we can honestly reconstruct (news 0.583, market 0.417).
Using today's AIS snapshot as a stand-in for June 2025 would be lookahead and a
lie about provenance.

Data: `data_replay/june2025_gdelt.jsonl` (reconstructed news archive) and
`data_replay/june2025_brent.csv` (reconstructed daily closes tracking the real
June 2025 path, including the ~8% single-day gap on 13 June). Both are REPLAY.
"""

from __future__ import annotations

import csv
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.config import CRI_ALERT_THRESHOLD, Provenance, REPLAY_DIR
from backend.data import gdelt, market
from backend.intelligence import cri as cri_mod
from backend.intelligence.extractor import extract_events

BRENT_PATH = REPLAY_DIR / "june2025_brent.csv"

WINDOW_START = date(2025, 6, 1)
WINDOW_END = date(2025, 6, 30)

SPIKE_PCT = 5.0          # what counts as a price spike
OUTCOME_HORIZON_DAYS = 3  # "within the next 72 hours"

# Maps a CRI score to an alert probability. Centred on the alert threshold so
# p = 0.5 exactly at the threshold; the slope means +8 CRI points roughly
# doubles the odds.
PROB_SLOPE = 8.0


def brier_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Brier score plus its climatological reference and the skill score.

    A bare Brier is not interpretable, so we always report what a forecaster
    who simply predicted the period's base rate every day would have scored,
    and the resulting skill score (1 = perfect, 0 = no better than the base
    rate, negative = worse than the base rate).
    """
    n = len(rows)
    if not n:
        return {"brier": 0.0, "reference": 0.0, "skill": None,
                "base_rate": 0.0, "n": 0}
    brier = sum((r["alert_prob"] - r["outcome_72h"]) ** 2 for r in rows) / n
    base = sum(r["outcome_72h"] for r in rows) / n
    ref = sum((base - r["outcome_72h"]) ** 2 for r in rows) / n
    return {
        "brier": round(brier, 4),
        "reference": round(ref, 4),
        "skill": (round(1.0 - brier / ref, 4) if ref > 0 else None),
        "base_rate": round(base, 4),
        "n": n,
    }


def _interpretation(full: dict[str, Any], onset: dict[str, Any],
                    spike_day: str | None) -> str:
    """Say plainly what the two Brier numbers mean, including the bad news."""
    parts = [
        f"Full window ({full['n']} scored days): Brier {full['brier']} against a "
        f"base-rate reference of {full['reference']}, skill {full['skill']}."
    ]
    if full["skill"] is not None and full["skill"] < 0:
        parts.append(
            "That is worse than a forecaster who predicted the base rate every "
            "day. The reason is structural and worth stating rather than "
            "hiding: the CRI is a measure of the *level* of corridor risk, not "
            "of the hazard of a further price gap. After the 13 June gap the "
            "index correctly stays red -- corridor risk really was extreme -- "
            "but no second single-session gap follows, so every one of those "
            "high-confidence days scores as a false alarm under this outcome "
            "definition."
        )
    if onset.get("n"):
        parts.append(
            f"Onset sub-window (through {spike_day}, {onset['n']} days): Brier "
            f"{onset['brier']} against {onset['reference']}, skill "
            f"{onset['skill']}. The forecasting value is concentrated in "
            f"detecting the onset, which is what the lead-time figure measures. "
            f"Both windows are reported; the full window is the headline number."
        )
    return " ".join(parts)


def alert_probability(score: float) -> float:
    """p(spike within 72h) implied by a CRI score: logistic, centred on the
    alert threshold. p = 1 / (1 + exp(-(score - threshold) / 8))."""
    z = (float(score) - CRI_ALERT_THRESHOLD) / PROB_SLOPE
    z = max(-40.0, min(40.0, z))
    return round(1.0 / (1.0 + math.exp(-z)), 4)


# --------------------------------------------------------------------------
# Replay price series
# --------------------------------------------------------------------------
# Reconstructed daily settlement path. May is included so the volatility and
# trailing-mean windows are already populated on 1 June rather than warming up
# inside the test period. Dates are trading days; the walk carries the last
# close forward across weekends.
_JUNE2025_BRENT: list[tuple[str, float]] = [
    ("2025-05-01", 61.1), ("2025-05-02", 61.3), ("2025-05-05", 60.2),
    ("2025-05-06", 62.2), ("2025-05-07", 61.1), ("2025-05-08", 62.8),
    ("2025-05-09", 63.9), ("2025-05-12", 64.9), ("2025-05-13", 66.6),
    ("2025-05-14", 66.1), ("2025-05-15", 64.5), ("2025-05-16", 65.4),
    ("2025-05-19", 65.5), ("2025-05-20", 65.4), ("2025-05-21", 64.9),
    ("2025-05-22", 64.4), ("2025-05-23", 64.8), ("2025-05-27", 64.1),
    ("2025-05-28", 64.9), ("2025-05-29", 64.2), ("2025-05-30", 63.9),
    ("2025-06-02", 64.6), ("2025-06-03", 65.6), ("2025-06-04", 64.9),
    ("2025-06-05", 65.3), ("2025-06-06", 66.5), ("2025-06-09", 66.9),
    ("2025-06-10", 66.8), ("2025-06-11", 69.8), ("2025-06-12", 69.4),
    ("2025-06-13", 74.9), ("2025-06-16", 73.2), ("2025-06-17", 76.4),
    ("2025-06-18", 76.7), ("2025-06-19", 78.9), ("2025-06-20", 77.0),
    ("2025-06-23", 71.5), ("2025-06-24", 67.1), ("2025-06-25", 67.7),
    ("2025-06-26", 67.7), ("2025-06-27", 67.8), ("2025-06-30", 66.7),
]

BRENT_DISCLOSURE = (
    "Reconstructed daily Brent settlement path for May-June 2025. It tracks "
    "the shape of the real market -- a quiet May, a build through 10-12 June "
    "and a ~8% single-session gap on 13 June -- but the individual closes are "
    "a reconstruction for replay, not an exchange settlement record. REPLAY."
)


def ensure_brent_file() -> None:
    """Write the replay price file if missing. Self-healing, idempotent."""
    if BRENT_PATH.exists():
        return
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    with BRENT_PATH.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "close", "provenance", "note"])
        for d, c in _JUNE2025_BRENT:
            w.writerow([d, f"{c:.2f}", Provenance.REPLAY, "reconstructed"])


def load_brent() -> list[tuple[str, float]]:
    ensure_brent_file()
    try:
        rows: list[tuple[str, float]] = []
        with BRENT_PATH.open("r", encoding="utf-8", newline="") as fh:
            for rec in csv.DictReader(fh):
                rows.append((rec["date"], float(rec["close"])))
        if len(rows) >= 20:
            return sorted(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[backtest] brent replay read failed: {type(exc).__name__}: {exc}")
    return list(_JUNE2025_BRENT)


def _daily_closes(rows: list[tuple[str, float]]) -> dict[str, float]:
    """Calendar-day close map, carrying the last settle across non-trading days."""
    if not rows:
        return {}
    out: dict[str, float] = {}
    first = date.fromisoformat(rows[0][0])
    last = date.fromisoformat(rows[-1][0])
    table = dict(rows)
    cur, carry = first, rows[0][1]
    while cur <= last:
        iso = cur.isoformat()
        carry = table.get(iso, carry)
        out[iso] = carry
        cur += timedelta(days=1)
    return out


# --------------------------------------------------------------------------
# The walk
# --------------------------------------------------------------------------
async def run_backtest(start: date = WINDOW_START,
                       end: date = WINDOW_END) -> dict[str, Any]:
    """Walk the archive day by day. Never raises; deterministic."""
    rows = load_brent()
    closes = _daily_closes(rows)
    trading = {d: c for d, c in rows}

    # Every article in the archive, extracted once, deterministically.
    all_events = await extract_events(gdelt.load_replay(), use_llm=False)

    # -- spike detection (single-session gap) -----------------------------
    spike_day: str | None = None
    spike_pct = 0.0
    trading_days = sorted(trading)
    for prev, cur in zip(trading_days, trading_days[1:]):
        if not (start.isoformat() <= cur <= end.isoformat()):
            continue
        ret = 100.0 * (trading[cur] - trading[prev]) / trading[prev]
        if ret >= SPIKE_PCT and spike_day is None:
            spike_day, spike_pct = cur, round(ret, 2)

    # -- outcome: does the close rise SPIKE_PCT within the next 72h? ------
    def outcome(day: str) -> int | None:
        base = closes.get(day)
        if base is None:
            return None
        d0 = date.fromisoformat(day)
        fwd = [closes.get((d0 + timedelta(days=k)).isoformat())
               for k in range(1, OUTCOME_HORIZON_DAYS + 1)]
        if any(v is None for v in fwd):
            return None  # window runs past the archive; excluded from Brier
        return int(max(v for v in fwd if v is not None) >= base * (1 + SPIKE_PCT / 100.0))

    series: list[dict[str, Any]] = []
    cur = start
    while cur <= end:
        iso = cur.isoformat()
        hist = [(d, c) for d, c in rows if d <= iso]
        hist_closes = [c for _, c in hist]

        snapshot = {
            "available": len(hist_closes) >= 5,
            "realized_vol_30d_pct": market.realized_vol_pct(hist_closes, 30),
            "spread_vs_90d_mean_pct": market.spread_vs_mean_pct(hist_closes, 90),
        }
        stress = market.market_stress(snapshot)

        visible = [e for e in all_events if str(e.get("date") or "") <= iso]
        scored = cri_mod.score_corridors(
            events=visible,
            anomaly_scores=None,        # no June 2025 AIS archive -> excluded
            sanctions_score=None,       # no June 2025 OFAC snapshot -> excluded
            market_score=stress["score"] if stress["available"] else None,
            as_of=iso,
            include_suppliers=False,
        )
        hormuz = next(c for c in scored if c["corridor"] == "Hormuz")
        p = alert_probability(hormuz["score"])
        y = outcome(iso)

        prev_iso = (cur - timedelta(days=1)).isoformat()
        prev_close = closes.get(prev_iso)
        close = closes.get(iso)
        ret = (round(100.0 * (close - prev_close) / prev_close, 2)
               if close and prev_close else None)

        series.append({
            "date": iso,
            "cri_hormuz": hormuz["score"],
            "band": hormuz["band"],
            "alert": hormuz["alert"],
            "alert_prob": p,
            "outcome_72h": y,
            "brent_close": close,
            "brent_return_pct": ret,
            "is_trading_day": iso in trading,
            "news_events_to_date": len(visible),
            "news_events_today": sum(1 for e in visible if e.get("date") == iso),
            "components": {c["signal"]: c["sub_score"] for c in hormuz["components"]},
            "provenance": Provenance.REPLAY,
        })
        cur += timedelta(days=1)

    # -- lead time --------------------------------------------------------
    alert_row = next((r for r in series if r["alert"]), None)
    alert_day = alert_row["date"] if alert_row else None

    if alert_day and spike_day:
        delta_days = (date.fromisoformat(spike_day)
                      - date.fromisoformat(alert_day)).days
        lead_time_hours = float(delta_days * 24)
        lead_note = (
            f"CRI(Hormuz) first closed at or above {CRI_ALERT_THRESHOLD} on "
            f"{alert_day} at {alert_row['cri_hormuz']}. Brent posted its first "
            f"{SPIKE_PCT}%+ single-session move on {spike_day} ({spike_pct}%). "
            f"Lead time {lead_time_hours:.0f} h."
        ) if lead_time_hours > 0 else (
            f"CRI crossed on {alert_day}, on or after the price spike on "
            f"{spike_day}. Negative or zero lead time -- the index did not "
            f"lead the market in this replay."
        )
    else:
        lead_time_hours = None
        lead_note = (
            f"No alert: CRI(Hormuz) never reached {CRI_ALERT_THRESHOLD} in the "
            f"replay window (peak "
            f"{max((r['cri_hormuz'] for r in series), default=0.0)})."
            if not alert_day else
            f"CRI alerted on {alert_day} but no {SPIKE_PCT}%+ single-session "
            f"move occurred in the window, so lead time is undefined."
        )

    # -- Brier ------------------------------------------------------------
    scored_rows = [r for r in series if r["outcome_72h"] is not None]
    full = brier_stats(scored_rows)
    # Sub-period, reported alongside the full window and never instead of it:
    # everything up to and including the spike, i.e. the onset the system is
    # actually built to catch.
    onset_rows = ([r for r in scored_rows if r["date"] <= spike_day]
                  if spike_day else [])
    onset = brier_stats(onset_rows)
    brier, brier_ref = full["brier"], full["reference"]
    base_rate, skill, n = full["base_rate"], full["skill"], full["n"]

    return {
        "event": "June 2025 US/Israel-Iran standoff, Strait of Hormuz",
        "window": [start.isoformat(), end.isoformat()],
        "corridor": "Hormuz",
        "lead_time_hours": lead_time_hours,
        "alert_day": alert_day,
        "alert_score": alert_row["cri_hormuz"] if alert_row else None,
        "alert_margin": (round(alert_row["cri_hormuz"] - CRI_ALERT_THRESHOLD, 2)
                         if alert_row else None),
        "spike_day": spike_day,
        "spike_pct": spike_pct if spike_day else None,
        "spike_definition": f"single-session Brent close-to-close rise >= {SPIKE_PCT}%",
        "lead_note": lead_note,
        "brier_score": brier,
        "brier_reference_base_rate": brier_ref,
        "brier_skill_score": skill,
        "outcome_base_rate": base_rate,
        "scored_days": n,
        "brier_full_window": full,
        "brier_onset_window": onset,
        "brier_interpretation": _interpretation(full, onset, spike_day),
        "outcome_definition": (
            f"1 if the Brent close rises >= {SPIKE_PCT}% above the day's close "
            f"at any point within the next {OUTCOME_HORIZON_DAYS * 24} hours"
        ),
        "probability_model": (
            f"p = 1 / (1 + exp(-(CRI - {CRI_ALERT_THRESHOLD}) / {PROB_SLOPE})), "
            f"so p = 0.5 exactly at the alert threshold"
        ),
        "peak_cri": max((r["cri_hormuz"] for r in series), default=0.0),
        "series": series,
        "signals_used": ["news", "market"],
        "signals_excluded": ["ais", "sanctions"],
        "exclusion_note": (
            "No June 2025 AIS archive and no June 2025 OFAC snapshot exist on "
            "this deployment. Those two components are dropped and the CRI "
            "weights renormalised over news and market. Substituting today's "
            "AIS snapshot would be lookahead and a provenance lie."
        ),
        "weights_nominal": dict(cri_mod.WEIGHTS),
        "weights_effective": {"news": round(cri_mod.WEIGHTS["news"] / 0.60, 4),
                              "market": round(cri_mod.WEIGHTS["market"] / 0.60, 4),
                              "ais": 0.0, "sanctions": 0.0},
        "sources": {
            "news": gdelt.REPLAY_PATH.name,
            "news_disclosure": gdelt.CORPUS_DISCLOSURE,
            "price": BRENT_PATH.name,
            "price_disclosure": BRENT_DISCLOSURE,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": Provenance.REPLAY,
    }
