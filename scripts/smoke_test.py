"""End-to-end smoke test over the HTTP surface. Run after every phase.

Usage:  python scripts/smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    with TestClient(app) as c:
        print("meta")
        r = c.get("/api/health")
        check("health 200", r.status_code == 200, r.text)
        r = c.get("/api/legend")
        check("legend has 5 provenance classes", len(r.json()["entries"]) == 5)

        print("digital twin")
        r = c.get("/api/summary")
        s = r.json()
        check("imports ~4.6 mbd", 4000 < s["import_kbd"] < 5200, str(s["import_kbd"]))
        check("spr ~39 mmbbl", 38 < s["spr_mmbbl"] < 40, str(s["spr_mmbbl"]))
        check("hormuz is top corridor",
              max(s["corridor_shares"], key=s["corridor_shares"].get) == "Hormuz")

        r = c.get("/api/network")
        n = r.json()
        check("network nodes", len(n["nodes"]) > 40, str(len(n["nodes"])))
        check("corridor paths = 4", len(n["corridor_paths"]) == 4)
        check("baseline flows", len(n["flows"]) == 21, str(len(n["flows"])))
        check("every node carries provenance",
              all("provenance" in x for x in n["nodes"]))

        r = c.get("/api/corridors")
        check("corridors listed", len(r.json()) == 4)

        r = c.get("/api/corridors/Hormuz")
        d = r.json()
        check("hormuz suppliers", len(d["suppliers"]) == 8, str(len(d["suppliers"])))
        check("hormuz chokepoint present",
              any(cp["chokepoint_id"] == "HORMUZ" for cp in d["chokepoints"]))
        check("hormuz exposure > 1800 kbd",
              d["total_kb_week"] / 7 > 1800, str(d["total_kb_week"] / 7))
        check("unknown corridor 404", c.get("/api/corridors/Nowhere").status_code == 404)

        r = c.get("/api/refineries")
        ref = r.json()
        check("12 refineries", len(ref) == 12)
        jam = next(x for x in ref if x["refinery_id"] == "JAM")
        mat = next(x for x in ref if x["refinery_id"] == "MAT")
        check("complex refinery runs more grades than simple one",
              jam["compatible_count"] > mat["compatible_count"],
              f"JAM={jam['compatible_count']} MAT={mat['compatible_count']}")

        r = c.get("/api/spr")
        check("spr 3 sites", len(r.json()["sites"]) == 3)

        print("scenario modeller")
        r = c.get("/api/scenarios")
        scen = r.json()
        check("scenario library >= 6", len(scen) >= 6, str(len(scen)))
        r = c.get("/api/assumptions")
        led = r.json()
        check("ledger has sources", all(a["source"] for a in led))
        check("ledger spans 5 stages", len({a["stage"] for a in led}) == 5)

        r = c.post("/api/simulate", json={"scenario_id": "hormuz_partial"})
        sim = r.json()
        check("cascade has 5 stages", len(sim["stages"]) == 5)
        h = sim["headline"]
        check("hormuz partial loses barrels", h["net_lost_kbd"] > 300, str(h["net_lost_kbd"]))
        check("brent rises", h["brent_delta_pct"] > 0, str(h["brent_delta_pct"]))
        # Physical consistency: you cannot cut more refinery throughput than the
        # crude you actually lost (absent a unit tripping entirely).
        check("refinery cut <= crude lost",
              h["refinery_cut_kbd"] <= h["net_lost_kbd"] * 1.02,
              f"cut={h['refinery_cut_kbd']} lost={h['net_lost_kbd']}")

        # Voyage time must bind: distant grades cannot rescue a short shock.
        stage2 = sim["stages"][1]
        check("voyage time strands distant crude",
              stage2["stranded_spare_kbd"] > 0, str(stage2["stranded_spare_kbd"]))
        # Stranded volume is a property of the barrels, so it must be counted
        # once -- not once per refinery.
        check("stranded volume not double-counted",
              stage2["stranded_spare_kbd"] < s["import_kbd"],
              f"stranded={stage2['stranded_spare_kbd']} imports={s['import_kbd']}")

        # Dragging an assumption must actually move the answer.
        r2 = c.post("/api/simulate", json={
            "scenario_id": "hormuz_partial",
            "overrides": {"brent_supply_elasticity": 12.0},
        })
        check("assumption override changes result",
              r2.json()["headline"]["brent_usd"] > h["brent_usd"],
              f"{r2.json()['headline']['brent_usd']} vs {h['brent_usd']}")

        # Severity must be monotonic: a worse shock cannot cost less.
        full = c.post("/api/simulate", json={"scenario_id": "hormuz_full"}).json()
        check("full closure worse than partial",
              full["headline"]["net_lost_kbd"] > h["net_lost_kbd"])

        r = c.post("/api/simulate", json={"shocks": [
            {"kind": "chokepoint", "target": "HORMUZ", "severity": 0.4,
             "duration_days": 14}]})
        check("custom shock accepted", r.status_code == 200, r.text[:120])
        check("bad scenario 404",
              c.post("/api/simulate", json={"scenario_id": "nope"}).status_code == 404)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
