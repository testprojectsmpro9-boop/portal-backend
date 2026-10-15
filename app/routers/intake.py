"""
Admin Intake Desk — endpoints for receiving and processing offline submissions.

Routes (all under /api/v1/admin/intake):
  POST   /                          create intake record
  GET    /                          list intake records (scoped by role)
  GET    /{intake_id}               get single intake
  PATCH  /{intake_id}               update intake fields
  POST   /{intake_id}/mark-complete mark completeness_status=COMPLETE
  POST   /{intake_id}/request-more-info  flag NEEDS_MORE_INFORMATION
  POST   /{intake_id}/convert-to-idea    create Idea from intake data

Role access:
  SUPER_ADMIN        → all intake records
  TEAM_ADMIN_GLOBAL  → source_program in GLOBAL_PROGRAMS only
  TEAM_ADMIN_LOCAL   → source_program in LOCAL_PROGRAMS only
  JURY, INVENTOR     → blocked (require_admin dependency)
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from fastapi import Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import re
from sqlalchemy import and_, or_

from app.database import get_db
from app.config import settings
from app.services.idea_notification_service import notify_intake_conversion
from app.services.email_service import get_admin_notification_recipient, send_applicant_email
from app.services.id_generator import generate_unique_year_id
from app.services.audit_log_service import record_audit_log
from app.services.file_service import resolve_abs_path, save_intake_file, validate_file
from app.utils.prototype_status import normalize_prototype_status
from app.utils.category import coerce_idea_category
from app.models.intake import (
    IntakeSubmission, IntakeStatus, CompletenessStatus, INTAKE_SOURCE_TYPES,
)
from app.models.idea import (
    Idea, IdeaStatus, PathwayStage,
    SourceType, SourceProgram, ApplicantType, VisibilityScope,
    IdeaSourceProgram, IdeaApplicantType, IdeaVisibilityScope,
    IdeaCategory,
)
from app.models.user import User, UserRole, ProgramTrack
from app.models.idea_file import FileType, IdeaFile
from app.models.intake_file import IntakeFile
from app.schemas.intake import (
    IntakeSubmissionCreate, IntakeSubmissionUpdate,
    IntakeSubmissionOut, IntakeConversionOut, MoreInfoRequest,
)
from app.schemas.file import IntakeFileOut
from app.schemas.pagination import PaginatedResponse
from app.utils.dependencies import require_admin, get_current_user
from app.utils.pagination import paginate_query

router = APIRouter(prefix="/admin/intake", tags=["admin-intake"])

_FILE_TYPE_CHOICES = ", ".join(ft.value for ft in FileType)

# ---------------------------------------------------------------------------
# Scope constants
# ---------------------------------------------------------------------------

# source_programs accessible to TEAM_ADMIN_GLOBAL
GLOBAL_PROGRAMS = frozenset([
    SourceProgram.NMF_NATIONAL,
    SourceProgram.IFIA_AFFILIATE,
    SourceProgram.EXTERNAL_REFERRAL,
])

# source_programs accessible to TEAM_ADMIN_LOCAL
LOCAL_PROGRAMS = frozenset([
    SourceProgram.NMF_LOCAL,
    SourceProgram.NMF_K12,
])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_intake_id(db: Session) -> str:
    return generate_unique_year_id(
        db=db,
        model=IntakeSubmission,
        column_name="intake_id",
        prefix=settings.INTAKE_ID_PREFIX,
    )


def _generate_application_id(db: Session) -> str:
    return generate_unique_year_id(
        db=db,
        model=Idea,
        column_name="application_id",
        prefix=settings.APPLICATION_ID_PREFIX,
    )


def _default_source_program(role: UserRole) -> SourceProgram:
    """Derive default source_program when caller omits it."""
    if role == UserRole.TEAM_ADMIN_GLOBAL:
        return SourceProgram.NMF_NATIONAL
    if role == UserRole.TEAM_ADMIN_LOCAL:
        return SourceProgram.NMF_LOCAL
    return SourceProgram.NMF_NATIONAL  # SUPER_ADMIN — sensible fallback


def _default_visibility_scope(role: UserRole) -> VisibilityScope:
    """Derive default visibility_scope when caller omits it."""
    if role == UserRole.TEAM_ADMIN_GLOBAL:
        return VisibilityScope.GLOBAL_ONLY
    if role == UserRole.TEAM_ADMIN_LOCAL:
        return VisibilityScope.LOCAL_ONLY
    return VisibilityScope.GLOBAL_AND_LOCAL  # SUPER_ADMIN


def _assert_program_scope(sp: SourceProgram, current_user: User) -> None:
    """Raise 403 if admin tries to create/update intake outside their allowed scope."""
    role = current_user.role
    if role == UserRole.SUPER_ADMIN:
        return
    if role == UserRole.TEAM_ADMIN_GLOBAL and sp not in GLOBAL_PROGRAMS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Global admin cannot create/update intake with source_program={sp.value}. "
                f"Allowed: {[p.value for p in GLOBAL_PROGRAMS]}"
            ),
        )
    if role == UserRole.TEAM_ADMIN_LOCAL and sp not in LOCAL_PROGRAMS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Local admin cannot create/update intake with source_program={sp.value}. "
                f"Allowed: {[p.value for p in LOCAL_PROGRAMS]}"
            ),
        )


def _filter_by_scope(query, current_user: User):
    """Filter intake list to records visible for current_user's role."""
    if current_user.role == UserRole.SUPER_ADMIN:
        return query
    if current_user.role == UserRole.TEAM_ADMIN_GLOBAL:
        return query.filter(IntakeSubmission.source_program.in_(GLOBAL_PROGRAMS))
    if current_user.role == UserRole.TEAM_ADMIN_LOCAL:
        return query.filter(IntakeSubmission.source_program.in_(LOCAL_PROGRAMS))
    return query.filter(False)


