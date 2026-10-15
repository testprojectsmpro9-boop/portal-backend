import logging
from html import escape
from typing import List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.idea import SourceProgram, VisibilityScope
from app.models.public_inquiry import PublicInquiry, PublicInquiryType
from app.models.user import ProgramTrack, User, UserRole
from app.schemas.public_inquiry import (
    PublicInquiryAssignmentUpdate,
    PublicInquiryCreate,
    PublicInquiryOut,
    PublicInquiryStatusUpdate,
)
from app.schemas.pagination import PaginatedResponse
from app.services.email_service import send_applicant_email, send_public_inquiry_notification
from app.services.audit_log_service import record_audit_log
from app.services.rate_limit import assert_rate_limit
from app.utils.dependencies import require_admin
from app.utils.pagination import paginate_query

router = APIRouter(tags=["public-inquiries"])
logger = logging.getLogger(__name__)

INQUIRY_ASSIGNABLE_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.TEAM_ADMIN_GLOBAL,
    UserRole.TEAM_ADMIN_LOCAL,
)

DEFAULT_VISIBILITY_BY_TYPE = {
    PublicInquiryType.CONTACT: VisibilityScope.GLOBAL_AND_LOCAL.value,
    PublicInquiryType.COLLABORATION: VisibilityScope.GLOBAL_AND_LOCAL.value,
    PublicInquiryType.MEMBERSHIP: VisibilityScope.GLOBAL_AND_LOCAL.value,
    PublicInquiryType.REGISTER_INTEREST: VisibilityScope.GLOBAL_AND_LOCAL.value,
    PublicInquiryType.SCHOOL_PARTNERSHIP: VisibilityScope.LOCAL_ONLY.value,
    PublicInquiryType.OTHER: VisibilityScope.SUPER_ADMIN_ONLY.value,
}


def _parse_inquiry_type(value: str) -> PublicInquiryType:
    try:
        return PublicInquiryType(value)
    except ValueError:
        valid = [item.value for item in PublicInquiryType]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid inquiry_type '{value}'. Valid: {valid}",
        )


def _parse_optional_program_track(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return ProgramTrack(value).value
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid program_track '{value}'. Valid: {[item.value for item in ProgramTrack]}",
        )


def _parse_optional_visibility_scope(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return VisibilityScope(value).value
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid visibility_scope '{value}'. Valid: {[item.value for item in VisibilityScope]}",
        )


def _parse_optional_source_program(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return SourceProgram(value).value
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source_program '{value}'. Valid: {[item.value for item in SourceProgram]}",
        )


def _scope_text(payload: PublicInquiryCreate) -> str:
    return " ".join(
        value or ""
        for value in (payload.interest_area, payload.message, payload.source_page)
    ).lower()


def _infer_program_track(payload: PublicInquiryCreate, inquiry_type: PublicInquiryType) -> str | None:
    text = _scope_text(payload)
    if inquiry_type == PublicInquiryType.SCHOOL_PARTNERSHIP or "school" in text or "k12" in text or "k-12" in text:
        return ProgramTrack.K12.value
    if "international" in text or "global" in text or "ifia" in text:
        return ProgramTrack.NATIONAL_INTERNATIONAL.value
    if "local" in text or "regional" in text:
        return ProgramTrack.LOCAL_REGIONAL.value
    return None


def _derive_source_program(program_track: str | None, payload: PublicInquiryCreate) -> str | None:
    if program_track == ProgramTrack.K12.value:
        return SourceProgram.NMF_K12.value
    if program_track == ProgramTrack.LOCAL_REGIONAL.value:
        return SourceProgram.NMF_LOCAL.value
    if program_track == ProgramTrack.NATIONAL_INTERNATIONAL.value:
        text = _scope_text(payload)
        if "ifia" in text or "international" in text:
            return SourceProgram.IFIA_AFFILIATE.value
        return SourceProgram.NMF_NATIONAL.value
    return None


