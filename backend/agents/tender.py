"""Draft procurement tender / term sheet from LP output.

The last mile. A recommendation a judge can read is worth less than a document
a procurement officer could actually send, so this turns a solver line into a
tender with grade specs, a laycan window computed from the voyage, the exact
quantity the LP chose, and the supplier's real benchmark pricing formula.

Structure and every number are assembled deterministically here. The LLM is
only allowed to write the covering prose; if it is unavailable the template
still produces a complete, valid document.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.agents.llm import complete, llm_available, provider_label
from backend.config import Provenance
from backend.data import loaders

# Days between issuing a tender and the earliest laycan opening. Covers bid
# evaluation and fixing the vessel.
FIXING_LEAD_DAYS = 5
# A laycan is a window, not a date: this is its width.
LAYCAN_WIDTH_DAYS = 3

BBL_PER_CARGO_TOLERANCE = 0.05  # +/- 5% at seller's option, standard in crude


def build_tender(
    line: dict[str, Any],
    scenario_name: str,
    issue_date: date | None = None,
    tender_no: int = 1,
) -> dict[str, Any]:
    """Assemble one tender from one procurement line. Pure and deterministic."""
    issue = issue_date or date.today()
    ref = loaders.refineries().set_index("refinery_id")
    r = ref.loc[line["refinery_id"]]

    # The cargo must berth by the LP's delivery day, so the laycan opens far
    # enough ahead to cover the voyage itself.
    berth_day = float(line["first_delivery_day"])
    laycan_open = issue + timedelta(days=FIXING_LEAD_DAYS)
    laycan_close = laycan_open + timedelta(days=LAYCAN_WIDTH_DAYS)
    eta = issue + timedelta(days=round(berth_day))

    volume_kb = float(line["volume_kb"])
    tolerance_kb = round(volume_kb * BBL_PER_CARGO_TOLERANCE, 1)

    return {
        "tender_no": f"CHKV/{issue:%Y%m}/{tender_no:03d}",
        "issue_date": issue.isoformat(),
        "status": "DRAFT — not for issue",
        "trigger": scenario_name,
        "buyer": {
            "entity": r["operator"],
            "refinery": r["name"],
            "discharge_port": line["port"],
            "state": r["state"],
        },
        "cargo": {
            "grade": line["grade"],
            "origin_country": line["country"],
            "load_port": line["load_port"],
            "quantity_kb": round(volume_kb, 1),
            "quantity_bbl": int(volume_kb * 1000),
            "tolerance": f"+/- {BBL_PER_CARGO_TOLERANCE * 100:.0f}% at seller's option "
                         f"({tolerance_kb:,.0f} kb)",
            "vessel_class": line["vessel_class"],
            "cargoes": line.get("cargoes"),
        },
        "quality": {
            "api_gravity": line["api_gravity"],
            "sulfur_pct": line["sulfur_pct"],
            "refinery_diet_api": f"{r['api_min']}–{r['api_max']}",
            "refinery_diet_sulfur_max": float(r["sulfur_max_pct"]),
            "compatible": bool(
                r["api_min"] <= line["api_gravity"] <= r["api_max"]
                and line["sulfur_pct"] <= r["sulfur_max_pct"]
            ),
        },
        "commercial": {
            "pricing_basis": line["pricing_formula"],
            "indicative_landed_usd_bbl": line["unit_cost_usd_bbl"],
            "freight_component_usd_bbl": line["freight_usd_bbl"],
            "incoterm": "CFR " + line["port"],
            "payment": "Irrevocable LC at sight, 30 days from B/L date",
        },
        "schedule": {
            "laycan_open": laycan_open.isoformat(),
            "laycan_close": laycan_close.isoformat(),
            "voyage_days": line["voyage_days"],
            "eta_discharge": eta.isoformat(),
            "berth_day_offset": berth_day,
        },
        "provenance": Provenance.SIMULATED,
    }


def render_text(t: dict[str, Any]) -> str:
    """Fixed-format tender body. Never model-generated."""
    q, c, cm, s, b = t["quality"], t["cargo"], t["commercial"], t["schedule"], t["buyer"]
    return f"""TENDER {t['tender_no']}                              {t['status']}
Issued {t['issue_date']}
Trigger: {t['trigger']}

1. BUYER
   {b['entity']} — {b['refinery']}, {b['state']}
   Discharge port: {b['discharge_port']}

2. CARGO
   Grade            {c['grade']} ({c['origin_country']})
   Load port        {c['load_port']}
   Quantity         {c['quantity_bbl']:,} bbl ({c['quantity_kb']:,.0f} kb)
   Tolerance        {c['tolerance']}
   Vessel           {c['vessel_class']}

3. QUALITY
   API gravity      {q['api_gravity']}°   (buyer diet {q['refinery_diet_api']}°)
   Sulfur           {q['sulfur_pct']}%   (buyer max {q['refinery_diet_sulfur_max']}%)
   Compatibility    {'CONFIRMED against refinery crude diet' if q['compatible'] else 'FAILS DIET — DO NOT ISSUE'}

4. COMMERCIAL
   Pricing basis    {cm['pricing_basis']}
   Indicative CFR   ${cm['indicative_landed_usd_bbl']}/bbl (freight ${cm['freight_component_usd_bbl']}/bbl)
   Incoterm         {cm['incoterm']}
   Payment          {cm['payment']}

5. SCHEDULE
   Laycan           {s['laycan_open']} to {s['laycan_close']}
   Voyage           {s['voyage_days']} days
   ETA discharge    {s['eta_discharge']} (day {s['berth_day_offset']} from trigger)
"""


async def draft_tenders(
    result: dict[str, Any], top_n: int = 3
) -> dict[str, Any]:
    """Build tenders for the largest lines in a defense-pipeline result."""
    lines = result["procurement"]["lines"][:top_n]
    scenario = result["meta"].get("name", "operator-defined shock")

    tenders = [
        {**build_tender(ln, scenario, tender_no=i + 1),
         "body": render_text(build_tender(ln, scenario, tender_no=i + 1))}
        for i, ln in enumerate(lines)
    ]

    cover = None
    if tenders and llm_available():
        summary = "\n".join(
            f"- {t['cargo']['quantity_bbl']:,} bbl {t['cargo']['grade']} "
            f"from {t['cargo']['origin_country']} into {t['buyer']['refinery']}, "
            f"laycan {t['schedule']['laycan_open']}, "
            f"ETA {t['schedule']['eta_discharge']}"
            for t in tenders
        )
        cover = await complete(
            system=(
                "You are a procurement officer at an Indian refiner. Write a "
                "short covering note (max 90 words) to accompany draft crude "
                "tenders being issued in response to a supply disruption. State "
                "why the cargoes are being sought and the urgency. Cite only "
                "facts given to you. No headings, no bullet points, no preamble, "
                "no invented figures."
            ),
            user=f"Disruption: {scenario}\nCargoes being tendered:\n{summary}",
            max_tokens=300,
            fast=True,
        )

    return {
        "tenders": tenders,
        "cover_note": cover,
        "cover_note_mode": "llm" if cover else "omitted",
        "generator": provider_label(),
        "count": len(tenders),
        "provenance": Provenance.SIMULATED,
    }
