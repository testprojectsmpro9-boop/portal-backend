import logging
from html import escape
from typing import Any, Iterable, Optional

from app.models.idea import Idea
from app.models.intake import IntakeSubmission
from app.models.user import User
from app.config import settings
from app.services.email_service import get_admin_notification_recipient, send_admin_notification, send_applicant_email

logger = logging.getLogger(__name__)


def _display(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _table_html(rows: Iterable[tuple[str, Any]]) -> str:
    body = "\n".join(
        f"<tr><th align=\"left\" style=\"padding:8px;border:1px solid #ddd;\">{escape(label)}</th>"
        f"<td style=\"padding:8px;border:1px solid #ddd;\">{escape(_display(value))}</td></tr>"
        for label, value in rows
    )
    return (
        "<table cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"border-collapse:collapse;border:1px solid #ddd;\">"
        f"{body}</table>"
    )


def _text(rows: Iterable[tuple[str, Any]]) -> str:
    return "\n".join(f"{label}: {_display(value)}" for label, value in rows)


def _portal_login_url() -> str:
    return f"{settings.portal_base_url}/login"


def _track_url(application_id: str) -> str:
    return f"{settings.public_site_base_url}/track?application_id={application_id}"


def _idea_admin_rows(idea: Idea, timestamp_label: str) -> list[tuple[str, Any]]:
    return [
        ("Application ID", idea.application_id),
        ("Idea Title", idea.idea_title),
        ("Applicant Name", idea.applicant_name),
        ("Email", idea.email),
        ("Phone", idea.phone),
        ("Age", idea.age),
        ("Location", idea.location),
        ("Organization", idea.organization),
        ("Applicant Type", idea.applicant_type),
        ("Program Track", idea.program_track),
        ("Source Program", idea.source_program),
        ("Category", idea.category),
        ("Sub-category", idea.sub_category),
        ("Prototype Status", idea.prototype_status),
        ("Support Needed", idea.support_needed),
        (timestamp_label, idea.created_at),
    ]


def _admin_body(title: str, rows: list[tuple[str, Any]]) -> tuple[str, str]:
    html = (
        "<html><body>"
        f"<h2>{escape(title)}</h2>"
        f"{_table_html(rows)}"
        "</body></html>"
    )
    return html, _text(rows)


def _applicant_body(
    applicant_name: str,
    message: str,
    application_id: str,
    idea_title: str,
    date_label: str,
    submitted_at: Any,
    include_review_note: bool = True,
) -> tuple[str, str]:
    rows = [
        ("Application ID", application_id),
        ("Idea Title", idea_title),
        (date_label, submitted_at),
    ]
    review_note = (
        "<p>Our team will review your submission and update the status.</p>"
        if include_review_note
        else ""
    )
    html = (
        "<html><body>"
        f"<p>Dear {escape(applicant_name)},</p>"
        f"<p>{escape(message)}</p>"
        f"{_table_html(rows)}"
        "<p>You can track your application using your Application ID and registered email/phone.</p>"
        f"{review_note}"
        "</body></html>"
    )
    text_parts = [
        f"Dear {applicant_name},",
        "",
        message,
        "",
        _text(rows),
        "",
        "You can track your application using your Application ID and registered email/phone.",
    ]
    if include_review_note:
        text_parts.extend(["", "Our team will review your submission and update the status."])
    return html, "\n".join(text_parts)


def _send_admin_safely(
    subject: str,
    html_body: str,
    text_body: str,
    source_platform: str | None = None,
) -> None:
    logger.info("Sending admin idea notification: subject=%s", subject)
    try:
        sent = send_admin_notification(
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            source_platform=source_platform,
        )
    except Exception:
        logger.exception("Admin idea notification failed: subject=%s", subject)
        return

    if sent:
        logger.info("Admin idea notification sent successfully: subject=%s", subject)
    else:
        logger.error("Admin idea notification was not sent: subject=%s", subject)


def _send_applicant_safely(
    to_email: Optional[str],
    subject: str,
    html_body: str,
    text_body: str,
    source_platform: str | None = None,
    bcc: str | list[str] | tuple[str, ...] | None = None,
) -> None:
    if not to_email:
        logger.info("Applicant idea notification skipped: no applicant email for subject=%s", subject)
        return

    logger.info(
        "Sending applicant idea notification: subject=%s, to_email=%s",
        subject,
        to_email,
    )
    try:
        sent = send_applicant_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            bcc=bcc,
            source_platform=source_platform,
        )
    except Exception:
        logger.exception(
            "Applicant idea notification failed: subject=%s, to_email=%s",
            subject,
            to_email,
        )
        return

    if sent:
        logger.info(
            "Applicant idea notification sent successfully: subject=%s, to_email=%s",
            subject,
            to_email,
        )
    else:
        logger.error(
            "Applicant idea notification was not sent: subject=%s, to_email=%s",
            subject,
            to_email,
        )


