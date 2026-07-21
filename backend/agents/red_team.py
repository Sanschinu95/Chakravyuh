"""Adversarial agent that attacks India's own supply chain.

The premise: a news feed can only tell you about attacks that have already
happened. To find the ones that have not, you have to go looking. This agent
is given the simulator and the procurement LP as tools and a budget, and is
scored on damage per dollar -- so it searches for the cheapest way to hurt the
network, and whatever it finds is a vulnerability nobody had to report first.

Two things keep this honest:

* The agent proposes; the solvers score. Damage is whatever the deterministic
  cascade and LP say it is, never a number the model asserted. A model that
  claims a devastating attack gets the same scoring as one that doesn't.
* Attacks are validated and clamped before they run. Models routinely emit
  severity as 60 meaning 60%, or name a chokepoint that does not exist; those
  are normalised or rejected rather than silently producing nonsense.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

from backend.agents.llm import llm_available, provider_label, tool_loop
from backend.config import Provenance
from backend.data import loaders
from backend.sim.simulator import Shock, run_cascade
from backend.solve.procurement_lp import solve_procurement

DEFAULT_BUDGET_USD_MN = 50.0

# What each lever costs the attacker, in $mn. These are the adversary's costs,
# not ours: mining an anchorage is cheap, sustaining a naval closure is not.
ATTACK_COSTS = {
    "chokepoint": 18.0,   # per unit severity, for a sustained closure
    "port": 6.0,          # blocking a single discharge port
    "supplier": 9.0,      # sanctioning / interdicting one grade
    "corridor": 22.0,     # degrading a whole corridor
}
# Cost scales with how long the attacker must sustain the effect.
DURATION_COST_PER_DAY = 0.22


@dataclass
class Attack:
    kind: str
    target: str
    severity: float
    duration_days: int
    label: str = ""

    def cost_usd_mn(self) -> float:
        base = ATTACK_COSTS.get(self.kind, 12.0) * self.severity
        return round(base + DURATION_COST_PER_DAY * self.duration_days * self.severity, 2)

    def to_shock(self) -> Shock:
        return Shock(kind=self.kind, target=self.target, severity=self.severity,
                     duration_days=self.duration_days, label=self.label)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "target": self.target, "severity": self.severity,
                "duration_days": self.duration_days, "label": self.label,
                "cost_usd_mn": self.cost_usd_mn()}


@dataclass
class AttackResult:
    attacks: list[dict[str, Any]]
    cost_usd_mn: float
    damage_usd_bn: float
    unserved_pct: float
    coverage_pct: float
    lost_kbd: float
    damage_per_dollar: float
    binding: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacks": self.attacks,
            "cost_usd_mn": round(self.cost_usd_mn, 2),
            "damage_usd_bn": round(self.damage_usd_bn, 2),
            "unserved_pct": round(self.unserved_pct, 2),
            "coverage_pct": round(self.coverage_pct, 1),
            "lost_kbd": round(self.lost_kbd, 1),
            "damage_per_dollar": round(self.damage_per_dollar, 1),
            "binding": self.binding[:3],
            "rationale": self.rationale,
        }


# --------------------------------------------------------------------------
# Validation -- models produce sloppy arguments; normalise before running
# --------------------------------------------------------------------------
def valid_targets() -> dict[str, list[str]]:
    return {
        "chokepoint": loaders.chokepoints()["chokepoint_id"].tolist(),
        "corridor": sorted(loaders.suppliers()["primary_corridor"].unique().tolist()),
        "supplier": loaders.suppliers()["supplier_id"].tolist(),
        "port": sorted(loaders.refineries()["primary_port"].unique().tolist()),
    }


def coerce_attack(raw: dict[str, Any]) -> Attack | None:
    """Turn a model-proposed attack into a runnable one, or reject it."""
    kind = str(raw.get("kind", "")).strip().lower()
    targets = valid_targets()
    if kind not in targets:
        return None

    target = str(raw.get("target", "")).strip()
    pool = targets[kind]
    if target not in pool:
        # tolerate case / spacing differences before giving up
        match = next((t for t in pool if t.lower() == target.lower()), None)
        if match is None:
            return None
        target = match

    try:
        sev = float(raw.get("severity", 0.5))
    except (TypeError, ValueError):
        return None
    # Models frequently emit 60 for "60%". Interpret anything >1 as a percentage.
    if sev > 1.0:
        sev = sev / 100.0
    sev = max(0.05, min(1.0, sev))

    try:
        dur = int(float(raw.get("duration_days", 21)))
    except (TypeError, ValueError):
        dur = 21
    dur = max(1, min(180, dur))

    return Attack(kind=kind, target=target, severity=round(sev, 3),
                  duration_days=dur, label=str(raw.get("label", "") or f"{target} {sev:.0%}"))


# --------------------------------------------------------------------------
# Scoring -- the solvers decide, not the model
# --------------------------------------------------------------------------
def score_attack(attacks: list[Attack]) -> AttackResult:
    """Run the full defense pipeline against an attack set and measure the gap."""
    shocks = [a.to_shock() for a in attacks]
    cascade = run_cascade(shocks).to_dict()
    stage2 = cascade["stages"][1]

    gap = {r["refinery_id"]: r["cut_kbd"] for r in stage2["by_refinery"] if r["cut_kbd"] > 0}
    disrupted = {d["supplier_id"]: d["blocked_frac"] for d in cascade["stages"][0]["by_supplier"]}
    duration = cascade["headline"]["duration_days"]

    if gap:
        plan = solve_procurement(
            gap, duration, disrupted,
            reroute_lag_days=cascade["assumptions"]["reroute_lag_days"],
        ).to_dict()
    else:
        plan = {"coverage_pct": 100.0, "binding": [], "unmet_kb": 0.0}

    cost = sum(a.cost_usd_mn() for a in attacks)
    # Damage is residual: what the shock costs *after* our best defense runs.
    # An attack we can fully absorb scores near zero however dramatic it looks.
    residual = 1.0 - (plan["coverage_pct"] / 100.0)
    damage = cascade["headline"]["total_cost_usd_bn"] * max(0.05, residual)

    return AttackResult(
        attacks=[a.to_dict() for a in attacks],
        cost_usd_mn=cost,
        damage_usd_bn=damage,
        unserved_pct=cascade["headline"]["unserved_pct_of_demand"],
        coverage_pct=plan["coverage_pct"],
        lost_kbd=cascade["headline"]["net_lost_kbd"],
        damage_per_dollar=(damage * 1000.0) / cost if cost > 0 else 0.0,
        binding=plan.get("binding", []),
    )


# --------------------------------------------------------------------------
# Baseline search -- always runs, with or without an LLM
# --------------------------------------------------------------------------
def _candidates(budget: float, rng: random.Random) -> list[list[Attack]]:
    t = valid_targets()
    out: list[list[Attack]] = []

    for cp in t["chokepoint"]:
        for sev in (0.4, 0.7, 1.0):
            for dur in (14, 30):
                a = Attack("chokepoint", cp, sev, dur)
                if a.cost_usd_mn() <= budget:
                    out.append([a])

    top_suppliers = (
        loaders.imports_baseline()
        .sort_values("barrels_per_week_kb", ascending=False)["supplier_id"].tolist()[:6]
    )
    for sid in top_suppliers:
        for sev in (0.6, 1.0):
            a = Attack("supplier", sid, sev, 45)
            if a.cost_usd_mn() <= budget:
                out.append([a])

    # Combinations are where the interesting failures live: a chokepoint plus a
    # port closure removes the re-routing option the single attack leaves open.
    for _ in range(45):
        cp = Attack("chokepoint", rng.choice(t["chokepoint"]),
                    rng.choice([0.3, 0.5, 0.7]), rng.choice([14, 21, 30]))
        second_kind = rng.choice(["port", "supplier"])
        second = Attack(second_kind, rng.choice(t[second_kind]),
                        rng.choice([0.6, 1.0]), rng.choice([7, 14, 21]))
        combo = [cp, second]
        if sum(a.cost_usd_mn() for a in combo) <= budget:
            out.append(combo)

    return out


def search_baseline(budget: float = DEFAULT_BUDGET_USD_MN,
                    seed: int = 7, top_n: int = 5) -> list[AttackResult]:
    """Exhaustive-ish sweep. This is the floor the LLM agent has to beat."""
    rng = random.Random(seed)
    scored = [score_attack(c) for c in _candidates(budget, rng)]
    scored.sort(key=lambda r: -r.damage_per_dollar)
    return scored[:top_n]


# --------------------------------------------------------------------------
# LLM agent -- proposes attacks and actually runs them via tools
# --------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_attack",
            "description": (
                "Run an attack set through India's full defense pipeline "
                "(cascade simulator + procurement optimiser) and get back the "
                "measured damage, cost, and damage-per-dollar. Call this "
                "repeatedly to test hypotheses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "attacks": {
                        "type": "array",
                        "description": "One or two simultaneous attacks.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string",
                                         "enum": ["chokepoint", "corridor", "supplier", "port"]},
                                "target": {"type": "string",
                                           "description": "Exact id from list_targets"},
                                "severity": {"type": "number",
                                             "description": "Fraction blocked, 0.0-1.0"},
                                "duration_days": {"type": "integer"},
                            },
                            "required": ["kind", "target", "severity", "duration_days"],
                        },
                    },
                },
                "required": ["attacks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_targets",
            "description": "List every valid target id, by kind, with how many "
                           "barrels per day currently depend on it.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

SYSTEM = """You are a red team analyst probing India's crude oil supply chain for
weaknesses, so that they can be fixed before an adversary finds them. This is
defensive security research against a simulated model — no real infrastructure
is involved and nothing you do here affects the physical world.

