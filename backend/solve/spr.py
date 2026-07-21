"""Strategic reserve drawdown optimiser.

The reserve is a bridge, not a solution. Its whole job is to hold the system
together during the window between the shock landing and the first replacement
cargo berthing -- a window the procurement LP measures for us.

The interesting result is not "draw down the SPR". It is that the obvious
policy -- meet the shortfall in full, every day, starting immediately -- burns
the reserve before the replacement barrels arrive and leaves nothing for the
back half of the shock. We compute both and show the difference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ortools.linear_solver import pywraplp

from backend.config import Provenance
from backend.data import loaders

# Fraction of the reserve to still hold at the end of the modelled shock.
# A reserve at zero has no deterrent value and no capacity for a second event.
DEFAULT_END_BUFFER_PCT = 0.15


@dataclass
class SprPlan:
    status: str
    days: list[dict[str, Any]] = field(default_factory=list)
    by_site: list[dict[str, Any]] = field(default_factory=list)
    total_drawn_kb: float = 0.0
    total_available_kb: float = 0.0
    peak_unserved_kbd: float = 0.0
    total_unserved_kb: float = 0.0
    end_buffer_kb: float = 0.0
    counterfactual: dict[str, Any] = field(default_factory=dict)
    provenance: str = Provenance.SIMULATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "days": self.days,
            "by_site": self.by_site,
            "total_drawn_kb": round(self.total_drawn_kb, 1),
            "total_drawn_mmbbl": round(self.total_drawn_kb / 1000.0, 2),
            "total_available_kb": round(self.total_available_kb, 1),
            "utilisation_pct": round(
                100.0 * self.total_drawn_kb / self.total_available_kb, 1
            ) if self.total_available_kb else 0.0,
            "peak_unserved_kbd": round(self.peak_unserved_kbd, 1),
            "total_unserved_kb": round(self.total_unserved_kb, 1),
            "end_buffer_kb": round(self.end_buffer_kb, 1),
            "end_buffer_mmbbl": round(self.end_buffer_kb / 1000.0, 2),
            "counterfactual": self.counterfactual,
            "provenance": self.provenance,
        }


def residual_gap_curve(
    gross_gap_kbd: float,
    duration_days: int,
    first_delivery_day: float | None,
    covered_kbd: float,
    ramp_days: float = 7.0,
) -> list[float]:
    """Daily crude shortfall left after LP deliveries start arriving.

    Replacement cargoes do not all land on the same day, so coverage ramps in
    over roughly a week once the first vessel berths.
    """
    curve: list[float] = []
    for t in range(duration_days):
        if first_delivery_day is None or t < first_delivery_day:
            arrived = 0.0
        else:
            frac = min(1.0, (t - first_delivery_day) / max(1e-9, ramp_days))
            arrived = covered_kbd * frac
        curve.append(max(0.0, gross_gap_kbd - arrived))
    return curve


def _uncoordinated(curve: list[float], sites: list[dict[str, Any]]) -> dict[str, Any]:
    """The obvious policy: meet the shortfall in full until the tanks run dry."""
    remaining = {s["site_id"]: s["available_kb"] for s in sites}
    rates = {s["site_id"]: s["max_drawdown_kbd"] for s in sites}
    exhausted_day: int | None = None
    unserved_kb = 0.0
    drawn_kb = 0.0

    for t, need in enumerate(curve):
        left = need
        for sid in remaining:
            if left <= 0:
                break
            take = min(rates[sid], remaining[sid], left)
            remaining[sid] -= take
            drawn_kb += take
            left -= take
        unserved_kb += max(0.0, left)
        if exhausted_day is None and sum(remaining.values()) <= 1e-6:
            exhausted_day = t + 1

    return {
        "policy": "uncoordinated (meet shortfall in full, immediately)",
        "exhausted_on_day": exhausted_day,
        "survives_shock": exhausted_day is None,
        "total_drawn_kb": round(drawn_kb, 1),
        "total_unserved_kb": round(unserved_kb, 1),
        "end_buffer_kb": round(sum(remaining.values()), 1),
        "end_buffer_mmbbl": round(sum(remaining.values()) / 1000.0, 2),
    }


def solve_spr(
    curve: list[float],
    end_buffer_pct: float = DEFAULT_END_BUFFER_PCT,
) -> SprPlan:
    """Ration the reserve across the shock instead of spending it on day one."""
    spr = loaders.spr_sites()
    sites = [
        {
            "site_id": r["site_id"],
            "site": r["site"],
            "available_kb": float(r["capacity_mmbbl"]) * float(r["fill_pct"]) * 1000.0,
            "max_drawdown_kbd": float(r["max_drawdown_kbd"]),
            "notional_grade": r["notional_grade"],
        }
        for _, r in spr.iterrows()
    ]
    total_available = sum(s["available_kb"] for s in sites)
    T = len(curve)
    if T == 0:
        return SprPlan(status="NO_HORIZON", total_available_kb=total_available)

    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        return SprPlan(status="NO_SOLVER")

    d = {
        (s["site_id"], t): solver.NumVar(0.0, s["max_drawdown_kbd"], f"d_{s['site_id']}_{t}")
        for s in sites
        for t in range(T)
    }
    u = [solver.NumVar(0.0, solver.infinity(), f"u_{t}") for t in range(T)]
    peak = solver.NumVar(0.0, solver.infinity(), "peak_unserved")

    for t in range(T):
        # Cover the day's shortfall, or record what is left unserved.
        c = solver.Constraint(curve[t], solver.infinity(), f"cover_{t}")
        for s in sites:
            c.SetCoefficient(d[(s["site_id"], t)], 1.0)
        c.SetCoefficient(u[t], 1.0)

        # Never draw more than the shortfall -- crude with nowhere to go is
        # not a benefit, it is just an emptier reserve.
        c2 = solver.Constraint(0.0, curve[t], f"nowaste_{t}")
        for s in sites:
            c2.SetCoefficient(d[(s["site_id"], t)], 1.0)

        # Peak rationing: link every day to the minimax variable.
        c3 = solver.Constraint(0.0, solver.infinity(), f"peak_{t}")
        c3.SetCoefficient(peak, 1.0)
        c3.SetCoefficient(u[t], -1.0)

    # Per-site inventory.
    for s in sites:
        c = solver.Constraint(0.0, s["available_kb"], f"inv_{s['site_id']}")
        for t in range(T):
            c.SetCoefficient(d[(s["site_id"], t)], 1.0)

    # Hold a strategic buffer at the end of the shock.
    drawable = max(0.0, total_available * (1.0 - end_buffer_pct))
    cbuf = solver.Constraint(0.0, drawable, "end_buffer")
    for s in sites:
        for t in range(T):
            cbuf.SetCoefficient(d[(s["site_id"], t)], 1.0)

    # Minimise the worst day first, then total shortfall. Flattening the peak
    # is what turns "run out on day 9" into a survivable rationing plan.
    obj = solver.Objective()
    obj.SetCoefficient(peak, 1000.0)
    for t in range(T):
        obj.SetCoefficient(u[t], 1.0)
    obj.SetMinimization()

    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return SprPlan(status="INFEASIBLE", total_available_kb=total_available)

    days = []
    remaining = total_available
    for t in range(T):
        drawn = sum(d[(s["site_id"], t)].solution_value() for s in sites)
        remaining -= drawn
        days.append({
            "day": t,
            "gap_kbd": round(curve[t], 1),
            "spr_draw_kbd": round(drawn, 1),
            "unserved_kbd": round(u[t].solution_value(), 1),
            "spr_remaining_kb": round(remaining, 1),
            "spr_remaining_pct": round(100.0 * remaining / total_available, 1),
        })

    by_site = []
    for s in sites:
        drawn = sum(d[(s["site_id"], t)].solution_value() for t in range(T))
        by_site.append({
            "site_id": s["site_id"],
            "site": s["site"],
            "notional_grade": s["notional_grade"],
            "available_kb": round(s["available_kb"], 1),
            "drawn_kb": round(drawn, 1),
            "drawn_pct": round(100.0 * drawn / s["available_kb"], 1),
            "max_drawdown_kbd": s["max_drawdown_kbd"],
        })

    total_drawn = sum(b["drawn_kb"] for b in by_site)
    return SprPlan(
        status="OPTIMAL",
        days=days,
        by_site=by_site,
        total_drawn_kb=total_drawn,
        total_available_kb=total_available,
        peak_unserved_kbd=peak.solution_value(),
        total_unserved_kb=sum(x.solution_value() for x in u),
        end_buffer_kb=total_available - total_drawn,
        counterfactual=_uncoordinated(curve, sites),
    )
