"""The Corridor Risk Index (CRI): one 0-100 number per shipping corridor.

WEIGHTING -- stated here, and returned in every payload as `weights`, because
a risk index whose weights you cannot see is a horoscope.

    news / GDELT events        0.35
    AIS behavioural anomalies  0.25
    market stress (Brent)      0.25
    sanctions activity         0.15
                               ----
                               1.00

Why this split. News leads: shipowners reprice on headlines hours before
anything is observable on the water, so it gets the largest single weight. AIS
is the confirming signal -- slower, but it is behaviour rather than talk, and
it is what turns a scary headline into a real transit disruption, so it is a
close second. Market stress is deliberately *not* dominant: Brent is the thing
we are trying to lead, and an index that mostly reads the price will always
look like it "predicted" a move it merely echoed. Sanctions is the smallest
weight because it moves in discrete administrative steps rather than
continuously, but it is the signal that persists after the headlines fade.

If a signal class is unavailable (no OFAC reachability, no market data, the
backtest replaying a day with no AIS archive), its weight is **dropped and the
remainder renormalised**, and both the nominal `weights` and the
`weights_effective` actually used are returned. We never silently score a
missing signal as zero risk.

Sub-scores are each 0-100 and each documented at their source:
  news       -> _news_scores below
  ais        -> backend.data.ais_stream.anomaly_score_by_corridor
  market     -> backend.data.market.market_stress
  sanctions  -> backend.data.sanctions._score

Bands: red at or above config.CRI_ALERT_THRESHOLD, amber at or above
0.7 * that threshold, green below.

Everything here is model output, so the payload provenance is SIMULATED; the
`inputs` block reports the provenance of each underlying feed so a reader can
see the index is currently standing on replayed data.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

from backend.config import CORRIDORS, CRI_ALERT_THRESHOLD, Provenance
from backend.data import ais_stream, gdelt, market, sanctions
from backend.data import loaders
from backend.intelligence.extractor import extract_events

# -- weighting -------------------------------------------------------------
WEIGHTS: dict[str, float] = {
    "news": 0.35,
    "ais": 0.25,
    "market": 0.25,
    "sanctions": 0.15,
}

AMBER_FRACTION = 0.7
AMBER_THRESHOLD = round(CRI_ALERT_THRESHOLD * AMBER_FRACTION, 2)

# News saturation constant: a decayed severity load of K produces ~63/100.
NEWS_SATURATION = 2.5
# Half-life, in days, of a headline's contribution.
NEWS_HALF_LIFE_DAYS = 3.0
# Events the extractor could not pin to a corridor still count, at this factor,
# against every corridor -- a global escalation is not zero risk anywhere.
NONE_SPILLOVER = 0.2

# How exposed each corridor is to a *global* signal. Sanctions pressure and
# oil-price stress are not corridor-specific observations, so they are scaled
# by how much of the world's tanker risk actually rides on that corridor.
SANCTIONS_SENSITIVITY = {"Hormuz": 1.0, "RedSea_Suez": 0.9,
                         "Malacca": 0.6, "Cape": 0.4}
MARKET_BETA = {"Hormuz": 1.0, "RedSea_Suez": 0.85,
               "Malacca": 0.6, "Cape": 0.5}

# supplier_disruption_prob shape parameters (see _supplier_probabilities).
PROB_CONVEXITY = 1.3
PROB_RISK_FLOOR = 0.55
PROB_RISK_GAIN = 0.90
PROB_CEILING = 0.97


def band_for(score: float) -> str:
    if score >= CRI_ALERT_THRESHOLD:
        return "red"
    if score >= AMBER_THRESHOLD:
        return "amber"
    return "green"


# --------------------------------------------------------------------------
# Sub-score: news
# --------------------------------------------------------------------------
def _decay(event_date: str | None, as_of: str) -> float:
    """Exponential recency decay with a NEWS_HALF_LIFE_DAYS half-life."""
    if not event_date:
        return 0.5
    try:
        d0 = date.fromisoformat(str(event_date)[:10])
        d1 = date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return 0.5
    age = max(0, (d1 - d0).days)
    return 0.5 ** (age / NEWS_HALF_LIFE_DAYS)


def _news_scores(events: list[dict[str, Any]],
                 as_of: str) -> tuple[dict[str, float], dict[str, float]]:
    """0-100 news pressure per corridor.

        load  = sum over events of  severity * (0.5 + 0.5*confidence) * decay
        score = 100 * (1 - exp(-load / NEWS_SATURATION))

    Confidence modulates rather than multiplies out: a low-confidence
    extraction of a severe event is still evidence, just weaker evidence.
    """
    load: dict[str, float] = {c: 0.0 for c in CORRIDORS}
    for e in events:
        sev = float(e.get("severity") or 0.0)
        conf = float(e.get("confidence") or 0.0)
        contrib = sev * (0.5 + 0.5 * conf) * _decay(e.get("date"), as_of)
        corridor = e.get("corridor_affected") or "none"
        if corridor in load:
            load[corridor] += contrib
        else:
            for c in load:
                load[c] += contrib * NONE_SPILLOVER
    scores = {
        c: round(100.0 * (1.0 - math.exp(-v / NEWS_SATURATION)), 2)
        for c, v in load.items()
    }
    return scores, {c: round(v, 4) for c, v in load.items()}


# --------------------------------------------------------------------------
# Supplier disruption probabilities
# --------------------------------------------------------------------------
def _supplier_probabilities(corridor: str, score: float) -> list[dict[str, Any]]:
    """Per-supplier probability of a material lifting disruption.

        p = (score/100)^1.3 * (0.55 + 0.90 * political_risk), capped at 0.97

    The exponent makes the mapping convex, so a quiet corridor implies a
    genuinely low probability rather than a floor of noise. political_risk is
    the curated per-supplier figure, so two suppliers on the same corridor do
    not get the same number.
    """
    try:
        sup = loaders.suppliers()
        imp = loaders.imports_baseline().set_index("supplier_id")
    except Exception as exc:  # noqa: BLE001
        print(f"[cri] supplier table unavailable: {type(exc).__name__}: {exc}")
        return []

    base = (max(0.0, min(100.0, score)) / 100.0) ** PROB_CONVEXITY
    out: list[dict[str, Any]] = []
    for _, r in sup[sup["primary_corridor"] == corridor].iterrows():
        pol = float(r["political_risk"])
        p = min(PROB_CEILING, base * (PROB_RISK_FLOOR + PROB_RISK_GAIN * pol))
        sid = r["supplier_id"]
        kb = float(imp.loc[sid, "barrels_per_week_kb"]) if sid in imp.index else 0.0
        out.append({
            "supplier_id": sid,
            "grade": r["grade"],
            "country": r["country"],
            "political_risk": pol,
            "kbd_at_risk": round(kb / 7.0 * p, 1),
            "disruption_prob": round(p, 4),
            "provenance": Provenance.SIMULATED,
        })
    out.sort(key=lambda d: -d["kbd_at_risk"])
    return out


# --------------------------------------------------------------------------
# Core scoring (pure -- the backtest calls this directly)
# --------------------------------------------------------------------------
def score_corridors(
    events: list[dict[str, Any]],
    anomaly_scores: dict[str, float] | None,
    sanctions_score: float | None,
    market_score: float | None,
    as_of: str,
    evidence_anomalies: list[dict[str, Any]] | None = None,
    market_detail: dict[str, Any] | None = None,
    sanctions_detail: dict[str, Any] | None = None,
    include_suppliers: bool = True,
) -> list[dict[str, Any]]:
    """Fuse the signal classes into one record per corridor.

    Pass None for a signal class that is unavailable for this evaluation; its
    weight is redistributed and the omission is reported per corridor.
    """
    news_scores, news_load = _news_scores(events, as_of)
    evidence_anomalies = evidence_anomalies or []

    available = {
        "news": True,  # keyword extraction is always available
        "ais": anomaly_scores is not None,
        "market": market_score is not None,
        "sanctions": sanctions_score is not None,
    }
    live_weight = sum(w for k, w in WEIGHTS.items() if available[k])
    weights_effective = {
        k: (round(WEIGHTS[k] / live_weight, 4) if available[k] and live_weight > 0
            else 0.0)
        for k in WEIGHTS
    }

    out: list[dict[str, Any]] = []
    for corridor in CORRIDORS:
        parts: dict[str, float] = {"news": news_scores.get(corridor, 0.0)}
        if available["ais"]:
            parts["ais"] = float((anomaly_scores or {}).get(corridor, 0.0))
        if available["market"]:
            parts["market"] = round(
                float(market_score or 0.0) * MARKET_BETA.get(corridor, 0.6), 2)
        if available["sanctions"]:
            parts["sanctions"] = round(
                float(sanctions_score or 0.0)
                * SANCTIONS_SENSITIVITY.get(corridor, 0.6), 2)

        score = round(sum(weights_effective[k] * v for k, v in parts.items()), 2)
        score = max(0.0, min(100.0, score))

        components = [
            {
                "signal": k,
                "sub_score": round(v, 2),
                "weight_nominal": WEIGHTS[k],
                "weight_effective": weights_effective[k],
                "contribution": round(weights_effective[k] * v, 2),
                "available": True,
            }
            for k, v in parts.items()
        ]
        components.extend(
            {"signal": k, "sub_score": None, "weight_nominal": WEIGHTS[k],
             "weight_effective": 0.0, "contribution": 0.0, "available": False}
            for k in WEIGHTS if not available[k]
        )
        components.sort(key=lambda c: -c["contribution"])

        corridor_events = [
            e for e in events
            if e.get("corridor_affected") == corridor
        ]
        corridor_events.sort(
            key=lambda e: (str(e.get("date") or ""), float(e.get("severity") or 0)),
            reverse=True,
        )
        corridor_anoms = [a for a in evidence_anomalies
                          if a.get("corridor") == corridor]

        record: dict[str, Any] = {
            "corridor": corridor,
            "score": score,
            "band": band_for(score),
            "alert": score >= CRI_ALERT_THRESHOLD,
            "as_of": as_of,
            "thresholds": {"red": CRI_ALERT_THRESHOLD, "amber": AMBER_THRESHOLD},
            "weights": dict(WEIGHTS),
            "weights_effective": weights_effective,
            "unavailable_signals": [k for k, v in available.items() if not v],
            "components": components,
            "news_load": news_load.get(corridor, 0.0),
            "evidence": {
                "events": corridor_events[:8],
                "event_count": len(corridor_events),
                "anomalies": corridor_anoms[:8],
                "anomaly_count": len(corridor_anoms),
                "market": market_detail,
                "sanctions": sanctions_detail,
            },
            "provenance": Provenance.SIMULATED,
        }
        if include_suppliers:
            record["supplier_disruption_prob"] = _supplier_probabilities(
                corridor, score)
        out.append(record)

    out.sort(key=lambda d: -d["score"])
    return out


# --------------------------------------------------------------------------
# Live/replay snapshot
# --------------------------------------------------------------------------
async def cri_snapshot(days: int = 7, use_llm: bool = False) -> dict[str, Any]:
    """Assemble every signal class and score all four corridors.

    Never raises: each feed already degrades to replay or to "unavailable", and
    an unavailable class is dropped from the weighting.
    """
    news = await gdelt.fetch_events("Strait of Hormuz OR tanker OR chokepoint",
                                    days=days)
    events = await extract_events(news.get("events", []), use_llm=use_llm)

    ais = await ais_stream.vessel_snapshot()
    brent = await market.brent_snapshot()
    stress = market.market_stress(brent)
    sdn = await sanctions.sdn_delta()

    as_of = (news.get("events") or [{}])[-1].get("date") \
        or datetime.now(timezone.utc).date().isoformat()

    corridors = score_corridors(
        events=events,
        anomaly_scores=ais.get("scores_by_corridor", {}),
        sanctions_score=sdn["score"] if sdn.get("available") else None,
        market_score=stress["score"] if stress.get("available") else None,
        as_of=str(as_of),
        evidence_anomalies=ais.get("anomalies", []),
        market_detail={
            "last_close": brent.get("last_close"),
            "change_pct": brent.get("change_pct"),
            "realized_vol_30d_pct": brent.get("realized_vol_30d_pct"),
            "spread_vs_90d_mean_pct": brent.get("spread_vs_90d_mean_pct"),
            "stress_score": stress.get("score"),
            "provenance": brent.get("provenance"),
        },
        sanctions_detail={
            "in_scope_maritime_entries": sdn.get("in_scope_maritime_entries"),
            "vessel_entries": sdn.get("vessel_entries"),
            "delta": sdn.get("delta"),
            "score": sdn.get("score"),
            "available": sdn.get("available"),
            "provenance": sdn.get("provenance"),
        },
    )

    return {
        "as_of": str(as_of),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weights": dict(WEIGHTS),
        "weighting_rationale": (
            "news 0.35 leads because shipowners reprice on headlines first; "
            "AIS 0.25 confirms with observed behaviour; market 0.25 is capped "
            "deliberately so the index is not merely echoing the price it "
            "claims to lead; sanctions 0.15 moves in discrete steps but "
            "persists after headlines fade."
        ),
        "thresholds": {"red": CRI_ALERT_THRESHOLD, "amber": AMBER_THRESHOLD},
        "corridors": corridors,
        "alerting": [c["corridor"] for c in corridors if c["alert"]],
        "inputs": {
            "news": {"provenance": news.get("provenance"),
                     "count": news.get("count"), "source": news.get("source"),
                     "note": news.get("note")},
            "ais": {"provenance": ais.get("provenance"),
                    "vessel_count": ais.get("vessel_count"),
                    "anomaly_count": ais.get("anomaly_count"),
                    "live_ais_configured": ais.get("live_ais_configured"),
                    "note": ais.get("note")},
            "market": {"provenance": brent.get("provenance"),
                       "available": brent.get("available"),
                       "source": brent.get("source"),
                       "note": brent.get("note")},
            "sanctions": {"provenance": sdn.get("provenance"),
                          "available": sdn.get("available"),
                          "source": sdn.get("source"),
                          "note": sdn.get("note")},
        },
        "extraction_method": ("llm+keyword" if use_llm else "keyword"),
        "provenance": Provenance.SIMULATED,
    }
