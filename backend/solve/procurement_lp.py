"""Procurement reallocation LP (OR-Tools / GLOP).

Given a supply gap per refinery, decide which alternative barrels to buy, on
which vessel class, into which port, in which week -- subject to the physical
constraints that make a recommendation executable rather than generic:

    * crude diet      API gravity and sulfur must fit the refinery's spec
    * liftability     a supplier cannot sell more than its spare capacity
    * tanker pools    prompt tonnage by class and region is finite
    * voyage time     a cargo fixed in week w lands in week w + transit
    * berth capacity  a port can only discharge so much per week

Two design decisions matter:

* We solve a continuous LP with GLOP rather than an integer program. Barrels
  are near-continuous at this scale, and the LP relaxation buys us **dual
  values** -- which is how we name the binding constraint honestly ("limited by
  VLCC availability, not supply") instead of guessing at it.

* Unmet demand is an explicit slack variable with a shadow price, not an
  infeasibility. A plan that cannot fully close the gap is still the best
  available plan, and the operator needs to see how much is left uncovered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ortools.linear_solver import pywraplp

from backend.config import Provenance
from backend.data import loaders
from backend.solve.regions import EAST_COAST_PORTS, FREIGHT_FAMILY, TANKER_POOL

# Cost of failing to deliver a barrel that a refinery needs, in $/bbl. Set well
# above any physical procurement cost so the solver exhausts every real option
# before it accepts a shortfall, while still preferring a small shortfall to an
# absurdly expensive cargo.
UNMET_PENALTY_USD_BBL = 250.0

BASE_CRUDE_USD_BBL = 82.0


@dataclass
class ProcurementPlan:
    status: str
    lines: list[dict[str, Any]] = field(default_factory=list)
    covered_kb: float = 0.0
    gap_kb: float = 0.0
    unmet_kb: float = 0.0
    shortfall_barrel_weeks: float = 0.0
    cost_delta_usd_mn: float = 0.0
    first_delivery_day: float | None = None
    binding: list[dict[str, Any]] = field(default_factory=list)
    horizon_weeks: int = 0
    solve_ms: float = 0.0
    provenance: str = Provenance.SIMULATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "lines": self.lines,
            "covered_kb": round(self.covered_kb, 1),
            "gap_kb": round(self.gap_kb, 1),
            "unmet_kb": round(self.unmet_kb, 1),
            "shortfall_barrel_weeks": round(self.shortfall_barrel_weeks, 1),
            "coverage_pct": round(
                100.0 * min(self.covered_kb, self.gap_kb) / self.gap_kb, 1
            ) if self.gap_kb > 0 else 100.0,
            "cost_delta_usd_mn": round(self.cost_delta_usd_mn, 2),
            "cost_delta_inr_crore": round(self.cost_delta_usd_mn * 8.65, 1),
            "first_delivery_day": self.first_delivery_day,
            "binding": self.binding,
            "horizon_weeks": self.horizon_weeks,
            "solve_ms": round(self.solve_ms, 1),
            "provenance": self.provenance,
        }


def _freight_lookup() -> dict[tuple[str, str], float]:
    fr = loaders.freight()
    return {
        (r["route_family"], r["vessel_class"]): float(r["usd_per_bbl"])
        for _, r in fr.iterrows()
    }


def _tanker_lookup() -> dict[tuple[str, str], tuple[float, float]]:
    """(region, class) -> (vessels available in 30d, cargo size kb)."""
    ta = loaders.tanker_availability()
    return {
        (r["region"], r["vessel_class"]):
            (float(r["vessels_available_30d"]), float(r["cargo_size_kb"]))
        for _, r in ta.iterrows()
    }


def solve_procurement(
    gap_by_refinery_kbd: dict[str, float],
    duration_days: int,
    disrupted_suppliers: dict[str, float] | None = None,
    reroute_lag_days: float = 4.0,
    horizon_weeks: int | None = None,
) -> ProcurementPlan:
    """Find the cheapest feasible reallocation that closes the supply gap.

    `gap_by_refinery_kbd` is the per-refinery crude shortfall from the cascade.
    `disrupted_suppliers` maps supplier_id -> blocked fraction, so the solver
    cannot "solve" a Hormuz closure by buying more Basrah.
    """
    disrupted = disrupted_suppliers or {}
    W = horizon_weeks or max(4, math.ceil(duration_days / 7))

    ref = loaders.refineries().set_index("refinery_id")
    sup = loaders.suppliers().set_index("supplier_id")
    imp = loaders.imports_baseline().set_index("supplier_id")
    routes = loaders.routes()
    gc = loaders.grade_compatibility()
    freight = _freight_lookup()
    tankers = _tanker_lookup()

    compatible = {
        (r["refinery_id"], r["supplier_id"])
        for _, r in gc[gc["compatible"]].iterrows()
    }

    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        return ProcurementPlan(status="NO_SOLVER")
    solver.SetTimeLimit(10_000)

    # ---------------------------------------------------------------- vars
    # x[(sid, rid, vclass, week)] = kb procured, fixed in `week`
    x: dict[tuple[str, str, str, int], Any] = {}
    meta: dict[tuple[str, str, str, int], dict[str, Any]] = {}

    lag_weeks = reroute_lag_days / 7.0

    for _, rt in routes.iterrows():
        sid = rt["supplier_id"]
        port = rt["discharge_port"]
        vclass = rt["vessel_class"]

        # Which modelled refineries sit behind this discharge port?
        rids = ref.index[ref["primary_port"] == port].tolist()
        if not rids:
            continue

        # You cannot charter a vessel class that does not trade in the loading
        # region. Without this the solver quietly routes around every tonnage
        # constraint by picking a class we never counted hulls for.
        pool = TANKER_POOL.get(sup.loc[sid, "region"])
        if pool is None or (pool, vclass) not in tankers:
            continue

        transit_weeks = (float(rt["voyage_days"]) + reroute_lag_days) / 7.0

        for rid in rids:
            if (rid, sid) not in compatible:
                continue
            if gap_by_refinery_kbd.get(rid, 0.0) <= 0:
                continue
            for w in range(W):
                # Delivery must land inside the horizon to be useful.
                deliver_week = w + transit_weeks
                if deliver_week > W:
                    continue
                key = (sid, rid, vclass, w)
                if key in x:
                    continue
                x[key] = solver.NumVar(0.0, solver.infinity(), f"x_{sid}_{rid}_{vclass}_{w}")
                meta[key] = {
                    "supplier_id": sid,
                    "refinery_id": rid,
                    "vessel_class": vclass,
                    "week": w,
                    "port": port,
                    "voyage_days": float(rt["voyage_days"]),
                    "deliver_day": float(rt["voyage_days"]) + reroute_lag_days,
                    "deliver_week": deliver_week,
                }

    if not x:
        return ProcurementPlan(status="NO_FEASIBLE_ROUTES", horizon_weeks=W)

    # Cumulative shortfall at the end of each week. Penalising every week it
    # stays open makes the objective a genuine days-of-cover shortfall: a
    # barrel that is three weeks late costs three times a barrel one week late.
    u: dict[tuple[str, int], Any] = {}
    for rid, kbd in gap_by_refinery_kbd.items():
        if kbd <= 0:
            continue
        for w in range(W):
            u[(rid, w)] = solver.NumVar(0.0, solver.infinity(), f"u_{rid}_{w}")

    # Which week does each cargo actually land in?
    by_refinery_week: dict[str, list[tuple[Any, int]]] = {}
    for key, var in x.items():
        rid = key[1]
        dw = int(math.floor(meta[key]["deliver_week"]))
        by_refinery_week.setdefault(rid, []).append((var, dw))

    # --------------------------------------------------------- constraints
    named: dict[str, Any] = {}

    # 1) Demand, cumulatively. By the end of week w the refinery has needed
    #    (w+1) weeks of crude, and can only have received cargoes that landed
    #    by then. Anything still missing shows up as cumulative shortfall.
    for rid, kbd in gap_by_refinery_kbd.items():
        if kbd <= 0:
            continue
        need_kb_week = kbd * 7.0
        for w in range(W):
            ct = solver.Constraint(need_kb_week * (w + 1), solver.infinity(),
                                   f"demand_{rid}_{w}")
            for var, dw in by_refinery_week.get(rid, []):
                if dw <= w:
                    ct.SetCoefficient(var, 1.0)
            ct.SetCoefficient(u[(rid, w)], 1.0)
            named[f"demand_{rid}_{w}"] = ct

    # 2) Supplier liftability: only spare capacity is for sale, and a disrupted
    #    supplier's spare shrinks with the disruption.
    for sid in sup.index:
        base = float(imp.loc[sid, "barrels_per_week_kb"]) / 7.0 if sid in imp.index else 0.0
        spare_kbd = max(0.0, float(sup.loc[sid, "max_liftable_kbd"]) - base)
        spare_kbd *= (1.0 - disrupted.get(sid, 0.0))
        cap_kb_week = spare_kbd * 7.0
        for w in range(W):
            vars_w = [v for k, v in x.items() if k[0] == sid and k[3] == w]
            if not vars_w:
                continue
            ct = solver.Constraint(0.0, cap_kb_week, f"lift_{sid}_{w}")
            for v in vars_w:
                ct.SetCoefficient(v, 1.0)
            named[f"lift_{sid}_{w}"] = ct

    # 3) Tanker availability: finite hulls per pool, per class, per week.
    pools: dict[tuple[str, str], list[tuple[Any, float]]] = {}
    for key, var in x.items():
        sid, _, vclass, w = key
        region = TANKER_POOL.get(sup.loc[sid, "region"])
        if region is None:
            continue
        cargo = tankers.get((region, vclass))
        if cargo is None:
            continue  # that pool has no hulls of this class at all
        pools.setdefault((region, vclass, w), []).append((var, cargo[1]))  # type: ignore[arg-type]

    for (region, vclass, w), entries in pools.items():  # type: ignore[misc]
        avail, cargo_kb = tankers[(region, vclass)]
        # Spread the 30-day prompt list across the weeks in the horizon.
        weekly_hulls = avail * 7.0 / 30.0
        ct = solver.Constraint(0.0, weekly_hulls, f"tanker_{region}_{vclass}_{w}")
        for var, csize in entries:
            ct.SetCoefficient(var, 1.0 / csize)  # volume -> vessel count
        named[f"tanker_{region}_{vclass}_{w}"] = ct

    # 4) Berth capacity per discharge port per week.
    port_caps: dict[str, float] = {}
    for rid, r in ref.iterrows():
        port_caps[r["primary_port"]] = port_caps.get(r["primary_port"], 0.0) + float(
            r["berth_capacity_kbd"]
        )
    for port, cap_kbd in port_caps.items():
        for w in range(W):
            vars_w = [v for k, v in x.items()
                      if meta[k]["port"] == port and math.floor(meta[k]["deliver_week"]) == w]
            if not vars_w:
                continue
            ct = solver.Constraint(0.0, cap_kbd * 7.0, f"berth_{port}_{w}")
            for v in vars_w:
                ct.SetCoefficient(v, 1.0)
            named[f"berth_{port}_{w}"] = ct

    # ----------------------------------------------------------- objective
    objective = solver.Objective()
    for key, var in x.items():
        sid = key[0]
        vclass = key[2]
        region = sup.loc[sid, "region"]
        family = FREIGHT_FAMILY.get(region, "AG-WCIndia")
        frt = freight.get((family, vclass))
        if frt is None:
            frt = max(v for (f, c), v in freight.items() if f == family) \
                if any(f == family for f, _ in freight) else 4.0
        east_uplift = 0.45 if meta[key]["port"] in EAST_COAST_PORTS else 0.0
        unit_cost = (
            BASE_CRUDE_USD_BBL
            + float(sup.loc[sid, "spot_premium_usd_bbl"])
            + frt
            + east_uplift
        )
        # x is in thousands of barrels, so $/bbl * kb = thousands of dollars.
        objective.SetCoefficient(var, unit_cost)
        meta[key]["unit_cost_usd_bbl"] = round(unit_cost, 2)
        meta[key]["freight_usd_bbl"] = round(frt + east_uplift, 2)

    for var in u.values():
        objective.SetCoefficient(var, UNMET_PENALTY_USD_BBL)
    objective.SetMinimization()

    status = solver.Solve()
    status_name = {
        pywraplp.Solver.OPTIMAL: "OPTIMAL",
        pywraplp.Solver.FEASIBLE: "FEASIBLE",
        pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
        pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
        pywraplp.Solver.ABNORMAL: "ABNORMAL",
        pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
    }.get(status, str(status))

    plan = ProcurementPlan(status=status_name, horizon_weeks=W,
                           solve_ms=solver.wall_time())
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return plan

    # ------------------------------------------------------------ extract
    agg: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, var in x.items():
        val = var.solution_value()
        if val <= 1e-4:
            continue
        sid, rid, vclass, w = key
        k = (sid, rid, vclass)
        m = meta[key]
        if k not in agg:
            agg[k] = {
                "supplier_id": sid,
                "grade": sup.loc[sid, "grade"],
                "country": sup.loc[sid, "country"],
                "refinery_id": rid,
                "refinery": ref.loc[rid, "name"],
                "port": m["port"],
                "vessel_class": vclass,
                "voyage_days": m["voyage_days"],
                "first_delivery_day": round(m["deliver_day"], 1),
                "volume_kb": 0.0,
                "unit_cost_usd_bbl": m["unit_cost_usd_bbl"],
                "freight_usd_bbl": m["freight_usd_bbl"],
                "api_gravity": float(sup.loc[sid, "api_gravity"]),
                "sulfur_pct": float(sup.loc[sid, "sulfur_pct"]),
                "pricing_formula": sup.loc[sid, "pricing_formula"],
                "load_port": sup.loc[sid, "load_port"],
            }
        agg[k]["volume_kb"] += val
        agg[k]["first_delivery_day"] = min(
            agg[k]["first_delivery_day"], round(m["deliver_day"], 1)
        )

    lines = sorted(agg.values(), key=lambda d: -d["volume_kb"])
    for ln in lines:
        ln["volume_kb"] = round(ln["volume_kb"], 1)
        ln["cargoes"] = round(
            ln["volume_kb"] / tankers.get(
                (TANKER_POOL.get(sup.loc[ln["supplier_id"], "region"], ""), ln["vessel_class"]),
                (1, 1000),
            )[1], 2
        )
        ln["cost_usd_mn"] = round(ln["volume_kb"] * ln["unit_cost_usd_bbl"] / 1000.0, 2)

    # Total crude the refineries needed across the horizon.
    gap_kb = sum(v * 7.0 for v in gap_by_refinery_kbd.values()) * W
    covered_kb = sum(ln["volume_kb"] for ln in lines)
    # Barrels never delivered = the shortfall still open in the final week.
    # (Summing every week would count the same missing barrel once per week --
    # that quantity is the days-of-cover penalty, not a volume.)
    unmet_kb = sum(
        u[(rid, W - 1)].solution_value()
        for rid in gap_by_refinery_kbd
        if (rid, W - 1) in u
    )
    shortfall_barrel_weeks = sum(v.solution_value() for v in u.values())

    # Cost delta is what these replacement barrels cost above the baseline
    # crude price -- the premium of the plan, not the whole oil bill.
    cost_delta = sum(
        ln["volume_kb"] * (ln["unit_cost_usd_bbl"] - BASE_CRUDE_USD_BBL) / 1000.0
        for ln in lines
    )

    plan.lines = lines
    plan.gap_kb = gap_kb
    plan.unmet_kb = unmet_kb
    plan.covered_kb = covered_kb
    plan.shortfall_barrel_weeks = shortfall_barrel_weeks
    plan.cost_delta_usd_mn = cost_delta
    plan.first_delivery_day = min((ln["first_delivery_day"] for ln in lines),
                                  default=None)
    plan.binding = _binding_constraints(named, tankers, sup, ref, disrupted)
    return plan


def _binding_constraints(named: dict[str, Any], tankers, sup, ref,
                         disrupted: dict[str, float] | None = None,
                         top_n: int = 5) -> list[dict[str, Any]]:
    """Name the constraints actually limiting the plan, via LP dual values.

    A non-zero dual means relaxing that constraint by one unit would improve
    the objective -- i.e. that constraint, not supply in general, is what is
    holding the plan back. This is what lets us say "limited by VLCC
    availability" and mean it.
    """
    disrupted = disrupted or {}
    scored: list[dict[str, Any]] = []
    for name, ct in named.items():
        try:
            dual = ct.dual_value()
        except Exception:
            continue
        if abs(dual) < 1e-6:
            continue

        kind, *rest = name.split("_")
        if kind == "tanker":
            region, vclass, week = rest[0], rest[1], rest[2]
            label = f"{vclass} tonnage in {region}"
            human = (f"Limited by {vclass} availability out of {region}, "
                     f"not by crude supply.")
        elif kind == "lift":
            sid = rest[0]
            grade = sup.loc[sid, "grade"] if sid in sup.index else sid
            blocked = disrupted.get(sid, 0.0)
            if blocked > 0.01:
                # Distinguish "the market is tight" from "we did this to them".
                label = f"{grade} blocked by the shock"
                human = (f"{grade} is {blocked * 100:.0f}% blocked by the "
                         f"disruption itself -- the barrels exist but cannot move.")
            else:
                label = f"{grade} liftable volume"
                human = f"Limited by how much {grade} is actually for sale."
        elif kind == "berth":
            port = "_".join(rest[:-1])
            label = f"{port} berth capacity"
            human = f"Limited by discharge capacity at {port}."
        elif kind == "demand":
            continue  # demand duals are the shadow price of the gap itself
        else:
            label, human = name, name

        scored.append({
            "constraint": name,
            "label": label,
            "explanation": human,
            "shadow_price_usd_bbl": round(abs(dual), 2),
            "kind": kind,
        })

    scored.sort(key=lambda d: -d["shadow_price_usd_bbl"])

    # Collapse the same constraint repeated across weeks into one line.
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for s in scored:
        if s["label"] in seen:
            continue
        seen.add(s["label"])
        out.append(s)
        if len(out) >= top_n:
            break
    return out
