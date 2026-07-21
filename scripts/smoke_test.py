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

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
