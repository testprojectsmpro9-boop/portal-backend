"""
Admin Decision + Stage Movement APIs.

Routes (all under /api/v1/admin):
  POST /ideas/{idea_id}/decision    record a decision and advance idea
  GET  /ideas/{idea_id}/decisions   list decision history

Role access: SUPER_ADMIN / TEAM_ADMIN_GLOBAL / TEAM_ADMIN_LOCAL (scoped)

Decision recording:
  - Captures old status/pathway_stage before change
  - Applies new_status and new_pathway_stage (auto-derived from decision if not provided)
  - Creates a StatusHistory record
  - If public_message provided, creates a Message for the inventor
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List
import logging

from app.database import get_db
from app.models.idea import Idea, IdeaStatus, PathwayStage, IdeaVisibilityScope
from app.models.decision import AdminDecision, IdeaDecision
from app.models.status_history import StatusHistory
from app.models.message import Message, MessageType
from app.models.user import User, UserRole, ProgramTrack
from app.schemas.decision import DecisionCreate, DecisionOut
from app.services.audit_log_service import record_audit_log
from app.services.idea_notification_service import notify_idea_status_update
from app.utils.dependencies import require_admin, require_admin_read

router = APIRouter(prefix="/admin", tags=["admin-decisions"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision → status/pathway defaults
# ---------------------------------------------------------------------------

_DECISION_DEFAULTS: dict[AdminDecision, tuple[IdeaStatus, PathwayStage]] = {
    AdminDecision.SHORTLISTED:                         (IdeaStatus.FIELD_REVIEW_CLEARED,               PathwayStage.SCREENING),
    AdminDecision.REJECTED:                            (IdeaStatus.REJECTED_BY_JURY,                   PathwayStage.COMPLETED),
    AdminDecision.NEEDS_MORE_INFORMATION:              (IdeaStatus.NEEDS_MORE_INFORMATION,              PathwayStage.ADMIN_VERIFICATION),
    AdminDecision.PROTOTYPE_REQUIRED:                  (IdeaStatus.PROTOTYPE_REQUIRED,                  PathwayStage.SCREENING),
    AdminDecision.PROTOTYPE_APPROVED:                  (IdeaStatus.PROTOTYPE_SUBMITTED,                 PathwayStage.SCREENING),
    AdminDecision.MENTORSHIP_ASSIGNED:                 (IdeaStatus.MENTOR_ASSIGNED,                     PathwayStage.INCUBATION),
    AdminDecision.INCUBATION_RECOMMENDED:              (IdeaStatus.INCUBATION_RECOMMENDED,              PathwayStage.INCUBATION),
    AdminDecision.SELECTED_FOR_LOCAL_SHOWCASE:         (IdeaStatus.SELECTED_FOR_LOCAL_SHOWCASE,         PathwayStage.LOCAL_REVIEW),
    AdminDecision.SELECTED_FOR_STATE_LEVEL:            (IdeaStatus.SELECTED_FOR_STATE_LEVEL,            PathwayStage.STATE_REVIEW),
    AdminDecision.RECOMMENDED_FOR_NATIONAL_LEVEL:      (IdeaStatus.RECOMMENDED_FOR_NATIONAL_LEVEL,      PathwayStage.NATIONAL_REVIEW),
    AdminDecision.RECOMMENDED_FOR_INTERNATIONAL_LEVEL: (IdeaStatus.RECOMMENDED_FOR_INTERNATIONAL_LEVEL, PathwayStage.INTERNATIONAL_REVIEW),
    AdminDecision.RECOGNITION_FUNDING_PATENT_SUPPORT:  (IdeaStatus.RECOGNITION_FUNDING_PATENT_SUPPORT,  PathwayStage.COMPLETED),
    AdminDecision.CLOSED:                              (IdeaStatus.CLOSED,                              PathwayStage.COMPLETED),
}


def _filter_ideas_by_scope(query, current_user: User):
    if current_user.role in (UserRole.SUPER_ADMIN, UserRole.VIEW_ADMIN_BOTH):
        return query
    if current_user.role in (UserRole.TEAM_ADMIN_GLOBAL, UserRole.VIEW_ADMIN_GLOBAL):
        return query.filter(
            or_(
                Idea.program_track == ProgramTrack.NATIONAL_INTERNATIONAL,
                Idea.visibility_scope.in_([IdeaVisibilityScope.GLOBAL_TEAM, IdeaVisibilityScope.ALL_TEAMS]),
            )
        )
    if current_user.role in (UserRole.TEAM_ADMIN_LOCAL, UserRole.VIEW_ADMIN_LOCAL):
        return query.filter(
            or_(
                Idea.program_track.in_([ProgramTrack.LOCAL_REGIONAL, ProgramTrack.K12]),
                Idea.visibility_scope.in_([
                    IdeaVisibilityScope.LOCAL_TEAM,
                    IdeaVisibilityScope.K12_TEAM,
                    IdeaVisibilityScope.ALL_TEAMS,
                ]),
            )
        )
    return query.filter(False)


def _get_scoped_idea(idea_id: int, current_user: User, db: Session) -> Idea:
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    scoped = _filter_ideas_by_scope(
        db.query(Idea).filter(Idea.id == idea_id), current_user
    ).first()
    if not scoped:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Idea outside your program track scope.",
        )
    return idea


# ---------------------------------------------------------------------------
# POST /admin/ideas/{idea_id}/decision
# ---------------------------------------------------------------------------

@router.post(
    "/ideas/{idea_id}/decision",
    response_model=DecisionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record an admin decision and advance idea stage",
    description=(
        "Records a formal decision for an idea. "
        "Automatically derives new status and pathway stage from decision type unless overridden. "
        "If public_message is provided, a message is sent to the inventor. "
        "All decisions are logged to status_history."
    ),
)
def record_decision(
    idea_id: int,
    payload: DecisionCreate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    idea = _get_scoped_idea(idea_id, current_user, db)

    # Snapshot old values
    old_status = idea.current_status.value if idea.current_status else None
    old_pathway = idea.current_pathway_stage.value if idea.current_pathway_stage else None

    # Derive new values
    default_status, default_pathway = _DECISION_DEFAULTS[payload.decision]

    if payload.new_status is not None:
        try:
            new_status = IdeaStatus(payload.new_status)
        except ValueError:
            valid = [s.value for s in IdeaStatus]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid new_status '{payload.new_status}'. Valid: {valid}",
            )
    else:
        new_status = default_status

    if payload.new_pathway_stage is not None:
        try:
            new_pathway = PathwayStage(payload.new_pathway_stage)
        except ValueError:
            valid = [s.value for s in PathwayStage]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid new_pathway_stage '{payload.new_pathway_stage}'. Valid: {valid}",
            )
    else:
        new_pathway = default_pathway

    # Apply to idea
    idea.current_status = new_status
    idea.current_pathway_stage = new_pathway

    # Decision record
    decision_record = IdeaDecision(
        idea_id=idea.id,
        decided_by_user_id=current_user.id,
        decision=payload.decision,
        old_status=old_status,
        old_pathway_stage=old_pathway,
        new_status=new_status.value,
        new_pathway_stage=new_pathway.value,
        admin_note=payload.admin_note,
        public_message=payload.public_message,
    )
    db.add(decision_record)

    # Status history record
    history = StatusHistory(
        idea_id=idea.id,
        changed_by_user_id=current_user.id,
        old_status=old_status,
        new_status=new_status.value,
        old_stage=old_pathway,
        new_stage=new_pathway.value,
        reason=payload.decision.value,
        remarks=payload.admin_note,
    )
    db.add(history)

    # Inventor message (if public_message provided)
    if payload.public_message:
        msg = Message(
            idea_id=idea.id,
            sender_user_id=current_user.id,
            receiver_user_id=idea.inventor_id,
            message_type=MessageType.STATUS_UPDATE,
            message=payload.public_message,
            is_internal=False,
        )
        db.add(msg)

    db.flush()
    record_audit_log(
        db,
        actor=current_user,
        action="admin_decision_created",
        entity_type="idea_decision",
        entity_id=decision_record.id,
        entity_display_id=idea.application_id,
        old_values={
            "current_status": old_status,
            "current_pathway_stage": old_pathway,
        },
        new_values={
            "decision": payload.decision.value,
            "new_status": new_status.value,
            "new_pathway_stage": new_pathway.value,
            "has_public_message": bool(payload.public_message),
            "has_admin_note": bool(payload.admin_note),
        },
        request=request,
    )
    db.commit()
    db.refresh(decision_record)
    if payload.notify_applicant and payload.public_message:
        try:
            notify_idea_status_update(
                idea,
                new_status=new_status.value,
                public_message=payload.public_message,
            )
        except Exception:
            logger.warning("Idea status notification failed after decision: idea_id=%s", idea.id)
    return decision_record


# ---------------------------------------------------------------------------
# GET /admin/ideas/{idea_id}/decisions
# ---------------------------------------------------------------------------

@router.get(
    "/ideas/{idea_id}/decisions",
    response_model=List[DecisionOut],
    summary="List all decisions for an idea",
    description="Returns full decision history including admin_note (admin-only field).",
)
def list_decisions(
    idea_id: int,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    _get_scoped_idea(idea_id, current_user, db)

    decisions = (
        db.query(IdeaDecision)
        .filter(IdeaDecision.idea_id == idea_id)
        .order_by(IdeaDecision.created_at.desc())
        .all()
    )
    return decisions
