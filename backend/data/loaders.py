"""Curated CSV -> DuckDB, and typed accessors for the rest of the backend.

Everything downstream (simulator, LP, red team) reads through here so there is
exactly one definition of "what the network looks like".
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from backend.config import CURATED_DIR, DB_PATH

# table name -> curated csv filename
CURATED_TABLES: dict[str, str] = {
    "refineries": "refineries.csv",
    "suppliers": "suppliers.csv",
    "routes": "routes.csv",
    "spr_sites": "spr_sites.csv",
    "imports_baseline": "imports_baseline.csv",
    "freight": "freight.csv",
    "tanker_availability": "tanker_availability.csv",
    "chokepoints": "chokepoints.csv",
    "corridor_waypoints": "corridor_waypoints.csv",
}


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
    except Exception:
        # Spatial is a nice-to-have for distance helpers; the app works without.
        pass
    return con


def seed(verbose: bool = True) -> dict[str, int]:
    """(Re)build the DuckDB from the curated CSVs. Idempotent."""
    counts: dict[str, int] = {}
    con = connect()
    try:
        for table, filename in CURATED_TABLES.items():
            path = CURATED_DIR / filename
            if not path.exists():
                raise FileNotFoundError(f"curated file missing: {path}")
            con.execute(f"DROP TABLE IF EXISTS {table}")
            con.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto(?, header=true)",
                [str(path)],
            )
            n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            counts[table] = n
            if verbose:
                print(f"  {table:<22} {n:>5} rows")

        # Recompute import shares rather than trusting the hand-entered column,
        # so the shares always sum to 100 no matter how the baseline is edited.
        con.execute(
            """
            CREATE OR REPLACE TABLE imports_baseline AS
            SELECT
                supplier_id,
                corridor,
                barrels_per_week_kb,
                round(100.0 * barrels_per_week_kb
                      / sum(barrels_per_week_kb) OVER (), 3) AS share_pct,
                typical_discharge_port
            FROM imports_baseline
            """
        )

        # Derived view: which supplier grades each refinery can physically run.
        # This single view is the reason our procurement recommendations are
        # executable rather than generic -- a refinery configured for heavy sour
        # cannot simply switch to light sweet and vice versa.
        con.execute(
            """
            CREATE OR REPLACE VIEW grade_compatibility AS
            SELECT
                r.refinery_id,
                r.name          AS refinery,
                s.supplier_id,
                s.grade,
                s.api_gravity,
                s.sulfur_pct,
                r.api_min,
                r.api_max,
                r.sulfur_max_pct,
                (s.api_gravity >= r.api_min
                 AND s.api_gravity <= r.api_max
                 AND s.sulfur_pct <= r.sulfur_max_pct) AS compatible
            FROM refineries r
            CROSS JOIN suppliers s
            """
        )
    finally:
        con.close()
    return counts


# --------------------------------------------------------------------------
# Cached accessors
# --------------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def _table(name: str) -> pd.DataFrame:
    con = connect(read_only=True)
    try:
        return con.execute(f"SELECT * FROM {name}").fetch_df()
    finally:
        con.close()


def clear_cache() -> None:
    _table.cache_clear()


def refineries() -> pd.DataFrame:
    return _table("refineries").copy()


def suppliers() -> pd.DataFrame:
    return _table("suppliers").copy()


def routes() -> pd.DataFrame:
    return _table("routes").copy()


def spr_sites() -> pd.DataFrame:
    return _table("spr_sites").copy()


def imports_baseline() -> pd.DataFrame:
    return _table("imports_baseline").copy()


def freight() -> pd.DataFrame:
    return _table("freight").copy()


def tanker_availability() -> pd.DataFrame:
    return _table("tanker_availability").copy()


def chokepoints() -> pd.DataFrame:
    return _table("chokepoints").copy()


def corridor_waypoints() -> pd.DataFrame:
    return _table("corridor_waypoints").copy()


def grade_compatibility() -> pd.DataFrame:
    return _table("grade_compatibility").copy()


def compatible_suppliers(refinery_id: str) -> list[str]:
    gc = grade_compatibility()
    mask = (gc["refinery_id"] == refinery_id) & (gc["compatible"])
    return gc.loc[mask, "supplier_id"].tolist()


def db_exists() -> bool:
    return Path(DB_PATH).exists()


def summary() -> dict[str, Any]:
    imp = imports_baseline()
    ref = refineries()
    spr = spr_sites()
    total_kb_week = float(imp["barrels_per_week_kb"].sum())
    spr_bbl = float((spr["capacity_mmbbl"] * spr["fill_pct"]).sum()) * 1e6
    daily_import_bbl = total_kb_week / 7.0 * 1e3
    return {
        "refinery_count": int(len(ref)),
        "refining_capacity_kbd": float(ref["capacity_kbd"].sum()),
        "supplier_count": int(len(suppliers())),
        "route_count": int(len(routes())),
        "import_kbd": round(total_kb_week / 7.0, 1),
        "spr_mmbbl": round(spr_bbl / 1e6, 2),
        "spr_days_cover": round(spr_bbl / daily_import_bbl, 1),
        "corridor_shares": (
            imp.groupby("corridor")["barrels_per_week_kb"].sum()
            / total_kb_week * 100.0
        ).round(2).to_dict(),
    }
