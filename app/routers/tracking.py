"""
Public Tracking API — no authentication required.

POST /api/v1/track
  Requires application_id + phone_or_email for identity verification.
  Returns limited public-safe tracking data only.
  Never exposes: jury names, jury scores, internal admin notes, raw file paths.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.idea import Idea
from app.schemas.tracking import PublicTrackRequest, PublicTrackResponse
from app.config import settings
from app.services.rate_limit import assert_rate_limit
from app.services.timeline_service import build_timeline

router = APIRouter(prefix="/track", tags=["public-tracking"])


def _verify_ownership(idea: Idea, phone_or_email: str) -> bool:
    """Return True if phone_or_email matches idea.email or idea.phone (case-insensitive email)."""
    val = phone_or_email.strip()
    if idea.email and idea.email.lower() == val.lower():
        return True
    if idea.phone and idea.phone.strip() == val:
        return True
    return False


def _build_response(idea: Idea) -> PublicTrackResponse:
    """Build public-safe tracking response — no jury/admin-internal data."""
    return PublicTrackResponse(
        application_id=idea.application_id,
        idea_title=idea.idea_title,
        current_status=idea.current_status.value if idea.current_status else "",
        current_stage=idea.current_stage,
        current_pathway_stage=(
            idea.current_pathway_stage.value if idea.current_pathway_stage else None
        ),
        next_action=idea.next_action,
        admin_message=idea.admin_message,
        created_at=idea.created_at,
        timeline=build_timeline(idea),
    )


@router.post(
    "",
    response_model=PublicTrackResponse,
    summary="Track idea status (public — no login required)",
    description=(
        "Verify your idea using Application ID + registered phone or email. "
        "Returns public-safe tracking data. Jury scores, internal notes, "
        "and file paths are never returned."
    ),
)
def track_idea(request: Request, payload: PublicTrackRequest, db: Session = Depends(get_db)):
    assert_rate_limit(
        request,
        "public-track",
        settings.RATE_LIMIT_TRACK_PER_HOUR,
        60 * 60,
        payload.application_id,
    )
    idea = db.query(Idea).filter(Idea.application_id == payload.application_id).first()

    # Return 404 for both not-found and ownership mismatch — prevents enumeration
    if not idea:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Idea not found or credentials do not match.",
        )

    if not _verify_ownership(idea, payload.phone_or_email):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Idea not found or credentials do not match.",
        )

    if not idea.is_public_tracking_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public tracking is not enabled for this idea.",
        )

    return _build_response(idea)
