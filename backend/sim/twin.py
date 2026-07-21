"""The digital twin: a networkx knowledge graph of India's crude supply network.

    supplier -> corridor -> chokepoint -> port -> refinery

The graph is the shared substrate. The simulator walks it to propagate a shock;
the red team walks it to find the cheapest cut; the frontend renders it. Node
ids are namespaced ("sup:BASM", "cp:HORMUZ") so a single graph can hold
heterogeneous entities without collisions.
"""

from __future__ import annotations

import functools
from typing import Any, Iterable

import networkx as nx
import pandas as pd

from backend.config import Provenance
from backend.data import loaders

# Node kinds
SUPPLIER = "supplier"
CORRIDOR = "corridor"
CHOKEPOINT = "chokepoint"
PORT = "port"
REFINERY = "refinery"
SPR = "spr"


def nid(kind: str, key: str) -> str:
    prefix = {
        SUPPLIER: "sup",
        CORRIDOR: "cor",
        CHOKEPOINT: "cp",
        PORT: "port",
        REFINERY: "ref",
        SPR: "spr",
    }[kind]
    return f"{prefix}:{key}"


def build_graph() -> nx.DiGraph:
    """Construct the twin from curated tables. Cheap enough to rebuild freely."""
    g = nx.DiGraph()

    sup = loaders.suppliers()
    ref = loaders.refineries()
    rts = loaders.routes()
    imp = loaders.imports_baseline()
    chk = loaders.chokepoints()
    spr = loaders.spr_sites()

    baseline = dict(zip(imp["supplier_id"], imp["barrels_per_week_kb"]))

    # --- suppliers -------------------------------------------------------
    for _, r in sup.iterrows():
        g.add_node(
            nid(SUPPLIER, r["supplier_id"]),
            kind=SUPPLIER,
            key=r["supplier_id"],
            label=r["grade"],
            country=r["country"],
            region=r["region"],
            lat=float(r["load_lat"]),
            lon=float(r["load_lon"]),
            api_gravity=float(r["api_gravity"]),
            sulfur_pct=float(r["sulfur_pct"]),
            corridor=r["primary_corridor"],
            load_port=r["load_port"],
            max_liftable_kbd=float(r["max_liftable_kbd"]),
            spot_premium_usd_bbl=float(r["spot_premium_usd_bbl"]),
            political_risk=float(r["political_risk"]),
            baseline_kb_week=float(baseline.get(r["supplier_id"], 0.0)),
            provenance=Provenance.CURATED,
        )

    # --- corridors -------------------------------------------------------
    corridor_flow = imp.groupby("corridor")["barrels_per_week_kb"].sum().to_dict()
    for corridor in sorted(sup["primary_corridor"].unique()):
        g.add_node(
            nid(CORRIDOR, corridor),
            kind=CORRIDOR,
            key=corridor,
            label=corridor.replace("_", "/"),
            baseline_kb_week=float(corridor_flow.get(corridor, 0.0)),
            provenance=Provenance.CURATED,
        )

    # --- chokepoints -----------------------------------------------------
    for _, r in chk.iterrows():
        g.add_node(
            nid(CHOKEPOINT, r["chokepoint_id"]),
            kind=CHOKEPOINT,
            key=r["chokepoint_id"],
            label=r["name"],
            lat=float(r["lat"]),
            lon=float(r["lon"]),
            global_oil_transit_mbd=float(r["global_oil_transit_mbd"]),
            bypass_capacity_mbd=float(r["bypass_capacity_mbd"]),
            alternative_exists=r["alternative_exists"],
            provenance=Provenance.CURATED,
        )

    # --- ports + refineries ----------------------------------------------
    for _, r in ref.iterrows():
        port_key = r["primary_port"]
        pnode = nid(PORT, port_key)
        if pnode not in g:
            g.add_node(
                pnode,
                kind=PORT,
                key=port_key,
                label=port_key,
                lat=float(r["port_lat"]),
                lon=float(r["port_lon"]),
                berth_capacity_kbd=0.0,
                provenance=Provenance.CURATED,
            )
        g.nodes[pnode]["berth_capacity_kbd"] += float(r["berth_capacity_kbd"])

        rnode = nid(REFINERY, r["refinery_id"])
        g.add_node(
            rnode,
            kind=REFINERY,
            key=r["refinery_id"],
            label=r["name"],
            operator=r["operator"],
            state=r["state"],
            lat=float(r["lat"]),
            lon=float(r["lon"]),
            capacity_kbd=float(r["capacity_kbd"]),
            api_min=float(r["api_min"]),
            api_max=float(r["api_max"]),
            sulfur_max_pct=float(r["sulfur_max_pct"]),
            nelson_complexity=float(r["nelson_complexity"]),
            primary_port=port_key,
            provenance=Provenance.CURATED,
        )
        g.add_edge(pnode, rnode, kind="delivers_to",
                   capacity_kbd=float(r["berth_capacity_kbd"]))

    # --- SPR sites -------------------------------------------------------
    for _, r in spr.iterrows():
        g.add_node(
            nid(SPR, r["site_id"]),
            kind=SPR,
            key=r["site_id"],
            label=r["site"],
            lat=float(r["lat"]),
            lon=float(r["lon"]),
            capacity_mmbbl=float(r["capacity_mmbbl"]),
            fill_pct=float(r["fill_pct"]),
            max_drawdown_kbd=float(r["max_drawdown_kbd"]),
            notional_grade=r["notional_grade"],
            provenance=Provenance.CURATED,
        )

    # --- edges: supplier -> corridor -> chokepoint ------------------------
    for _, r in sup.iterrows():
        s = nid(SUPPLIER, r["supplier_id"])
        c = nid(CORRIDOR, r["primary_corridor"])
        g.add_edge(s, c, kind="ships_via",
                   baseline_kb_week=float(baseline.get(r["supplier_id"], 0.0)))

    # A corridor traverses the chokepoints named on its routes.
    corridor_chokes: dict[str, set[str]] = {}
    name_to_id = dict(zip(chk["name"], chk["chokepoint_id"]))
    for _, r in rts.iterrows():
        names = str(r["chokepoints"]).split("|")
        corridor_chokes.setdefault(r["corridor"], set()).update(
            name_to_id[n] for n in names if n in name_to_id
        )
    for corridor, cps in corridor_chokes.items():
        for cp in cps:
            g.add_edge(nid(CORRIDOR, corridor), nid(CHOKEPOINT, cp),
                       kind="transits")

    # --- edges: supplier -> port (one per distinct route pairing) ---------
    for (sid, port, vclass), grp in rts.groupby(
        ["supplier_id", "discharge_port", "vessel_class"]
    ):
        row = grp.iloc[0]
        pnode = nid(PORT, port)
        if pnode not in g:
            continue  # discharge port not attached to a modelled refinery
        g.add_edge(
            nid(SUPPLIER, sid), pnode,
            kind="route",
            vessel_class=vclass,
            voyage_days=float(row["voyage_days"]),
            distance_nm=float(row["distance_nm"]),
            corridor=row["corridor"],
        )

    return g


