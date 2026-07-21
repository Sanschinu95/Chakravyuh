"""Country sourcing advisor -- who to buy from, how much, and by when.

Answers three questions a procurement desk actually asks:

* Where are we over-exposed?  Concentration by country and by corridor,
  measured with HHI (the same index competition regulators use), not vibes.
* Who could we shift to?      Spare liftable capacity that is grade-compatible
  with at least one Indian refinery and physically reachable.
* By when must we order?      Lead time is the fastest voyage on the fastest
  vessel class, so "arrive by D+30" means "fix the cargo by D+30 minus that".

Every recommendation is deterministic and traceable to the curated dataset --
no model invents a barrel here.
"""

from __future__ import annotations

from typing import Any

from backend.config import Provenance
from backend.data import loaders

# Country dependency above this share is flagged as concentration risk.
HIGH_DEPENDENCE_SHARE = 15.0
# Political risk above this is treated as an elevated-risk counterparty.
ELEVATED_RISK = 0.40


def _fastest_days_by_supplier() -> dict[str, float]:
    rts = loaders.routes()
    ref_ports = set(loaders.refineries()["primary_port"])
    rts = rts[rts["discharge_port"].isin(ref_ports)]
    return rts.groupby("supplier_id")["voyage_days"].min().to_dict()


def sourcing_view(disrupted: dict[str, float] | None = None) -> dict[str, Any]:
    """Country-level sourcing picture, optionally under a disruption."""
    disrupted = disrupted or {}
    sup = loaders.suppliers()
    imp = loaders.imports_baseline().set_index("supplier_id")
    gc = loaders.grade_compatibility()
    fastest = _fastest_days_by_supplier()

    compatible_counts = (
        gc[gc["compatible"]].groupby("supplier_id")["refinery_id"].nunique().to_dict()
    )

    total_kbd = float(imp["barrels_per_week_kb"].sum()) / 7.0

    rows: list[dict[str, Any]] = []
    for country, grp in sup.groupby("country"):
        grades: list[dict[str, Any]] = []
        cur = spare = 0.0
        risk_num = 0.0
        premium_num = 0.0
        corridors: set[str] = set()
        blocked_kbd = 0.0

        for _, s in grp.iterrows():
            sid = s["supplier_id"]
            base = float(imp.loc[sid, "barrels_per_week_kb"]) / 7.0 if sid in imp.index else 0.0
            liftable = float(s["max_liftable_kbd"])
            head = max(0.0, liftable - base)
            frac_blocked = float(disrupted.get(sid, 0.0))

            cur += base
            spare += head * (1.0 - frac_blocked)
            blocked_kbd += base * frac_blocked
            risk_num += float(s["political_risk"]) * max(base, 1.0)
            premium_num += float(s["spot_premium_usd_bbl"]) * max(base, 1.0)
            corridors.add(s["primary_corridor"])

            grades.append({
                "supplier_id": sid,
                "grade": s["grade"],
                "api_gravity": float(s["api_gravity"]),
                "sulfur_pct": float(s["sulfur_pct"]),
                "current_kbd": round(base, 1),
                "spare_kbd": round(head, 1),
                "corridor": s["primary_corridor"],
                "compatible_refineries": int(compatible_counts.get(sid, 0)),
                "fastest_days": round(float(fastest.get(sid, 0.0)), 1),
                "blocked_pct": round(frac_blocked * 100, 1),
                "pricing_formula": s["pricing_formula"],
            })

        weight = sum(max(g["current_kbd"], 1.0) for g in grades)
        share = 100.0 * cur / total_kbd if total_kbd else 0.0
        lead = min((g["fastest_days"] for g in grades if g["fastest_days"] > 0), default=0.0)
        reachable = any(g["compatible_refineries"] > 0 for g in grades)

        rows.append({
            "country": country,
            "region": grp.iloc[0]["region"],
            "grades": sorted(grades, key=lambda g: -g["current_kbd"]),
            "current_kbd": round(cur, 1),
            "share_pct": round(share, 2),
            "spare_kbd": round(spare, 1),
            "blocked_kbd": round(blocked_kbd, 1),
            "political_risk": round(risk_num / weight, 3),
            "avg_premium_usd_bbl": round(premium_num / weight, 2),
            "corridors": sorted(corridors),
            "single_corridor": len(corridors) == 1,
            "lead_time_days": round(lead, 1),
            "reachable": reachable,
        })

    # ---- concentration ---------------------------------------------------
    hhi = sum(r["share_pct"] ** 2 for r in rows)
    top3 = sum(sorted((r["share_pct"] for r in rows), reverse=True)[:3])
    if hhi > 2500:
        verdict = "highly concentrated"
    elif hhi > 1500:
        verdict = "moderately concentrated"
    else:
        verdict = "diversified"

    corridor_share: dict[str, float] = {}
    for r in rows:
        for c in r["corridors"]:
            corridor_share[c] = corridor_share.get(c, 0.0) + r["share_pct"] / len(r["corridors"])

    # ---- recommendations -------------------------------------------------
    for r in rows:
        r["recommendation"] = _recommend(r, corridor_share)

    rows.sort(key=lambda r: -r["current_kbd"])

    return {
        "countries": rows,
        "concentration": {
            "hhi": round(hhi, 0),
            "top3_share_pct": round(top3, 1),
            "verdict": verdict,
            "note": "HHI is the sum of squared percentage shares. Above 2500 is "
                    "the threshold competition regulators treat as highly "
                    "concentrated.",
            "corridor_share_pct": {k: round(v, 1) for k, v in
                                   sorted(corridor_share.items(), key=lambda kv: -kv[1])},
        },
        "total_import_kbd": round(total_kbd, 1),
        "under_disruption": bool(disrupted),
        "provenance": Provenance.CURATED if not disrupted else Provenance.SIMULATED,
    }