def _resolve_scope_fields(
    payload: PublicInquiryCreate,
    inquiry_type: PublicInquiryType,
) -> tuple[str | None, str | None, str | None]:
    program_track = _parse_optional_program_track(payload.program_track)
    visibility_scope = _parse_optional_visibility_scope(payload.visibility_scope)
    source_program = _parse_optional_source_program(payload.source_program)

    if program_track is None:
        program_track = _infer_program_track(payload, inquiry_type)

    if visibility_scope is None:
        visibility_scope = DEFAULT_VISIBILITY_BY_TYPE[inquiry_type]

    if source_program is None:
        source_program = _derive_source_program(program_track, payload)

    return program_track, visibility_scope, source_program


def _filter_inquiries_by_scope(query, current_user: User):
    if current_user.role == UserRole.SUPER_ADMIN:
        return query

    not_super_admin_only = or_(
        PublicInquiry.visibility_scope.is_(None),
        PublicInquiry.visibility_scope != VisibilityScope.SUPER_ADMIN_ONLY.value,
    )

    if current_user.role == UserRole.TEAM_ADMIN_GLOBAL:
        return query.filter(
            and_(
                not_super_admin_only,
                or_(
                    PublicInquiry.program_track == ProgramTrack.NATIONAL_INTERNATIONAL.value,
                    PublicInquiry.visibility_scope.in_([
                        VisibilityScope.GLOBAL_ONLY.value,
                        VisibilityScope.GLOBAL_AND_LOCAL.value,
                    ]),
                ),
            )
        )

    if current_user.role == UserRole.TEAM_ADMIN_LOCAL:
        return query.filter(
            and_(
                not_super_admin_only,
                or_(
                    PublicInquiry.program_track.in_([
                        ProgramTrack.LOCAL_REGIONAL.value,
                        ProgramTrack.K12.value,
                    ]),
                    PublicInquiry.visibility_scope.in_([
                        VisibilityScope.LOCAL_ONLY.value,
                        VisibilityScope.GLOBAL_AND_LOCAL.value,
                    ]),
                ),
            )
        )

    return query.filter(False)


def _get_scoped_inquiry_or_404(inquiry_id: int, current_user: User, db: Session) -> PublicInquiry:
    inquiry = _filter_inquiries_by_scope(
        db.query(PublicInquiry).filter(PublicInquiry.id == inquiry_id),
        current_user,
    ).first()
    if not inquiry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inquiry not found")
    return inquiry


def _get_assignable_inquiry_user_or_400(user_id: int, current_user: User, db: Session) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user not found.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be active.")
    if user.role not in INQUIRY_ASSIGNABLE_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be an internal admin user.")

    if current_user.role == UserRole.SUPER_ADMIN:
        return user
    if current_user.role == UserRole.TEAM_ADMIN_GLOBAL:
        if user.role == UserRole.TEAM_ADMIN_GLOBAL and user.program_track in (None, ProgramTrack.NATIONAL_INTERNATIONAL):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assigned user outside your scope.")
    if current_user.role == UserRole.TEAM_ADMIN_LOCAL:
        if user.role == UserRole.TEAM_ADMIN_LOCAL and user.program_track in (None, ProgramTrack.LOCAL_REGIONAL, ProgramTrack.K12):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assigned user outside your scope.")

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


def _apply_public_inquiry_filters(
    query,
    search: str | None = None,
    status_filter: str | None = None,
    inquiry_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(
            PublicInquiry.full_name.ilike(term),
            PublicInquiry.email.ilike(term),
            PublicInquiry.phone.ilike(term),
            PublicInquiry.interest_area.ilike(term),
            PublicInquiry.message.ilike(term),
        ))
    if status_filter:
        query = query.filter(PublicInquiry.status == status_filter.strip().upper())
    if inquiry_type:
        query = query.filter(PublicInquiry.inquiry_type == _parse_inquiry_type(inquiry_type))
    if date_from:
        query = query.filter(PublicInquiry.created_at >= date_from)
    if date_to:
        query = query.filter(PublicInquiry.created_at <= date_to)
    return query


