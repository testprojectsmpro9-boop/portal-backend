from __future__ import annotations

from typing import Optional


PROTOTYPE_STATUS_LABELS: dict[str, str] = {
    "IDEA_STAGE": "Idea stage only",
    "SKETCH_AVAILABLE": "Sketch / drawing available",
    "CONCEPT_NOTE": "Concept note available",
    "BASIC_PROTOTYPE": "Basic prototype available",
    "WORKING_PROTOTYPE": "Working prototype available",
    "PILOT_TESTED": "Pilot tested",
    "MARKET_READY": "Market ready",
}

_ALIASES: dict[str, str] = {
    "idea stage only": "IDEA_STAGE",
    "only an idea": "IDEA_STAGE",
    "only an idea / concept": "IDEA_STAGE",
    "idea_stage": "IDEA_STAGE",
    "idea stage": "IDEA_STAGE",
    "concept": "CONCEPT_NOTE",
    "concept note": "CONCEPT_NOTE",
    "concept note available": "CONCEPT_NOTE",
    "sketch available": "SKETCH_AVAILABLE",
    "sketch / drawing available": "SKETCH_AVAILABLE",
    "drawing or sketch available": "SKETCH_AVAILABLE",
    "basic prototype": "BASIC_PROTOTYPE",
    "basic prototype available": "BASIC_PROTOTYPE",
    "basic prototype or model available": "BASIC_PROTOTYPE",
    "working prototype": "WORKING_PROTOTYPE",
    "working prototype available": "WORKING_PROTOTYPE",
    "working model ready for demonstration": "WORKING_PROTOTYPE",
    "pilot tested": "PILOT_TESTED",
    "product tested with real users": "PILOT_TESTED",
    "market ready": "MARKET_READY",
    "patent applied": "MARKET_READY",
}


def normalize_prototype_status(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    canonical = raw.upper().replace("-", "_").replace(" ", "_")
    if canonical in PROTOTYPE_STATUS_LABELS:
        return canonical

    return _ALIASES.get(raw.lower(), raw)


def prototype_status_label(value: Optional[str]) -> str:
    normalized = normalize_prototype_status(value)
    if not normalized:
        return ""
    return PROTOTYPE_STATUS_LABELS.get(normalized, str(value).strip())