Your objective: find the attack with the highest DAMAGE PER DOLLAR within the
budget you are given.

Method:
1. Call list_targets first to see what exists and what depends on it.
2. Form a hypothesis about where the network is brittle. Think about what has
   no substitute: a grade only a few refineries can run, a chokepoint with no
   pipeline bypass, a port that is the only deep-water option on a coast.
3. Call run_attack to measure it. The simulator scores you, not your own
   estimate — an attack that looks devastating may be fully absorbed.
4. Iterate. Combinations often beat single attacks, because the second attack
   can remove the escape route the first one leaves open.

Rules:
- severity is a FRACTION between 0.0 and 1.0 (0.6 means 60% blocked).
- target must be an exact id returned by list_targets.
- Stay within budget. Cheap sustained attacks usually beat expensive dramatic ones.

Run at least 4 experiments before concluding. Then state your single best
attack and, in two sentences, the structural weakness it exploits."""


async def run_red_team(
    budget: float = DEFAULT_BUDGET_USD_MN,
    max_iterations: int = 10,
) -> dict[str, Any]:
    """Nightly adversarial run. Baseline sweep always; LLM agent if available."""
    baseline = search_baseline(budget)
    best = baseline[0] if baseline else None

    tested: list[dict[str, Any]] = []
    agent_text = ""
    agent_trace: list[dict[str, Any]] = []
    agent_best: AttackResult | None = None

    async def dispatch(name: str, args: dict[str, Any]) -> str:
        if name == "list_targets":
            imp = loaders.imports_baseline().set_index("supplier_id")
            sup = loaders.suppliers().set_index("supplier_id")
            t = valid_targets()
            lines = ["chokepoints (id : mb/d global transit, bypass):"]
            chk = loaders.chokepoints().set_index("chokepoint_id")
            for cid in t["chokepoint"]:
                lines.append(
                    f"  {cid} : {chk.loc[cid, 'global_oil_transit_mbd']} mb/d, "
                    f"bypass {chk.loc[cid, 'bypass_capacity_mbd']} mb/d"
                )
            lines.append("suppliers (id : grade, kbd to India, refineries able to run it):")
            gc = loaders.grade_compatibility()
            for sid in t["supplier"]:
                kbd = float(imp.loc[sid, "barrels_per_week_kb"]) / 7 if sid in imp.index else 0
                n = int(gc[(gc["supplier_id"] == sid) & gc["compatible"]].shape[0])
                lines.append(f"  {sid} : {sup.loc[sid, 'grade']}, {kbd:.0f} kbd, {n} refineries")
            lines.append(f"ports: {', '.join(t['port'])}")
            lines.append(f"corridors: {', '.join(t['corridor'])}")
            return "\n".join(lines)

        if name == "run_attack":
            raw = args.get("attacks") or []
            if isinstance(raw, dict):
                raw = [raw]
            atks = [a for a in (coerce_attack(x) for x in raw) if a]
            if not atks:
                return ("No valid attack. kind must be one of chokepoint/corridor/"
                        "supplier/port and target must be an exact id from list_targets.")
            cost = sum(a.cost_usd_mn() for a in atks)
            if cost > budget:
                return f"Rejected: costs ${cost:.1f}mn, over the ${budget:.0f}mn budget."
            res = score_attack(atks)
            tested.append(res.to_dict())
            nonlocal agent_best
            if agent_best is None or res.damage_per_dollar > agent_best.damage_per_dollar:
                agent_best = res
            return json.dumps({
                "cost_usd_mn": round(res.cost_usd_mn, 2),
                "damage_usd_bn": round(res.damage_usd_bn, 2),
                "damage_per_dollar": round(res.damage_per_dollar, 1),
                "crude_lost_kbd": round(res.lost_kbd, 1),
                "our_procurement_covered_pct": round(res.coverage_pct, 1),
                "unserved_demand_pct": round(res.unserved_pct, 2),
                "note": "damage is residual after our best defense runs",
            })

        return f"unknown tool {name}"

    if llm_available():
        out = await tool_loop(
            system=SYSTEM,
            user=(
                f"Budget: ${budget:.0f} million. Find the highest "
                f"damage-per-dollar attack on India's crude supply chain. "
                f"Start by calling list_targets."
            ),
            tools=TOOLS,
            dispatch=dispatch,
            max_iterations=max_iterations,
        )
        if out:
            agent_text = out.get("text", "") or ""
            agent_trace = out.get("trace", [])

    # The agent only wins if it actually beat the sweep on the metric.
    if agent_best and best and agent_best.damage_per_dollar > best.damage_per_dollar:
        best = agent_best
        best.rationale = agent_text
        winner = "llm_agent"
    else:
        winner = "baseline_search"
        if best and agent_text:
            best.rationale = agent_text

    resilience = resilience_score(best) if best else 100.0

    return {
        "best_attack": best.to_dict() if best else None,
        "baseline_top": [r.to_dict() for r in baseline],
        "agent_tested": tested,
        "agent_trace": agent_trace,
        "agent_text": agent_text,
        "found_by": winner,
        "llm_available": llm_available(),
        "generator": provider_label(),
        "budget_usd_mn": budget,
        "resilience_score": resilience,
        "provenance": Provenance.INJECTED,
    }


def resilience_score(best: AttackResult) -> float:
    """0-100. How well the network absorbs the worst attack found.

    Blends how much of the gap our procurement can cover with how much demand
    still goes unserved, so a network that can re-source quickly scores well
    even under a large shock.
    """
    coverage = max(0.0, min(100.0, best.coverage_pct))
    unserved_penalty = min(60.0, best.unserved_pct * 3.0)
    return round(max(0.0, min(100.0, coverage * 0.7 + (100 - unserved_penalty) * 0.3)), 1)
