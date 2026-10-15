import logging

from datetime import datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.services.user_notification_service import notify_user_created

logger = logging.getLogger(__name__)
from app.schemas.user import (
    AdminUserCreate,
    AdminUserRead,
    AdminUserStatusUpdate,
    AdminUserUpdate,
    AdminUserSummaryResponse,
)
from app.schemas.audit_log import AuditLogRead
from app.schemas.idea import AdminIdeaDetailOut, IdeaOut, IdeaStatusUpdate
from app.schemas.pagination import PaginatedResponse
from app.schemas.file import FileAccessLogRead, IdeaFileOut
from app.schemas.message import MessageCreate, MessageOut, MessageAccessUpdate, MessageAccessOut
from app.models.idea import IdeaStatus, PathwayStage, IdeaVisibilityScope, Idea
from app.models.idea_file import FileType, IdeaFile
from app.models.file_access_log import FileAccessLog
from app.services.file_service import save_file, validate_file
from app.models.message import Message, MessageType
from app.models.audit_log import AuditLog
from app.services.audit_log_service import record_audit_log
from app.services.email_service import get_admin_notification_recipient, send_applicant_email
from app.services.idea_notification_service import notify_idea_status_update
from app.services.status_history_service import record_status_history
from app.utils.dependencies import get_current_user, require_admin, require_admin_read
from app.utils.pagination import paginate_query
from app.utils.category import coerce_idea_category
from app.utils.security import PASSWORD_POLICY_MESSAGE, hash_password, validate_password_strength
from app.models.user import User, UserRole, ProgramTrack

router = APIRouter(prefix="/admin", tags=["admin"])

SCOPED_USER_ROLES = (UserRole.JURY, UserRole.INVENTOR)
LOCAL_TRACKS = (ProgramTrack.LOCAL_REGIONAL, ProgramTrack.K12)


def _parse_user_role(value: str) -> UserRole:
    try:
        return UserRole(value)
    except ValueError:
        valid = [role.value for role in UserRole]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{value}'. Valid: {valid}",
        )


def _parse_program_track(value: str | None) -> ProgramTrack | None:
    if not value:
        return None
    try:
        return ProgramTrack(value)
    except ValueError:
        valid = [track.value for track in ProgramTrack]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid program_track '{value}'. Valid: {valid}",
        )


def _default_program_track_for(role: UserRole) -> ProgramTrack | None:
    if role == UserRole.TEAM_ADMIN_GLOBAL:
        return ProgramTrack.NATIONAL_INTERNATIONAL
    if role == UserRole.TEAM_ADMIN_LOCAL:
        return ProgramTrack.LOCAL_REGIONAL
    return None


def _assert_can_create_user(
    current_user: User,
    target_role: UserRole,
    target_track: ProgramTrack | None,
) -> ProgramTrack | None:
    if target_role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creating SUPER_ADMIN users is not allowed through this endpoint.",
        )

    if current_user.role == UserRole.SUPER_ADMIN:
        if target_role not in (
            UserRole.TEAM_ADMIN_GLOBAL,
            UserRole.TEAM_ADMIN_LOCAL,
            UserRole.VIEW_ADMIN_LOCAL,
            UserRole.VIEW_ADMIN_GLOBAL,
            UserRole.VIEW_ADMIN_BOTH,
            UserRole.JURY,
            UserRole.INVENTOR,
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role cannot be created.")

        if target_role in (UserRole.TEAM_ADMIN_GLOBAL, UserRole.VIEW_ADMIN_GLOBAL):
            if target_track and target_track != ProgramTrack.NATIONAL_INTERNATIONAL:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Global admins must use NATIONAL_INTERNATIONAL scope.",
                )
            return ProgramTrack.NATIONAL_INTERNATIONAL

        if target_role in (UserRole.TEAM_ADMIN_LOCAL, UserRole.VIEW_ADMIN_LOCAL):
            if target_track and target_track not in LOCAL_TRACKS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Local admins must use LOCAL_REGIONAL or K12 scope.",
                )
            return target_track or ProgramTrack.LOCAL_REGIONAL

        # VIEW_ADMIN_BOTH sees both scopes — no single program_track applies.
        if target_role == UserRole.VIEW_ADMIN_BOTH:
            return None

        return target_track

    if current_user.role == UserRole.TEAM_ADMIN_GLOBAL:
        if target_role not in SCOPED_USER_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Global admins can create only JURY or INVENTOR users.",
            )
        if target_track and target_track != ProgramTrack.NATIONAL_INTERNATIONAL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Global admins can create users only in NATIONAL_INTERNATIONAL scope.",
            )
        return ProgramTrack.NATIONAL_INTERNATIONAL

    if current_user.role == UserRole.TEAM_ADMIN_LOCAL:
        if target_role not in SCOPED_USER_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Local admins can create only JURY or INVENTOR users.",
            )
        if target_track and target_track not in LOCAL_TRACKS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Local admins can create users only in LOCAL_REGIONAL or K12 scope.",
            )
        return target_track or ProgramTrack.LOCAL_REGIONAL

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to create users.",
    )


