"""Deterministic cascade engine.

Given a shock, propagate it through five stages:

    1. supply gap        which barrels stop arriving, net of re-routing
    2. refinery runs     who has to cut, respecting crude diet compatibility
    3. price             crude spike and how much reaches the pump
    4. sector stress     which products go short once diesel is protected
    5. macro             GDP and import-bill impact

Two properties matter more than sophistication:

* It is deterministic. Same shock plus same ledger gives the same numbers,
  every time, so a judge dragging a slider sees a real relationship rather
  than noise.
* It is unmitigated. This is the "we did nothing clever" counterfactual. The
  procurement LP in solve/ is what improves on it, and the gap between the two
  is the measurable value of the system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.config import INDIA_PRODUCT_DEMAND_KBD, Provenance
from backend.data import loaders
from backend.sim import twin
from backend.sim.assumptions import ledger_dict

# Global crude supply, used to turn India's lost barrels into a world price
# move. Source: IEA Oil Market Report, total world liquids supply ~103 mb/d.
GLOBAL_SUPPLY_KBD = 103_000.0
BASE_BRENT_USD = 82.0
INDIA_GDP_USD_BN = 3_900.0

ShockKind = Literal["chokepoint", "corridor", "supplier", "port"]


@dataclass
class Shock:
    """One hostile event. Scenarios are lists of these."""

    kind: ShockKind
    target: str
    severity: float          # 0..1 fraction of flow blocked
    duration_days: int
    start_day: int = 0
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "target": self.target, "severity": self.severity,
            "duration_days": self.duration_days, "start_day": self.start_day,
            "label": self.label or f"{self.target} {int(self.severity * 100)}%",
        }


@dataclass
class CascadeResult:
    shocks: list[dict[str, Any]]
    assumptions: dict[str, float]
    stages: list[dict[str, Any]] = field(default_factory=list)
    headline: dict[str, Any] = field(default_factory=dict)
    provenance: str = Provenance.SIMULATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "shocks": self.shocks,
            "assumptions": self.assumptions,
            "stages": self.stages,
            "headline": self.headline,
            "provenance": self.provenance,
        }


# --------------------------------------------------------------------------
# Stage 1 -- supply gap
# --------------------------------------------------------------------------
def _affected_suppliers(shock: Shock, g) -> dict[str, float]:
    """supplier_id -> fraction of its flow blocked by this shock."""
    hit: dict[str, float] = {}

    if shock.kind == "chokepoint":
        for corridor in twin.corridors_through(shock.target, g):
            for sid in twin.suppliers_on_corridor(corridor, g):
                hit[sid] = max(hit.get(sid, 0.0), shock.severity)

    elif shock.kind == "corridor":
        for sid in twin.suppliers_on_corridor(shock.target, g):
            hit[sid] = max(hit.get(sid, 0.0), shock.severity)

    elif shock.kind == "supplier":
        hit[shock.target] = shock.severity

    elif shock.kind == "port":
        # A blocked discharge port stops whatever normally lands there.
        imp = loaders.imports_baseline()
        for _, r in imp.iterrows():
            if r["typical_discharge_port"] == shock.target:
                hit[r["supplier_id"]] = max(
                    hit.get(r["supplier_id"], 0.0), shock.severity
                )

    return hit


def stage_supply_gap(shocks: list[Shock], a: dict[str, float], g) -> dict[str, Any]:
    imp = loaders.imports_baseline().set_index("supplier_id")
    chk = loaders.chokepoints().set_index("chokepoint_id")

    blocked: dict[str, float] = {}
    for s in shocks:
        for sid, frac in _affected_suppliers(s, g).items():
            blocked[sid] = max(blocked.get(sid, 0.0), frac)

    # Gross barrels stopped, before any bypass.
    per_supplier = []
    gross_lost_kbd = 0.0
    for sid, frac in blocked.items():
        if sid not in imp.index:
            continue
        base_kbd = float(imp.loc[sid, "barrels_per_week_kb"]) / 7.0
        lost = base_kbd * frac
        gross_lost_kbd += lost
        per_supplier.append({
            "supplier_id": sid,
            "corridor": imp.loc[sid, "corridor"],
            "baseline_kbd": round(base_kbd, 1),
            "blocked_frac": round(frac, 3),
            "lost_kbd": round(lost, 1),
        })

    # Pipeline bypass: only chokepoints with real bypass capacity offer relief,
    # and India can only claim its share of that capacity.
    bypass_kbd = 0.0
    bypass_detail = []
    for s in shocks:
        if s.kind != "chokepoint" or s.target not in chk.index:
            continue
        cap_kbd = float(chk.loc[s.target, "bypass_capacity_mbd"]) * 1000.0
        if cap_kbd <= 0:
            continue
        exposure = twin.exposure_to_chokepoint(s.target, g)
        global_kbd = float(chk.loc[s.target, "global_oil_transit_mbd"]) * 1000.0
        india_share = exposure["exposed_kbd"] / global_kbd if global_kbd else 0.0
        claim = cap_kbd * india_share * a["bypass_utilisation"]
        bypass_kbd += claim
        bypass_detail.append({
            "chokepoint": s.target,
            "bypass_capacity_kbd": round(cap_kbd, 0),
            "india_share_pct": round(india_share * 100, 2),
            "relief_kbd": round(claim, 1),
        })

    net_lost_kbd = max(0.0, gross_lost_kbd - bypass_kbd)
    baseline_kbd = float(imp["barrels_per_week_kb"].sum()) / 7.0

    # Push the bypass relief back down onto the individual suppliers, pro rata.
    # Without this the per-supplier losses still describe the gross shock, and
    # stage 2 would cut more refinery throughput than the crude actually lost.
    if gross_lost_kbd > 0 and bypass_kbd > 0:
        keep = net_lost_kbd / gross_lost_kbd
        for d in per_supplier:
            d["gross_lost_kbd"] = d["lost_kbd"]
            d["lost_kbd"] = round(d["lost_kbd"] * keep, 1)

    per_supplier.sort(key=lambda d: -d["lost_kbd"])
    return {
        "stage": 1,
        "name": "Supply gap",
        "baseline_import_kbd": round(baseline_kbd, 1),
        "gross_lost_kbd": round(gross_lost_kbd, 1),
        "bypass_relief_kbd": round(bypass_kbd, 1),
        "net_lost_kbd": round(net_lost_kbd, 1),
        "lost_pct_of_imports": round(100.0 * net_lost_kbd / baseline_kbd, 2),
        "by_supplier": per_supplier,
        "bypass_detail": bypass_detail,
        "reroute_lag_days": a["reroute_lag_days"],
    }


# --------------------------------------------------------------------------
# Stage 2 -- refinery run cuts, respecting crude diet
# --------------------------------------------------------------------------
def _min_voyage_days() -> dict[tuple[str, str], float]:
    """(supplier_id, discharge_port) -> fastest voyage across vessel classes."""
    rts = loaders.routes()
    return (
        rts.groupby(["supplier_id", "discharge_port"])["voyage_days"]
        .min()
        .to_dict()
    )


def stage_refinery(gap: dict[str, Any], shocks: list[Shock],
                   a: dict[str, float], g) -> dict[str, Any]:
    """Allocate the shortfall across refineries by what they can actually run.

    Two constraints make this non-generic, and both are the point of the system:

    * Crude diet. A refinery that loses heavy sour barrels cannot be rescued by
      light sweet ones sitting in the market.
    * Voyage time. A substitute barrel only counts if it can physically berth
      before the shock ends. West African and US Gulf crude is 25-45 days away,
      so it cannot patch a three-week Hormuz closure no matter how much of it
      is for sale. This is why "just buy from somewhere else" is not an answer.
    """
    ref = loaders.refineries()
    sup = loaders.suppliers().set_index("supplier_id")
    gc = loaders.grade_compatibility()
    imp = loaders.imports_baseline().set_index("supplier_id")
    voyage = _min_voyage_days()

    duration = max((s.duration_days for s in shocks), default=0)
    # Barrels have to be fixed, loaded and delivered inside the window.
    delivery_budget_days = max(0.0, duration - a["reroute_lag_days"])

    lost_by_supplier = {d["supplier_id"]: d["lost_kbd"] for d in gap["by_supplier"]}

    # Baseline crude allocation: split each supplier's barrels across the
    # refineries that can run that grade, weighted by refinery capacity.
    alloc: dict[str, dict[str, float]] = {r: {} for r in ref["refinery_id"]}
    cap = dict(zip(ref["refinery_id"], ref["capacity_kbd"]))

    for sid in imp.index:
        base_kbd = float(imp.loc[sid, "barrels_per_week_kb"]) / 7.0
        ok = gc[(gc["supplier_id"] == sid) & (gc["compatible"])]["refinery_id"].tolist()
        if not ok:
            continue
        total_cap = sum(cap[r] for r in ok)
        for r in ok:
            alloc[r][sid] = base_kbd * cap[r] / total_cap

    # Spare liftable capacity on grades that were NOT hit -- the only source of
    # substitute barrels.
    spare: dict[str, float] = {}
    for sid in sup.index:
        if lost_by_supplier.get(sid, 0.0) > 0:
            continue
        base = float(imp.loc[sid, "barrels_per_week_kb"]) / 7.0 if sid in imp.index else 0.0
        spare[sid] = max(0.0, float(sup.loc[sid, "max_liftable_kbd"]) - base)

    rows = []
    total_cut = 0.0
    total_base_run = 0.0
    for _, r in ref.iterrows():
        rid = r["refinery_id"]
        base_run = float(sum(alloc[rid].values()))
        total_base_run += base_run
        lost = sum(
            alloc[rid].get(sid, 0.0) * (lost_by_supplier.get(sid, 0.0)
                                        / max(1e-9, float(imp.loc[sid, "barrels_per_week_kb"]) / 7.0))
            for sid in alloc[rid]
            if sid in imp.index
        )

        # What can this refinery substitute in? Grade-compatible spare barrels
        # that can also physically arrive before the shock is over.
        compat = set(
            gc[(gc["refinery_id"] == rid) & (gc["compatible"])]["supplier_id"]
        )
        port = r["primary_port"]
        reachable: list[str] = []
        available_sub = 0.0
        for sid, vol in spare.items():
            if vol <= 0 or sid not in compat:
                continue
            days = voyage.get((sid, port))
            if days is None or days > delivery_budget_days:
                continue
            reachable.append(sid)
            available_sub += vol

        # Grade-compatible barrels that exist but are simply too far away.
        stranded = sum(
            v for sid, v in spare.items()
            if v > 0 and sid in compat and sid not in reachable
        )
        substituted = min(lost, available_sub) * a["substitution_efficiency"]

        cut = max(0.0, lost - substituted)
        min_run = base_run * a["refinery_min_run_pct"]
        run = base_run - cut
        tripped = run < min_run
        if tripped:
            # Below turndown the unit trips rather than throttling.
            run = 0.0 if run < min_run * 0.7 else min_run
        cut = base_run - run
        total_cut += cut

        rows.append({
            "refinery_id": rid,
            "refinery": r["name"],
            "capacity_kbd": float(r["capacity_kbd"]),
            "baseline_run_kbd": round(base_run, 1),
            "crude_lost_kbd": round(lost, 1),
            "substituted_kbd": round(substituted, 1),
            "run_kbd": round(run, 1),
            "cut_kbd": round(cut, 1),
            "utilisation_pct": round(100.0 * run / max(1e-9, base_run), 1),
            "reachable_spare_kbd": round(available_sub, 1),
            "stranded_spare_kbd": round(stranded, 1),
            "reachable_grades": [sup.loc[s, "grade"] for s in reachable
                                 if s in sup.index][:6],
            "tripped": bool(tripped),
            "binding": _binding_reason(lost, available_sub, stranded),
        })

    rows.sort(key=lambda d: -d["cut_kbd"])

    # Aggregate stranded volume is a property of the barrels, not of each
    # refinery, so it must be counted once per supplier. Summing the
    # per-refinery figures would count the same cargo twelve times.
    ports_needing_crude = {
        r["primary_port"] for _, r in ref.iterrows()
    }
    stranded_pool = 0.0
    stranded_grades: list[str] = []
    for sid, vol in spare.items():
        if vol <= 0:
            continue
        fastest = min(
            (voyage.get((sid, p), math.inf) for p in ports_needing_crude),
            default=math.inf,
        )
        if fastest > delivery_budget_days:
            stranded_pool += vol
            if sid in sup.index:
                stranded_grades.append(f"{sup.loc[sid, 'grade']} ({fastest:.0f}d)")

    return {
        "stage": 2,
        "name": "Refinery runs",
        "baseline_run_kbd": round(total_base_run, 1),
        "total_cut_kbd": round(total_cut, 1),
        "run_kbd": round(total_base_run - total_cut, 1),
        "utilisation_pct": round(
            100.0 * (total_base_run - total_cut) / max(1e-9, total_base_run), 1
        ),
        "refineries_tripped": sum(1 for r in rows if r["tripped"]),
        "delivery_budget_days": round(delivery_budget_days, 1),
        "stranded_spare_kbd": round(stranded_pool, 1),
        "stranded_grades": sorted(stranded_grades)[:8],
        "by_refinery": rows,
    }


def _binding_reason(lost: float, reachable: float, stranded: float) -> str:
    if lost <= 1e-6:
        return "unaffected"
    if reachable >= lost:
        return "substitution available in time"
    if stranded > lost - reachable:
        return "compatible barrels exist but are too far away to arrive in time"
    return "no grade-compatible spare crude available at any distance"


# --------------------------------------------------------------------------
# Stage 3 -- price
# --------------------------------------------------------------------------
def stage_price(gap: dict[str, Any], shocks: list[Shock],
                a: dict[str, float]) -> dict[str, Any]:
    # India's lost barrels are a loss to the world market too.
    world_loss_pct = 100.0 * gap["net_lost_kbd"] / GLOBAL_SUPPLY_KBD
    physical_pct = world_loss_pct * a["brent_supply_elasticity"]

    # Fear premium applies once, for chokepoint-class events, scaled by severity.
    worst = max((s.severity for s in shocks if s.kind == "chokepoint"), default=0.0)
    premium_usd = a["chokepoint_risk_premium_usd"] * worst

    brent = BASE_BRENT_USD * (1 + physical_pct / 100.0) + premium_usd
    brent_delta_pct = 100.0 * (brent - BASE_BRENT_USD) / BASE_BRENT_USD

    pump_pct = brent_delta_pct * a["price_passthrough"]

    return {
        "stage": 3,
        "name": "Price",
        "base_brent_usd": BASE_BRENT_USD,
        "world_supply_loss_pct": round(world_loss_pct, 3),
        "physical_price_pct": round(physical_pct, 2),
        "risk_premium_usd": round(premium_usd, 2),
        "brent_usd": round(brent, 2),
        "brent_delta_pct": round(brent_delta_pct, 2),
        "pump_price_delta_pct": round(pump_pct, 2),
        "passthrough": a["price_passthrough"],
    }


# --------------------------------------------------------------------------
# Stage 4 -- sector stress
# --------------------------------------------------------------------------
def stage_sector(refinery: dict[str, Any], price: dict[str, Any],
                 a: dict[str, float]) -> dict[str, Any]:
    # Lost crude runs become lost products roughly one-for-one on a volume basis.
    product_short_kbd = refinery["total_cut_kbd"]

    # Price does some of the rationing for us.
    destroyed = product_short_kbd * a["demand_destruction"]
    unserved = max(0.0, product_short_kbd - destroyed)

    unserved_pct = 100.0 * unserved / INDIA_PRODUCT_DEMAND_KBD

    # Diesel is protected, so the shortage concentrates elsewhere.
    diesel_share = 0.44
    diesel_demand = INDIA_PRODUCT_DEMAND_KBD * diesel_share
    diesel_short = unserved * (1.0 - a["diesel_priority_share"])
    other_short = unserved - diesel_short
    other_demand = INDIA_PRODUCT_DEMAND_KBD - diesel_demand

    return {
        "stage": 4,
        "name": "Sector stress",
        "product_short_kbd": round(product_short_kbd, 1),
        "demand_destroyed_kbd": round(destroyed, 1),
        "unserved_kbd": round(unserved, 1),
        "unserved_pct_of_demand": round(unserved_pct, 2),
        "diesel_short_kbd": round(diesel_short, 1),
        "diesel_short_pct": round(100.0 * diesel_short / diesel_demand, 2),
        "other_products_short_kbd": round(other_short, 1),
        "other_products_short_pct": round(100.0 * other_short / other_demand, 2),
        "sectors": [
            {"sector": "Road freight",
             "stress_pct": round(min(100.0, 100.0 * diesel_short / diesel_demand * 2.2), 1)},
            {"sector": "Agriculture (pumps, tractors)",
             "stress_pct": round(min(100.0, 100.0 * diesel_short / diesel_demand * 1.8), 1)},
            {"sector": "Aviation",
             "stress_pct": round(min(100.0, 100.0 * other_short / other_demand * 2.5), 1)},
            {"sector": "Power (diesel gensets)",
             "stress_pct": round(min(100.0, 100.0 * diesel_short / diesel_demand * 1.2), 1)},
            {"sector": "Petrochemicals",
             "stress_pct": round(min(100.0, 100.0 * other_short / other_demand * 1.9), 1)},
        ],
    }


# --------------------------------------------------------------------------
# Stage 5 -- macro
# --------------------------------------------------------------------------
def stage_macro(gap: dict[str, Any], price: dict[str, Any], sector: dict[str, Any],
                shocks: list[Shock], a: dict[str, float]) -> dict[str, Any]:
    duration = max((s.duration_days for s in shocks), default=0)
    year_frac = duration / 365.0

    # Channel 1: the price of the barrels we still buy.
    price_gdp_pct = (price["brent_delta_pct"] / 10.0) * a["gdp_pct_per_10pct_oil"]

    # Channel 2: the barrels that simply are not there.
    shortage_gdp_pct = sector["unserved_pct_of_demand"] * a["shortage_gdp_multiplier"]

    total_annualised_pct = price_gdp_pct + shortage_gdp_pct
    gdp_loss_usd_bn = INDIA_GDP_USD_BN * (total_annualised_pct / 100.0) * year_frac

    # Import bill: extra dollars per barrel on everything still arriving.
    still_importing = gap["baseline_import_kbd"] - gap["net_lost_kbd"]
    extra_usd_bn = (
        still_importing * 1000.0
        * (price["brent_usd"] - price["base_brent_usd"])
        * duration / 1e9
    )

    return {
        "stage": 5,
        "name": "Macro impact",
        "duration_days": duration,
        "price_channel_gdp_pct": round(price_gdp_pct, 3),
        "shortage_channel_gdp_pct": round(shortage_gdp_pct, 3),
        "gdp_impact_annualised_pct": round(total_annualised_pct, 3),
        "gdp_loss_usd_bn": round(gdp_loss_usd_bn, 2),
        "gdp_loss_inr_crore": round(gdp_loss_usd_bn * 1000 * 8.65, 0),
        "extra_import_bill_usd_bn": round(extra_usd_bn, 2),
        "extra_import_bill_inr_crore": round(extra_usd_bn * 1000 * 8.65, 0),
        "total_cost_usd_bn": round(gdp_loss_usd_bn + extra_usd_bn, 2),
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run_cascade(shocks: list[Shock],
                overrides: dict[str, float] | None = None) -> CascadeResult:
    a = ledger_dict(overrides)
    g = twin.get_graph()

    gap = stage_supply_gap(shocks, a, g)
    refinery = stage_refinery(gap, shocks, a, g)
    price = stage_price(gap, shocks, a)
    sector = stage_sector(refinery, price, a)
    macro = stage_macro(gap, price, sector, shocks, a)

    duration = max((s.duration_days for s in shocks), default=0)
    spr = loaders.spr_sites()
    spr_bbl = float((spr["capacity_mmbbl"] * spr["fill_pct"]).sum()) * 1e6
    days_of_spr = spr_bbl / max(1.0, gap["net_lost_kbd"] * 1000.0)

    result = CascadeResult(
        shocks=[s.to_dict() for s in shocks],
        assumptions=a,
        stages=[gap, refinery, price, sector, macro],
        headline={
            "net_lost_kbd": gap["net_lost_kbd"],
            "lost_pct_of_imports": gap["lost_pct_of_imports"],
            "refinery_cut_kbd": refinery["total_cut_kbd"],
            "refineries_tripped": refinery["refineries_tripped"],
            "brent_usd": price["brent_usd"],
            "brent_delta_pct": price["brent_delta_pct"],
            "unserved_pct_of_demand": sector["unserved_pct_of_demand"],
            "gdp_loss_usd_bn": macro["gdp_loss_usd_bn"],
            "total_cost_usd_bn": macro["total_cost_usd_bn"],
            "duration_days": duration,
            "spr_days_at_this_gap": round(days_of_spr, 1),
            "spr_exhausted": bool(days_of_spr < duration),
        },
    )
    return result
