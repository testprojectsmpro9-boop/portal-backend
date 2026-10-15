"""
Jury Dashboard APIs.

Routes (all under /api/v1/jury):
  GET  /assigned-ideas             list ideas assigned to current jury
  GET  /ideas/{idea_id}            get details of an assigned idea
  GET  /ideas/{idea_id}/files      list files for an assigned idea
  POST /ideas/{idea_id}/review     submit evaluation (one per idea per jury)
  GET  /my-reviews                 list own submitted evaluations

Role: JURY only.
Access gated by active JuryAssignment (non-CANCELLED, non-REASSIGNED).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import logging

from app.database import get_db
from app.models.idea import Idea, IdeaStatus
from app.models.idea_file import IdeaFile
from app.models.jury import JuryAssignment, ReviewStatus
from app.models.evaluation import Evaluation, Recommendation
from app.models.user import User
from app.schemas.idea import IdeaOut
from app.schemas.file import IdeaFileOut
from app.schemas.evaluation import EvaluationCreate, EvaluationOut
from app.schemas.jury import JuryAssignmentOut
from app.schemas.pagination import PaginatedResponse
from app.services.audit_log_service import record_audit_log
from app.services.idea_notification_service import notify_jury_review_completed
from app.utils.dependencies import require_jury
from app.utils.pagination import paginate_query

router = APIRouter(prefix="/jury", tags=["jury"])
logger = logging.getLogger(__name__)

_INACTIVE = (ReviewStatus.CANCELLED, ReviewStatus.REASSIGNED)


def _get_active_assignment(idea_id: int, jury_user_id: int, db: Session) -> JuryAssignment:
    """Return active assignment or raise 403."""
    assignment = db.query(JuryAssignment).filter(
        JuryAssignment.idea_id == idea_id,
        JuryAssignment.jury_user_id == jury_user_id,
        JuryAssignment.review_status.notin_(_INACTIVE),
    ).first()
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to review this idea.",
        )
    return assignment


def _file_to_out(f: IdeaFile) -> IdeaFileOut:
    return IdeaFileOut(
        id=f.id,
        idea_id=f.idea_id,
        uploaded_by_user_id=f.uploaded_by_user_id,
        file_type=f.file_type.value if f.file_type else "",
        file_name=f.file_name,
        mime_type=f.mime_type,
        file_size=f.file_size,
        description=f.description,
        download_url=f"/api/v1/files/{f.id}",
        created_at=f.created_at,
    )


# ---------------------------------------------------------------------------
# GET /jury/assigned-ideas
# ---------------------------------------------------------------------------

@router.get(
    "/assigned-ideas",
    response_model=List[IdeaOut],
    summary="List all ideas assigned to the current jury member",
)
def list_assigned_ideas(
    current_user: User = Depends(require_jury),
    db: Session = Depends(get_db),
):
    assigned_ids = [
        row[0]
        for row in db.query(JuryAssignment.idea_id).filter(
            JuryAssignment.jury_user_id == current_user.id,
            JuryAssignment.review_status.notin_(_INACTIVE),
        ).all()
    ]
    if not assigned_ids:
        return []
    return db.query(Idea).filter(Idea.id.in_(assigned_ids)).all()


# ---------------------------------------------------------------------------
# GET /jury/ideas/{idea_id}
# ---------------------------------------------------------------------------

@router.get(
    "/ideas/{idea_id}",
    response_model=IdeaOut,
    summary="Get details of an assigned idea",
)
def get_assigned_idea(
    idea_id: int,
    current_user: User = Depends(require_jury),
    db: Session = Depends(get_db),
):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    _get_active_assignment(idea_id, current_user.id, db)
    return idea


# ---------------------------------------------------------------------------
# GET /jury/ideas/{idea_id}/files
# ---------------------------------------------------------------------------

@router.get(
    "/ideas/{idea_id}/files",
    response_model=List[IdeaFileOut],
    summary="List files for an assigned idea",
)
def list_idea_files(
    idea_id: int,
    current_user: User = Depends(require_jury),
    db: Session = Depends(get_db),
):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    _get_active_assignment(idea_id, current_user.id, db)
    files = (
        db.query(IdeaFile)
        .filter(IdeaFile.idea_id == idea_id)
        .order_by(IdeaFile.created_at.desc())
        .all()
    )
    return [_file_to_out(f) for f in files]


# ---------------------------------------------------------------------------
# POST /jury/ideas/{idea_id}/review
# ---------------------------------------------------------------------------

@router.post(
    "/ideas/{idea_id}/review",
    response_model=EvaluationOut,
    status_code=status.HTTP_201_CREATED,
    tags=["evaluations"],
    summary="Submit evaluation for an assigned idea",
    description=(
        "Submit scores and recommendation. total_score is auto-calculated server-side. "
        "Max possible score: 100. One review per jury per idea."
    ),
)
def submit_review(
    idea_id: int,
    payload: EvaluationCreate,
    request: Request,
    current_user: User = Depends(require_jury),
    db: Session = Depends(get_db),
):
    assignment = _get_active_assignment(idea_id, current_user.id, db)

    # Guard: already reviewed
    if db.query(Evaluation).filter(
        Evaluation.idea_id == idea_id,
        Evaluation.jury_user_id == current_user.id,
    ).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already submitted a review for this idea.",
        )

    try:
        rec = Recommendation(payload.recommendation)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid recommendation '{payload.recommendation}'. Valid: {[r.value for r in Recommendation]}",
        )

    # Auto-calculate total — never trust client value
    total = round(
        payload.problem_clarity_score
        + payload.novelty_score
        + payload.feasibility_score
        + payload.impact_score
        + payload.scalability_score
        + payload.prototype_readiness_score
        + payload.practical_usefulness_score,
        2,
    )

    evaluation = Evaluation(
        idea_id=idea_id,
        jury_user_id=current_user.id,
        problem_clarity_score=payload.problem_clarity_score,
        novelty_score=payload.novelty_score,
        feasibility_score=payload.feasibility_score,
        impact_score=payload.impact_score,
        scalability_score=payload.scalability_score,
        prototype_readiness_score=payload.prototype_readiness_score,
        practical_usefulness_score=payload.practical_usefulness_score,
        total_score=total,
        remarks=payload.remarks,
        recommendation=rec,
        reason=payload.reason,
    )
    db.add(evaluation)

    # Mark assignment COMPLETED
    assignment.review_status = ReviewStatus.COMPLETED
    assignment.completed_at = datetime.utcnow()

    # Advance idea status from PENDING → IN_PROGRESS on first review
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if idea and idea.current_status == IdeaStatus.FIELD_JURY_REVIEW_PENDING:
        idea.current_status = IdeaStatus.FIELD_JURY_REVIEW_IN_PROGRESS

    db.flush()
    record_audit_log(
        db,
        actor=current_user,
        action="jury_review_submitted",
        entity_type="evaluation",
        entity_id=evaluation.id,
        entity_display_id=idea.application_id if idea else str(idea_id),
        new_values={
            "idea_id": idea_id,
            "total_score": evaluation.total_score,
            "recommendation": evaluation.recommendation.value if evaluation.recommendation else None,
        },
        request=request,
    )
    db.commit()
    db.refresh(evaluation)
    if idea:
        try:
            notify_jury_review_completed(idea, current_user)
        except Exception:
            logger.warning("Jury review completion notification failed: evaluation_id=%s", evaluation.id)
    return evaluation


@router.get(
    "/assignments/page",
    response_model=PaginatedResponse,
    summary="Paginated assignments for the current jury member",
)
def list_my_assignments_page(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user: User = Depends(require_jury),
    db: Session = Depends(get_db),
):
    query = db.query(JuryAssignment).filter(JuryAssignment.jury_user_id == current_user.id)
    if status_filter:
        try:
            query = query.filter(JuryAssignment.review_status == ReviewStatus(status_filter))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{status_filter}'. Valid: {[s.value for s in ReviewStatus]}",
            )
    if date_from:
        query = query.filter(JuryAssignment.assigned_at >= date_from)
    if date_to:
        query = query.filter(JuryAssignment.assigned_at <= date_to)
    return paginate_query(
        query.order_by(JuryAssignment.assigned_at.desc()),
        limit,
        offset,
        transform=JuryAssignmentOut.model_validate,
    )


# ---------------------------------------------------------------------------
# GET /jury/my-reviews
# ---------------------------------------------------------------------------

@router.get(
    "/my-reviews",
    response_model=List[EvaluationOut],
    tags=["evaluations"],
    summary="List all evaluations submitted by the current jury member",
)
def list_my_reviews(
    current_user: User = Depends(require_jury),
    db: Session = Depends(get_db),
):
    return (
        db.query(Evaluation)
        .filter(Evaluation.jury_user_id == current_user.id)
        .order_by(Evaluation.created_at.desc())
        .all()
    )