def _filter_users_by_scope(query, current_user: User):
    if current_user.role == UserRole.SUPER_ADMIN:
        return query
    if current_user.role == UserRole.TEAM_ADMIN_GLOBAL:
        return query.filter(
            User.role.in_(SCOPED_USER_ROLES),
            User.program_track == ProgramTrack.NATIONAL_INTERNATIONAL,
        )
    if current_user.role == UserRole.TEAM_ADMIN_LOCAL:
        return query.filter(
            User.role.in_(SCOPED_USER_ROLES),
            User.program_track.in_(LOCAL_TRACKS),
        )
    return query.filter(False)


def _assert_idea_scope(idea: Idea, current_user: User, db: Session) -> None:
    scoped = _filter_ideas_by_scope(db.query(Idea).filter(Idea.id == idea.id), current_user).first()
    if not scoped:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Idea outside your program track scope.",
        )


def _assert_file_activity_access(idea: Idea, current_user: User, db: Session) -> None:
    if current_user.role in (UserRole.SUPER_ADMIN, UserRole.TEAM_ADMIN_GLOBAL, UserRole.TEAM_ADMIN_LOCAL):
        _assert_idea_scope(idea, current_user, db)
        return

    if current_user.role == UserRole.JURY:
        from app.models.jury import JuryAssignment, ReviewStatus

        inactive = (ReviewStatus.CANCELLED, ReviewStatus.REASSIGNED)
        assignment = db.query(JuryAssignment).filter(
            JuryAssignment.idea_id == idea.id,
            JuryAssignment.jury_user_id == current_user.id,
            JuryAssignment.review_status.notin_(inactive),
        ).first()
        if assignment:
            return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


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


def _idea_detail_out(idea: Idea, db: Session) -> AdminIdeaDetailOut:
    files = (
        db.query(IdeaFile)
        .filter(IdeaFile.idea_id == idea.id)
        .order_by(IdeaFile.created_at.desc())
        .all()
    )
    data = AdminIdeaDetailOut.model_validate(idea)
    data.files = [_file_to_out(f) for f in files]
    return data


def _visible_summary_roles(current_user: User) -> tuple[UserRole, ...]:
    if current_user.role == UserRole.SUPER_ADMIN:
        return tuple(UserRole)
    return SCOPED_USER_ROLES


def _visible_summary_tracks(current_user: User) -> tuple[ProgramTrack, ...]:
    if current_user.role == UserRole.TEAM_ADMIN_GLOBAL:
        return (ProgramTrack.NATIONAL_INTERNATIONAL,)
    if current_user.role == UserRole.TEAM_ADMIN_LOCAL:
        return LOCAL_TRACKS
    return tuple(ProgramTrack)


def _track_key(track: ProgramTrack | None) -> str:
    return track.value if track else "UNASSIGNED"


def _build_user_summary(users: list[User], current_user: User) -> AdminUserSummaryResponse:
    roles = _visible_summary_roles(current_user)
    tracks = _visible_summary_tracks(current_user)

    by_role = {role.value: 0 for role in roles}
    by_program_track = {track.value: 0 for track in tracks}
    if current_user.role == UserRole.SUPER_ADMIN and any(user.program_track is None for user in users):
        by_program_track["UNASSIGNED"] = 0

    scoped_role_counts = {
        role.value: {track.value: 0 for track in tracks}
        for role in roles
    }
    if current_user.role == UserRole.SUPER_ADMIN and any(user.program_track is None for user in users):
        for role_counts in scoped_role_counts.values():
            role_counts["UNASSIGNED"] = 0

    for user in users:
        role_value = user.role.value
        track_value = _track_key(user.program_track)

        if role_value in by_role:
            by_role[role_value] += 1
        if track_value in by_program_track:
            by_program_track[track_value] += 1
        if role_value in scoped_role_counts and track_value in scoped_role_counts[role_value]:
            scoped_role_counts[role_value][track_value] += 1

    active_users = sum(1 for user in users if user.is_active)
    total_users = len(users)
    return AdminUserSummaryResponse(
        total_users=total_users,
        active_users=active_users,
        inactive_users=total_users - active_users,
        by_role=by_role,
        by_program_track=by_program_track,
        scoped_role_counts=scoped_role_counts,
    )