def _admin_notification_bodies(inquiry: PublicInquiry) -> tuple[str, str]:
    created_at = inquiry.created_at.isoformat() if inquiry.created_at else ""
    rows = [
        ("Full name", inquiry.full_name),
        ("Email", inquiry.email),
        ("Phone", inquiry.phone),
        ("Organization", inquiry.organization),
        ("Interest area", inquiry.interest_area),
        ("Message", inquiry.message),
        ("Created date", created_at),
    ]
    html_rows = "\n".join(
        f"<tr><th align=\"left\">{escape(label)}</th><td>{escape(str(value or ''))}</td></tr>"
        for label, value in rows
    )
    text_body = "\n".join(f"{label}: {value or ''}" for label, value in rows)
    html_body = f"""
    <html>
      <body>
        <h2>New {escape(inquiry.inquiry_type.value)} inquiry</h2>
        <table cellpadding="6" cellspacing="0" border="1">
          {html_rows}
        </table>
      </body>
    </html>
    """
    return html_body, text_body


def _submitter_confirmation_bodies(inquiry: PublicInquiry) -> tuple[str, str]:
    rows = [
        ("Inquiry type", inquiry.inquiry_type.value),
        ("Interest area", inquiry.interest_area),
        ("Message summary", inquiry.message),
    ]
    html_rows = "\n".join(
        f"<tr><th align=\"left\">{escape(label)}</th><td>{escape(str(value or ''))}</td></tr>"
        for label, value in rows
    )
    text_body = "\n".join(
        [
            f"Dear {inquiry.full_name},",
            "",
            "Thank you for contacting the NMF-IFIA Innovation Hub.",
            "",
            *[f"{label}: {value or ''}" for label, value in rows],
            "",
            "Our team will contact you soon.",
        ]
    )
    html_body = f"""
    <html>
      <body>
        <p>Dear {escape(inquiry.full_name)},</p>
        <p>Thank you for contacting the NMF-IFIA Innovation Hub.</p>
        <table cellpadding="6" cellspacing="0" border="1">
          {html_rows}
        </table>
        <p>Our team will contact you soon.</p>
      </body>
    </html>
    """
    return html_body, text_body


def _send_admin_notification_safely(inquiry: PublicInquiry) -> None:
    subject = f"New {inquiry.inquiry_type.value} inquiry - {inquiry.full_name}"
    html_body, text_body = _admin_notification_bodies(inquiry)
    logger.info("Sending admin inquiry notification: inquiry_id=%s, subject=%s", inquiry.id, subject)
    try:
        sent = send_public_inquiry_notification(
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            reply_to=inquiry.email,
        )
    except Exception:
        logger.exception("Admin inquiry notification failed: inquiry_id=%s", inquiry.id)
        return

    if sent:
        logger.info("Admin inquiry notification sent successfully: inquiry_id=%s", inquiry.id)
    else:
        logger.error("Admin inquiry notification was not sent: inquiry_id=%s", inquiry.id)


