"""Calibration: is the CRI's probability honest, and does it disagree with oil?

Two questions, answered on the June 2025 replay.

**1. Is it calibrated?** We bin the daily CRI-implied probabilities and compare
the mean prediction in each bin against the frequency of the outcome actually
observed in that bin. A perfectly calibrated forecaster sits on the diagonal.
The bins and the reliability-curve series are returned so the UI can plot the
curve against the 45-degree line without recomputing anything.

**2. Does it disagree with the market?** We need a market-implied probability
of the same event to compare against. Brent options surfaces are not available
on this deployment, so we use a documented realized-volatility proxy rather
than pretending to have implied vol:

    Model the log price as driftless Brownian motion with sigma set to the
    trailing 30-day realized volatility (annualised). Over a horizon
    T = 72h = 3/365 years, the probability that the price touches +X% at some
    point in the window follows from the reflection principle for the running
    maximum of a driftless Brownian motion:

        P(max_{t<=T} S_t >= S_0 * (1+X))  =  2 * Phi( -ln(1+X) / (sigma * sqrt(T)) )

    with X = 5%, matching the backtest's outcome definition exactly.

Three things this proxy is not, stated up front: it has no drift term, it uses
realized rather than implied volatility (so it lags a repricing by construction
and carries no volatility risk premium), and it is symmetric in a market whose
option skew is not. It is a reference point, not a market quote -- which is
precisely why a large gap between it and the CRI is interesting rather than
embarrassing: the CRI is supposed to move on information the realized-vol
proxy cannot see yet.

Disagreements larger than DISAGREEMENT_THRESHOLD are flagged with a direction,
so an operator can read "the system is pricing a corridor event the oil market
has not repriced yet" straight off the payload.

Everything here is model output: SIMULATED, over REPLAY inputs.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

from backend.config import Provenance
from backend.data import market
from backend.eval import backtest as bt

HORIZON_DAYS = bt.OUTCOME_HORIZON_DAYS
HORIZON_YEARS = HORIZON_DAYS / 365.0
MOVE_PCT = bt.SPIKE_PCT

# Absolute probability gap at which we flag a system/market disagreement.
DISAGREEMENT_THRESHOLD = 0.25

# Reliability bins over [0, 1].
BIN_EDGES: list[float] = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def _phi(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def market_implied_prob(vol_annual_pct: float,
                        move_pct: float = MOVE_PCT,
                        horizon_years: float = HORIZON_YEARS) -> float:
    """P(price touches +move_pct within the horizon) from realized volatility.

    Reflection principle, driftless GBM. See the module docstring for the
    assumptions this buys and what it costs.
    """
    sigma = max(0.0, float(vol_annual_pct)) / 100.0
    if sigma <= 0.0 or horizon_years <= 0.0:
        return 0.0
    barrier = math.log(1.0 + move_pct / 100.0)
    z = barrier / (sigma * math.sqrt(horizon_years))
    return round(min(1.0, 2.0 * _phi(-z)), 4)


def _bin_index(p: float) -> int:
    for i in range(len(BIN_EDGES) - 1):
        if p < BIN_EDGES[i + 1] or i == len(BIN_EDGES) - 2:
            return i
    return len(BIN_EDGES) - 2


def _reliability(points: list[tuple[float, int]]) -> list[dict[str, Any]]:
    """Bin (predicted, outcome) pairs into the reliability curve.

    Counts across bins sum to len(points) by construction -- every point lands
    in exactly one bin, and empty bins are returned with count 0 so the curve
    has a stable x-axis.
    """
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(len(BIN_EDGES) - 1)]
    for p, y in points:
        buckets[_bin_index(max(0.0, min(1.0, p)))].append((p, y))

    out: list[dict[str, Any]] = []
    for i, bucket in enumerate(buckets):
        lo, hi = BIN_EDGES[i], BIN_EDGES[i + 1]
        n = len(bucket)
        out.append({
            "bin": f"{lo:.1f}-{hi:.1f}",
            "bin_lower": lo,
            "bin_upper": hi,
            "bin_mid": round((lo + hi) / 2.0, 3),
            "count": n,
            "predicted_mean": (round(sum(p for p, _ in bucket) / n, 4) if n else None),
            "observed_freq": (round(sum(y for _, y in bucket) / n, 4) if n else None),
            "observed_count": sum(y for _, y in bucket),
        })
    return out


async def run_calibration() -> dict[str, Any]:
    """Compare CRI-implied against market-implied probabilities on the replay.

    Never raises; deterministic.
    """
    back = await bt.run_backtest()
    rows = bt.load_brent()
    closes = dict(rows)

    daily: list[dict[str, Any]] = []
    for r in back["series"]:
        if r["outcome_72h"] is None:
            continue
        iso = r["date"]
        hist = [c for d, c in rows if d <= iso]
        vol = market.realized_vol_pct(hist, 30)
        p_mkt = market_implied_prob(vol)
        p_cri = float(r["alert_prob"])
        gap = round(p_cri - p_mkt, 4)
        daily.append({
            "date": iso,
            "cri_hormuz": r["cri_hormuz"],
            "p_system": p_cri,
            "p_market": p_mkt,
            "gap": gap,
            "abs_gap": abs(gap),
            "realized_vol_30d_pct": vol,
            "brent_close": closes.get(iso, r["brent_close"]),
            "outcome_72h": r["outcome_72h"],
            "disagreement": abs(gap) > DISAGREEMENT_THRESHOLD,
            "direction": ("system_above_market" if gap > 0
                          else "system_below_market" if gap < 0 else "aligned"),
            "provenance": Provenance.REPLAY,
        })

    sys_points = [(d["p_system"], d["outcome_72h"]) for d in daily]
    mkt_points = [(d["p_market"], d["outcome_72h"]) for d in daily]
    sys_bins = _reliability(sys_points)
    mkt_bins = _reliability(mkt_points)

    n = len(daily)
    flags = [
        {
            "date": d["date"],
            "p_system": d["p_system"],
            "p_market": d["p_market"],
            "gap": d["gap"],
            "direction": d["direction"],
            "cri_hormuz": d["cri_hormuz"],
            "outcome_72h": d["outcome_72h"],
            "reading": (
                f"System priced {d['p_system']:.0%} vs a realized-vol proxy of "
                f"{d['p_market']:.0%} -- "
                + ("the index was pricing corridor information the oil market "
                   "had not repriced." if d["gap"] > 0 else
                   "the oil market was more nervous than the corridor signals.")
            ),
            "provenance": Provenance.SIMULATED,
        }
        for d in daily if d["disagreement"]
    ]

    mean_sys = round(sum(d["p_system"] for d in daily) / n, 4) if n else 0.0
    mean_mkt = round(sum(d["p_market"] for d in daily) / n, 4) if n else 0.0
    observed = round(sum(d["outcome_72h"] for d in daily) / n, 4) if n else 0.0

    return {
        "window": back["window"],
        "corridor": "Hormuz",
        "event": back["event"],
        "n_points": n,
        "bins": sys_bins,
        "bin_count_total": sum(b["count"] for b in sys_bins),
        "market_bins": mkt_bins,
        "market_bin_count_total": sum(b["count"] for b in mkt_bins),
        "reliability_curve": [
            {"bin_mid": b["bin_mid"], "predicted": b["predicted_mean"],
             "observed": b["observed_freq"], "count": b["count"]}
            for b in sys_bins
        ],
        "market_reliability_curve": [
            {"bin_mid": b["bin_mid"], "predicted": b["predicted_mean"],
             "observed": b["observed_freq"], "count": b["count"]}
            for b in mkt_bins
        ],
        "daily": daily,
        "flags": flags,
        "flag_count": len(flags),
        "disagreement_threshold": DISAGREEMENT_THRESHOLD,
        "mean_p_system": mean_sys,
        "mean_p_market": mean_mkt,
        "observed_frequency": observed,
        "system_bias": round(mean_sys - observed, 4),
        "market_bias": round(mean_mkt - observed, 4),
        "bias_note": (
            "Positive bias means over-forecasting. The system's bias is the "
            "same structural effect the backtest reports: it stays alarmed "
            "while corridor risk is genuinely elevated, which over-forecasts a "
            "*further* 72-hour price gap."
        ),
        "market_proxy": {
            "method": "reflection principle, driftless GBM on realized vol",
            "formula": ("P = 2 * Phi( -ln(1+X) / (sigma * sqrt(T)) ), "
                        f"X = {MOVE_PCT}%, T = {HORIZON_DAYS}/365 yr"),
            "sigma_source": "trailing 30-day realized volatility, annualised",
            "caveats": [
                "no drift term",
                "realized volatility, not implied -- lags a repricing by construction",
                "no volatility risk premium",
                "symmetric, while Brent option skew is not",
                "not a market quote; a reference point",
            ],
        },
        "outcome_definition": back["outcome_definition"],
        "probability_model": back["probability_model"],
        "sources": back["sources"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": Provenance.SIMULATED,
    }