def _assert_super_admin(current_user: User) -> None:
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only SUPER_ADMIN can access audit logs.",
        )


def _apply_user_list_filters(
    query,
    search: str | None = None,
    role: str | None = None,
    program_track: str | None = None,
    is_active: bool | None = None,
):
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(
            User.full_name.ilike(term),
            User.email.ilike(term),
            User.phone.ilike(term),
        ))
    if role:
        query = query.filter(User.role == _parse_user_role(role))
    if program_track:
        query = query.filter(User.program_track == _parse_program_track(program_track))
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    return query


def _apply_idea_list_filters(
    query,
    search: str | None = None,
    current_status: str | None = None,
    category: str | None = None,
    program_track: str | None = None,
    applicant_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(
            Idea.application_id.ilike(term),
            Idea.idea_title.ilike(term),
            Idea.applicant_name.ilike(term),
            Idea.email.ilike(term),
            Idea.phone.ilike(term),
        ))
    if current_status:
        try:
            query = query.filter(Idea.current_status == IdeaStatus(current_status))
        except ValueError:
            valid = [s.value for s in IdeaStatus]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{current_status}'. Valid: {valid}",
            )
    if category:
        query = query.filter(Idea.category == coerce_idea_category(category))
    if program_track:
        query = query.filter(Idea.program_track == _parse_program_track(program_track))
    if applicant_type:
        query = query.filter(Idea.applicant_type == applicant_type)
    if date_from:
        query = query.filter(Idea.created_at >= date_from)
    if date_to:
        query = query.filter(Idea.created_at <= date_to)
    return query


def _assert_can_manage_user(current_user: User, target_user: User) -> None:
    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot change their own active status.",
        )

    if current_user.role == UserRole.SUPER_ADMIN:
        return

    if target_user.role not in SCOPED_USER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only SUPER_ADMIN can manage admin users.",
        )

    if current_user.role == UserRole.TEAM_ADMIN_GLOBAL:
        if target_user.program_track == ProgramTrack.NATIONAL_INTERNATIONAL:
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User outside your scope.")

    if current_user.role == UserRole.TEAM_ADMIN_LOCAL:
        if target_user.program_track in LOCAL_TRACKS:
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User outside your scope.")

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


def _assert_user_update_scope(
    current_user: User,
    target_role: UserRole,
    target_track: ProgramTrack | None,
) -> None:
    if target_role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Updating users to SUPER_ADMIN is not allowed through this endpoint.",
        )

    if current_user.role == UserRole.SUPER_ADMIN:
        return

    if current_user.role == UserRole.TEAM_ADMIN_GLOBAL:
        if target_role not in SCOPED_USER_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Global admins can edit only JURY or INVENTOR users.",
            )
        if target_track != ProgramTrack.NATIONAL_INTERNATIONAL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Global admins can edit users only in NATIONAL_INTERNATIONAL scope.",
            )
        return

    if current_user.role == UserRole.TEAM_ADMIN_LOCAL:
        if target_role not in SCOPED_USER_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Local admins can edit only JURY or INVENTOR users.",
            )
        if target_track not in LOCAL_TRACKS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Local admins can edit users only in LOCAL_REGIONAL or K12 scope.",
            )
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


