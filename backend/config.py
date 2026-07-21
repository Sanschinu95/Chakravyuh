"""Central configuration and the provenance vocabulary.

The provenance tags here are not decoration. Rule 1 of this project is the
honesty legend: anything the UI shows must carry a tag saying where it came
from. Every record that crosses the API boundary is stamped with one of these,
and the frontend colours it accordingly. If you add a new data source, you add
its tag here first.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CURATED_DIR: Final[Path] = ROOT / "data_curated"
REPLAY_DIR: Final[Path] = ROOT / "data_replay"
DB_PATH: Final[Path] = ROOT / "chakravyuh.duckdb"
STATE_DIR: Final[Path] = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)


# --------------------------------------------------------------------------
# Provenance / honesty legend
# --------------------------------------------------------------------------
class Provenance:
    """Where a number came from. Rendered as a colour in the UI."""

    LIVE = "live"          # green  - fetched from a live external feed right now
    CURATED = "curated"    # amber  - static reference data we loaded from CSV
    REPLAY = "replay"      # blue   - archived real data replayed on a clock
    SIMULATED = "simulated"  # purple - produced by our own simulator/solver
    INJECTED = "injected"  # red    - a human or the red team injected this event


PROVENANCE_LABELS = {
    Provenance.LIVE: "LIVE FEED",
    Provenance.CURATED: "CURATED / STATIC",
    Provenance.REPLAY: "REPLAYED ARCHIVE",
    Provenance.SIMULATED: "MODEL OUTPUT",
    Provenance.INJECTED: "INJECTED / TEST",
}

PROVENANCE_COLORS = {
    Provenance.LIVE: "#22c55e",
    Provenance.CURATED: "#f59e0b",
    Provenance.REPLAY: "#3b82f6",
    Provenance.SIMULATED: "#a855f7",
    Provenance.INJECTED: "#ef4444",
}


# --------------------------------------------------------------------------
# External services
# --------------------------------------------------------------------------
ANTHROPIC_API_KEY: Final[str | None] = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL: Final[str] = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
ANTHROPIC_FAST_MODEL: Final[str] = os.getenv("ANTHROPIC_FAST_MODEL", "claude-sonnet-5")
AISSTREAM_API_KEY: Final[str | None] = os.getenv("AISSTREAM_API_KEY")

LLM_ENABLED: Final[bool] = bool(ANTHROPIC_API_KEY)
AIS_ENABLED: Final[bool] = bool(AISSTREAM_API_KEY)


# --------------------------------------------------------------------------
# Domain constants
# --------------------------------------------------------------------------
CORRIDORS: Final[list[str]] = ["Hormuz", "RedSea_Suez", "Cape", "Malacca"]

# India's refined-product demand, used to convert crude shortfall into
# days-of-cover. ~5.4 mb/d product consumption, ~4.6 mb/d crude imports.
INDIA_CRUDE_RUN_KBD: Final[float] = 5300.0
INDIA_PRODUCT_DEMAND_KBD: Final[float] = 5400.0

USD_INR: Final[float] = 86.5
CRORE_PER_USD_MN: Final[float] = USD_INR / 10.0  # 1 USD mn -> INR crore

# Alert threshold on the Corridor Risk Index (0-100).
CRI_ALERT_THRESHOLD: Final[float] = 62.0
