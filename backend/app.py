"""CHAKRAVYUH FastAPI entry point + WebSocket hub.

Phase 1 surface: the digital twin (network, summary, corridor drill-down) and
the honesty legend. Later phases mount additional routers onto this app.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.bus import bus
from backend.config import (
    AIS_ENABLED,
    CORRIDORS,
    LLM_ENABLED,
    PROVENANCE_COLORS,
    PROVENANCE_LABELS,
    Provenance,
)
from backend.data import loaders
from backend.sim import scenarios as scenario_lib
from backend.sim import twin
from backend.sim.assumptions import ledger_payload
from backend.sim.simulator import Shock, run_cascade
from backend.solve.pipeline import run_defense_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not loaders.db_exists():
        raise RuntimeError(
            "chakravyuh.duckdb not found -- run `python scripts/seed_db.py` first"
        )
    twin.get_graph()  # warm the cache so first request is fast
    yield


app = FastAPI(
    title="CHAKRAVYUH",
    description="Anticipatory energy supply-chain resilience system for India",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Meta / honesty legend
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "llm_enabled": LLM_ENABLED,
        "ais_enabled": AIS_ENABLED,
        "ws_clients": bus.client_count,
    }


@app.get("/api/legend")
def legend() -> dict[str, Any]:
    """The honesty legend. The UI renders this verbatim -- never hardcodes it.

    `active` tells the judge which classes of data are actually flowing in this
    session, so a missing API key downgrades the claim instead of faking it.
    """
    active = {
        Provenance.LIVE: AIS_ENABLED,
        Provenance.CURATED: True,
        Provenance.REPLAY: True,
        Provenance.SIMULATED: True,
        Provenance.INJECTED: True,
    }
    return {
        "entries": [
            {
                "key": k,
                "label": PROVENANCE_LABELS[k],
                "color": PROVENANCE_COLORS[k],
                "active": active[k],
            }
            for k in [
                Provenance.LIVE,
                Provenance.CURATED,
                Provenance.REPLAY,
                Provenance.SIMULATED,
                Provenance.INJECTED,
            ]
        ],
        "disclosure": (
            "Green is fetched live this session. Amber is static reference data. "
            "Blue is a real archive replayed on a clock. Purple is computed by "
            "our own model. Red was injected by a human or the red team agent. "
            "Nothing simulated is ever presented as live."
        ),
    }


# --------------------------------------------------------------------------
# Digital twin
# --------------------------------------------------------------------------
@app.get("/api/summary")
def summary() -> dict[str, Any]:
    s = loaders.summary()
    s["provenance"] = Provenance.CURATED
    return s


@app.get("/api/network")
def network() -> dict[str, Any]:
    """Everything the map needs in one payload."""
    g = twin.get_graph()
    payload = twin.to_geojson_like(g)

    wp = loaders.corridor_waypoints().sort_values(["corridor", "seq"])
    corridor_paths = [
        {
            "corridor": corridor,
            "path": grp[["lon", "lat"]].values.tolist(),
            "labels": grp["label"].tolist(),
            "baseline_kb_week": float(
                g.nodes[twin.nid(twin.CORRIDOR, corridor)]["baseline_kb_week"]
            ),
            "provenance": Provenance.CURATED,
        }
        for corridor, grp in wp.groupby("corridor")
    ]

    # Baseline flow arcs: supplier origin -> its typical discharge port.
    imp = loaders.imports_baseline()
    sup = loaders.suppliers().set_index("supplier_id")
    ports = {
        d["key"]: (d["lon"], d["lat"])
        for _, d in g.nodes(data=True)
        if d.get("kind") == twin.PORT
    }
    flows = []
    for _, r in imp.iterrows():
        s = sup.loc[r["supplier_id"]]
        dest = ports.get(r["typical_discharge_port"])
        if dest is None:
            continue
        flows.append({
            "supplier_id": r["supplier_id"],
            "grade": s["grade"],
            "country": s["country"],
            "corridor": r["corridor"],
            "from": [float(s["load_lon"]), float(s["load_lat"])],
            "to": list(dest),
            "kb_week": float(r["barrels_per_week_kb"]),
            "share_pct": float(r["share_pct"]),
            "provenance": Provenance.CURATED,
        })

    payload["corridor_paths"] = corridor_paths
    payload["flows"] = flows
    payload["provenance"] = Provenance.CURATED
    return payload


@app.get("/api/corridors")
def corridors() -> list[dict[str, Any]]:
    g = twin.get_graph()
    imp = loaders.imports_baseline()
    total = float(imp["barrels_per_week_kb"].sum())
    out = []
    for c in CORRIDORS:
        node = g.nodes[twin.nid(twin.CORRIDOR, c)]
        kb = node["baseline_kb_week"]
        out.append({
            "corridor": c,
            "label": node["label"],
            "kb_week": kb,
            "kbd": round(kb / 7.0, 1),
            "share_pct": round(100.0 * kb / total, 2),
            "supplier_count": len(twin.suppliers_on_corridor(c, g)),
            "provenance": Provenance.CURATED,
        })
    return sorted(out, key=lambda d: -d["share_pct"])


@app.get("/api/corridors/{corridor}")
def corridor_detail(corridor: str) -> dict[str, Any]:
    g = twin.get_graph()
    if twin.nid(twin.CORRIDOR, corridor) not in g:
        raise HTTPException(404, f"unknown corridor: {corridor}")

    sids = twin.suppliers_on_corridor(corridor, g)
    sup = loaders.suppliers().set_index("supplier_id")
    imp = loaders.imports_baseline().set_index("supplier_id")

    suppliers = []
    for sid in sids:
        s = sup.loc[sid]
        kb = float(imp.loc[sid, "barrels_per_week_kb"]) if sid in imp.index else 0.0
        suppliers.append({
            "supplier_id": sid,
            "grade": s["grade"],
            "country": s["country"],
            "api_gravity": float(s["api_gravity"]),
            "sulfur_pct": float(s["sulfur_pct"]),
            "kb_week": kb,
            "kbd": round(kb / 7.0, 1),
            "load_port": s["load_port"],
            "pricing_formula": s["pricing_formula"],
            "political_risk": float(s["political_risk"]),
        })
    suppliers.sort(key=lambda d: -d["kb_week"])

    chk = loaders.chokepoints().set_index("chokepoint_id")
    cp_ids = [
        g.nodes[v]["key"]
        for _, v, d in g.out_edges(twin.nid(twin.CORRIDOR, corridor), data=True)
        if d.get("kind") == "transits"
    ]
    cps = [
        {
            "chokepoint_id": cid,
            "name": chk.loc[cid, "name"],
            "lat": float(chk.loc[cid, "lat"]),
            "lon": float(chk.loc[cid, "lon"]),
            "global_oil_transit_mbd": float(chk.loc[cid, "global_oil_transit_mbd"]),
            "bypass_capacity_mbd": float(chk.loc[cid, "bypass_capacity_mbd"]),
            "exposure": twin.exposure_to_chokepoint(cid, g),
        }
        for cid in cp_ids
    ]

    rts = loaders.routes()
    rts = rts[rts["corridor"] == corridor]
    voyage = (
        rts.groupby("vessel_class")["voyage_days"]
        .agg(["min", "max", "mean"]).round(1).to_dict("index")
    )

    return {
        "corridor": corridor,
        "suppliers": suppliers,
        "chokepoints": cps,
        "voyage_days_by_class": voyage,
        "total_kb_week": round(sum(s["kb_week"] for s in suppliers), 1),
        "provenance": Provenance.CURATED,
    }


@app.get("/api/refineries")
def refineries() -> list[dict[str, Any]]:
    ref = loaders.refineries()
    gc = loaders.grade_compatibility()
    out = []
    for _, r in ref.iterrows():
        sel = gc[(gc["refinery_id"] == r["refinery_id"]) & (gc["compatible"])]
        out.append({
            **{k: (float(v) if isinstance(v, (int, float)) else v)
               for k, v in r.items()},
            "compatible_grades": sel["grade"].tolist(),
            "compatible_count": int(len(sel)),
            "provenance": Provenance.CURATED,
        })
    return out


@app.get("/api/spr")
def spr() -> dict[str, Any]:
    sites = loaders.spr_sites()
    s = loaders.summary()
    return {
        "sites": sites.to_dict("records"),
        "total_mmbbl": round(float((sites["capacity_mmbbl"] * sites["fill_pct"]).sum()), 2),
        "total_capacity_mmbbl": round(float(sites["capacity_mmbbl"].sum()), 2),
        "days_cover": s["spr_days_cover"],
        "max_drawdown_kbd": float(sites["max_drawdown_kbd"].sum()),
        "provenance": Provenance.CURATED,
    }


# --------------------------------------------------------------------------
# Phase 2 -- scenario modeller
# --------------------------------------------------------------------------
class ShockIn(BaseModel):
    kind: str = Field(description="chokepoint | corridor | supplier | port")
    target: str
    severity: float = Field(ge=0.0, le=1.0)
    duration_days: int = Field(ge=1, le=365)
    start_day: int = 0
    label: str = ""


class SimulateRequest(BaseModel):
    scenario_id: str | None = None
    shocks: list[ShockIn] | None = None
    overrides: dict[str, float] = Field(default_factory=dict)


@app.get("/api/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    return scenario_lib.listing()


@app.get("/api/assumptions")
def assumptions(overrides: str | None = None) -> list[dict[str, Any]]:
    """The assumption ledger. Every coefficient the cascade uses, with sources."""
    return ledger_payload()


@app.post("/api/simulate")
async def simulate(req: SimulateRequest) -> dict[str, Any]:
    """Run the deterministic cascade.

    Accepts either a named scenario or an arbitrary shock list, so the same
    endpoint serves the scenario panel and the judge's attack console.
    """
    if req.scenario_id:
        sc = scenario_lib.get(req.scenario_id)
        if sc is None:
            raise HTTPException(404, f"unknown scenario: {req.scenario_id}")
        shocks = list(sc["shocks"])
        meta = {"scenario_id": req.scenario_id, "name": sc["name"],
                "summary": sc["summary"],
                "historical_anchor": sc["historical_anchor"]}
    elif req.shocks:
        shocks = [
            Shock(kind=s.kind, target=s.target, severity=s.severity,
                  duration_days=s.duration_days, start_day=s.start_day,
                  label=s.label)
            for s in req.shocks
        ]
        meta = {"scenario_id": None, "name": "Custom shock",
                "summary": "Operator-defined shock set.",
                "historical_anchor": None}
    else:
        raise HTTPException(400, "provide either scenario_id or shocks")

    result = run_cascade(shocks, req.overrides).to_dict()
    result["meta"] = meta
    result["ledger"] = ledger_payload(req.overrides)

    await bus.publish("cascade.complete", {
        "name": meta["name"],
        "headline": result["headline"],
    }, provenance=Provenance.SIMULATED)

    return result


# --------------------------------------------------------------------------
# Phase 3 -- defense pipeline (cascade -> LP -> SPR -> narration)
# --------------------------------------------------------------------------
@app.post("/api/defend")
async def defend(req: SimulateRequest) -> dict[str, Any]:
    """The full defense pipeline. This is the path the demo stopwatch times."""
    if req.scenario_id:
        sc = scenario_lib.get(req.scenario_id)
        if sc is None:
            raise HTTPException(404, f"unknown scenario: {req.scenario_id}")
        shocks = list(sc["shocks"])
        meta = {"scenario_id": req.scenario_id, "name": sc["name"],
                "summary": sc["summary"],
                "historical_anchor": sc["historical_anchor"]}
    elif req.shocks:
        shocks = [
            Shock(kind=s.kind, target=s.target, severity=s.severity,
                  duration_days=s.duration_days, start_day=s.start_day,
                  label=s.label)
            for s in req.shocks
        ]
        meta = {"scenario_id": None, "name": "Custom shock",
                "summary": "Operator-defined shock set.",
                "historical_anchor": None}
    else:
        raise HTTPException(400, "provide either scenario_id or shocks")

    result = await run_defense_pipeline(shocks, req.overrides, meta)
    result["ledger"] = ledger_payload(req.overrides)
    return result


# --------------------------------------------------------------------------
# WebSocket hub
# --------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await bus.connect(ws)
    try:
        while True:
            # Client messages are not required; this keeps the socket open and
            # lets the browser send pings.
            await ws.receive_text()
    except WebSocketDisconnect:
        await bus.disconnect(ws)
    except Exception:
        await bus.disconnect(ws)


@app.get("/api/events")
def events(n: int = 100) -> list[dict[str, Any]]:
    return bus.recent(n)