def _filter_ideas_by_scope(query, current_user: User):
    """
    UPGRADE (0006): Uses IdeaVisibilityScope (team-aligned) + program_track OR logic.

    Rules:
      SUPER_ADMIN, VIEW_ADMIN_BOTH     → all ideas, no filter
      TEAM_ADMIN_GLOBAL, VIEW_ADMIN_GLOBAL → program_track=NATIONAL_INTERNATIONAL
                          OR visibility_scope in (GLOBAL_TEAM, ALL_TEAMS)
      TEAM_ADMIN_LOCAL, VIEW_ADMIN_LOCAL  → program_track in (LOCAL_REGIONAL, K12)
                          OR visibility_scope in (LOCAL_TEAM, K12_TEAM, ALL_TEAMS)

    VIEW_ADMIN_* roles are read-only counterparts of the full-admin roles and
    always see exactly the same idea scope as their full-admin equivalent.
    """
    from sqlalchemy import or_

    if current_user.role in (UserRole.SUPER_ADMIN, UserRole.VIEW_ADMIN_BOTH):
        return query

    if current_user.role in (UserRole.TEAM_ADMIN_GLOBAL, UserRole.VIEW_ADMIN_GLOBAL):
        return query.filter(
            or_(
                Idea.program_track == ProgramTrack.NATIONAL_INTERNATIONAL,
                Idea.visibility_scope.in_([
                    IdeaVisibilityScope.GLOBAL_TEAM,
                    IdeaVisibilityScope.ALL_TEAMS,
                ]),
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

    # unknown role — deny all
    return query.filter(False)


@router.get("/users", response_model=List[AdminUserRead])
def list_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User).order_by(User.created_at.desc())
    return _filter_users_by_scope(query, current_user).all()


@router.get("/users/page", response_model=PaginatedResponse)
def list_users_page(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    role: Optional[str] = None,
    program_track: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = _filter_users_by_scope(db.query(User), current_user)
    query = _apply_user_list_filters(query, search, role, program_track, is_active)
    return paginate_query(
        query.order_by(User.created_at.desc()),
        limit,
        offset,
        transform=AdminUserRead.model_validate,
    )


@router.get("/users/summary", response_model=AdminUserSummaryResponse)
def summarize_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = _filter_users_by_scope(db.query(User), current_user)
    return _build_user_summary(query.all(), current_user)


@router.get("/audit-logs", response_model=List[AuditLogRead])
def list_audit_logs(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    entity_display_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _assert_super_admin(current_user)
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if actor_user_id is not None:
        query = query.filter(AuditLog.actor_user_id == actor_user_id)
    if entity_display_id:
        query = query.filter(AuditLog.entity_display_id == entity_display_id)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)
    return (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post("/users", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    try:
        validate_password_strength(payload.password)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PASSWORD_POLICY_MESSAGE,
        )

    target_role = _parse_user_role(payload.role)
    requested_track = _parse_program_track(payload.program_track)
    target_track = _assert_can_create_user(current_user, target_role, requested_track)
    if target_track is None:
        target_track = _default_program_track_for(target_role)

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=target_role,
        program_track=target_track,
        is_active=payload.is_active,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    record_audit_log(
        db,
        actor=current_user,
        action="admin_user_created",
        entity_type="user",
        entity_id=user.id,
        entity_display_id=user.email,
        new_values={
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role.value,
            "program_track": user.program_track.value if user.program_track else None,
            "is_active": user.is_active,
            "must_change_password": user.must_change_password,
        },
        request=request,
    )
    db.commit()
    db.refresh(user)

    # Send portal access email — failure is logged but never blocks user creation
    try:
        notify_user_created(user, payload.password)
    except Exception:
        logger.warning(
            "Portal access email raised unexpectedly for user_id=%s; user creation succeeded.",
            user.id,
        )

    return user


@router.patch("/users/{user_id}/status", response_model=AdminUserRead)
def update_user_status(
    user_id: int,
    payload: AdminUserStatusUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _assert_can_manage_user(current_user, user)

    old_active = user.is_active
    user.is_active = payload.is_active
    record_audit_log(
        db,
        actor=current_user,
        action="admin_user_status_updated",
        entity_type="user",
        entity_id=user.id,
        entity_display_id=user.email,
        old_values={"is_active": old_active},
        new_values={"is_active": user.is_active},
        request=request,
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=AdminUserRead)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _assert_can_manage_user(current_user, user)

    new_role = _parse_user_role(payload.role) if payload.role else user.role
    new_track = _parse_program_track(payload.program_track) if payload.program_track is not None else user.program_track

    if new_role == UserRole.TEAM_ADMIN_GLOBAL and new_track is None:
        new_track = ProgramTrack.NATIONAL_INTERNATIONAL
    elif new_role == UserRole.TEAM_ADMIN_LOCAL and new_track is None:
        new_track = ProgramTrack.LOCAL_REGIONAL

    _assert_user_update_scope(current_user, new_role, new_track)

    old_values = {
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role.value,
        "program_track": user.program_track.value if user.program_track else None,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
    }

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.email is not None:
        user.email = payload.email
    if payload.phone is not None:
        user.phone = payload.phone
    user.role = new_role
    user.program_track = new_track
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        validate_password_strength(payload.password)
        user.password_hash = hash_password(payload.password)
        user.must_change_password = True if payload.must_change_password is None else payload.must_change_password
    elif payload.must_change_password is not None:
        user.must_change_password = payload.must_change_password

    record_audit_log(
        db,
        actor=current_user,
        action="admin_user_updated",
        entity_type="user",
        entity_id=user.id,
        entity_display_id=user.email,
        old_values=old_values,
        new_values={
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role.value,
            "program_track": user.program_track.value if user.program_track else None,
            "is_active": user.is_active,
            "must_change_password": user.must_change_password,
        },
        request=request,
    )
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# DELETE /admin/users/{user_id} — delete a user (admin only)
# ---------------------------------------------------------------------------
@router.delete("/users/{user_id}", status_code=204, summary="Delete a user (admin only)")
def delete_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _assert_can_manage_user(current_user, user)
    db.delete(user)
    record_audit_log(
        db,
        actor=current_user,
        action="admin_user_deleted",
        entity_type="user",
        entity_id=user.id,
        entity_display_id=user.email,
        old_values={
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role.value,
            "program_track": user.program_track.value if user.program_track else None,
            "is_active": user.is_active,
        },
        new_values=None,
        request=request,
    )
    db.commit()
    return None


@router.get("/ideas", response_model=List[IdeaOut])
def list_ideas(
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = db.query(Idea).order_by(Idea.created_at.desc())
    query = _filter_ideas_by_scope(query, current_user)
    return query.all()


@router.get("/ideas/page", response_model=PaginatedResponse)
def list_ideas_page(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    current_status: Optional[str] = None,
    category: Optional[str] = None,
    program_track: Optional[str] = None,
    applicant_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = _filter_ideas_by_scope(db.query(Idea), current_user)
    query = _apply_idea_list_filters(
        query,
        search=search,
        current_status=current_status or status_filter,
        category=category,
        program_track=program_track,
        applicant_type=applicant_type,
        date_from=date_from,
        date_to=date_to,
    )
    return paginate_query(
        query.order_by(Idea.created_at.desc()),
        limit,
        offset,
        transform=IdeaOut.model_validate,
    )


@router.get("/ideas/{idea_id}", response_model=AdminIdeaDetailOut)
def get_admin_idea_detail(
    idea_id: str,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = db.query(Idea)
    if idea_id.isdigit():
        idea = query.filter(Idea.id == int(idea_id)).first()
    else:
        idea = query.filter(Idea.application_id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    _assert_idea_scope(idea, current_user, db)
    return _idea_detail_out(idea, db)


@router.get("/ideas/{idea_id}/file-activity", response_model=List[FileAccessLogRead])
def list_idea_file_activity(
    idea_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    _assert_file_activity_access(idea, current_user, db)
    return (
        db.query(FileAccessLog)
        .filter(FileAccessLog.idea_id == idea.id)
        .order_by(FileAccessLog.created_at.desc(), FileAccessLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post(
    "/ideas/{idea_id}/files",
    response_model=IdeaFileOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_admin_idea_file(
    idea_id: int,
    request: Request,
    file: UploadFile = File(...),
    file_type: str = Form("OTHER"),
    description: Optional[str] = Form(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        ft = FileType(file_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file_type '{file_type}'. Valid: {[v.value for v in FileType]}",
        )

    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    _assert_idea_scope(idea, current_user, db)

    ext, content = validate_file(file, ft)
    meta = save_file(
        content=content,
        ext=ext,
        file_type=ft,
        application_id=idea.application_id,
        original_name=file.filename or "upload",
        mime_type=file.content_type,
    )
    idea_file = IdeaFile(
        idea_id=idea.id,
        uploaded_by_user_id=current_user.id,
        file_type=ft,
        file_name=meta["file_name"],
        stored_file_name=meta["stored_file_name"],
        file_path=meta["file_path"],
        mime_type=meta["mime_type"],
        file_size=meta["file_size"],
        description=description,
    )
    db.add(idea_file)
    db.flush()
    record_audit_log(
        db,
        actor=current_user,
        action="admin_idea_file_uploaded",
        entity_type="idea_file",
        entity_id=idea_file.id,
        entity_display_id=idea.application_id,
        new_values={
            "idea_id": idea.id,
            "file_name": idea_file.file_name,
            "file_type": idea_file.file_type.value if idea_file.file_type else None,
            "mime_type": idea_file.mime_type,
            "file_size": idea_file.file_size,
            "description": idea_file.description,
        },
        request=request,
    )
    db.commit()
    db.refresh(idea_file)
    return _file_to_out(idea_file)


@router.patch("/ideas/{idea_id}/status", response_model=IdeaOut)
def update_idea_status(
    idea_id: int,
    payload: IdeaStatusUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")

    # Scope check — admin can only update ideas within their visible scope
    _assert_idea_scope(idea, current_user, db)

    old_values = {
        "current_status": idea.current_status.value if idea.current_status else None,
        "current_stage": idea.current_stage,
        "next_action": idea.next_action,
        "admin_message": idea.admin_message,
        "current_pathway_stage": idea.current_pathway_stage.value if idea.current_pathway_stage else None,
        "visibility_scope": idea.visibility_scope.value if idea.visibility_scope else None,
    }

    if payload.current_status is not None:
        try:
            idea.current_status = IdeaStatus(payload.current_status)
        except ValueError:
            valid = [s.value for s in IdeaStatus]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{payload.current_status}'. Valid: {valid}",
            )

    if payload.current_stage is not None:
        idea.current_stage = payload.current_stage

    if payload.next_action is not None:
        idea.next_action = payload.next_action

    if payload.admin_message is not None:
        idea.admin_message = payload.admin_message

    # UPGRADE (0002): admin can now advance structured pathway stage and change visibility
    if payload.current_pathway_stage is not None:
        try:
            idea.current_pathway_stage = PathwayStage(payload.current_pathway_stage)
        except ValueError:
            valid = [s.value for s in PathwayStage]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid pathway stage '{payload.current_pathway_stage}'. Valid: {valid}",
            )

    if payload.visibility_scope is not None:
        try:
            idea.visibility_scope = IdeaVisibilityScope(payload.visibility_scope)
        except ValueError:
            valid = [s.value for s in IdeaVisibilityScope]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid visibility_scope '{payload.visibility_scope}'. Valid: {valid}",
            )

    new_values = {
        "current_status": idea.current_status.value if idea.current_status else None,
        "current_stage": idea.current_stage,
        "next_action": idea.next_action,
        "admin_message": idea.admin_message,
        "current_pathway_stage": idea.current_pathway_stage.value if idea.current_pathway_stage else None,
        "visibility_scope": idea.visibility_scope.value if idea.visibility_scope else None,
    }
    status_changed = old_values["current_status"] != new_values["current_status"]
    if status_changed:
        record_status_history(
            db,
            idea_id=idea.id,
            changed_by_user_id=current_user.id,
            old_status=old_values["current_status"],
            new_status=new_values["current_status"],
            old_stage=old_values["current_pathway_stage"],
            new_stage=new_values["current_pathway_stage"],
            reason="MANUAL_STATUS_UPDATE",
            remarks=payload.admin_message,
        )
    record_audit_log(
        db,
        actor=current_user,
        action="admin_idea_status_updated",
        entity_type="idea",
        entity_id=idea.id,
        entity_display_id=idea.application_id,
        old_values=old_values,
        new_values=new_values,
        request=request,
    )
    db.commit()
    db.refresh(idea)
    if status_changed:
        try:
            notify_idea_status_update(
                idea,
                new_status=new_values["current_status"] or "",
                public_message=idea.admin_message,
            )
        except Exception:
            logger.warning("Idea status notification failed after status update: idea_id=%s", idea.id)
    return idea


# ---------------------------------------------------------------------------
# DELETE /admin/ideas/{idea_id} — delete an idea (admin only)
# ---------------------------------------------------------------------------
@router.delete("/ideas/{idea_id}", status_code=204, summary="Delete an idea (admin only)")
def delete_idea(
    idea_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    _assert_idea_scope(idea, current_user, db)
    db.delete(idea)
    record_audit_log(
        db,
        actor=current_user,
        action="admin_idea_deleted",
        entity_type="idea",
        entity_id=idea.id,
        entity_display_id=idea.application_id,
        old_values={
            "application_id": idea.application_id,
            "idea_title": idea.idea_title,
            "current_status": idea.current_status.value if idea.current_status else None,
            "program_track": idea.program_track.value if idea.program_track else None,
        },
        new_values=None,
        request=request,
    )
    db.commit()
    return None


# ---------------------------------------------------------------------------
# POST /admin/ideas/{idea_id}/messages — send message to inventor
# GET  /admin/ideas/{idea_id}/messages — list all messages (admin sees internal too)
# ---------------------------------------------------------------------------

@router.post(
    "/ideas/{idea_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin-messages"],
    summary="Send a message to an inventor (admin only)",
    description=(
        "Create a message linked to an idea. "
        "Set is_internal=false for messages visible to the inventor. "
        "Set is_internal=true for admin-only internal notes (never shown to inventor)."
    ),
)
def send_message(
    idea_id: int,
    payload: MessageCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")

    # Scope check — admin can only message ideas within their visible scope
    scoped = _filter_ideas_by_scope(
        db.query(Idea).filter(Idea.id == idea_id), current_user
    ).first()
    if not scoped:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Idea outside your program track scope.",
        )

    try:
        msg_type = MessageType(payload.message_type)
    except ValueError:
        valid = [t.value for t in MessageType]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid message_type '{payload.message_type}'. Valid: {valid}",
        )

    msg = Message(
        idea_id=idea_id,
        sender_user_id=current_user.id,
        receiver_user_id=payload.receiver_user_id,
        message_type=msg_type,
        message=payload.message,
        is_internal=payload.is_internal,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    if not msg.is_internal:
        sent = send_applicant_email(
            to_email=idea.email,
            subject=f"Message from Innovation Portal - {idea.application_id}",
            html_body=(
                "<html><body>"
                f"<p>Dear {escape(idea.applicant_name)},</p>"
                "<p>You have received a message about your idea submission.</p>"
                f"<p>{escape(payload.message)}</p>"
                f"<p>Application ID: {escape(idea.application_id)}</p>"
                "</body></html>"
            ),
            text_body="\n".join([
                f"Dear {idea.applicant_name},",
                "",
                "You have received a message about your idea submission.",
                "",
                payload.message,
                "",
                f"Application ID: {idea.application_id}",
            ]),
            bcc=get_admin_notification_recipient(getattr(idea, "source_platform", None)),
            source_platform=getattr(idea, "source_platform", None),
        )
        if not sent:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Message was saved, but the applicant email could not be sent.",
            )
    return msg


@router.get(
    "/ideas/{idea_id}/messages",
    response_model=List[MessageOut],
    tags=["admin-messages"],
    summary="List all messages for an idea (admin sees internal + public)",
)
def list_messages_admin(
    idea_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")

    scoped = _filter_ideas_by_scope(
        db.query(Idea).filter(Idea.id == idea_id), current_user
    ).first()
    if not scoped:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    return (
        db.query(Message)
        .filter(Message.idea_id == idea_id)
        .order_by(Message.created_at.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# PATCH /admin/ideas/{idea_id}/message-access — block/unblock inventor messages
# ---------------------------------------------------------------------------

@router.patch(
    "/ideas/{idea_id}/message-access",
    response_model=MessageAccessOut,
    tags=["admin-messages"],
    summary="Block or unblock inventor messaging for an idea",
)
def update_message_access(
    idea_id: int,
    payload: MessageAccessUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from datetime import datetime

    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")

    scoped = _filter_ideas_by_scope(
        db.query(Idea).filter(Idea.id == idea_id), current_user
    ).first()
    if not scoped:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    idea.inventor_messages_blocked = payload.inventor_messages_blocked

    if payload.inventor_messages_blocked:
        idea.inventor_messages_blocked_reason = payload.reason or None
        idea.inventor_messages_blocked_at = datetime.utcnow()
        idea.inventor_messages_blocked_by_user_id = current_user.id
    else:
        # Unblock — clear active block fields (reason cleared so it doesn't confuse future state)
        idea.inventor_messages_blocked_reason = None
        idea.inventor_messages_blocked_at = None
        idea.inventor_messages_blocked_by_user_id = None

    db.commit()
    db.refresh(idea)

    return MessageAccessOut(
        idea_id=idea.id,
        inventor_messages_blocked=idea.inventor_messages_blocked,
        inventor_messages_blocked_reason=idea.inventor_messages_blocked_reason,
        inventor_messages_blocked_at=idea.inventor_messages_blocked_at,
        inventor_messages_blocked_by_user_id=idea.inventor_messages_blocked_by_user_id,
    )
