"""Brent crude market feed (yfinance) with a replay cache behind it.

Honesty contract for this module:

* A successful fetch this session is LIVE.
* Anything served from `data_replay/brent_cache.csv` (a snapshot of a previous
  successful fetch) is REPLAY, never LIVE.
* If neither is available the payload says `available: false` and carries an
  explicit note. We do not invent a price.

The realized-volatility figure is a plain annualised standard deviation of
daily log returns -- no GARCH, no model risk hidden in a single number. It is
the input the Corridor Risk Index uses for its market-stress component and the
input the calibration module uses for its market-implied probability proxy.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from backend.config import Provenance, REPLAY_DIR

BRENT_SYMBOL = "BZ=F"
CACHE_PATH = REPLAY_DIR / "brent_cache.csv"
TRADING_DAYS = 252

_FETCH_TIMEOUT_S = 15.0


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
def log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for a, b in zip(closes, closes[1:]):
        if a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def realized_vol_pct(closes: list[float], window: int = 30) -> float:
    """Annualised realized volatility in percent, from daily log returns.

    Returns 0.0 when there is not enough history to say anything, rather than
    a made-up default.
    """
    rets = log_returns(closes)[-window:]
    if len(rets) < 5:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(TRADING_DAYS) * 100.0, 2)


def spread_vs_mean_pct(closes: list[float], window: int = 90) -> float:
    """How far the last close sits above/below its trailing mean, in percent.

    This is the 'spread' half of the market-stress signal: vol says how jumpy
    the market is, spread says whether it has actually repriced upward.
    """
    tail = closes[-window:]
    if len(tail) < 5:
        return 0.0
    mean = sum(tail) / len(tail)
    if mean <= 0:
        return 0.0
    return round(100.0 * (tail[-1] - mean) / mean, 2)


# --------------------------------------------------------------------------
# Cache I/O
# --------------------------------------------------------------------------
def _write_cache(frame: pd.DataFrame) -> None:
    try:
        REPLAY_DIR.mkdir(parents=True, exist_ok=True)
        frame.to_csv(CACHE_PATH, index=False)
    except Exception as exc:  # noqa: BLE001 - caching must never break a request
        print(f"[market] cache write failed: {type(exc).__name__}: {exc}")


def _read_cache() -> pd.DataFrame | None:
    if not CACHE_PATH.exists():
        return None
    try:
        df = pd.read_csv(CACHE_PATH)
        if {"date", "close"} <= set(df.columns) and len(df) >= 2:
            return df
    except Exception as exc:  # noqa: BLE001
        print(f"[market] cache read failed: {type(exc).__name__}: {exc}")
    return None


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def _fetch_blocking(days: int) -> pd.DataFrame:
    import yfinance as yf

    period = f"{max(days + 40, 120)}d"
    hist = yf.Ticker(BRENT_SYMBOL).history(period=period)
    if hist is None or hist.empty or "Close" not in hist:
        raise RuntimeError("yfinance returned an empty frame")
    out = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in hist.index],
        "close": [round(float(c), 2) for c in hist["Close"]],
    })
    out = out.dropna().reset_index(drop=True)
    if len(out) < 10:
        raise RuntimeError(f"yfinance returned only {len(out)} rows")
    return out


def _payload_from_frame(frame: pd.DataFrame, days: int, provenance: str,
                        source: str, note: str) -> dict[str, Any]:
    frame = frame.tail(days + 1).reset_index(drop=True)
    closes = [float(c) for c in frame["close"]]
    dates = [str(d) for d in frame["date"]]
    last = closes[-1]
    prev = closes[-2] if len(closes) > 1 else last
    change_pct = round(100.0 * (last - prev) / prev, 3) if prev else 0.0
    return {
        "symbol": BRENT_SYMBOL,
        "available": True,
        "last_close": round(last, 2),
        "prev_close": round(prev, 2),
        "change_pct": change_pct,
        "as_of": dates[-1],
        "series": [{"date": d, "close": round(c, 2)}
                   for d, c in zip(dates, closes)][-days:],
        "realized_vol_30d_pct": realized_vol_pct(closes, 30),
        "realized_vol_90d_pct": realized_vol_pct(closes, 90),
        "spread_vs_90d_mean_pct": spread_vs_mean_pct(closes, 90),
        "source": source,
        "note": note,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": provenance,
    }


async def brent_snapshot(days: int = 90) -> dict[str, Any]:
    """Last close, % change, a `days`-long series and realized volatility.

    Never raises. Live fetch -> LIVE; cache -> REPLAY; nothing -> available
    false, still REPLAY-tagged so no consumer can mistake it for a live quote.
    """
    try:
        frame = await asyncio.wait_for(
            asyncio.to_thread(_fetch_blocking, days), timeout=_FETCH_TIMEOUT_S
        )
        _write_cache(frame)
        return _payload_from_frame(
            frame, days, Provenance.LIVE, "yfinance:BZ=F",
            "Fetched from Yahoo Finance this session.",
        )
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        reason = f"{type(exc).__name__}: {exc}"
        print(f"[market] live fetch failed, falling back to cache: {reason}")

    cached = _read_cache()
    if cached is not None:
        return _payload_from_frame(
            cached, days, Provenance.REPLAY, str(CACHE_PATH.name),
            "Live Brent feed unavailable this session; replaying the last "
            "cached snapshot. This is NOT a live quote.",
        )

    return {
        "symbol": BRENT_SYMBOL,
        "available": False,
        "last_close": None,
        "prev_close": None,
        "change_pct": 0.0,
        "as_of": None,
        "series": [],
        "realized_vol_30d_pct": 0.0,
        "realized_vol_90d_pct": 0.0,
        "spread_vs_90d_mean_pct": 0.0,
        "source": "none",
        "note": "Brent feed unavailable and no cached snapshot exists. "
                "No price is being reported rather than a fabricated one.",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": Provenance.REPLAY,
    }


def market_stress(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map a Brent snapshot onto a 0-100 market-stress score.

    stress = 100 * clip( 0.55 * vol30/45  +  0.45 * max(0, spread)/12 , 0, 1)

    45% annualised vol and a 12% premium to the 90-day mean are the "pinned"
    points: at or beyond both, the market alone is screaming and the component
    saturates. Both anchors are stated here so a reviewer can move them.
    """
    if not snapshot.get("available"):
        return {"score": 0.0, "available": False, "vol_30d_pct": 0.0,
                "spread_vs_90d_mean_pct": 0.0,
                "note": "market component excluded: no Brent data"}
    vol = float(snapshot.get("realized_vol_30d_pct") or 0.0)
    spread = float(snapshot.get("spread_vs_90d_mean_pct") or 0.0)
    raw = 0.55 * (vol / 45.0) + 0.45 * (max(0.0, spread) / 12.0)
    return {
        "score": round(100.0 * max(0.0, min(1.0, raw)), 2),
        "available": True,
        "vol_30d_pct": vol,
        "spread_vs_90d_mean_pct": spread,
        "note": "0.55*vol30/45 + 0.45*max(0,spread)/12, clipped to [0,1]",
    }
