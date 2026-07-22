"""Turns solver output into a plain-English justification.

The narrator explains; it does not decide. Every number it is allowed to say
is handed to it from the LP and the cascade. When the LLM is unavailable it
falls back to a deterministic template built from the same numbers, so the
panel is never empty and never invents anything.
"""

from __future__ import annotations

from typing import Any

from backend.agents.llm import complete, llm_available, provider_label
from backend.config import Provenance

SYSTEM = """You are the analyst on an energy supply-chain war room desk in India.

You will be given the output of a linear program that has already decided a
crude procurement plan, plus a strategic reserve drawdown schedule.

Your job is to explain the decision to a senior official who has thirty
seconds. You do NOT make decisions and you do NOT compute anything. Every
figure you cite must appear verbatim in the data you were given. If a number
is not in the data, do not state it.

Write 3 short paragraphs, no headings, no bullet points, no preamble:
1. What the shock does to supply, and which refineries are worst hit and why.
2. What the plan buys, from where, and when the first cargo berths. Name the
   binding constraint explicitly if one is given.
3. What the strategic reserve has to cover in the meantime, and whether the
   plan closes the gap or leaves a shortfall.

Be direct and concrete. No hedging, no filler, no restating the question."""


def _facts(result: dict[str, Any]) -> str:
    cascade = result["cascade"]
    plan = result["procurement"]
    spr = result["spr"]
    h = cascade["headline"]
    stage2 = cascade["stages"][1]

    worst = "\n".join(
        f"  - {r['refinery']}: running at {r['utilisation_pct']}% "
        f"(cut {r['cut_kbd']:.0f} kbd) — {r['binding']}"
        for r in stage2["by_refinery"][:4] if r["cut_kbd"] > 0
    )
    lines = "\n".join(
        f"  - {ln['volume_kb']:.0f} kb of {ln['grade']} ({ln['country']}) "
        f"to {ln['refinery']} by {ln['vessel_class']}, first berth day "
        f"{ln['first_delivery_day']}, ${ln['unit_cost_usd_bbl']}/bbl"
        for ln in plan["lines"][:6]
    )
    binding = "\n".join(
        f"  - {b['explanation']} (shadow price ${b['shadow_price_usd_bbl']}/bbl)"
        for b in plan["binding"][:3]
    ) or "  - none: the plan is not constrained"

    cf = spr.get("counterfactual", {})
    return f"""SHOCK
  {result['meta'].get('name', 'Custom shock')} lasting {h['duration_days']} days.
  Net supply gap {h['net_lost_kbd']:.0f} kbd ({h['lost_pct_of_imports']}% of imports).
  Brent ${h['brent_usd']} ({h['brent_delta_pct']:+.1f}%).
  Unserved product demand {h['unserved_pct_of_demand']}%.
  Grade-compatible crude that exists but is too far away to arrive in time:
    {stage2['stranded_spare_kbd']:.0f} kbd (delivery window {stage2['delivery_budget_days']} days).

WORST-HIT REFINERIES
{worst or '  - none'}

PROCUREMENT PLAN (from the LP, status {plan['status']})
  Covers {plan['coverage_pct']}% of the gap; {plan['unmet_kb']:.0f} kb left unmet.
  Cost delta ${plan['cost_delta_usd_mn']}mn (INR {plan['cost_delta_inr_crore']} crore).
  First replacement cargo berths on day {plan['first_delivery_day']}.
{lines or '  - no feasible cargoes'}

BINDING CONSTRAINTS
{binding}

STRATEGIC RESERVE
  Draws {spr['total_drawn_mmbbl']} mmbbl of {spr['total_available_kb'] / 1000:.1f} mmbbl available.
  Holds {spr['end_buffer_mmbbl']} mmbbl in reserve at the end of the shock.
  Peak unserved after drawdown: {spr['peak_unserved_kbd']:.0f} kbd.
  Uncoordinated policy for comparison: {'exhausts the reserve on day ' + str(cf.get('exhausted_on_day')) if cf.get('exhausted_on_day') else 'survives the shock'}.
"""


