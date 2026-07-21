"""Seed the DuckDB store from curated CSVs and print a sanity report.

Run:  python scripts/seed_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data import loaders  # noqa: E402
from backend.sim.twin import build_graph, graph_stats  # noqa: E402


def main() -> int:
    print("CHAKRAVYUH :: seeding digital twin\n")
    print("Loading curated tables:")
    loaders.seed()
    loaders.clear_cache()

    s = loaders.summary()
    print("\nNetwork summary:")
    print(f"  refineries              {s['refinery_count']}")
    print(f"  refining capacity       {s['refining_capacity_kbd']:,.0f} kbd")
    print(f"  supplier grades         {s['supplier_count']}")
    print(f"  routes                  {s['route_count']}")
    print(f"  crude imports           {s['import_kbd']:,.0f} kbd")
    print(f"  strategic reserve       {s['spr_mmbbl']:.1f} mmbbl "
          f"({s['spr_days_cover']:.1f} days of import cover)")
    print("\nCorridor exposure (% of imported barrels):")
    for corridor, share in sorted(
        s["corridor_shares"].items(), key=lambda kv: -kv[1]
    ):
        bar = "#" * int(share / 2)
        print(f"  {corridor:<14} {share:5.1f}%  {bar}")

    g = build_graph()
    gs = graph_stats(g)
    print("\nKnowledge graph:")
    print(f"  nodes {gs['nodes']}  edges {gs['edges']}")
    for kind, n in sorted(gs["by_kind"].items()):
        print(f"    {kind:<12} {n}")

    # Grade compatibility is the constraint that makes recommendations
    # executable, so surface it at seed time -- if it looks wrong, everything
    # downstream is wrong.
    gc = loaders.grade_compatibility()
    pct = 100.0 * gc["compatible"].mean()
    print(f"\nGrade compatibility matrix: {int(gc['compatible'].sum())}"
          f"/{len(gc)} refinery-grade pairs feasible ({pct:.0f}%)")
    tight = (
        gc.groupby("refinery")["compatible"].mean().sort_values().head(3) * 100
    )
    print("  most constrained refineries:")
    for name, p in tight.items():
        print(f"    {name:<28} {p:4.0f}% of grades runnable")

    print("\nSeed complete ->", loaders.DB_PATH if hasattr(loaders, "DB_PATH")
          else "chakravyuh.duckdb")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
