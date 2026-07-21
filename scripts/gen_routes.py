"""Generate data_curated/routes.csv from a curated sea-distance table.

Distances are laden sea distances in nautical miles, curated from published
port-to-port distance tables (BP Shipping / Marine Traffic voyage calculators,
Worldscale route definitions). They are approximate but plausible: the point of
the prototype is that voyage TIME is a hard constraint on how fast a barrel can
physically arrive, and that time comes from distance/speed, not from a guess.

Routing rule: each supplier has a primary corridor. We do NOT route Russian
Baltic or US Gulf VLCC cargoes through Suez, because fully laden VLCCs cannot
transit the canal at max draft -- they go around the Cape. That constraint is
why "just buy from the US instead" costs 3+ weeks of lead time, which is
exactly the kind of thing the procurement LP has to respect.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data_curated"

# Sea distance (nm) from each supplier load port to the India West Coast
# gateway (Sikka / Vadinar, ~22.4N 69.8E), by the supplier's primary corridor.
LOADPORT_TO_WESTCOAST_NM = {
    "BASM": 1500,   # Basrah -> Hormuz -> Arabian Sea
    "BASH": 1500,
    "ARBL": 1550,   # Ras Tanura
    "ARBM": 1550,
    "MURB": 1200,   # Jebel Dhanna
    "UZAK": 1220,   # Zirku Island
    "OMAN": 900,    # Mina al Fahal (outside Hormuz, but Gulf-adjacent)
    "QALS": 1350,   # Ras Laffan
    "URAL": 4600,   # Novorossiysk -> Bosphorus -> Suez -> Bab el-Mandeb
    "URLB": 11500,  # Primorsk -> Baltic -> Cape of Good Hope (no laden Suez)
    "ESPO": 5600,   # Kozmino -> Malacca
    "SOKL": 6000,   # De-Kastri -> Malacca
    "WTIM": 11800,  # Corpus Christi -> Cape
    "MARS": 11900,  # LOOP -> Cape
    "BONL": 6900,   # Bonny -> Cape
    "QUAI": 6850,   # Qua Iboe -> Cape
    "GIRA": 6200,   # Girassol FPSO (Angola) -> Cape
    "TUPI": 8300,   # Angra dos Reis -> Cape
    "LIZA": 10300,  # Guyana -> Cape
    "CPCB": 4600,   # CPC Novorossiysk -> Suez
    "JSVE": 11200,  # Mongstad -> Cape
}

# Coastal steaming distance (nm) from the West Coast gateway to each discharge
# port. East coast ports route around Sri Lanka, which is why Paradip is ~2,650
# nm further than Sikka -- roughly 8 extra days on a VLCC.
DISCHARGE_PORTS = {
    "Sikka": 0,
    "Vadinar SPM": 20,
    "Mundra": 120,
    "Mumbai (Butcher Island)": 380,
    "New Mangalore": 830,
    "Kochi (Puthuvypeen SPM)": 1050,
    "Chennai": 1850,
    "Visakhapatnam": 2300,
    "Paradip": 2650,
}

# Ports without deep-draft SPM capability for a fully laden VLCC.
NO_VLCC = {"Chennai", "Mumbai (Butcher Island)"}

# Service speed (knots) and cargo size (thousand bbl) by vessel class.
VESSEL_CLASSES = {
    "VLCC": {"speed_kn": 13.0, "cargo_kb": 2000},
    "Suezmax": {"speed_kn": 13.5, "cargo_kb": 1000},
    "Aframax": {"speed_kn": 13.5, "cargo_kb": 650},
}

# Port + terminal overhead: loading, waiting for berth, discharge (days).
PORT_OVERHEAD_DAYS = 2.0

CORRIDOR_CHOKEPOINTS = {
    "Hormuz": "Strait of Hormuz",
    "RedSea_Suez": "Bab el-Mandeb|Suez Canal",
    "Cape": "Cape of Good Hope",
    "Malacca": "Strait of Malacca",
}

# Baltic-origin cargoes also transit the Danish Straits before the Cape leg.
EXTRA_CHOKEPOINTS = {"URLB": "Danish Straits", "JSVE": ""}


def load_suppliers() -> list[dict]:
    with open(CURATED / "suppliers.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_rows(suppliers: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for sup in suppliers:
        sid = sup["supplier_id"]
        corridor = sup["primary_corridor"]
        base_nm = LOADPORT_TO_WESTCOAST_NM[sid]
        chokes = CORRIDOR_CHOKEPOINTS[corridor]
        extra = EXTRA_CHOKEPOINTS.get(sid)
        if extra:
            chokes = f"{extra}|{chokes}"

        for port, coastal_nm in DISCHARGE_PORTS.items():
            total_nm = base_nm + coastal_nm
            for vclass, spec in VESSEL_CLASSES.items():
                if vclass == "VLCC" and port in NO_VLCC:
                    continue
                steaming = total_nm / (spec["speed_kn"] * 24.0)
                voyage_days = round(steaming + PORT_OVERHEAD_DAYS, 1)
                rows.append(
                    {
                        "route_id": f"{sid}-{port.split()[0][:4].upper()}-{vclass[:3].upper()}",
                        "supplier_id": sid,
                        "load_port": sup["load_port"],
                        "discharge_port": port,
                        "corridor": corridor,
                        "vessel_class": vclass,
                        "distance_nm": total_nm,
                        "voyage_days": voyage_days,
                        "cargo_size_kb": spec["cargo_kb"],
                        "chokepoints": chokes,
                    }
                )
    return rows


def main() -> None:
    rows = build_rows(load_suppliers())
    out = CURATED / "routes.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} routes -> {out}")


if __name__ == "__main__":
    main()