def _fallback(result: dict[str, Any]) -> str:
    """Deterministic narration built from the same numbers the LLM would see."""
    cascade = result["cascade"]
    plan = result["procurement"]
    spr = result["spr"]
    h = cascade["headline"]
    stage2 = cascade["stages"][1]

    worst = stage2["by_refinery"][0] if stage2["by_refinery"] else None
    binding = plan["binding"][0]["explanation"] if plan["binding"] else None
    cf = spr.get("counterfactual", {})

    p1 = (
        f"The shock removes {h['net_lost_kbd']:,.0f} kbd of crude, "
        f"{h['lost_pct_of_imports']}% of imports, for {h['duration_days']} days. "
    )
    if worst and worst["cut_kbd"] > 0:
        p1 += (
            f"{worst['refinery']} is worst hit, running at "
            f"{worst['utilisation_pct']}% because {worst['binding']}. "
        )
    p1 += (
        f"There are {stage2['stranded_spare_kbd']:,.0f} kbd of grade-compatible "
        f"barrels for sale that cannot reach an Indian berth inside the "
        f"{stage2['delivery_budget_days']:.0f}-day window."
    )

    if plan["lines"]:
        top = plan["lines"][0]
        p2 = (
            f"The optimiser closes {plan['coverage_pct']}% of the gap for "
            f"${plan['cost_delta_usd_mn']}mn above baseline crude cost "
            f"(INR {plan['cost_delta_inr_crore']:,.0f} crore). The largest single "
            f"line is {top['volume_kb']:,.0f} kb of {top['grade']} from "
            f"{top['country']} into {top['refinery']} on a {top['vessel_class']}, "
            f"first berthing on day {top['first_delivery_day']}. "
        )
    else:
        p2 = "The optimiser found no feasible replacement cargoes. "
    if binding:
        p2 += f"{binding}"

    p3 = (
        f"Until those cargoes land the strategic reserve carries the gap, drawing "
        f"{spr['total_drawn_mmbbl']} mmbbl and holding {spr['end_buffer_mmbbl']} mmbbl "
        f"back as a buffer. "
    )
    if cf.get("exhausted_on_day"):
        p3 += (
            f"Meeting the shortfall in full from day one instead would empty the "
            f"reserve on day {cf['exhausted_on_day']}, before the shock ends. "
        )
    if plan["unmet_kb"] > 1:
        p3 += (
            f"Even so, {plan['unmet_kb']:,.0f} kb of demand goes unserved — this "
            f"plan mitigates the shock, it does not eliminate it."
        )
    else:
        p3 += "The plan closes the gap."

    return f"{p1}\n\n{p2}\n\n{p3}"


async def narrate_plan(result: dict[str, Any]) -> dict[str, Any]:
    facts = _facts(result)
    text = None
    if llm_available():
        text = await complete(
            system=SYSTEM,
            user=facts,
            max_tokens=1200,
            effort="medium",
        )

    if text:
        return {
            "text": text,
            "mode": "llm",
            "generator": provider_label(),
            # Name the model that actually wrote this. Attributing Groq output
            # to Claude would be exactly the kind of quiet inaccuracy the
            # honesty legend exists to prevent.
            "model_note": f"{provider_label()} narrating solver output; all "
                          f"figures come from the LP and cascade, not from "
                          f"the model.",
            "provenance": Provenance.SIMULATED,
        }

    return {
        "text": _fallback(result),
        "mode": "deterministic",
        "generator": "deterministic template",
        "model_note": "No LLM provider configured (set GROQ_API_KEY or "
                      "ANTHROPIC_API_KEY) — this narration is a deterministic "
                      "template over the same solver output, not a language "
                      "model.",
        "provenance": Provenance.SIMULATED,
    }
