"""Headline -> structured event extraction.

The LLM is used for *labelling* only: who, what, where, which corridor, how bad
on a 0-1 scale. It never produces a barrel, a price, or a probability that
reaches the API -- those come from the solver and the index arithmetic.

Every extraction degrades to a deterministic keyword pass when the LLM is
absent, slow, or returns something unparseable, and the payload always says
which path ran (`method`: "llm" | "keyword"). Extraction output is model
output, so it is tagged SIMULATED regardless of path; the *article* keeps its
own provenance (LIVE or REPLAY) alongside.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Iterable

from backend.agents.llm import extract, llm_available
from backend.config import Provenance

CORRIDOR_CHOICES = ["Hormuz", "RedSea_Suez", "Cape", "Malacca", "none"]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "actor": {"type": "string"},
        "action": {"type": "string"},
        "location": {"type": "string"},
        "severity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "corridor_affected": {"type": "string", "enum": CORRIDOR_CHOICES},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["actor", "action", "location", "severity",
                 "corridor_affected", "confidence"],
}

SYSTEM = (
    "You label maritime energy security news for a supply-chain risk system. "
    "Given one headline, identify the acting party, the action taken, the "
    "location, which shipping corridor is affected, how severe the event is "
    "for crude flows on a 0-1 scale, and your confidence. Severity 1.0 means "
    "a corridor is physically closed to tankers; 0.0 means no effect on crude "
    "movement. Choose corridor_affected from "
    f"{CORRIDOR_CHOICES}. Answer only about the headline you are given."
)

_LLM_TIMEOUT_S = 8.0


# --------------------------------------------------------------------------
# Deterministic keyword fallback
# --------------------------------------------------------------------------
# Ordered most-specific first; the first match wins for action, and the
# highest severity across all matches is taken.
_ACTION_RULES: list[tuple[str, str, float, float]] = [
    # (regex, action label, severity, confidence)
    (r"\bclos(e|ing|ure)\b.{0,30}\bstrait\b|\bstrait\b.{0,30}\bclos", "corridor_closure", 0.97, 0.85),
    (r"\bmine[sd]?\b|\bmining\b|\bblockad", "mining_or_blockade", 0.93, 0.8),
    (r"\bseiz(e|ed|ure)\b|\bdetain|\bboard(ed|ing)\b.{0,20}\btanker", "vessel_seizure", 0.82, 0.8),
    (r"\btanker\b.{0,40}\b(hit|struck|attack|collid)", "vessel_attack", 0.86, 0.8),
    (r"\bstrikes?\b|\bstruck\b|\bmissile|\bdrone\b|\bbomb", "military_strike", 0.78, 0.78),
    (r"\bretaliat|\bvows?\b|\bwarn(s|ed|ing)?\b|\bthreat", "threat", 0.55, 0.6),
    (r"\bdark\b|\bjamming\b|\binterference\b|\bgps\b|\bais\b", "signal_disruption", 0.6, 0.65),
    (r"\bsuspend|\bdeclin(e|ing)\b.{0,20}\bfixtur|\bturn(s|ed)? away|\bwait(ing)?\b.{0,20}\boutside", "shipping_withdrawal", 0.62, 0.7),
    (r"\breroute|\bavoid|\bdivert|\badvisor(y|ies)\b|\bwar risk\b|\bpremium\b", "risk_repricing", 0.45, 0.6),
    (r"\bsanction|\bcensur|\bnon-compliance\b|\bbreach\b|\bsafeguards\b", "sanctions_or_censure", 0.42, 0.6),
    (r"\bevacuat|\bdrawdown\b|\bdepart(ure)?\b.{0,20}\bdependan|\breduce staffing\b|\bembassy\b", "posture_change", 0.5, 0.65),
    (r"\bdeploy|\bcarrier\b|\bexercise\b|\bdrill\b|\bairspace\b", "military_posture", 0.4, 0.55),
    (r"\bceasefire\b|\btruce\b|\bresum(e|ed|ing)\b|\beas(e|ed|ing)\b|\bnormal\b|\bdeal\b|\btalks\b", "de_escalation", 0.1, 0.6),
]

_CORRIDOR_RULES: list[tuple[str, str]] = [
    (r"\bhormuz\b|\bpersian gulf\b|\barabian gulf\b|\bfujairah\b|\bras tanura\b"
     r"|\bbasrah\b|\bjebel dhanna\b|\bal udeid\b|\bqatar\b|\bkuwait\b|\bbahrain\b"
     r"|\biran(ian)?\b|\btehran\b|\bgulf\b|\bomani?\b|\bsaudi\b|\buae\b|\bdubai\b", "Hormuz"),
    (r"\bred sea\b|\bbab el-?mandeb\b|\bsuez\b|\bhouthi\b|\byemen\b|\baden\b"
     r"|\bdjibouti\b|\bsumed\b|\bjeddah\b", "RedSea_Suez"),
    (r"\bmalacca\b|\bsingapore\b|\blombok\b|\bsunda\b|\bstraits? of malacca\b"
     r"|\bkozmino\b|\bespo\b", "Malacca"),
    (r"\bcape of good hope\b|\bcape town\b|\bwest africa\b|\bnigeria\b|\bangola\b"
     r"|\bbonny\b|\bqua iboe\b|\bgirassol\b|\batlantic basin\b", "Cape"),
]

_ACTOR_RULES: list[tuple[str, str]] = [
    (r"\biran(ian)?\b|\btehran\b|\birgc\b", "Iran"),
    (r"\bisrael(i)?\b|\bidf\b", "Israel"),
    (r"\bus\b|\bunited states\b|\bwashington\b|\bamerican\b|\bpentagon\b", "United States"),
    (r"\bhouthi", "Houthi forces"),
    (r"\biaea\b|\bnuclear watchdog\b", "IAEA"),
    (r"\bopec\b|\bsaudi aramco\b|\badnoc\b|\bsomo\b", "Producer/NOC"),
    (r"\bshipowner|\bcharterer|\bowners?\b|\bbroker|\binsurer|\bunderwrit", "Shipping market"),
    (r"\brefiner|\bindian?\b|\bdelhi\b", "Refiner/importer"),
    (r"\bqatar\b|\boman\b|\buae\b|\bsaudi\b|\bkuwait\b|\bbahrain\b", "Gulf state"),
]

_LOCATION_RULES: list[tuple[str, str]] = [
    (r"\bhormuz\b", "Strait of Hormuz"),
    (r"\bfujairah\b", "Fujairah"),
    (r"\bbab el-?mandeb\b", "Bab el-Mandeb"),
    (r"\bred sea\b", "Red Sea"),
    (r"\bsuez\b", "Suez Canal"),
    (r"\bmalacca\b", "Strait of Malacca"),
    (r"\bcape of good hope\b", "Cape of Good Hope"),
    (r"\btehran\b", "Tehran"),
    (r"\bbaghdad\b", "Baghdad"),
    (r"\bqatar\b", "Qatar"),
    (r"\bgulf\b", "Persian Gulf"),
    (r"\bmuscat\b|\boman\b", "Oman"),
    (r"\bgeneva\b|\bvienna\b", "Europe (diplomatic)"),
]


def _first_match(rules: Iterable[tuple[str, str]], text: str,
                 default: str) -> str:
    for pattern, label in rules:
        if re.search(pattern, text, flags=re.I):
            return label
    return default


def keyword_extract(article: dict[str, Any]) -> dict[str, Any]:
    """Deterministic extraction. Always available, never raises."""
    title = str(article.get("title") or "")
    text = title.lower()

    action, severity, confidence = "unclassified", 0.15, 0.3
    for pattern, label, sev, conf in _ACTION_RULES:
        if re.search(pattern, text, flags=re.I):
            if action == "unclassified":
                action, confidence = label, conf
            severity = max(severity, sev)

    # GDELT tone, when present, nudges severity: strongly negative coverage of
    # an ambiguous headline is evidence of severity the keywords missed.
    tone = article.get("tone")
    if isinstance(tone, (int, float)):
        tone_sev = max(0.0, min(1.0, (-float(tone)) / 12.0))
        severity = max(severity, 0.65 * tone_sev + 0.35 * severity)
        if action == "de_escalation" and float(tone) > 0:
            severity = min(severity, 0.15)

    corridor = _first_match(_CORRIDOR_RULES, text, "none")
    actor = _first_match(_ACTOR_RULES, text, "unattributed")
    location = _first_match(_LOCATION_RULES, text, "unspecified")

    return {
        "actor": actor,
        "action": action,
        "location": location,
        "severity": round(max(0.0, min(1.0, severity)), 3),
        "corridor_affected": corridor,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "method": "keyword",
        "title": title,
        "date": article.get("date"),
        "source": article.get("source"),
        "url": article.get("url"),
        "article_provenance": article.get("provenance", Provenance.REPLAY),
        "provenance": Provenance.SIMULATED,
    }


# --------------------------------------------------------------------------
# LLM path
# --------------------------------------------------------------------------
def _coerce(raw: dict[str, Any], article: dict[str, Any],
            fallback: dict[str, Any]) -> dict[str, Any]:
    """Trust nothing the model returns; clamp it into the schema or drop back."""
    def num(key: str, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    corridor = str(raw.get("corridor_affected") or "none")
    if corridor not in CORRIDOR_CHOICES:
        corridor = fallback["corridor_affected"]

    return {
        "actor": str(raw.get("actor") or fallback["actor"])[:80],
        "action": str(raw.get("action") or fallback["action"])[:80],
        "location": str(raw.get("location") or fallback["location"])[:80],
        "severity": round(num("severity", fallback["severity"]), 3),
        "corridor_affected": corridor,
        "confidence": round(num("confidence", fallback["confidence"]), 3),
        "method": "llm",
        "title": fallback["title"],
        "date": article.get("date"),
        "source": article.get("source"),
        "url": article.get("url"),
        "article_provenance": article.get("provenance", Provenance.REPLAY),
        "provenance": Provenance.SIMULATED,
    }


async def extract_event(article: dict[str, Any]) -> dict[str, Any]:
    """Extract one structured event from an article dict.

    `article` needs at least `title`; `date`, `source`, `url`, `tone` and
    `provenance` are carried through when present.
    """
    fallback = keyword_extract(article)
    if not llm_available():
        fallback["fallback_reason"] = "no LLM provider configured"
        return fallback

    user = (
        f"Headline: {article.get('title')}\n"
        f"Date: {article.get('date')}\n"
        f"Source channel: {article.get('source')}\n"
        f"Coverage tone (GDELT scale, negative = negative): {article.get('tone')}"
    )
    try:
        raw = await asyncio.wait_for(
            extract(SYSTEM, user, SCHEMA), timeout=_LLM_TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[extractor] llm call failed: {type(exc).__name__}: {exc}")
        raw = None

    if not isinstance(raw, dict):
        fallback["fallback_reason"] = "LLM unavailable or returned no parseable JSON"
        return fallback
    return _coerce(raw, article, fallback)


async def extract_events(articles: list[dict[str, Any]],
                         use_llm: bool = False,
                         max_llm: int = 8) -> list[dict[str, Any]]:
    """Extract a batch.

    Default is keyword-only and therefore deterministic and fast, which is what
    the Corridor Risk Index and the backtest need -- an index that changes
    because a language model felt different today is not an index. Set
    `use_llm=True` to enrich the most recent `max_llm` articles for drill-down.
    """
    if not articles:
        return []
    if not use_llm or not llm_available():
        return [keyword_extract(a) for a in articles]

    ordered = sorted(articles, key=lambda a: str(a.get("date") or ""), reverse=True)
    head, tail = ordered[:max_llm], ordered[max_llm:]
    enriched = await asyncio.gather(*(extract_event(a) for a in head),
                                    return_exceptions=True)
    out: list[dict[str, Any]] = []
    for article, res in zip(head, enriched):
        out.append(res if isinstance(res, dict) else keyword_extract(article))
    out.extend(keyword_extract(a) for a in tail)
    return out
