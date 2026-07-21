"""Scenario library -- named parameter sets over the shock model.

These are the situations a planner already worries about. The red team agent in
phase 7 does not draw from this list; its whole job is to find the ones nobody
wrote down.
"""

from __future__ import annotations

from typing import Any

from backend.sim.simulator import Shock

SCENARIOS: dict[str, dict[str, Any]] = {
    "hormuz_partial": {
        "name": "Hormuz partial closure",
        "summary": "Strait of Hormuz throughput cut by half for three weeks "
                   "following a naval confrontation.",
        "severity_label": "severe",
        "shocks": [Shock("chokepoint", "HORMUZ", 0.50, 21, label="Hormuz 50%")],
        "historical_anchor": "Jun 2025 US-Iran standoff; Iranian parliament "
                             "voted to close the strait.",
    },
    "hormuz_full": {
        "name": "Hormuz closure",
        "summary": "Full closure of the Strait of Hormuz for two weeks. The "
                   "worst credible single-chokepoint event for India.",
        "severity_label": "extreme",
        "shocks": [Shock("chokepoint", "HORMUZ", 1.0, 14, label="Hormuz closed")],
        "historical_anchor": "Never realised; repeatedly threatened since 1984.",
    },
    "red_sea_suspension": {
        "name": "Red Sea suspension",
        "summary": "Bab el-Mandeb effectively closed to tankers; Suez traffic "
                   "reroutes around the Cape, adding 10-14 days per voyage.",
        "severity_label": "moderate",
        "shocks": [Shock("chokepoint", "BAB", 0.85, 60, label="Bab el-Mandeb 85%")],
        "historical_anchor": "Houthi attacks, Dec 2023 onward; most carriers "
                             "diverted via the Cape.",
    },
    "malacca_disruption": {
        "name": "Malacca disruption",
        "summary": "Strait of Malacca restricted, cutting Russian Far East "
                   "barrels into India's east coast refineries.",
        "severity_label": "moderate",
        "shocks": [Shock("chokepoint", "MALACCA", 0.60, 30, label="Malacca 60%")],
        "historical_anchor": "Congestion and piracy risk; no full closure on record.",
    },
    "russia_sanctions": {
        "name": "Russian barrels sanctioned out",
        "summary": "Secondary sanctions make Urals and ESPO untouchable for "
                   "Indian refiners, removing India's largest single source.",
        "severity_label": "severe",
        "shocks": [
            Shock("supplier", "URAL", 0.90, 90, label="Urals 90%"),
            Shock("supplier", "URLB", 0.90, 90, label="Urals Baltic 90%"),
            Shock("supplier", "ESPO", 0.75, 90, label="ESPO 75%"),
        ],
        "historical_anchor": "Jan 2025 OFAC designations of Sovcomflot tonnage "
                             "and shadow-fleet operators.",
    },
    "combined_hormuz_monsoon": {
        "name": "Hormuz slowdown + monsoon port closure",
        "summary": "A partial Hormuz restriction lands at the same time as a "
                   "cyclone shuts Paradip, so the east coast cannot absorb the "
                   "re-routed cargoes.",
        "severity_label": "severe",
        "shocks": [
            Shock("chokepoint", "HORMUZ", 0.35, 21, label="Hormuz 35%"),
            Shock("port", "Paradip", 0.80, 10, label="Paradip closed"),
        ],
        "historical_anchor": "Cyclone Fani (2019) shut Paradip for six days.",
    },
    "opec_cut": {
        "name": "OPEC+ deep cut",
        "summary": "Coordinated Gulf production cut removes term barrels "
                   "without any physical blockage.",
        "severity_label": "moderate",
        "shocks": [
            Shock("supplier", "ARBL", 0.25, 90, label="Arab Light -25%"),
            Shock("supplier", "ARBM", 0.25, 90, label="Arab Medium -25%"),
            Shock("supplier", "BASM", 0.15, 90, label="Basrah Medium -15%"),
        ],
        "historical_anchor": "Apr 2023 surprise OPEC+ cut of 1.16 mb/d.",
    },
}


def get(scenario_id: str) -> dict[str, Any] | None:
    return SCENARIOS.get(scenario_id)


def listing() -> list[dict[str, Any]]:
    return [
        {
            "id": sid,
            "name": s["name"],
            "summary": s["summary"],
            "severity_label": s["severity_label"],
            "historical_anchor": s["historical_anchor"],
            "shocks": [sh.to_dict() for sh in s["shocks"]],
        }
        for sid, s in SCENARIOS.items()
    ]
