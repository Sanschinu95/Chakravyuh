"""The defense pipeline: cascade -> procurement LP -> SPR bridge -> narration.

This is the path the stopwatch times. Every stage publishes to the event bus as
it completes, so the UI can show the pipeline running rather than freezing for
a few seconds and then dumping an answer.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from backend.bus import bus
from backend.config import Provenance
from backend.sim.simulator import Shock, run_cascade
from backend.solve.procurement_lp import solve_procurement
from backend.solve.spr import residual_gap_curve, solve_spr


async def run_defense_pipeline(
    shocks: list[Shock],
    overrides: dict[str, float] | None = None,
    meta: dict[str, Any] | None = None,
    narrate: bool = True,
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    trace: list[dict[str, Any]] = []

    def mark(step: str, detail: str) -> float:
        elapsed = (time.perf_counter() - t0) * 1000.0
        trace.append({"step": step, "detail": detail, "elapsed_ms": round(elapsed, 1)})
        return elapsed

    await bus.publish("pipeline.start",
                      {"run_id": run_id, "shocks": [s.to_dict() for s in shocks]},
                      provenance=Provenance.INJECTED, run_id=run_id)

    # -- 1. cascade -------------------------------------------------------
    # The simulator and both solvers are synchronous and CPU-bound; running
    # them inline would block the event loop (and every other request) for the
    # duration of the pipeline.
    cascade = (await asyncio.to_thread(run_cascade, shocks, overrides)).to_dict()
    ms = mark("cascade", f"{cascade['headline']['net_lost_kbd']:.0f} kbd supply gap "
                         f"across {len(cascade['stages'])} stages")
    await bus.publish("pipeline.cascade", {"run_id": run_id, "elapsed_ms": ms,
                                           "headline": cascade["headline"]},
                      provenance=Provenance.SIMULATED, run_id=run_id)

    # -- 2. procurement LP ------------------------------------------------
    stage2 = cascade["stages"][1]
    gap_by_refinery = {
        r["refinery_id"]: r["cut_kbd"]
        for r in stage2["by_refinery"] if r["cut_kbd"] > 0
    }
    disrupted = {
        d["supplier_id"]: d["blocked_frac"] for d in cascade["stages"][0]["by_supplier"]
    }
    duration = cascade["headline"]["duration_days"]

    plan = (await asyncio.to_thread(
        solve_procurement,
        gap_by_refinery, duration, disrupted,
        cascade["assumptions"]["reroute_lag_days"],
    )).to_dict()
    ms = mark("procurement_lp",
              f"{plan['status']}: {plan['coverage_pct']}% of gap covered, "
              f"first delivery day {plan['first_delivery_day']}")
    await bus.publish("pipeline.procurement", {"run_id": run_id, "elapsed_ms": ms,
                                               "coverage_pct": plan["coverage_pct"],
                                               "binding": plan["binding"][:2]},
                      provenance=Provenance.SIMULATED, run_id=run_id)

    # -- 3. SPR bridge ----------------------------------------------------
    covered_kbd = (plan["covered_kb"] / max(1, plan["horizon_weeks"])) / 7.0
    curve = residual_gap_curve(
        gross_gap_kbd=cascade["headline"]["net_lost_kbd"],
        duration_days=max(1, duration),
        first_delivery_day=plan["first_delivery_day"],
        covered_kbd=covered_kbd,
    )
    spr = (await asyncio.to_thread(solve_spr, curve)).to_dict()
    ms = mark("spr_bridge",
              f"draws {spr['total_drawn_mmbbl']} mmbbl, holds "
              f"{spr['end_buffer_mmbbl']} mmbbl buffer")
    await bus.publish("pipeline.spr", {"run_id": run_id, "elapsed_ms": ms,
                                       "counterfactual": spr["counterfactual"]},
                      provenance=Provenance.SIMULATED, run_id=run_id)

    result = {
        "run_id": run_id,
        "meta": meta or {},
        "cascade": cascade,
        "procurement": plan,
        "spr": spr,
        "trace": trace,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 1),
        "provenance": Provenance.SIMULATED,
    }

    # -- 4. narration -----------------------------------------------------
    if narrate:
        from backend.agents.narrator import narrate_plan

        narration = await narrate_plan(result)
        result["narration"] = narration
        ms = mark("narration", f"{narration['mode']} narration produced")
        await bus.publish("pipeline.narration",
                          {"run_id": run_id, "elapsed_ms": ms,
                           "mode": narration["mode"]},
                          provenance=narration["provenance"], run_id=run_id)

    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    result["trace"] = trace

    await bus.publish("pipeline.complete",
                      {"run_id": run_id, "elapsed_ms": result["elapsed_ms"]},
                      provenance=Provenance.SIMULATED, run_id=run_id)
    return result