def _get_or_404(intake_id: str, db: Session) -> IntakeSubmission:
    rec = db.query(IntakeSubmission).filter(IntakeSubmission.intake_id == intake_id).first()
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intake {intake_id} not found",
        )
    return rec


def _assert_read_access(intake: IntakeSubmission, current_user: User) -> None:
    """Raise 403 if current_user's scope doesn't cover this intake."""
    role = current_user.role
    if role == UserRole.SUPER_ADMIN:
        return
    sp = intake.source_program
    if role == UserRole.TEAM_ADMIN_GLOBAL and (sp is None or sp not in GLOBAL_PROGRAMS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    if role == UserRole.TEAM_ADMIN_LOCAL and (sp is None or sp not in LOCAL_PROGRAMS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    if role in (UserRole.TEAM_ADMIN_GLOBAL, UserRole.TEAM_ADMIN_LOCAL):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


def _program_track_to_source_programs(program_track: str) -> tuple[SourceProgram, ...]:
    try:
        track = ProgramTrack(program_track)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid program_track '{program_track}'. Valid: {[item.value for item in ProgramTrack]}",
        )
    if track == ProgramTrack.NATIONAL_INTERNATIONAL:
        return tuple(GLOBAL_PROGRAMS)
    if track == ProgramTrack.K12:
        return (SourceProgram.NMF_K12,)
    return (SourceProgram.NMF_LOCAL,)


def _apply_intake_filters(
    query,
    search: str | None = None,
    status_filter: str | None = None,
    source_type: str | None = None,
    source_program: str | None = None,
    program_track: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(
            IntakeSubmission.intake_id.ilike(term),
            IntakeSubmission.applicant_name.ilike(term),
            IntakeSubmission.email.ilike(term),
            IntakeSubmission.phone.ilike(term),
            IntakeSubmission.raw_title.ilike(term),
        ))
    if status_filter:
        try:
            query = query.filter(IntakeSubmission.intake_status == IntakeStatus(status_filter))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{status_filter}'. Valid: {[item.value for item in IntakeStatus]}",
            )
    if source_type:
        try:
            query = query.filter(IntakeSubmission.source_type == SourceType(source_type))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source_type '{source_type}'. Valid: {[item.value for item in SourceType]}",
            )
    if source_program:
        try:
            query = query.filter(IntakeSubmission.source_program == SourceProgram(source_program))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source_program '{source_program}'. Valid: {[item.value for item in SourceProgram]}",
            )
    if program_track:
        query = query.filter(IntakeSubmission.source_program.in_(_program_track_to_source_programs(program_track)))
    if date_from:
        query = query.filter(IntakeSubmission.created_at >= date_from)
    if date_to:
        query = query.filter(IntakeSubmission.created_at <= date_to)
    return query
    if role == UserRole.TEAM_ADMIN_LOCAL and (sp is None or sp not in LOCAL_PROGRAMS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


def _to_out(rec: IntakeSubmission) -> IntakeSubmissionOut:
    """Convert ORM IntakeSubmission → IntakeSubmissionOut (explicit, no from_attributes)."""
    return IntakeSubmissionOut(
        id=rec.id,
        intake_id=rec.intake_id,
        created_by_user_id=rec.created_by_user_id,
        assigned_team_user_id=rec.assigned_team_user_id,
        source_type=rec.source_type.value if rec.source_type else "",
        source_program=rec.source_program.value if rec.source_program else None,
        source_platform=rec.source_platform,
        applicant_type=rec.applicant_type.value if rec.applicant_type else None,
        visibility_scope=rec.visibility_scope.value if rec.visibility_scope else None,
        original_language=rec.original_language,
        applicant_name=rec.applicant_name,
        phone=rec.phone,
        email=rec.email,
        age=rec.age,
        gender=rec.gender,
        location=rec.location,
        organization=rec.organization,
        team_name=rec.team_name,
        team_member_count=rec.team_member_count,
        team_member_names=rec.team_member_names,
        guardian_name=rec.guardian_name,
        guardian_phone=rec.guardian_phone,
        guardian_email=rec.guardian_email,
        guardian_relationship=rec.guardian_relationship,
        guardian_consent=rec.guardian_consent,
        raw_title=rec.raw_title,
        raw_description=rec.raw_description,
        problem_statement=rec.problem_statement,
        solution_description=rec.solution_description,
        application_context=rec.application_context,
        uniqueness=rec.uniqueness,
        category=rec.category,
        sub_category=rec.sub_category,
        target_users=rec.target_users,
        prototype_status=rec.prototype_status,
        support_needed=rec.support_needed,
        consent_data=rec.consent_data,
        consent_original=rec.consent_original,
        consent_contact=rec.consent_contact,
        standardized_idea_id=rec.standardized_idea_id,
        intake_status=rec.intake_status.value if rec.intake_status else "",
        completeness_status=rec.completeness_status.value if rec.completeness_status else "",
        admin_notes=rec.admin_notes,
        missing_information_note=rec.missing_information_note,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


def _intake_file_to_out(f: IntakeFile) -> IntakeFileOut:
    return IntakeFileOut(
        id=f.id,
        intake_id=f.intake.intake_id if f.intake else "",
        intake_submission_id=f.intake_submission_id,
        uploaded_by_user_id=f.uploaded_by_user_id,
        file_type=f.file_type.value if f.file_type else "",
        file_name=f.file_name,
        mime_type=f.mime_type,
        file_size=f.file_size,
        description=f.description,
        download_url=f"/api/v1/admin/intake/files/{f.id}",
        created_at=f.created_at,
    )


def _get_intake_file_or_404(file_id: int, db: Session) -> IntakeFile:
    file_record = db.query(IntakeFile).filter(IntakeFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake file not found")
    return file_record


def _source_program_to_track(sp: SourceProgram) -> ProgramTrack:
    """Map source_program → program_track for newly created Idea on conversion."""
    if sp in (SourceProgram.NMF_NATIONAL, SourceProgram.IFIA_AFFILIATE, SourceProgram.EXTERNAL_REFERRAL):
        return ProgramTrack.NATIONAL_INTERNATIONAL
    if sp == SourceProgram.NMF_K12:
        return ProgramTrack.K12
    if sp == SourceProgram.NMF_LOCAL:
        return ProgramTrack.LOCAL_REGIONAL
    return ProgramTrack.LOCAL_REGIONAL  # OTHER — default to local


def _map_source_program(sp: SourceProgram) -> IdeaSourceProgram:
    """Map Intake SourceProgram → Ideas IdeaSourceProgram (track-aligned values)."""
    if sp in (SourceProgram.NMF_NATIONAL, SourceProgram.IFIA_AFFILIATE, SourceProgram.EXTERNAL_REFERRAL):
        return IdeaSourceProgram.NATIONAL_INTERNATIONAL
    if sp == SourceProgram.NMF_K12:
        return IdeaSourceProgram.K12
    if sp == SourceProgram.NMF_LOCAL:
        return IdeaSourceProgram.LOCAL_REGIONAL
    return IdeaSourceProgram.LOCAL_REGIONAL  # OTHER


def _map_applicant_type(at: ApplicantType | None, age: int | None) -> IdeaApplicantType:
    """Map Intake ApplicantType → Ideas IdeaApplicantType. Age-aware for STUDENT."""
    if at is None:
        return IdeaApplicantType.GENERAL_PUBLIC
    if at == ApplicantType.STUDENT:
        if age is not None and age <= 18:
            return IdeaApplicantType.K12_STUDENT
        return IdeaApplicantType.COLLEGE_STUDENT
    mapping = {
        ApplicantType.INDIVIDUAL: IdeaApplicantType.ADULT_INNOVATOR,
        ApplicantType.TEAM: IdeaApplicantType.ADULT_INNOVATOR,
        ApplicantType.STARTUP: IdeaApplicantType.STARTUP,
        ApplicantType.NGO: IdeaApplicantType.GENERAL_PUBLIC,
        ApplicantType.INSTITUTION: IdeaApplicantType.RESEARCHER,
        ApplicantType.OTHER: IdeaApplicantType.OTHER,
    }
    return mapping.get(at, IdeaApplicantType.OTHER)


def _map_visibility_scope(sp: SourceProgram, vs: VisibilityScope | None) -> IdeaVisibilityScope:
    """Map Intake VisibilityScope → Ideas IdeaVisibilityScope. NMF_K12 source → K12_TEAM."""
    if sp == SourceProgram.NMF_K12:
        return IdeaVisibilityScope.K12_TEAM
    if vs is None:
        return IdeaVisibilityScope.LOCAL_TEAM
    mapping = {
        VisibilityScope.GLOBAL_ONLY: IdeaVisibilityScope.GLOBAL_TEAM,
        VisibilityScope.LOCAL_ONLY: IdeaVisibilityScope.LOCAL_TEAM,
        VisibilityScope.GLOBAL_AND_LOCAL: IdeaVisibilityScope.ALL_TEAMS,
        VisibilityScope.SUPER_ADMIN_ONLY: IdeaVisibilityScope.ALL_TEAMS,
    }
    return mapping.get(vs, IdeaVisibilityScope.LOCAL_TEAM)


def _parse_raw_description(raw: str | None) -> dict[str, str]:
    """Parse structured intake notes while preserving old unstructured intakes."""
    if not raw:
        return {}

    labels = [
        "Problem",
        "Solution",
        "Category",
        "Sub-category",
        "Sub Category",
        "Target Users / Beneficiaries",
        "Target Users",
        "Beneficiaries",
        "Prototype Status",
        "Support Needed",
    ]
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    pattern = re.compile(rf"(?im)^\s*({label_pattern})\s*:\s*")

    matches = list(pattern.finditer(raw))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = match.group(1).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        value = raw[start:end].strip()
        if value:
            sections[label] = value
    return sections


def _section(sections: dict[str, str], *labels: str) -> str | None:
    for label in labels:
        value = sections.get(label.lower())
        if value:
            return value
    return None


def _safe_category(value: str | None) -> IdeaCategory | None:
    return coerce_idea_category(value)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _request_more_info_bodies(intake: IntakeSubmission, note: str) -> tuple[str, str]:
    html = (
        "<html><body>"
        f"<p>Dear {intake.applicant_name},</p>"
        "<p>We need a little more information to continue processing your intake submission.</p>"
        f"<p>{note}</p>"
        f"<p>Intake reference: {intake.intake_id}</p>"
        "</body></html>"
    )
    text = "\n".join([
        f"Dear {intake.applicant_name},",
        "",
        "We need a little more information to continue processing your intake submission.",
        "",
        note,
        "",
        f"Intake reference: {intake.intake_id}",
    ])
    return html, text


def _is_k12_or_minor(source_program: SourceProgram | None, age: int | None) -> bool:
    return (age is not None and age < 18) or source_program == SourceProgram.NMF_K12


def _validate_intake_alignment(intake: IntakeSubmission) -> None:
    if intake.applicant_type == ApplicantType.TEAM:
        if intake.team_member_count is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="team_member_count is required for Team / Group intake submissions.")
        if intake.team_member_count < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="team_member_count must be at least 2 for Team / Group intake submissions.")

    if _is_k12_or_minor(intake.source_program, intake.age):
        if not _clean(intake.guardian_name):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="guardian_name is required for K-12 or minor intake submissions.")
        if not _clean(intake.guardian_phone):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="guardian_phone is required for K-12 or minor intake submissions.")
        if not _clean(intake.guardian_relationship):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="guardian_relationship is required for K-12 or minor intake submissions.")
        if intake.guardian_consent is not True:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="guardian_consent is required for K-12 or minor intake submissions.")


