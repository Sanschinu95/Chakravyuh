"""Nightly red team run. Persists the artifact the API then serves instantly.

Run:  python scripts/run_redteam.py [--budget 50] [--quiet]

This is deliberately a batch job. The search puts every candidate attack
through the full cascade + procurement LP, which takes minutes of solver time
-- far too long to run while a judge is watching, and heavy enough that doing
it inside the API process degrades every other request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.agents.red_team import run_red_team  # noqa: E402
from backend.config import STATE_DIR  # noqa: E402
from backend.solve.portfolio import optimise_portfolio  # noqa: E402

ARTIFACT = STATE_DIR / "redteam.json"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=50.0,
                    help="attacker budget in $mn")
    ap.add_argument("--portfolio-budget", type=float, default=220.0,
                    help="defender budget in $mn")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    t0 = time.perf_counter()
    if not args.quiet:
        print(f"CHAKRAVYUH :: red team, ${args.budget:.0f}mn attacker budget\n")

    out = await run_red_team(budget=args.budget)
    out["computed_in_s"] = round(time.perf_counter() - t0, 1)
    out["computed_at"] = datetime.now(timezone.utc).isoformat()
    out["cached"] = False

    ARTIFACT.write_text(json.dumps(out, indent=1), encoding="utf-8")

    if args.quiet:
        return 0

    best = out["best_attack"]
    print(f"  provider        {out['generator']}")
    print(f"  found by        {out['found_by']}")
    print(f"  experiments     {len(out['agent_tested'])} agent runs, "
          f"{len(out['baseline_top'])} kept from sweep")
    print(f"  resilience      {out['resilience_score']}/100")
    if best:
        atk = "; ".join(
            f"{a['kind']}:{a['target']}@{a['severity']:.0%} for {a['duration_days']}d"
            for a in best["attacks"]
        )
        print(f"\n  WORST ATTACK FOUND\n    {atk}")
        print(f"    costs ${best['cost_usd_mn']}mn -> "
              f"${best['damage_usd_bn']}bn damage "
              f"({best['damage_per_dollar']:,.0f}x)")
        print(f"    crude lost {best['lost_kbd']:,.0f} kbd; "
              f"our procurement covers {best['coverage_pct']}%; "
              f"{best['unserved_pct']}% of demand unserved")

    attacks = ([best] if best else []) + [
        a for a in out["baseline_top"] if a != best
    ]
    pf = optimise_portfolio(attacks[:6], budget_usd_mn=args.portfolio_budget)
    if pf["status"] == "OPTIMAL":
        print(f"\n  PEACETIME PORTFOLIO\n    {pf['headline']}")
        for h in pf["holdings"]:
            print(f"      {h['units']:>2} x {h['instrument']:<32} "
                  f"${h['cost_usd_mn']:>6.1f}mn")

    print(f"\n  wrote {ARTIFACT}  ({out['computed_in_s']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