def _recommend(r: dict[str, Any], corridor_share: dict[str, float]) -> dict[str, Any]:
    """Deterministic, explainable sourcing advice for one country."""
    reasons: list[str] = []
    action = "hold"
    urgency = "routine"

    if r["blocked_kbd"] > 0:
        action = "replace now"
        urgency = "immediate"
        reasons.append(
            f"{r['blocked_kbd']:,.0f} kbd of current supply is blocked by the "
            f"active disruption"
        )
    elif r["share_pct"] >= HIGH_DEPENDENCE_SHARE and r["political_risk"] >= ELEVATED_RISK:
        action = "reduce"
        urgency = "near-term"
        reasons.append(
            f"{r['share_pct']:.1f}% of imports from a counterparty with "
            f"political risk {r['political_risk']:.2f}"
        )
    elif r["share_pct"] >= HIGH_DEPENDENCE_SHARE and r["single_corridor"]:
        action = "diversify route"
        urgency = "near-term"
        reasons.append(
            f"{r['share_pct']:.1f}% of imports all transit "
            f"{r['corridors'][0]} with no alternative corridor"
        )
    elif r["spare_kbd"] >= 100 and r["political_risk"] < ELEVATED_RISK and r["reachable"]:
        action = "increase"
        urgency = "opportunistic"
        reasons.append(
            f"{r['spare_kbd']:,.0f} kbd of spare liftable capacity at "
            f"political risk {r['political_risk']:.2f}"
        )
    else:
        reasons.append("share and risk are both within tolerance")

    # Corridor context is a second-order reason worth surfacing either way.
    worst = max(r["corridors"], key=lambda c: corridor_share.get(c, 0.0)) if r["corridors"] else None
    if worst and corridor_share.get(worst, 0) > 35 and action in ("hold", "increase"):
        reasons.append(
            f"note: {worst} already carries {corridor_share[worst]:.0f}% of all imports"
        )

    when = (
        f"order by D-{r['lead_time_days']:.0f} to berth on day D"
        if r["lead_time_days"] else "no modelled route"
    )

    return {
        "action": action,
        "urgency": urgency,
        "rationale": "; ".join(reasons),
        "when": when,
        "lead_time_days": r["lead_time_days"],
    }
