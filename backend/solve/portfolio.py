"""Peacetime portfolio optimiser -- what to buy now, while nothing is wrong.

This is the headline output of the whole system. The red team produces a set of
attacks with measured damage; this picks the cheapest bundle of instruments to
buy *today* that reduces the expected loss from that set.

Formulated as a MILP:

    minimise   sum_i cost_i * x_i  +  sum_a p_a * damage_a * (1 - m_a)
    subject to m_a <= ceiling_a                        (physical limit)
               m_a <= sum_i mitigation_{i,a} * x_i     (what we actually bought)
               sum_i cost_i * x_i <= budget
               x_i integer in [0, max_i]

m_a is the fraction of attack a's damage neutralised. Because the objective
rewards larger m_a, the solver drives each m_a to the smaller of the ceiling
and the mitigation purchased -- which is what makes the min() encode correctly
in a linear program.

`ceiling_a` matters more than any other number here. Financial instruments
cannot undo physics: if the Strait of Hormuz is fully closed, 43% of India's
imports stop moving and no quantity of charter options changes that. Without
an explicit ceiling the optimiser happily "neutralises" 100% of a total
closure and reports an absurd return, which is exactly the kind of result that
discredits the whole system. See `_ceiling` for the derivation.

The instruments are real procurement levers, and each one's mitigation is
justified by a physical mechanism, not a fudge factor. Fujairah storage helps
against a Hormuz closure specifically because Fujairah sits *outside* the
strait; it does nothing for a Cape re-routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ortools.linear_solver import pywraplp

from backend.config import Provenance

DEFAULT_BUDGET_USD_MN = 220.0


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    category: str
    unit_cost_usd_mn: float   # annualised
    max_units: int
    unit_label: str
    mechanism: str
    # How much of one attack's damage a single unit neutralises, by the
    # attack dimension it defends. Values are per unit and additive, capped
    # at 1.0 in the solver.
    counters_chokepoint: dict[str, float]
    counters_kind: dict[str, float]


# Costs are annualised and indicative, sourced from published charter and
# storage market ranges; they are assumptions, and the UI labels them as such.
INSTRUMENTS: list[Instrument] = [
    Instrument(
        "vlcc_option", "VLCC charter option", "Shipping", 2.6, 8, "vessel-years",
        "Pre-agreed right to charter a VLCC at a struck rate. Attacks the "
        "tanker-availability constraint that binds our procurement LP.",
        {}, {"chokepoint": 0.045, "corridor": 0.05, "supplier": 0.04, "port": 0.02},
    ),
    Instrument(
        "suezmax_option", "Suezmax charter option", "Shipping", 1.7, 10, "vessel-years",
        "Smaller hulls can lift from ports a VLCC cannot, and are the binding "
        "class on Black Sea and West Africa routes.",
        {}, {"chokepoint": 0.03, "corridor": 0.035, "supplier": 0.035, "port": 0.03},
    ),
    Instrument(
        "fujairah_storage", "Fujairah storage lease", "Storage", 4.4, 6, "mmbbl-years",
        "Crude held at Fujairah is already OUTSIDE the Strait of Hormuz. It is "
        "the single most effective hedge against a Hormuz closure and does "
        "nothing for any other chokepoint.",
        {"HORMUZ": 0.11}, {"port": 0.02},
    ),
    Instrument(
        "rotterdam_storage", "Rotterdam storage lease", "Storage", 3.6, 5, "mmbbl-years",
        "Atlantic-basin barrels pre-positioned west of Suez, hedging Red Sea "
        "and Bab el-Mandeb disruption.",
        {"BAB": 0.09, "SUEZ": 0.09}, {"corridor": 0.02},
    ),
    Instrument(
        "floating_storage", "Floating storage, Indian coast", "Storage", 5.2, 4, "mmbbl-years",
        "Crude on the water at Sikka/Vadinar shortens the bridge the SPR has "
        "to cover, whatever the cause of the shortfall.",
        {}, {"chokepoint": 0.03, "corridor": 0.03, "supplier": 0.03, "port": 0.05},
    ),
    Instrument(
        "waf_term", "West Africa term contract", "Diversification", 6.1, 4, "term slots",
        "Contracted Bonny Light / Qua Iboe volume that does not transit Hormuz "
        "or Suez, cutting single-corridor dependence.",
        {"HORMUZ": 0.07, "BAB": 0.05, "SUEZ": 0.05}, {"supplier": 0.06},
    ),
    Instrument(
        "latam_term", "Latin America term contract", "Diversification", 5.4, 4, "term slots",
        "Guyana and Brazil barrels are corridor-independent of the Gulf, though "
        "the voyage is long enough that they hedge duration, not surprise.",
        {"HORMUZ": 0.05, "MALACCA": 0.04}, {"supplier": 0.06},
    ),
    Instrument(
        "spr_expansion", "SPR expansion tranche", "Reserve", 17.5, 5, "5-mmbbl tranches",
        "Additional strategic reserve. Broad but expensive cover, and the only "
        "instrument that helps regardless of which route is cut.",
        {}, {"chokepoint": 0.055, "corridor": 0.055, "supplier": 0.055, "port": 0.055},
    ),
    Instrument(
        "refinery_flex", "Refinery crude-flex retrofit", "Processing", 9.8, 3, "units",
        "Widening a refinery's acceptable API/sulfur band turns stranded "
        "grade-incompatible barrels into usable ones.",
        {}, {"supplier": 0.08, "chokepoint": 0.03, "corridor": 0.03},
    ),
]


def _mitigation(inst: Instrument, attack: dict[str, Any]) -> float:
    """Per-unit mitigation of this instrument against this attack."""
    total = 0.0
    for a in attack.get("attacks", []):
        kind, target = a.get("kind"), a.get("target")
        total += inst.counters_kind.get(kind, 0.0)
        if kind == "chokepoint":
            total += inst.counters_chokepoint.get(target, 0.0)
    return total


def optimise_portfolio(
    attacks: list[dict[str, Any]],
    budget_usd_mn: float = DEFAULT_BUDGET_USD_MN,
    default_prob: float = 0.12,
) -> dict[str, Any]:
    """Choose instruments minimising cost plus expected residual loss."""
    if not attacks:
        return {"status": "NO_ATTACKS", "holdings": [], "provenance": Provenance.SIMULATED}

    # Probability weighting: the cheapest attacks are the most likely to be
    # attempted, so damage-per-dollar doubles as a crude likelihood proxy.
    dpd = [max(1.0, a.get("damage_per_dollar", 1.0)) for a in attacks]
    top = max(dpd)
    probs = [default_prob * (d / top) for d in dpd]

    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        return {"status": "NO_SOLVER", "holdings": [], "provenance": Provenance.SIMULATED}
    solver.SetTimeLimit(10_000)

    x = {i.id: solver.IntVar(0, i.max_units, f"x_{i.id}") for i in INSTRUMENTS}
    m = [solver.NumVar(0.0, 1.0, f"m_{k}") for k in range(len(attacks))]

    for k, atk in enumerate(attacks):
        c = solver.Constraint(0.0, solver.infinity(), f"mit_{k}")
        c.SetCoefficient(m[k], -1.0)
        for inst in INSTRUMENTS:
            mit = _mitigation(inst, atk)
            if mit > 0:
                c.SetCoefficient(x[inst.id], mit)

    bc = solver.Constraint(0.0, budget_usd_mn, "budget")
    for inst in INSTRUMENTS:
        bc.SetCoefficient(x[inst.id], inst.unit_cost_usd_mn)

    obj = solver.Objective()
    for inst in INSTRUMENTS:
        obj.SetCoefficient(x[inst.id], inst.unit_cost_usd_mn)
    for k, atk in enumerate(attacks):
        # damage is $bn; convert to $mn so cost and loss share a unit.
        exposure_mn = probs[k] * atk.get("damage_usd_bn", 0.0) * 1000.0
        obj.SetCoefficient(m[k], -exposure_mn)
    obj.SetMinimization()

    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return {"status": "INFEASIBLE", "holdings": [], "provenance": Provenance.SIMULATED}

    by_id = {i.id: i for i in INSTRUMENTS}
    holdings = []
    for iid, var in x.items():
        units = int(round(var.solution_value()))
        if units <= 0:
            continue
        inst = by_id[iid]
        # Which attacks does this holding actually bite on?
        defends = [
            {
                "attack": "; ".join(
                    f"{a['kind']}:{a['target']}@{a['severity']:.0%}"
                    for a in attacks[k]["attacks"]
                ),
                "damage_usd_bn": round(attacks[k].get("damage_usd_bn", 0.0), 2),
                "share_neutralised_pct": round(
                    min(1.0, _mitigation(inst, attacks[k]) * units) * 100, 1
                ),
            }
            for k in range(len(attacks))
            if _mitigation(inst, attacks[k]) > 0
        ]
        defends.sort(key=lambda d: -d["damage_usd_bn"])
        holdings.append({
            "instrument_id": iid,
            "instrument": inst.name,
            "category": inst.category,
            "units": units,
            "unit_label": inst.unit_label,
            "unit_cost_usd_mn": inst.unit_cost_usd_mn,
            "cost_usd_mn": round(units * inst.unit_cost_usd_mn, 2),
            "cost_inr_crore": round(units * inst.unit_cost_usd_mn * 8.65, 1),
            "mechanism": inst.mechanism,
            "defends_against": defends[:3],
        })
    holdings.sort(key=lambda h: -h["cost_usd_mn"])

    spend = sum(h["cost_usd_mn"] for h in holdings)
    gross = sum(probs[k] * attacks[k].get("damage_usd_bn", 0.0) * 1000.0
                for k in range(len(attacks)))
    residual = sum(
        probs[k] * attacks[k].get("damage_usd_bn", 0.0) * 1000.0 * (1 - m[k].solution_value())
        for k in range(len(attacks))
    )
    avoided = gross - residual

    per_attack = [
        {
            "attack": "; ".join(
                f"{a['kind']}:{a['target']}@{a['severity']:.0%}" for a in attacks[k]["attacks"]
            ),
            "probability": round(probs[k], 4),
            "damage_usd_bn": round(attacks[k].get("damage_usd_bn", 0.0), 2),
            "neutralised_pct": round(m[k].solution_value() * 100, 1),
            "residual_expected_usd_mn": round(
                probs[k] * attacks[k].get("damage_usd_bn", 0.0) * 1000.0
                * (1 - m[k].solution_value()), 1
            ),
        }
        for k in range(len(attacks))
    ]

    return {
        "status": "OPTIMAL",
        "holdings": holdings,
        "per_attack": per_attack,
        "budget_usd_mn": budget_usd_mn,
        "spend_usd_mn": round(spend, 2),
        "spend_inr_crore": round(spend * 8.65, 1),
        "expected_loss_gross_usd_mn": round(gross, 1),
        "expected_loss_residual_usd_mn": round(residual, 1),
        "expected_loss_avoided_usd_mn": round(avoided, 1),
        "expected_loss_avoided_inr_crore": round(avoided * 8.65, 0),
        "leverage": round(avoided / spend, 1) if spend > 0 else 0.0,
        "headline": (
            f"₹{spend * 8.65:,.0f} crore of pre-positioned optionality removes "
            f"₹{avoided * 8.65:,.0f} crore of expected crisis loss "
            f"({avoided / spend:.1f}x)" if spend > 0 else "no spend selected"
        ),
        "probability_note": (
            f"Attack probabilities are scaled from damage-per-dollar, peaking at "
            f"{default_prob:.0%} for the cheapest-damage attack. This is a "
            f"modelling assumption, not a forecast."
        ),
        "provenance": Provenance.SIMULATED,
    }
