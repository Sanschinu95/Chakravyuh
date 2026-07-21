"""Mapping between supplier regions, freight route families and tanker pools.

Kept separate so the LP reads cleanly and so a new sourcing region is a data
change in one file rather than a change to the optimiser.
"""

from __future__ import annotations

# supplier region -> tanker availability region
TANKER_POOL: dict[str, str] = {
    "Middle East": "Arabian Gulf",
    "West Africa": "West Africa",
    "Atlantic": "US Gulf",
    "Latin America": "Latin America",
    "Black Sea": "Black Sea",
    "Caspian": "Black Sea",
    "Baltic": "Baltic",
    "Far East": "Far East Russia",
    "North Sea": "North Sea",
}

# supplier region -> freight route family
FREIGHT_FAMILY: dict[str, str] = {
    "Middle East": "AG-WCIndia",
    "West Africa": "WAF-India",
    "Atlantic": "USG-India",
    "Latin America": "LatAm-India",
    "Black Sea": "BlackSea-India",
    "Caspian": "BlackSea-India",
    "Baltic": "Baltic-India",
    "Far East": "FarEast-India",
    "North Sea": "NorthSea-India",
}

# India east-coast discharge ports carry an extra freight leg around Sri Lanka.
EAST_COAST_PORTS = {"Paradip", "Visakhapatnam", "Chennai"}
