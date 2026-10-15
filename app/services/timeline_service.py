"""
Timeline builder for public tracking and inventor dashboard.

Maps IdeaStatus + PathwayStage to a fixed 13-stage visual progression.

Rules (normal flow):
  - current_idx = max(status_idx, pathway_idx)
  - stages before current_idx  → "completed"
  - stage at current_idx       → "current"
  - stages after current_idx   → "upcoming"

Rules (terminal rejected / closed):
  - _FORCE_STATUS_ONLY statuses (REJECTED_BY_JURY, PUBLIC_DOMAIN_REJECTED):
    pathway_stage is ignored — rejection point is determined by status alone.
  - _TERMINAL_REJECTED statuses (above + CLOSED):
    a shorter timeline is returned: all stages up to the rejection point
    marked "completed", then a REJECTED_CLOSED terminal item as "current".
    Upcoming stages are hidden to avoid confusion.

IMPORTANT — PathwayStage.COMPLETED fix:
  COMPLETED is a terminal pathway marker, NOT a stage advancement.
  It must NOT map to RECOGNITION (index 11).
  RECOGNITION is only reached via IdeaStatus.RECOGNITION_FUNDING_PATENT_SUPPORT.
"""
from typing import List
from app.models.idea import IdeaStatus, PathwayStage
from app.schemas.tracking import TimelineItem

STAGE_ORDER: List[str] = [
    "SUBMITTED",
    "ADMIN_VERIFICATION",
    "PUBLIC_DOMAIN_REVIEW",
    "FIELD_JURY_REVIEW",
    "PROTOTYPE",
    "MENTORSHIP",
    "INCUBATION",
    "LOCAL_SHOWCASE",
    "STATE_LEVEL",
    "NATIONAL_LEVEL",
    "INTERNATIONAL_LEVEL",
    "RECOGNITION",
    "COMMERCIALIZATION",
]

STAGE_LABELS: dict = {
    "SUBMITTED":            "Submitted",
    "ADMIN_VERIFICATION":   "Under Verification",
    "PUBLIC_DOMAIN_REVIEW": "Public Domain Review",
    "FIELD_JURY_REVIEW":    "Jury Review",
    "PROTOTYPE":            "Prototype Stage",
    "MENTORSHIP":           "Mentorship",
    "INCUBATION":           "Incubation",
    "LOCAL_SHOWCASE":       "Local Showcase",
    "STATE_LEVEL":          "State Level",
    "NATIONAL_LEVEL":       "National Level",
    "INTERNATIONAL_LEVEL":  "International Level",
    "RECOGNITION":          "Recognition & Funding",
    "COMMERCIALIZATION":    "Commercialization",
}

# Maps IdeaStatus → index in STAGE_ORDER
# IdeaStatus.CLOSED is intentionally absent — see _TERMINAL_REJECTED handling.
_STATUS_INDEX: dict = {
    IdeaStatus.SUBMITTED:                          0,
    IdeaStatus.UNDER_VERIFICATION:                 1,
    IdeaStatus.NEEDS_MORE_INFORMATION:             1,
    IdeaStatus.PUBLIC_DOMAIN_REVIEW_PENDING:       2,
    IdeaStatus.PUBLIC_DOMAIN_CLEARED:              2,
    IdeaStatus.PUBLIC_DOMAIN_REJECTED:             2,
    IdeaStatus.FIELD_JURY_REVIEW_PENDING:          3,
    IdeaStatus.FIELD_JURY_REVIEW_IN_PROGRESS:      3,
    IdeaStatus.FIELD_REVIEW_CLEARED:               3,
    IdeaStatus.REJECTED_BY_JURY:                   3,
    IdeaStatus.PROTOTYPE_REQUIRED:                 4,
    IdeaStatus.PROTOTYPE_SUBMITTED:                4,
    IdeaStatus.MENTOR_ASSIGNED:                    5,
    IdeaStatus.INCUBATION_RECOMMENDED:             6,
    IdeaStatus.SELECTED_FOR_LOCAL_SHOWCASE:        7,
    IdeaStatus.SELECTED_FOR_STATE_LEVEL:           8,
    IdeaStatus.RECOMMENDED_FOR_NATIONAL_LEVEL:     9,
    IdeaStatus.RECOMMENDED_FOR_INTERNATIONAL_LEVEL: 10,
    IdeaStatus.RECOGNITION_FUNDING_PATENT_SUPPORT: 11,
    # CLOSED: not mapped here — handled via _TERMINAL_REJECTED path
}

