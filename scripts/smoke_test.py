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

        print("defense pipeline")
        import time as _t
        t0 = _t.perf_counter()
        r = c.post("/api/defend", json={"scenario_id": "hormuz_partial"})
        wall_s = _t.perf_counter() - t0
        d = r.json()
        check("pipeline 200", r.status_code == 200, r.text[:200])
        check("pipeline under 3 min", wall_s < 180, f"{wall_s:.1f}s")

        lp = d["procurement"]
        check("LP optimal", lp["status"] == "OPTIMAL", lp["status"])
        check("LP produced lines", len(lp["lines"]) > 0)
        # Grade compatibility must hold for every recommended cargo -- this is
        # what makes the plan executable rather than generic.
        refs = {x["refinery_id"]: x for x in c.get("/api/refineries").json()}
        bad = [
            ln for ln in lp["lines"]
            if not (refs[ln["refinery_id"]]["api_min"] <= ln["api_gravity"]
                    <= refs[ln["refinery_id"]]["api_max"]
                    and ln["sulfur_pct"] <= refs[ln["refinery_id"]]["sulfur_max_pct"])
        ]
        check("every cargo is grade-compatible", not bad,
              f"{len(bad)} violations e.g. {bad[:1]}")
        # Voyage time must be respected: nothing berths on day zero.
        check("no instantaneous deliveries",
              all(ln["first_delivery_day"] >= 1 for ln in lp["lines"]))
        check("coverage accounting reconciles",
              abs((lp["covered_kb"] + lp["unmet_kb"]) - lp["gap_kb"])
              / max(1.0, lp["gap_kb"]) < 0.02,
              f"covered={lp['covered_kb']} unmet={lp['unmet_kb']} gap={lp['gap_kb']}")
        check("binding constraints named", len(lp["binding"]) > 0)

        spr = d["spr"]
        check("SPR optimal", spr["status"] == "OPTIMAL", spr["status"])
        check("SPR holds an end buffer", spr["end_buffer_kb"] > 0)
        check("SPR never over-draws",
              spr["total_drawn_kb"] <= spr["total_available_kb"] + 1)
        check("SPR counterfactual present", "policy" in spr["counterfactual"])

        check("narration present", bool(d["narration"]["text"]))
        check("narration mode labelled",
              d["narration"]["mode"] in ("llm", "deterministic"))
        check("pipeline trace has 4 steps", len(d["trace"]) == 4,
              str([t["step"] for t in d["trace"]]))

        # A worse shock must not produce a cheaper plan.
        full = c.post("/api/defend", json={"scenario_id": "hormuz_full"}).json()
        check("worse shock leaves more unmet",
              full["procurement"]["unmet_kb"] > lp["unmet_kb"])

        print("phase 5-6")
        r = c.get("/api/cri")
        check("cri 200", r.status_code == 200, r.text[:200])
        cri = r.json()
        cors = cri["corridors"]
        check("cri covers 4 corridors", len(cors) == 4, str(len(cors)))
        check("every cri score in 0-100",
              all(0.0 <= x["score"] <= 100.0 for x in cors),
              str([x["score"] for x in cors]))
        # The band is the alert contract; it must follow the threshold exactly.
        thr = cri["thresholds"]["red"]
        amber = cri["thresholds"]["amber"]
        bad_band = [
            x for x in cors
            if x["band"] != ("red" if x["score"] >= thr
                             else "amber" if x["score"] >= amber else "green")
        ]
        check("bands agree with the threshold", not bad_band,
              str([(x["corridor"], x["score"], x["band"]) for x in bad_band]))
        check("alert flag agrees with band",
              all(x["alert"] == (x["score"] >= thr) for x in cors))
        # Weights must be visible, sum to 1, and be renormalised over whatever
        # signals were actually available.
        check("cri weights sum to 1",
              abs(sum(cri["weights"].values()) - 1.0) < 1e-6,
              str(cri["weights"]))
        check("effective weights sum to 1",
              all(abs(sum(x["weights_effective"].values()) - 1.0) < 1e-6
                  for x in cors))
        # Score must reconcile with the components the payload shows.
        recon = [
            x for x in cors
            if abs(sum(cp["contribution"] for cp in x["components"]) - x["score"]) > 0.5
        ]
        check("score reconciles with its components", not recon,
              str([(x["corridor"], x["score"]) for x in recon]))
        check("hormuz carries the most supplier exposure",
              len(next(x for x in cors if x["corridor"] == "Hormuz")
                  ["supplier_disruption_prob"]) == 8)
        check("supplier probabilities are probabilities",
              all(0.0 <= s["disruption_prob"] <= 1.0
                  for x in cors for s in x["supplier_disruption_prob"]))
        check("cri is model output", cri["provenance"] == "simulated")

        r = c.get("/api/cri/Hormuz")
        one = r.json()
        check("corridor drill-down 200", r.status_code == 200, r.text[:200])
        check("evidence is present",
              one["evidence"]["event_count"] > 0
              or one["evidence"]["anomaly_count"] > 0,
              str(one["evidence"]["event_count"]))
        check("evidence events carry titles",
              all(e.get("title") for e in one["evidence"]["events"]))
        check("unknown corridor 404", c.get("/api/cri/Nowhere").status_code == 404)

        r = c.get("/api/vessels")
        ves = r.json()
        # Rule 1: no AIS key means this can never be labelled live.
        check("ais provenance is never live without a key",
              ves["provenance"] != "live" or ves["live_ais_configured"],
              f"provenance={ves['provenance']} key={ves['live_ais_configured']}")
        check("ais is replay on this deployment", ves["provenance"] == "replay")
        check("vessels present", ves["vessel_count"] >= 35, str(ves["vessel_count"]))
        check("anomalies detected", ves["anomaly_count"] > 0)
        check("every vessel carries provenance",
              all("provenance" in v for v in ves["vessels"]))

        r = c.get("/api/market")
        mkt = r.json()
        check("market 200", r.status_code == 200, r.text[:200])
        check("market provenance is live or replay",
              mkt["provenance"] in ("live", "replay"), mkt["provenance"])
        check("market series or an explicit unavailable flag",
              bool(mkt["series"]) or mkt["available"] is False)

        r = c.get("/api/backtest")
        bt = r.json()
        check("backtest 200", r.status_code == 200, r.text[:200])
        check("backtest is replay", bt["provenance"] == "replay")
        check("lead time is numeric or honestly null",
              isinstance(bt["lead_time_hours"], (int, float))
              or bt["lead_time_hours"] is None,
              str(bt["lead_time_hours"]))
        check("backtest produced a lead time",
              isinstance(bt["lead_time_hours"], (int, float)),
              bt["lead_note"])
        check("brier score in [0,1]",
              0.0 <= bt["brier_score"] <= 1.0, str(bt["brier_score"]))
        check("brier has a reference to compare against",
              0.0 <= bt["brier_reference_base_rate"] <= 1.0)
        check("backtest walks the whole month", len(bt["series"]) == 30,
              str(len(bt["series"])))
        check("alert precedes the price spike",
              bt["alert_day"] < bt["spike_day"],
              f"alert={bt['alert_day']} spike={bt['spike_day']}")
        # Signals with no June 2025 archive must be declared, not faked.
        check("unavailable signals declared",
              set(bt["signals_excluded"]) == {"ais", "sanctions"})

        r = c.get("/api/calibration")
        cal = r.json()
        check("calibration 200", r.status_code == 200, r.text[:200])
        check("calibration bins sum to the sample",
              cal["bin_count_total"] == cal["n_points"],
              f"bins={cal['bin_count_total']} n={cal['n_points']}")
        check("market bins sum to the sample",
              cal["market_bin_count_total"] == cal["n_points"])
        check("bin observed counts sum to the outcomes",
              sum(b["observed_count"] for b in cal["bins"])
              == round(cal["observed_frequency"] * cal["n_points"]))
        check("reliability curve is plottable",
              len(cal["reliability_curve"]) == len(cal["bins"]))
        check("every populated bin has a predicted and observed value",
              all(b["predicted_mean"] is not None and b["observed_freq"] is not None
                  for b in cal["bins"] if b["count"] > 0))
        check("disagreement flags carry a direction",
              all(f["direction"] in ("system_above_market", "system_below_market")
                  for f in cal["flags"]))
        check("market proxy derivation is documented",
              bool(cal["market_proxy"]["formula"])
              and len(cal["market_proxy"]["caveats"]) >= 3)

        print("sourcing advisor")
        r = c.get("/api/sourcing")
        sv = r.json()
        check("countries returned", len(sv["countries"]) > 8)
        check("shares sum to ~100",
              abs(sum(x["share_pct"] for x in sv["countries"]) - 100) < 1.0,
              str(sum(x["share_pct"] for x in sv["countries"])))
        check("HHI in valid range", 0 < sv["concentration"]["hhi"] <= 10000)
        check("every country has an action",
              all(x["recommendation"]["action"] for x in sv["countries"]))
        check("every country has a lead time",
              all(x["lead_time_days"] >= 0 for x in sv["countries"]))
        # Under a Hormuz closure, Gulf counterparties must flip to replace-now.
        sv2 = c.get("/api/sourcing?scenario_id=hormuz_full").json()
        iraq = next(x for x in sv2["countries"] if x["country"] == "Iraq")
        check("blocked country flips to replace now",
              iraq["recommendation"]["action"] == "replace now",
              iraq["recommendation"]["action"])
        check("blocked volume is reported", iraq["blocked_kbd"] > 0)

        print("phase 4 -- tender")
        r = c.post("/api/tender", json={"scenario_id": "hormuz_partial"})
        td = r.json()
        check("tender 200", r.status_code == 200, r.text[:160])
        check("tenders drafted", td["count"] > 0)
        t0 = td["tenders"][0]
        check("tender has a body", len(t0["body"]) > 300)
        # A tender that fails the buyer's crude diet must never be issuable.
        check("every tender is grade-compatible",
              all(t["quality"]["compatible"] for t in td["tenders"]))
        check("laycan opens before ETA",
              all(t["schedule"]["laycan_open"] < t["schedule"]["eta_discharge"]
                  for t in td["tenders"]))
        check("tender carries pricing basis",
              all(t["commercial"]["pricing_basis"] for t in td["tenders"]))
        check("tender marked draft",
              all("DRAFT" in t["status"] for t in td["tenders"]))

        print("phase 7 -- red team + portfolio")
        r = c.get("/api/redteam")
        rt = r.json()
        check("redteam 200", r.status_code == 200, r.text[:160])
        check("best attack found", rt["best_attack"] is not None)
        check("resilience score 0-100", 0 <= rt["resilience_score"] <= 100)
        check("attacks stay within budget",
              rt["best_attack"]["cost_usd_mn"] <= rt["budget_usd_mn"] + 0.01,
              f"{rt['best_attack']['cost_usd_mn']} vs {rt['budget_usd_mn']}")
        check("damage measured by solvers, not asserted",
              rt["best_attack"]["damage_usd_bn"] > 0
              and rt["best_attack"]["coverage_pct"] <= 100)
        check("baseline sweep ran", len(rt["baseline_top"]) > 0)
        check("red team output is labelled injected",
              rt["provenance"] == "injected", rt["provenance"])

        r = c.get("/api/portfolio")
        pf = r.json()
        check("portfolio 200", r.status_code == 200, r.text[:160])
        check("portfolio optimal", pf["status"] == "OPTIMAL", pf["status"])
        check("holdings selected", len(pf["holdings"]) > 0)
        check("spend within budget", pf["spend_usd_mn"] <= pf["budget_usd_mn"] + 0.01)
        # Instruments cannot undo physics: a total closure must never be
        # reported as fully neutralised.
        check("no attack fully neutralised",
              all(a["neutralised_pct"] <= 45.1 for a in pf["per_attack"]),
              str(max(a["neutralised_pct"] for a in pf["per_attack"])))
        check("neutralisation respects its ceiling",
              all(a["neutralised_pct"] <= a["max_mitigable_pct"] + 0.1
                  for a in pf["per_attack"]))
        check("portfolio is diversified, not one lever",
              len(pf["holdings"]) >= 2, str(len(pf["holdings"])))
        check("residual loss is below gross",
              pf["expected_loss_residual_usd_mn"] < pf["expected_loss_gross_usd_mn"])
        check("assumptions disclosed",
              bool(pf["probability_note"]) and bool(pf["ceiling_note"]))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