def _source_label(idea: Idea) -> str:
    """Return a bracketed source label for admin notification subjects."""
    platform = _display(getattr(idea, "source_platform", None))
    if not platform:
        return ""
    label = {
        "ingeniouspark": "Ingeniouspark",
        "sirmv-idea": "SIR MV Idea",
        "admin-intake": "Admin Intake",
    }.get(platform, platform.replace("-", " ").replace("_", " ").title())
    return f"[{label}] "


def notify_public_idea_submission(idea: Idea) -> None:
    logger.info(
        "Preparing public idea submission notifications: application_id=%s, applicant_email=%s",
        idea.application_id,
        idea.email,
    )
    prefix = _source_label(idea)
    admin_rows = _idea_admin_rows(idea, "Created At")
    admin_html, admin_text = _admin_body(f"{prefix}New idea submitted", admin_rows)
    _send_admin_safely(
        subject=f"{prefix}New idea submitted - {idea.application_id}",
        html_body=admin_html,
        text_body=admin_text,
        source_platform=getattr(idea, "source_platform", None),
    )

    applicant_html, applicant_text = _applicant_body(
        applicant_name=idea.applicant_name,
        message="Thank you for submitting your idea to the NMF-IFIA system.",
        application_id=idea.application_id,
        idea_title=idea.idea_title,
        date_label="Submitted Date",
        submitted_at=idea.created_at,
    )
    _send_applicant_safely(
        to_email=idea.email,
        subject=f"Your idea has been submitted - {idea.application_id}",
        html_body=applicant_html,
        text_body=applicant_text,
        source_platform=getattr(idea, "source_platform", None),
    )


def notify_intake_conversion(idea: Idea, intake: IntakeSubmission) -> None:
    logger.info(
        "Preparing intake conversion notifications: application_id=%s, intake_id=%s, applicant_email=%s",
        idea.application_id,
        intake.intake_id,
        idea.email,
    )
    admin_rows = [
        ("Application ID", idea.application_id),
        ("Intake ID", intake.intake_id),
        ("Idea Title", idea.idea_title),
        ("Applicant Name", idea.applicant_name),
        ("Email", idea.email),
        ("Phone", idea.phone),
        ("Age", idea.age),
        ("Location", idea.location),
        ("Organization", idea.organization),
        ("Applicant Type", idea.applicant_type),
        ("Program Track", idea.program_track),
        ("Source Program", idea.source_program),
        ("Category", idea.category),
        ("Sub-category", idea.sub_category),
        ("Prototype Status", idea.prototype_status),
        ("Support Needed", idea.support_needed),
        ("Converted At", idea.created_at),
    ]
    admin_html, admin_text = _admin_body("[Admin Intake] Offline intake converted to idea", admin_rows)
    _send_admin_safely(
        subject=f"[Admin Intake] Offline intake converted to idea - {idea.application_id}",
        html_body=admin_html,
        text_body=admin_text,
        source_platform=getattr(idea, "source_platform", None),
    )

    applicant_html, applicant_text = _applicant_body(
        applicant_name=idea.applicant_name,
        message="Your offline form/entry has been registered in the NMF-IFIA system.",
        application_id=idea.application_id,
        idea_title=idea.idea_title,
        date_label="Submitted/Registered Date",
        submitted_at=idea.created_at,
        include_review_note=False,
    )
    _send_applicant_safely(
        to_email=idea.email,
        subject=f"Your offline idea entry has been registered - {idea.application_id}",
        html_body=applicant_html,
        text_body=applicant_text,
        source_platform=getattr(idea, "source_platform", None),
    )