# Maps PathwayStage → index in STAGE_ORDER
# PathwayStage.COMPLETED intentionally maps to -1 (no-op).
# It is a terminal lifecycle marker, not a stage position.
# Only IdeaStatus.RECOGNITION_FUNDING_PATENT_SUPPORT drives index 11 (RECOGNITION).
_PATHWAY_INDEX: dict = {
    PathwayStage.INTAKE:               0,
    PathwayStage.ADMIN_VERIFICATION:   1,
    PathwayStage.SCREENING:            1,
    PathwayStage.LOCAL_REVIEW:         3,
    PathwayStage.STATE_REVIEW:         8,
    PathwayStage.NATIONAL_REVIEW:      9,
    PathwayStage.INTERNATIONAL_REVIEW: 10,
    PathwayStage.INCUBATION:           6,
    PathwayStage.COMPLETED:            -1,  # FIX: was 11 — caused RECOGNITION false-current bug
}

# For these statuses, pathway_stage must NOT advance the stage index.
# The rejection point is determined by status alone.
_FORCE_STATUS_ONLY = frozenset({
    IdeaStatus.REJECTED_BY_JURY,
    IdeaStatus.PUBLIC_DOMAIN_REJECTED,
})

# All statuses that produce a terminal REJECTED_CLOSED item in the timeline.
# The timeline is shortened: stages up to rejection point are shown, rest hidden.
_TERMINAL_REJECTED = frozenset({
    IdeaStatus.REJECTED_BY_JURY,
    IdeaStatus.PUBLIC_DOMAIN_REJECTED,
    IdeaStatus.CLOSED,
})


def _current_stage_index(idea) -> int:
    """Return STAGE_ORDER index for the idea's furthest-reached stage.

    For _FORCE_STATUS_ONLY statuses, pathway_stage is ignored so it cannot
    advance the index past the rejection point (e.g. pathway=COMPLETED
    must not pull REJECTED_BY_JURY to RECOGNITION).
    """
    status_idx = _STATUS_INDEX.get(idea.current_status, 0)

    if idea.current_status in _FORCE_STATUS_ONLY:
        return status_idx

    pathway_idx = (
        _PATHWAY_INDEX.get(idea.current_pathway_stage, -1)
        if idea.current_pathway_stage
        else -1
    )
    return max(status_idx, pathway_idx, 0)


def build_timeline(idea) -> List[TimelineItem]:
    """Build the visual pipeline timeline for an idea.

    Normal flow: returns all 13 stages with completed/current/upcoming markers.

    Terminal rejected/closed flow: returns a shortened timeline —
    stages up to the rejection point marked "completed", then a
    REJECTED_CLOSED terminal item marked "current". Upcoming stages
    are omitted to avoid misleading the inventor.
    """
    current_idx = _current_stage_index(idea)

    if idea.current_status in _TERMINAL_REJECTED:
        items: List[TimelineItem] = [
            TimelineItem(
                stage=STAGE_ORDER[i],
                label=STAGE_LABELS[STAGE_ORDER[i]],
                status="completed",
            )
            for i in range(current_idx + 1)
        ]
        items.append(TimelineItem(
            stage="REJECTED_CLOSED",
            label="Rejected / Closed",
            status="current",
        ))
        return items

    # Normal progression: all 13 stages
    return [
        TimelineItem(
            stage=stage,
            label=STAGE_LABELS[stage],
            status=(
                "completed" if i < current_idx else
                "current"   if i == current_idx else
                "upcoming"
            ),
        )
        for i, stage in enumerate(STAGE_ORDER)
    ]