# ---------------------------------------------------------------------------
# POST /admin/intake — create intake record
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=IntakeSubmissionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an intake submission (admin only)",
)
def create_intake(
    payload: IntakeSubmissionCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # Validate source_type
    try:
        st = SourceType(payload.source_type)
    except ValueError:
        valid = [s.value for s in INTAKE_SOURCE_TYPES]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source_type '{payload.source_type}'. Allowed for intake: {valid}",
        )
    if st not in INTAKE_SOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ONLINE_FORM is not allowed for admin intake. Use the public idea submission endpoint.",
        )

    # Resolve source_program — use payload value or derive from role
    if payload.source_program:
        try:
            sp = SourceProgram(payload.source_program)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source_program '{payload.source_program}'. Valid: {[s.value for s in SourceProgram]}",
            )
    else:
        sp = _default_source_program(current_user.role)

    _assert_program_scope(sp, current_user)

    # Resolve visibility_scope
    if payload.visibility_scope:
        try:
            vs = VisibilityScope(payload.visibility_scope)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid visibility_scope '{payload.visibility_scope}'. Valid: {[v.value for v in VisibilityScope]}",
            )
    else:
        vs = _default_visibility_scope(current_user.role)

    # Resolve applicant_type
    at = None
    if payload.applicant_type:
        try:
            at = ApplicantType(payload.applicant_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid applicant_type '{payload.applicant_type}'. Valid: {[a.value for a in ApplicantType]}",
            )

    intake = IntakeSubmission(
        intake_id=_generate_intake_id(db),
        created_by_user_id=current_user.id,
        assigned_team_user_id=payload.assigned_team_user_id,
        source_type=st,
        source_program=sp,
        source_platform=payload.source_platform or "ingeniouspark",
        applicant_type=at,
        visibility_scope=vs,
        original_language=payload.original_language,
        applicant_name=payload.applicant_name,
        phone=payload.phone,
        email=payload.email,
        age=payload.age,
        gender=payload.gender,
        location=payload.location,
        organization=payload.organization,
        team_name=payload.team_name,
        team_member_count=payload.team_member_count,
        team_member_names=payload.team_member_names,
        guardian_name=payload.guardian_name,
        guardian_phone=payload.guardian_phone,
        guardian_email=payload.guardian_email,
        guardian_relationship=payload.guardian_relationship,
        guardian_consent=payload.guardian_consent,
        raw_title=payload.raw_title,
        raw_description=payload.raw_description,
        problem_statement=payload.problem_statement,
        solution_description=payload.solution_description,
        application_context=payload.application_context,
        uniqueness=payload.uniqueness,
        category=payload.category,
        sub_category=payload.sub_category,
        target_users=payload.target_users,
        prototype_status=payload.prototype_status,
        support_needed=payload.support_needed,
        consent_data=payload.consent_data,
        consent_original=payload.consent_original,
        consent_contact=payload.consent_contact,
        admin_notes=payload.admin_notes,
        intake_status=IntakeStatus.RAW_RECEIVED,
        completeness_status=CompletenessStatus.NOT_CHECKED,
    )
    _validate_intake_alignment(intake)
    db.add(intake)
    db.commit()
    db.refresh(intake)
    return _to_out(intake)