def notify_idea_status_update(idea: Idea, new_status: str, public_message: str | None = None) -> None:
    message = public_message or "Your idea status has been updated."
    rows = [
        ("Application ID", idea.application_id),
        ("Idea Title", idea.idea_title),
        ("New Status", new_status),
        ("Track Idea", _track_url(idea.application_id)),
    ]
    html = (
        "<html><body>"
        f"<p>Dear {escape(idea.applicant_name)},</p>"
        f"<p>{escape(message)}</p>"
        f"{_table_html(rows)}"
        "</body></html>"
    )
    text_body = "\n".join([
        f"Dear {idea.applicant_name},",
        "",
        message,
        "",
        _text(rows),
    ])
    _send_applicant_safely(
        to_email=idea.email,
        subject=f"Idea status updated - {idea.application_id}",
        html_body=html,
        text_body=text_body,
        source_platform=getattr(idea, "source_platform", None),
        bcc=get_admin_notification_recipient(getattr(idea, "source_platform", None)),
    )


def notify_jury_assignment(idea: Idea, jury_user: User) -> None:
    rows = [
        ("Application ID", idea.application_id),
        ("Idea Title", idea.idea_title),
        ("Portal Login URL", _portal_login_url()),
    ]
    html = (
        "<html><body>"
        f"<p>Hello {escape(jury_user.full_name)},</p>"
        "<p>You have been assigned an idea for review.</p>"
        f"{_table_html(rows)}"
        "<p>Please sign in to the portal to view the assigned idea and submit your review.</p>"
        "</body></html>"
    )
    text_body = "\n".join([
        f"Hello {jury_user.full_name},",
        "",
        "You have been assigned an idea for review.",
        "",
        _text(rows),
        "",
        "Please sign in to the portal to view the assigned idea and submit your review.",
    ])
    _send_applicant_safely(
        to_email=jury_user.email,
        subject=f"Jury review assigned - {idea.application_id}",
        html_body=html,
        text_body=text_body,
        source_platform=getattr(idea, "source_platform", None),
    )


def notify_jury_assignment_status(idea: Idea, jury_user: User, review_status: str) -> None:
    rows = [
        ("Application ID", idea.application_id),
        ("Idea Title", idea.idea_title),
        ("Assignment Status", review_status),
        ("Portal Login URL", _portal_login_url()),
    ]
    html = (
        "<html><body>"
        f"<p>Hello {escape(jury_user.full_name)},</p>"
        "<p>Your jury assignment status has been updated.</p>"
        f"{_table_html(rows)}"
        "</body></html>"
    )
    text_body = "\n".join([
        f"Hello {jury_user.full_name},",
        "",
        "Your jury assignment status has been updated.",
        "",
        _text(rows),
    ])
    _send_applicant_safely(
        to_email=jury_user.email,
        subject=f"Jury assignment updated - {idea.application_id}",
        html_body=html,
        text_body=text_body,
        source_platform=getattr(idea, "source_platform", None),
    )


def notify_jury_review_completed(idea: Idea, jury_user: User) -> None:
    rows = [
        ("Application ID", idea.application_id),
        ("Idea Title", idea.idea_title),
        ("Jury Name", jury_user.full_name),
        ("Portal Login URL", _portal_login_url()),
    ]
    html, text_body = _admin_body("Jury review submitted", rows)
    _send_admin_safely(
        subject=f"Jury review submitted - {idea.application_id}",
        html_body=html,
        text_body=text_body,
    )
