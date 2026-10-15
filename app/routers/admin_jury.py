"""
Admin Jury Management APIs.

Routes (all under /api/v1/admin, registered alongside existing admin router):
  POST /jury-profiles                          create jury profile (SUPER_ADMIN only)
  GET  /jury-profiles                          list all jury profiles
  GET  /jury-profiles/{jury_user_id}           get profile by user
  POST /ideas/{idea_id}/assign-jury            assign 1–3 jury members
  GET  /ideas/{idea_id}/jury-assignments       list assignments for idea
  GET  /jury-assignments                       list all assignments (scoped)
  GET  /ideas/{idea_id}/evaluation-summary     jury review summary

Role access:
  create profile    → SUPER_ADMIN only
  all other reads   → SUPER_ADMIN / TEAM_ADMIN_GLOBAL / TEAM_ADMIN_LOCAL
  assign jury       → SUPER_ADMIN / TEAM_ADMIN_GLOBAL / TEAM_ADMIN_LOCAL (scoped)
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
import logging

from app.database import get_db
from app.models.idea import Idea, IdeaStatus, IdeaVisibilityScope
from app.models.jury import JuryProfile, JuryAssignment, ReviewStatus
from app.models.evaluation import Evaluation
from app.models.user import User, UserRole, ProgramTrack
from app.schemas.jury import (
    JuryProfileCreate, JuryProfileOut, JuryProfileUpdate,
    AssignJuryRequest, JuryAssignmentOut, JuryAssignmentStatusUpdate,
)
from app.schemas.evaluation import EvaluationSummary, ReviewSummaryItem
from app.schemas.pagination import PaginatedResponse
from app.services.audit_log_service import record_audit_log
from app.services.idea_notification_service import (
    notify_jury_assignment,
    notify_jury_assignment_status,
)
from app.utils.dependencies import require_admin, require_admin_read
from app.utils.pagination import paginate_query

router = APIRouter(prefix="/admin", tags=["admin-jury"])
logger = logging.getLogger(__name__)

MAX_JURY_PER_IDEA = 3
_INACTIVE = (ReviewStatus.CANCELLED, ReviewStatus.REASSIGNED)
LOCAL_TRACKS = (ProgramTrack.LOCAL_REGIONAL, ProgramTrack.K12)


def _assert_jury_user_in_scope(user: User, current_user: User) -> None:
    if user.role != UserRole.JURY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User {user.id} does not have JURY role. Current role: {user.role.value}",
        )
    if current_user.role == UserRole.SUPER_ADMIN:
        return
    if (
        current_user.role == UserRole.TEAM_ADMIN_GLOBAL
        and user.program_track == ProgramTrack.NATIONAL_INTERNATIONAL
    ):
        return
    if current_user.role == UserRole.TEAM_ADMIN_LOCAL and user.program_track in LOCAL_TRACKS:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Jury user is outside your scope.",
    )


def _filter_jury_profiles_by_scope(query, current_user: User):
    query = query.join(User, JuryProfile.user_id == User.id).filter(User.role == UserRole.JURY)
    if current_user.role in (UserRole.SUPER_ADMIN, UserRole.VIEW_ADMIN_BOTH):
        return query
    if current_user.role in (UserRole.TEAM_ADMIN_GLOBAL, UserRole.VIEW_ADMIN_GLOBAL):
        return query.filter(User.program_track == ProgramTrack.NATIONAL_INTERNATIONAL)
    if current_user.role in (UserRole.TEAM_ADMIN_LOCAL, UserRole.VIEW_ADMIN_LOCAL):
        return query.filter(User.program_track.in_(LOCAL_TRACKS))
    return query.filter(False)


def _get_jury_profile_in_scope(jury_user_id: int, current_user: User, db: Session) -> JuryProfile:
    profile = _filter_jury_profiles_by_scope(
        db.query(JuryProfile).filter(JuryProfile.user_id == jury_user_id),
        current_user,
    ).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Jury profile not found for user {jury_user_id}",
        )
    return profile


def _profile_to_out(profile: JuryProfile) -> JuryProfileOut:
    user = profile.user
    return JuryProfileOut(
        id=profile.id,
        user_id=profile.user_id,
        full_name=user.full_name if user else None,
        email=user.email if user else None,
        phone=user.phone if user else None,
        program_track=(
            user.program_track.value
            if user and user.program_track is not None
            else None
        ),
        is_active=user.is_active if user else None,
        expertise_field=profile.expertise_field,
        sub_field=profile.sub_field,
        qualification=profile.qualification,
        organization=profile.organization,
        experience_years=profile.experience_years,
        max_review_capacity=profile.max_review_capacity,
        is_available=profile.is_available,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


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


def _get_idea_in_scope(idea_id: int, current_user: User, db: Session) -> Idea:
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    scoped = _filter_ideas_by_scope(db.query(Idea).filter(Idea.id == idea_id), current_user).first()
    if not scoped:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return idea


def _get_assignment_in_scope(assignment_id: int, current_user: User, db: Session) -> JuryAssignment:
    assignment = db.query(JuryAssignment).filter(JuryAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jury assignment not found")
    _get_idea_in_scope(assignment.idea_id, current_user, db)
    return assignment


def _apply_jury_profile_filters(
    query,
    search: str | None = None,
    program_track: str | None = None,
    is_available: bool | None = None,
    is_active: bool | None = None,
    expertise: str | None = None,
):
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(
            User.full_name.ilike(term),
            User.email.ilike(term),
            User.phone.ilike(term),
            JuryProfile.expertise_field.ilike(term),
            JuryProfile.organization.ilike(term),
            JuryProfile.qualification.ilike(term),
        ))
    if program_track:
        try:
            query = query.filter(User.program_track == ProgramTrack(program_track))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid program_track '{program_track}'. Valid: {[item.value for item in ProgramTrack]}",
            )
    if is_available is not None:
        query = query.filter(JuryProfile.is_available == is_available)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if expertise:
        query = query.filter(JuryProfile.expertise_field.ilike(f"%{expertise.strip()}%"))
    return query


def _scoped_assignment_query(db: Session, current_user: User):
    query = db.query(JuryAssignment).join(Idea, JuryAssignment.idea_id == Idea.id)
    return _filter_ideas_by_scope(query, current_user)


def _apply_assignment_filters(
    query,
    idea_id: int | None = None,
    application_id: str | None = None,
    jury_user_id: int | None = None,
    status_filter: str | None = None,
    program_track: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    if idea_id is not None:
        query = query.filter(JuryAssignment.idea_id == idea_id)
    if application_id:
        query = query.filter(Idea.application_id == application_id)
    if jury_user_id is not None:
        query = query.filter(JuryAssignment.jury_user_id == jury_user_id)
    if status_filter:
        try:
            query = query.filter(JuryAssignment.review_status == ReviewStatus(status_filter))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{status_filter}'. Valid: {[s.value for s in ReviewStatus]}",
            )
    if program_track:
        try:
            query = query.filter(Idea.program_track == ProgramTrack(program_track))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid program_track '{program_track}'. Valid: {[item.value for item in ProgramTrack]}",
            )
    if date_from:
        query = query.filter(JuryAssignment.assigned_at >= date_from)
    if date_to:
        query = query.filter(JuryAssignment.assigned_at <= date_to)
    return query


# ---------------------------------------------------------------------------
# Jury Profiles
# ---------------------------------------------------------------------------

@router.post(
    "/jury-profiles",
    response_model=JuryProfileOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create jury profile for a JURY-role user (SUPER_ADMIN only)",
)
def create_jury_profile(
    payload: JuryProfileCreate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {payload.user_id} not found")
    _assert_jury_user_in_scope(user, current_user)
    existing = db.query(JuryProfile).filter(JuryProfile.user_id == payload.user_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Jury profile already exists for user {payload.user_id}",
        )

    profile = JuryProfile(
        user_id=payload.user_id,
        expertise_field=payload.expertise_field,
        sub_field=payload.sub_field,
        qualification=payload.qualification,
        organization=payload.organization,
        experience_years=payload.experience_years,
        max_review_capacity=payload.max_review_capacity,
        is_available=payload.is_available,
    )
    db.add(profile)
    db.flush()
    record_audit_log(
        db,
        actor=current_user,
        action="jury_profile_created",
        entity_type="jury_profile",
        entity_id=profile.id,
        entity_display_id=str(profile.user_id),
        new_values=payload.model_dump(),
        request=request,
    )
    db.commit()
    db.refresh(profile)
    return _profile_to_out(profile)


@router.get(
    "/jury-profiles",
    response_model=List[JuryProfileOut],
    summary="List all jury profiles",
)
def list_jury_profiles(
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    profiles = (
        _filter_jury_profiles_by_scope(db.query(JuryProfile), current_user)
        .order_by(JuryProfile.created_at.desc())
        .all()
    )
    return [_profile_to_out(profile) for profile in profiles]


@router.get(
    "/jury-profiles/page",
    response_model=PaginatedResponse,
    summary="Paginated jury profiles",
)
def list_jury_profiles_page(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    program_track: Optional[str] = None,
    is_available: Optional[bool] = None,
    is_active: Optional[bool] = None,
    expertise: Optional[str] = None,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = _filter_jury_profiles_by_scope(db.query(JuryProfile), current_user)
    query = _apply_jury_profile_filters(
        query,
        search=search,
        program_track=program_track,
        is_available=is_available,
        is_active=is_active,
        expertise=expertise,
    )
    return paginate_query(
        query.order_by(JuryProfile.created_at.desc()),
        limit,
        offset,
        transform=_profile_to_out,
    )


@router.get(
    "/jury-profiles/{jury_user_id}",
    response_model=JuryProfileOut,
    summary="Get jury profile for a specific user",
)
def get_jury_profile(
    jury_user_id: int,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    return _profile_to_out(_get_jury_profile_in_scope(jury_user_id, current_user, db))


@router.patch(
    "/jury-profiles/{jury_user_id}",
    response_model=JuryProfileOut,
    summary="Update scoped jury profile for a specific user",
)
def update_jury_profile(
    jury_user_id: int,
    payload: JuryProfileUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    profile = _get_jury_profile_in_scope(jury_user_id, current_user, db)
    old_values = {
        "expertise_field": profile.expertise_field,
        "sub_field": profile.sub_field,
        "qualification": profile.qualification,
        "organization": profile.organization,
        "experience_years": profile.experience_years,
        "max_review_capacity": profile.max_review_capacity,
        "is_available": profile.is_available,
    }
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)
    record_audit_log(
        db,
        actor=current_user,
        action="jury_profile_updated",
        entity_type="jury_profile",
        entity_id=profile.id,
        entity_display_id=str(profile.user_id),
        old_values=old_values,
        new_values=update_data,
        request=request,
    )
    db.commit()
    db.refresh(profile)
    return _profile_to_out(profile)


@router.delete(
    "/jury-profiles/{jury_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a jury profile (admin only)",
)
def delete_jury_profile(
    jury_user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    profile = _get_jury_profile_in_scope(jury_user_id, current_user, db)
    old_values = {
        "user_id": profile.user_id,
        "expertise_field": profile.expertise_field,
        "sub_field": profile.sub_field,
        "qualification": profile.qualification,
        "organization": profile.organization,
        "experience_years": profile.experience_years,
        "max_review_capacity": profile.max_review_capacity,
        "is_available": profile.is_available,
    }
    db.delete(profile)
    record_audit_log(
        db,
        actor=current_user,
        action="jury_profile_deleted",
        entity_type="jury_profile",
        entity_id=profile.id,
        entity_display_id=str(profile.user_id),
        old_values=old_values,
        new_values=None,
        request=request,
    )
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Jury Assignments
# ---------------------------------------------------------------------------

@router.post(
    "/ideas/{idea_id}/assign-jury",
    response_model=List[JuryAssignmentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Assign 1–3 jury members to an idea",
    description=(
        "Assign jury members to an idea. "
        "Total active assignments (existing + new) must not exceed 3. "
        "Duplicate active assignments for the same idea+jury are rejected. "
        "Assigned users must have JURY role."
    ),
)
def assign_jury(
    idea_id: int,
    payload: AssignJuryRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    idea = _get_idea_in_scope(idea_id, current_user, db)

    # Current active assignments count
    active_count = db.query(JuryAssignment).filter(
        JuryAssignment.idea_id == idea_id,
        JuryAssignment.review_status.notin_(_INACTIVE),
    ).count()

    if active_count + len(payload.jury_user_ids) > MAX_JURY_PER_IDEA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot assign {len(payload.jury_user_ids)} member(s). "
                f"Idea already has {active_count} active assignment(s). "
                f"Maximum allowed: {MAX_JURY_PER_IDEA}."
            ),
        )

    created = []
    for juid in payload.jury_user_ids:
        user = db.query(User).filter(User.id == juid).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {juid} not found")
        if user.role != UserRole.JURY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User {juid} does not have JURY role (current: {user.role.value})",
            )

        dup = db.query(JuryAssignment).filter(
            JuryAssignment.idea_id == idea_id,
            JuryAssignment.jury_user_id == juid,
            JuryAssignment.review_status.notin_(_INACTIVE),
        ).first()
        if dup:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User {juid} is already actively assigned to idea {idea_id}",
            )

        assignment = JuryAssignment(
            idea_id=idea_id,
            jury_user_id=juid,
            assigned_by_user_id=current_user.id,
            review_status=ReviewStatus.PENDING,
            due_date=payload.due_date,
        )
        db.add(assignment)
        created.append(assignment)

    # Advance idea status when jury is first assigned
    early = (
        IdeaStatus.SUBMITTED,
        IdeaStatus.UNDER_VERIFICATION,
        IdeaStatus.NEEDS_MORE_INFORMATION,
        IdeaStatus.PUBLIC_DOMAIN_CLEARED,
        IdeaStatus.FIELD_REVIEW_CLEARED,
    )
    if idea.current_status in early:
        idea.current_status = IdeaStatus.FIELD_JURY_REVIEW_PENDING

    db.flush()
    record_audit_log(
        db,
        actor=current_user,
        action="jury_assigned_to_idea",
        entity_type="jury_assignment",
        entity_id=idea.id,
        entity_display_id=idea.application_id,
        new_values={
            "idea_id": idea.id,
            "jury_user_ids": payload.jury_user_ids,
            "due_date": payload.due_date.isoformat() if payload.due_date else None,
            "assignment_ids": [assignment.id for assignment in created],
        },
        request=request,
    )
    db.commit()
    for a in created:
        db.refresh(a)
    for assignment in created:
        if assignment.jury_user:
            try:
                notify_jury_assignment(idea, assignment.jury_user)
            except Exception:
                logger.warning(
                    "Jury assignment notification failed: assignment_id=%s",
                    assignment.id,
                )
    return created


@router.patch(
    "/jury-assignments/{assignment_id}/status",
    response_model=JuryAssignmentOut,
    summary="Update jury assignment status",
)
def update_jury_assignment_status(
    assignment_id: int,
    payload: JuryAssignmentStatusUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    assignment = _get_assignment_in_scope(assignment_id, current_user, db)
    idea = db.query(Idea).filter(Idea.id == assignment.idea_id).first()
    try:
        new_status = ReviewStatus(payload.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{payload.status}'. Valid: {[s.value for s in ReviewStatus]}",
        )

    if assignment.review_status == ReviewStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completed assignments cannot be changed.",
        )
    if new_status == ReviewStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use jury review submission to complete an assignment.",
        )

    old_status = assignment.review_status.value if assignment.review_status else None
    assignment.review_status = new_status
    if new_status in _INACTIVE:
        assignment.completed_at = None

    record_audit_log(
        db,
        actor=current_user,
        action="jury_assignment_status_updated",
        entity_type="jury_assignment",
        entity_id=assignment.id,
        entity_display_id=idea.application_id if idea else str(assignment.idea_id),
        old_values={"review_status": old_status},
        new_values={
            "review_status": assignment.review_status.value,
            "note": payload.note,
            "jury_user_id": assignment.jury_user_id,
            "idea_id": assignment.idea_id,
        },
        request=request,
    )
    db.commit()
    db.refresh(assignment)
    if idea and assignment.jury_user and old_status != assignment.review_status.value:
        try:
            notify_jury_assignment_status(idea, assignment.jury_user, assignment.review_status.value)
        except Exception:
            logger.warning(
                "Jury assignment status notification failed: assignment_id=%s",
                assignment.id,
            )
    return assignment


@router.get(
    "/ideas/{idea_id}/jury-assignments",
    response_model=List[JuryAssignmentOut],
    summary="List all jury assignments for a specific idea",
)
def list_idea_jury_assignments(
    idea_id: int,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    _get_idea_in_scope(idea_id, current_user, db)
    return (
        db.query(JuryAssignment)
        .filter(JuryAssignment.idea_id == idea_id)
        .order_by(JuryAssignment.assigned_at.desc())
        .all()
    )


@router.get(
    "/jury-assignments",
    response_model=List[JuryAssignmentOut],
    summary="List all jury assignments (scoped to admin's visible ideas)",
)
def list_all_jury_assignments(
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    if current_user.role in (UserRole.SUPER_ADMIN, UserRole.VIEW_ADMIN_BOTH):
        return (
            db.query(JuryAssignment)
            .order_by(JuryAssignment.assigned_at.desc())
            .all()
        )
    visible_ids = [
        r.id for r in _filter_ideas_by_scope(db.query(Idea), current_user).all()
    ]
    return (
        db.query(JuryAssignment)
        .filter(JuryAssignment.idea_id.in_(visible_ids))
        .order_by(JuryAssignment.assigned_at.desc())
        .all()
    )


@router.get(
    "/jury-assignments/page",
    response_model=PaginatedResponse,
    summary="Paginated jury assignments",
)
def list_jury_assignments_page(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    idea_id: Optional[int] = None,
    application_id: Optional[str] = None,
    jury_user_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    program_track: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = _scoped_assignment_query(db, current_user)
    query = _apply_assignment_filters(
        query,
        idea_id=idea_id,
        application_id=application_id,
        jury_user_id=jury_user_id,
        status_filter=status_filter,
        program_track=program_track,
        date_from=date_from,
        date_to=date_to,
    )
    return paginate_query(
        query.order_by(JuryAssignment.assigned_at.desc()),
        limit,
        offset,
        transform=JuryAssignmentOut.model_validate,
    )


# ---------------------------------------------------------------------------
# Evaluation Summary
# ---------------------------------------------------------------------------

@router.get(
    "/ideas/{idea_id}/evaluation-summary",
    response_model=EvaluationSummary,
    tags=["evaluations"],
    summary="Jury evaluation summary for an idea (admin only)",
    description=(
        "Returns assigned jury count, completion status, average score, "
        "recommendation breakdown, and per-reviewer summaries."
    ),
)
def get_evaluation_summary(
    idea_id: int,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    _get_idea_in_scope(idea_id, current_user, db)

    assignments = (
        db.query(JuryAssignment)
        .filter(JuryAssignment.idea_id == idea_id)
        .all()
    )
    active = [a for a in assignments if a.review_status not in _INACTIVE]
    completed = [a for a in active if a.review_status == ReviewStatus.COMPLETED]
    pending = [a for a in active if a.review_status in (ReviewStatus.PENDING, ReviewStatus.IN_PROGRESS)]

    evaluations = db.query(Evaluation).filter(Evaluation.idea_id == idea_id).all()

    avg_score: Optional[float] = None
    if evaluations:
        avg_score = round(sum(e.total_score for e in evaluations) / len(evaluations), 2)

    rec_counts: dict = {}
    for ev in evaluations:
        key = ev.recommendation.value if hasattr(ev.recommendation, "value") else str(ev.recommendation)
        rec_counts[key] = rec_counts.get(key, 0) + 1

    eval_by_jury = {e.jury_user_id: e for e in evaluations}
    review_summaries = []
    for a in active:
        ev = eval_by_jury.get(a.jury_user_id)
        review_summaries.append(ReviewSummaryItem(
            jury_user_id=a.jury_user_id,
            review_status=a.review_status.value,
            total_score=ev.total_score if ev else None,
            recommendation=(
                ev.recommendation.value
                if ev and hasattr(ev.recommendation, "value")
                else (str(ev.recommendation) if ev else None)
            ),
            completed_at=a.completed_at,
        ))

    return EvaluationSummary(
        idea_id=idea_id,
        assigned_jury_count=len(active),
        completed_review_count=len(completed),
        pending_review_count=len(pending),
        average_score=avg_score,
        recommendations=rec_counts,
        reviews=review_summaries,
    )