# ---------------------------------------------------------------------------
# GET /admin/intake — list (scoped)
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=List[IntakeSubmissionOut],
    summary="List intake submissions visible to current admin",
)
def list_intake(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(IntakeSubmission).order_by(IntakeSubmission.created_at.desc())
    query = _filter_by_scope(query, current_user)
    return [_to_out(r) for r in query.all()]


@router.get(
    "/page",
    response_model=PaginatedResponse,
    summary="Paginated intake submissions visible to current admin",
)
def list_intake_page(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    source_type: Optional[str] = None,
    source_program: Optional[str] = None,
    program_track: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = _filter_by_scope(db.query(IntakeSubmission), current_user)
    query = _apply_intake_filters(
        query,
        search=search,
        status_filter=status_filter,
        source_type=source_type,
        source_program=source_program,
        program_track=program_track,
        date_from=date_from,
        date_to=date_to,
    )
    return paginate_query(
        query.order_by(IntakeSubmission.created_at.desc()),
        limit,
        offset,
        transform=_to_out,
    )


# ---------------------------------------------------------------------------
# GET /admin/intake/stats
# ---------------------------------------------------------------------------

def _pending_intake_query(db: Session):
    return db.query(IntakeSubmission).filter(
        and_(
            IntakeSubmission.standardized_idea_id.is_(None),
            IntakeSubmission.intake_status.in_([
                IntakeStatus.RAW_RECEIVED,
                IntakeStatus.STANDARDIZATION_PENDING,
                IntakeStatus.STANDARDIZED,
                IntakeStatus.NEEDS_MORE_INFORMATION,
                IntakeStatus.READY_FOR_REVIEW,
            ]),
        )
    )


@router.get(
    "/stats",
    summary="Get scoped intake dashboard counts",
)
def get_intake_stats(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    pending_query = _pending_intake_query(db)
    pending_query = _filter_by_scope(pending_query, current_user)
    return {"pending_intake": pending_query.count()}


# ---------------------------------------------------------------------------
# Intake file attachments
# ---------------------------------------------------------------------------

@router.post(
    "/{intake_id}/files",
    response_model=List[IntakeFileOut],
    status_code=status.HTTP_201_CREATED,
    summary="Upload supporting files to an intake submission",
    description=(
        f"Upload one or more files linked to an intake record. `file_type` must be one of: "
        f"{_FILE_TYPE_CHOICES}. Max file size: 50 MB."
    ),
)
def upload_intake_files(
    intake_id: str,
    request: Request,
    files: List[UploadFile] = File(..., description="One or more files to upload"),
    file_type: str = Form(FileType.OTHER.value, description=f"One of: {_FILE_TYPE_CHOICES}"),
    description: Optional[str] = Form(None, description="Optional description of these attachments"),
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

    intake = _get_or_404(intake_id, db)
    _assert_read_access(intake, current_user)

    created_files: list[IntakeFile] = []
    for upload in files:
        ext, content = validate_file(upload, ft)
        meta = save_intake_file(
            content=content,
            ext=ext,
            file_type=ft,
            intake_id=intake.intake_id,
            original_name=upload.filename or "upload",
            mime_type=upload.content_type,
        )
        intake_file = IntakeFile(
            intake_submission_id=intake.id,
            uploaded_by_user_id=current_user.id,
            file_type=ft,
            file_name=meta["file_name"],
            stored_file_name=meta["stored_file_name"],
            file_path=meta["file_path"],
            mime_type=meta["mime_type"],
            file_size=meta["file_size"],
            description=description,
        )
        db.add(intake_file)
        db.flush()
        record_audit_log(
            db,
            actor=current_user,
            action="intake_file_uploaded",
            entity_type="intake_file",
            entity_id=intake_file.id,
            entity_display_id=intake.intake_id,
            new_values={
                "intake_submission_id": intake.id,
                "file_name": intake_file.file_name,
                "file_type": intake_file.file_type.value if intake_file.file_type else None,
                "mime_type": intake_file.mime_type,
                "file_size": intake_file.file_size,
                "description": intake_file.description,
            },
            request=request,
        )
        created_files.append(intake_file)

    db.commit()
    for intake_file in created_files:
        db.refresh(intake_file)
    return [_intake_file_to_out(f) for f in created_files]


@router.get(
    "/{intake_id}/files",
    response_model=List[IntakeFileOut],
    summary="List supporting files for an intake submission",
)
def list_intake_files(
    intake_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    intake = _get_or_404(intake_id, db)
    _assert_read_access(intake, current_user)
    files = (
        db.query(IntakeFile)
        .filter(IntakeFile.intake_submission_id == intake.id)
        .order_by(IntakeFile.created_at.desc())
        .all()
    )
    return [_intake_file_to_out(f) for f in files]


@router.get(
    "/files/{file_id}",
    summary="Download an intake supporting file",
)
def download_intake_file(
    file_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    file_record = _get_intake_file_or_404(file_id, db)
    _assert_read_access(file_record.intake, current_user)
    abs_path = resolve_abs_path(file_record.file_path)
    if not abs_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File record exists but content is missing from storage.",
        )
    return FileResponse(
        path=str(abs_path),
        filename=file_record.file_name,
        media_type=file_record.mime_type or "application/octet-stream",
    )


@router.delete(
    "/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an intake supporting file",
)
def delete_intake_file(
    file_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    file_record = _get_intake_file_or_404(file_id, db)
    _assert_read_access(file_record.intake, current_user)

    abs_path = resolve_abs_path(file_record.file_path)
    linked_idea_file = db.query(IdeaFile).filter(IdeaFile.file_path == file_record.file_path).first()
    record_audit_log(
        db,
        actor=current_user,
        action="intake_file_deleted",
        entity_type="intake_file",
        entity_id=file_record.id,
        entity_display_id=file_record.intake.intake_id if file_record.intake else None,
        old_values={
            "intake_submission_id": file_record.intake_submission_id,
            "file_name": file_record.file_name,
            "file_type": file_record.file_type.value if file_record.file_type else None,
            "preserved_for_idea": bool(linked_idea_file),
        },
        request=request,
    )
    db.delete(file_record)
    db.commit()

    if not linked_idea_file and abs_path.exists():
        abs_path.unlink()
    return None


# ---------------------------------------------------------------------------
# GET /admin/intake/{intake_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{intake_id}",
    response_model=IntakeSubmissionOut,
    summary="Get a single intake submission",
)
def get_intake(
    intake_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    intake = _get_or_404(intake_id, db)
    _assert_read_access(intake, current_user)
    return _to_out(intake)


# ---------------------------------------------------------------------------
# PATCH /admin/intake/{intake_id}
# ---------------------------------------------------------------------------

@router.patch(
    "/{intake_id}",
    response_model=IntakeSubmissionOut,
    summary="Update intake fields",
)
def update_intake(
    intake_id: str,
    payload: IntakeSubmissionUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    intake = _get_or_404(intake_id, db)
    _assert_read_access(intake, current_user)

    if payload.source_type is not None:
        try:
            st = SourceType(payload.source_type)
        except ValueError:
            raise HTTPException(400, f"Invalid source_type '{payload.source_type}'")
        if st not in INTAKE_SOURCE_TYPES:
            raise HTTPException(400, "ONLINE_FORM not allowed for intake.")
        intake.source_type = st

    if payload.source_program is not None:
        try:
            sp = SourceProgram(payload.source_program)
        except ValueError:
            raise HTTPException(400, f"Invalid source_program '{payload.source_program}'")
        _assert_program_scope(sp, current_user)
        intake.source_program = sp

    if payload.source_platform is not None:
        intake.source_platform = payload.source_platform

    if payload.visibility_scope is not None:
        try:
            intake.visibility_scope = VisibilityScope(payload.visibility_scope)
        except ValueError:
            raise HTTPException(400, f"Invalid visibility_scope '{payload.visibility_scope}'")

    if payload.applicant_type is not None:
        try:
            intake.applicant_type = ApplicantType(payload.applicant_type)
        except ValueError:
            raise HTTPException(400, f"Invalid applicant_type '{payload.applicant_type}'")

    if payload.intake_status is not None:
        try:
            intake.intake_status = IntakeStatus(payload.intake_status)
        except ValueError:
            raise HTTPException(400, f"Invalid intake_status '{payload.intake_status}'. Valid: {[s.value for s in IntakeStatus]}")

    if payload.completeness_status is not None:
        try:
            intake.completeness_status = CompletenessStatus(payload.completeness_status)
        except ValueError:
            raise HTTPException(400, f"Invalid completeness_status '{payload.completeness_status}'")

    for field in ("original_language", "applicant_name", "phone", "email", "age",
                  "gender", "location", "organization", "team_name", "team_member_count",
                  "team_member_names", "guardian_name", "guardian_phone", "guardian_email",
                  "guardian_relationship", "guardian_consent", "raw_title", "raw_description",
                  "problem_statement", "solution_description", "application_context", "uniqueness",
                  "category", "sub_category", "target_users", "prototype_status", "support_needed",
                  "consent_data", "consent_original", "consent_contact", "admin_notes",
                  "missing_information_note", "assigned_team_user_id"):
        val = getattr(payload, field)
        if val is not None:
            setattr(intake, field, val)

    _validate_intake_alignment(intake)
    db.commit()
    db.refresh(intake)
    return _to_out(intake)


# ---------------------------------------------------------------------------
# DELETE /admin/intake/{intake_id} — delete an intake submission (admin only)
# ---------------------------------------------------------------------------
@router.delete("/{intake_id}", status_code=204, summary="Delete an intake submission (admin only)")
def delete_intake(
    intake_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    intake = _get_or_404(intake_id, db)
    _assert_read_access(intake, current_user)
    db.delete(intake)
    record_audit_log(
        db,
        actor=current_user,
        action="admin_intake_deleted",
        entity_type="intake_submission",
        entity_id=intake.id,
        entity_display_id=intake.intake_id,
        old_values={
            "intake_id": intake.intake_id,
            "applicant_name": intake.applicant_name,
            "email": intake.email,
            "source_program": intake.source_program.value if intake.source_program else None,
            "intake_status": intake.intake_status.value if intake.intake_status else None,
        },
        new_values=None,
        request=request,
    )
    db.commit()
    return None


# ---------------------------------------------------------------------------
# POST /admin/intake/{intake_id}/mark-complete
# ---------------------------------------------------------------------------

@router.post(
    "/{intake_id}/mark-complete",
    response_model=IntakeSubmissionOut,
    summary="Mark intake completeness as COMPLETE",
)
def mark_complete(
    intake_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    intake = _get_or_404(intake_id, db)
    _assert_read_access(intake, current_user)

    intake.completeness_status = CompletenessStatus.COMPLETE
    # Advance status if still in early stages
    if intake.intake_status in (IntakeStatus.RAW_RECEIVED, IntakeStatus.STANDARDIZATION_PENDING):
        intake.intake_status = IntakeStatus.STANDARDIZED
    # If it was flagged for more info and is now marked complete, move to READY_FOR_REVIEW
    elif intake.intake_status == IntakeStatus.NEEDS_MORE_INFORMATION:
        intake.intake_status = IntakeStatus.READY_FOR_REVIEW

    db.commit()
    db.refresh(intake)
    return _to_out(intake)


# ---------------------------------------------------------------------------
# POST /admin/intake/{intake_id}/request-more-info
# ---------------------------------------------------------------------------

@router.post(
    "/{intake_id}/request-more-info",
    response_model=IntakeSubmissionOut,
    summary="Flag intake as needing more information",
)
def request_more_info(
    intake_id: str,
    payload: MoreInfoRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    intake = _get_or_404(intake_id, db)
    _assert_read_access(intake, current_user)

    if intake.intake_status == IntakeStatus.CONVERTED_TO_IDEA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Intake already converted to idea. Cannot request more info.",
        )
    if not _clean(intake.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Applicant email is missing. Please add an email before requesting more information.",
        )

    intake.intake_status = IntakeStatus.NEEDS_MORE_INFORMATION
    intake.completeness_status = CompletenessStatus.INCOMPLETE
    intake.missing_information_note = payload.missing_information_note

    db.commit()
    db.refresh(intake)
    html_body, text_body = _request_more_info_bodies(intake, payload.missing_information_note)
    sent = send_applicant_email(
        to_email=intake.email,
        subject=f"More information requested - {intake.intake_id}",
        html_body=html_body,
        text_body=text_body,
        bcc=get_admin_notification_recipient(intake.source_platform or "ingeniouspark"),
        source_platform=intake.source_platform or "ingeniouspark",
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Request was saved, but the applicant email could not be sent.",
        )
    return _to_out(intake)


# ---------------------------------------------------------------------------
# POST /admin/intake/{intake_id}/convert-to-idea
# ---------------------------------------------------------------------------

@router.post(
    "/{intake_id}/convert-to-idea",
    response_model=IntakeConversionOut,
    summary="Convert intake to a formal idea record",
    description=(
        "Creates a new Idea from the intake's standardized fields. "
        "intake_status must be STANDARDIZED or READY_FOR_REVIEW. "
        "completeness_status must be COMPLETE. "
        "email is optional business data — a blank/malformed intake email does not block conversion. "
        "Response includes created_application_id for direct navigation to the new idea."
    ),
)
def convert_to_idea(
    intake_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    intake = _get_or_404(intake_id, db)
    _assert_read_access(intake, current_user)

    # Guard: already converted
    if intake.intake_status == IntakeStatus.CONVERTED_TO_IDEA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Intake already converted to an idea.",
        )

    # Guard: must be ready
    allowed_statuses = (IntakeStatus.STANDARDIZED, IntakeStatus.READY_FOR_REVIEW)
    if intake.intake_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Intake status must be STANDARDIZED or READY_FOR_REVIEW before conversion. "
                f"Current: {intake.intake_status.value}. "
                f"Use PATCH to update status or POST /mark-complete first."
            ),
        )

    # Guard: must be complete
    if intake.completeness_status != CompletenessStatus.COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Intake completeness_status must be COMPLETE before conversion. Call /mark-complete first.",
        )

    # Derive program_track + ideas-specific enum values from intake enums
    sp = intake.source_program or SourceProgram.NMF_LOCAL
    program_track = _source_program_to_track(sp)
    idea_source_program = _map_source_program(sp)
    idea_applicant_type = _map_applicant_type(intake.applicant_type, intake.age)
    idea_visibility_scope = _map_visibility_scope(sp, intake.visibility_scope)

    application_id = _generate_application_id(db)
    raw_sections = _parse_raw_description(intake.raw_description)
    problem_statement = _clean(intake.problem_statement) or _section(raw_sections, "Problem")
    solution_description = _clean(intake.solution_description) or _section(raw_sections, "Solution")
    category = _safe_category(_clean(intake.category) or _section(raw_sections, "Category") or "Others")
    sub_category = _clean(intake.sub_category) or _section(raw_sections, "Sub-category", "Sub Category")
    target_users = (
        _clean(intake.target_users)
        or _section(raw_sections, "Target Users / Beneficiaries", "Target Users", "Beneficiaries")
    )
    prototype_status = normalize_prototype_status(
        _clean(intake.prototype_status) or _section(raw_sections, "Prototype Status")
    )
    support_needed = _clean(intake.support_needed) or _section(raw_sections, "Support Needed")

    if not any([
        problem_statement, solution_description, category, sub_category,
        target_users, prototype_status, support_needed,
    ]):
        problem_statement = intake.raw_description
    if not solution_description:
        solution_description = "Not provided"

    idea = Idea(
        application_id=application_id,
        applicant_name=intake.applicant_name,
        # ideas.email is NOT NULL at the DB level, but intake email is
        # intentionally optional business data — fall back to "" rather
        # than raise, so a blank intake email never blocks conversion.
        email=intake.email or "",
        phone=intake.phone,
        age=intake.age,
        gender=intake.gender,
        location=intake.location,
        organization=intake.organization,
        original_language=intake.original_language,
        team_name=intake.team_name,
        team_member_count=intake.team_member_count,
        team_member_names=intake.team_member_names,
        guardian_name=intake.guardian_name,
        guardian_phone=intake.guardian_phone,
        guardian_email=intake.guardian_email,
        guardian_relationship=intake.guardian_relationship,
        guardian_consent=intake.guardian_consent,
        program_track=program_track,
        source_type=intake.source_type,
        source_program=idea_source_program,
        applicant_type=idea_applicant_type,
        visibility_scope=idea_visibility_scope,
        source_platform=intake.source_platform or "ingeniouspark",
        idea_title=intake.raw_title,
        problem_statement=problem_statement,
        solution_description=solution_description,
        application_context=intake.application_context,
        uniqueness=intake.uniqueness,
        category=category,
        sub_category=sub_category,
        target_users=target_users,
        prototype_status=prototype_status,
        support_needed=support_needed,
        consent_data=intake.consent_data,
        consent_original=intake.consent_original,
        consent_contact=intake.consent_contact,
        current_status=IdeaStatus.UNDER_VERIFICATION,
        current_pathway_stage=PathwayStage.ADMIN_VERIFICATION,
        next_action=(
            "Idea submitted via admin intake desk. "
            f"Intake reference: {intake.intake_id}. "
            "Pending admin verification and review pipeline entry."
        ),
        is_public_tracking_enabled=True,
    )
    db.add(idea)
    db.flush()  # get idea.id before linking

    intake_files = (
        db.query(IntakeFile)
        .filter(IntakeFile.intake_submission_id == intake.id)
        .order_by(IntakeFile.created_at.asc())
        .all()
    )
    converted_file_count = 0
    for intake_file in intake_files:
        exists = db.query(IdeaFile).filter(
            IdeaFile.idea_id == idea.id,
            IdeaFile.file_path == intake_file.file_path,
        ).first()
        if exists:
            continue
        idea_file = IdeaFile(
            idea_id=idea.id,
            uploaded_by_user_id=intake_file.uploaded_by_user_id,
            file_type=intake_file.file_type,
            file_name=intake_file.file_name,
            stored_file_name=intake_file.stored_file_name,
            file_path=intake_file.file_path,
            mime_type=intake_file.mime_type,
            file_size=intake_file.file_size,
            description=intake_file.description,
        )
        db.add(idea_file)
        converted_file_count += 1

    old_intake_status = intake.intake_status.value if intake.intake_status else None
    intake.standardized_idea_id = idea.id
    intake.intake_status = IntakeStatus.CONVERTED_TO_IDEA
    record_audit_log(
        db,
        actor=current_user,
        action="intake_converted_to_idea",
        entity_type="intake_submission",
        entity_id=intake.id,
        entity_display_id=intake.intake_id,
        old_values={"intake_status": old_intake_status},
        new_values={
            "intake_status": intake.intake_status.value,
            "standardized_idea_id": idea.id,
            "application_id": idea.application_id,
            "converted_file_count": converted_file_count,
        },
        request=request,
    )

    db.commit()
    db.refresh(idea)
    db.refresh(intake)
    notify_intake_conversion(idea, intake)
    return IntakeConversionOut(
        **_to_out(intake).model_dump(),
        created_application_id=idea.application_id,
    )