def _send_submitter_confirmation_safely(inquiry: PublicInquiry) -> None:
    if not inquiry.email:
        logger.info("Inquiry submitter confirmation skipped: inquiry_id=%s has no email", inquiry.id)
        return

    subject = "We received your inquiry - NMF-IFIA Innovation Hub"
    html_body, text_body = _submitter_confirmation_bodies(inquiry)
    logger.info(
        "Sending inquiry submitter confirmation: inquiry_id=%s, to_email=%s",
        inquiry.id,
        inquiry.email,
    )
    try:
        sent = send_applicant_email(
            to_email=inquiry.email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
    except Exception:
        logger.exception(
            "Inquiry submitter confirmation failed: inquiry_id=%s, to_email=%s",
            inquiry.id,
            inquiry.email,
        )
        return

    if sent:
        logger.info(
            "Inquiry submitter confirmation sent successfully: inquiry_id=%s, to_email=%s",
            inquiry.id,
            inquiry.email,
        )
    else:
        logger.error(
            "Inquiry submitter confirmation was not sent: inquiry_id=%s, to_email=%s",
            inquiry.id,
            inquiry.email,
        )


@router.post(
    "/public/inquiries",
    response_model=PublicInquiryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_public_inquiry(
    request: Request,
    payload: PublicInquiryCreate,
    db: Session = Depends(get_db),
):
    assert_rate_limit(
        request,
        "public-inquiry",
        settings.RATE_LIMIT_PUBLIC_INQUIRY_PER_HOUR,
        60 * 60,
        str(payload.email) if payload.email else None,
    )
    inquiry_type = _parse_inquiry_type(payload.inquiry_type)
    program_track, visibility_scope, source_program = _resolve_scope_fields(payload, inquiry_type)
    inquiry = PublicInquiry(
        inquiry_type=inquiry_type,
        full_name=payload.full_name,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
        organization=payload.organization,
        interest_area=payload.interest_area,
        message=payload.message,
        source_page=payload.source_page,
        program_track=program_track,
        visibility_scope=visibility_scope,
        source_program=source_program,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)

    _send_admin_notification_safely(inquiry)
    _send_submitter_confirmation_safely(inquiry)

    return inquiry


@router.get("/admin/inquiries", response_model=List[PublicInquiryOut])
def list_public_inquiries(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(PublicInquiry).order_by(PublicInquiry.created_at.desc())
    query = _filter_inquiries_by_scope(query, current_user)
    return query.all()


@router.get("/admin/inquiries/page", response_model=PaginatedResponse)
def list_public_inquiries_page(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    inquiry_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = _filter_inquiries_by_scope(db.query(PublicInquiry), current_user)
    query = _apply_public_inquiry_filters(
        query,
        search=search,
        status_filter=status_filter,
        inquiry_type=inquiry_type,
        date_from=date_from,
        date_to=date_to,
    )
    return paginate_query(
        query.order_by(PublicInquiry.created_at.desc()),
        limit,
        offset,
        transform=PublicInquiryOut.model_validate,
    )


@router.get("/admin/inquiries/{inquiry_id}", response_model=PublicInquiryOut)
def get_public_inquiry(
    inquiry_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _get_scoped_inquiry_or_404(inquiry_id, current_user, db)


@router.patch("/admin/inquiries/{inquiry_id}/assignment", response_model=PublicInquiryOut)
def update_public_inquiry_assignment(
    inquiry_id: int,
    payload: PublicInquiryAssignmentUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    inquiry = _get_scoped_inquiry_or_404(inquiry_id, current_user, db)
    old_assignee = inquiry.assigned_team_user_id

    if payload.assigned_team_user_id is None:
        inquiry.assigned_team_user_id = None
    else:
        assigned_user = _get_assignable_inquiry_user_or_400(
            payload.assigned_team_user_id,
            current_user,
            db,
        )
        inquiry.assigned_team_user_id = assigned_user.id

    record_audit_log(
        db,
        actor=current_user,
        action="public_inquiry_assignment_updated",
        entity_type="public_inquiry",
        entity_id=inquiry.id,
        entity_display_id=str(inquiry.id),
        old_values={"assigned_team_user_id": old_assignee},
        new_values={"assigned_team_user_id": inquiry.assigned_team_user_id},
        request=request,
    )
    db.commit()
    db.refresh(inquiry)
    return inquiry


@router.patch("/admin/inquiries/{inquiry_id}/status", response_model=PublicInquiryOut)
def update_public_inquiry_status(
    inquiry_id: int,
    payload: PublicInquiryStatusUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    inquiry = _get_scoped_inquiry_or_404(inquiry_id, current_user, db)

    normalized_status = payload.status.strip().upper()
    if not normalized_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must not be empty",
        )

    old_status = inquiry.status
    inquiry.status = normalized_status
    record_audit_log(
        db,
        actor=current_user,
        action="public_inquiry_status_updated",
        entity_type="public_inquiry",
        entity_id=inquiry.id,
        entity_display_id=str(inquiry.id),
        old_values={"status": old_status},
        new_values={"status": inquiry.status},
        request=request,
    )
    db.commit()
    db.refresh(inquiry)
    return inquiry
