"""The assumption ledger.

Every number the cascade uses that is not measured data lives here, with a
range, a unit and a citation. The UI renders this as sliders; dragging one
re-runs the cascade. This is the honest answer to "where did that GDP number
come from" -- you can see the elasticity, see its source, and move it.

Nothing in simulator.py is allowed to hardcode a coefficient. If you need a new
one, add it here with a source.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Assumption:
    key: str
    label: str
    value: float
    min: float
    max: float
    step: float
    unit: str
    stage: str
    source: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Stage names, used to group the sliders in the UI.
S_SUPPLY = "1. supply gap"
S_REFINERY = "2. refinery runs"
S_PRICE = "3. price pass-through"
S_SECTOR = "4. sector stress"
S_MACRO = "5. macro impact"


def default_ledger() -> list[Assumption]:
    return [
        # -- stage 1: how much of the blocked flow actually finds a way through
        Assumption(
            key="bypass_utilisation",
            label="Pipeline bypass utilisation",
            value=0.70, min=0.0, max=1.0, step=0.05, unit="fraction",
            stage=S_SUPPLY,
            source="EIA World Oil Transit Chokepoints (2024): Hormuz bypass = "
                   "Saudi East-West 5.0 mb/d + UAE ADCOP 1.5 mb/d",
            note="Spare pipeline capacity is rarely fully usable on short "
                 "notice; India's claim on it is its share of chokepoint flow.",
        ),
        Assumption(
            key="reroute_lag_days",
            label="Re-routing decision lag",
            value=4.0, min=0.0, max=21.0, step=1.0, unit="days",
            stage=S_SUPPLY,
            source="Observed charterer response in Red Sea diversions, Dec 2023 "
                   "- Feb 2024 (Clarksons / Lloyd's List reporting)",
            note="Time before replacement cargoes are even fixed.",
        ),
        # -- stage 2: what a refinery can physically do when its diet is cut
        Assumption(
            key="refinery_min_run_pct",
            label="Refinery technical minimum run",
            value=0.55, min=0.30, max=0.85, step=0.05, unit="fraction",
            stage=S_REFINERY,
            source="Typical CDU turndown limit; below this a unit trips rather "
                   "than throttles (industry engineering practice)",
            note="A refinery cannot idle smoothly to zero.",
        ),
        Assumption(
            key="substitution_efficiency",
            label="Crude substitution efficiency",
            value=0.75, min=0.0, max=1.0, step=0.05, unit="fraction",
            stage=S_REFINERY,
            source="Yield loss when running an off-design but compatible crude",
            note="Even a grade-compatible substitute gives up some yield and "
                 "throughput versus the design slate.",
        ),
        # -- stage 3: crude price and how much reaches the pump
        Assumption(
            key="brent_supply_elasticity",
            label="Brent response to supply loss",
            value=6.0, min=2.0, max=15.0, step=0.5, unit="% per 1% supply lost",
            stage=S_PRICE,
            source="Short-run price elasticity of oil demand ~0.05-0.15 implies "
                   "a 1% supply loss moves price 6-20% (Hamilton 2009; IMF WEO "
                   "Oct 2023 oil-shock box)",
            note="The single most leveraged assumption in the model.",
        ),
        Assumption(
            key="chokepoint_risk_premium_usd",
            label="Chokepoint risk premium",
            value=6.0, min=0.0, max=30.0, step=0.5, unit="USD/bbl",
            stage=S_PRICE,
            source="Brent premium observed during Jun 2025 US-Iran standoff and "
                   "Sep 2019 Abqaiq strike",
            note="Priced fear, on top of the physical barrels lost.",
        ),
        Assumption(
            key="price_passthrough",
            label="Crude to pump pass-through",
            value=0.35, min=0.0, max=1.0, step=0.05, unit="fraction",
            stage=S_PRICE,
            source="RBI Bulletin oil pass-through estimates for India; muted by "
                   "excise adjustment and OMC margin absorption",
            note="India historically absorbs much of a spike through taxes and "
                 "OMC margins rather than the pump price.",
        ),
        # -- stage 4: who feels the physical shortage
        Assumption(
            key="diesel_priority_share",
            label="Diesel protected share",
            value=0.80, min=0.0, max=1.0, step=0.05, unit="fraction",
            stage=S_SECTOR,
            source="Essential-use allocation practice (agriculture, freight, "
                   "defence) under fuel rationing",
            note="Diesel is protected first, so shortage lands on other products.",
        ),
        Assumption(
            key="demand_destruction",
            label="Demand destruction",
            value=0.15, min=0.0, max=0.5, step=0.05, unit="fraction",
            stage=S_SECTOR,
            source="Discretionary consumption response to a sharp price spike",
            note="Some of the gap closes itself because consumption falls.",
        ),
        # -- stage 5: macro
        Assumption(
            key="gdp_pct_per_10pct_oil",
            label="GDP impact per +10% oil",
            value=0.20, min=0.05, max=0.60, step=0.01, unit="% of GDP",
            stage=S_MACRO,
            source="IMF/RBI estimates for oil-importing India: a sustained 10% "
                   "crude increase costs roughly 0.15-0.30% of GDP",
            note="Applies to the price channel only.",
        ),
        Assumption(
            key="shortage_gdp_multiplier",
            label="Physical shortage GDP multiplier",
            value=1.2, min=0.0, max=5.0, step=0.1, unit="x",
            stage=S_MACRO,
            source="Rationed fuel is more damaging than expensive fuel; scales "
                   "the unserved-product share into GDP terms",
            note="Captures that you cannot buy diesel that does not exist.",
        ),
    ]


def ledger_dict(overrides: dict[str, float] | None = None) -> dict[str, float]:
    """Resolve the ledger to a flat {key: value}, applying overrides."""
    vals = {a.key: a.value for a in default_ledger()}
    if overrides:
        valid = set(vals)
        for k, v in overrides.items():
            if k in valid:
                vals[k] = float(v)
    return vals


def ledger_payload(overrides: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Ledger for the UI, with any overrides already applied to `value`."""
    ov = overrides or {}
    out = []
    for a in default_ledger():
        d = a.to_dict()
        if a.key in ov:
            d["value"] = float(ov[a.key])
            d["overridden"] = True
        else:
            d["overridden"] = False
        out.append(d)
    return out