def graph_stats(g: nx.DiGraph) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    for _, d in g.nodes(data=True):
        by_kind[d.get("kind", "?")] = by_kind.get(d.get("kind", "?"), 0) + 1
    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
            "by_kind": by_kind}


@functools.lru_cache(maxsize=1)
def get_graph() -> nx.DiGraph:
    """Process-wide cached graph. Call invalidate() after reseeding."""
    return build_graph()


def invalidate() -> None:
    get_graph.cache_clear()
    loaders.clear_cache()


# --------------------------------------------------------------------------
# Queries used by the API / simulator / red team
# --------------------------------------------------------------------------
def suppliers_on_corridor(corridor: str, g: nx.DiGraph | None = None) -> list[str]:
    g = g or get_graph()
    cnode = nid(CORRIDOR, corridor)
    return [
        g.nodes[u]["key"]
        for u, v, d in g.in_edges(cnode, data=True)
        if d.get("kind") == "ships_via"
    ]


def corridors_through(chokepoint_id: str, g: nx.DiGraph | None = None) -> list[str]:
    g = g or get_graph()
    cp = nid(CHOKEPOINT, chokepoint_id)
    if cp not in g:
        return []
    return [
        g.nodes[u]["key"]
        for u, v, d in g.in_edges(cp, data=True)
        if d.get("kind") == "transits"
    ]


def exposure_to_chokepoint(chokepoint_id: str,
                           g: nx.DiGraph | None = None) -> dict[str, Any]:
    """How many barrels/week ride through a given chokepoint, and whose."""
    g = g or get_graph()
    corridors = corridors_through(chokepoint_id, g)
    sids: list[str] = []
    for c in corridors:
        sids.extend(suppliers_on_corridor(c, g))
    total = sum(g.nodes[nid(SUPPLIER, s)]["baseline_kb_week"] for s in sids)
    return {
        "chokepoint": chokepoint_id,
        "corridors": corridors,
        "suppliers": sids,
        "exposed_kb_week": round(total, 1),
        "exposed_kbd": round(total / 7.0, 1),
    }


def refineries_fed_by(supplier_id: str,
                      g: nx.DiGraph | None = None) -> list[dict[str, Any]]:
    """Grade-compatible refineries reachable from a supplier, with lead time."""
    g = g or get_graph()
    snode = nid(SUPPLIER, supplier_id)
    if snode not in g:
        return []
    compat = set()
    gc = loaders.grade_compatibility()
    sel = gc[(gc["supplier_id"] == supplier_id) & (gc["compatible"])]
    compat.update(sel["refinery_id"].tolist())

    out: list[dict[str, Any]] = []
    for _, port, d in g.out_edges(snode, data=True):
        if d.get("kind") != "route":
            continue
        for _, rnode, dd in g.out_edges(port, data=True):
            if dd.get("kind") != "delivers_to":
                continue
            rkey = g.nodes[rnode]["key"]
            if rkey not in compat:
                continue
            out.append({
                "refinery_id": rkey,
                "refinery": g.nodes[rnode]["label"],
                "port": g.nodes[port]["key"],
                "vessel_class": d["vessel_class"],
                "voyage_days": d["voyage_days"],
            })
    return out


def to_geojson_like(g: nx.DiGraph | None = None) -> dict[str, Any]:
    """Flat node/edge payload for deck.gl. Provenance travels with each node."""
    g = g or get_graph()
    nodes = []
    for n, d in g.nodes(data=True):
        if "lat" not in d:
            continue
        nodes.append({"id": n, **{k: v for k, v in d.items()}})
    edges = []
    for u, v, d in g.edges(data=True):
        du, dv = g.nodes[u], g.nodes[v]
        if "lat" not in du or "lat" not in dv:
            continue
        edges.append({
            "source": u, "target": v,
            "from": [du["lon"], du["lat"]], "to": [dv["lon"], dv["lat"]],
            **{k: v2 for k, v2 in d.items()},
        })
    return {"nodes": nodes, "edges": edges}
