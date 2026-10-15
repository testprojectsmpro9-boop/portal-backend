import logging
from html import escape

from app.config import settings
from app.models.user import User
from app.services.email_service import send_applicant_email

logger = logging.getLogger(__name__)


def _portal_login_url() -> str:
    return f"{settings.portal_base_url}/login"


def _user_created_body(user: User, plain_password: str) -> tuple[str, str]:
    track = user.program_track.value if user.program_track else "Not assigned"
    login_url = _portal_login_url()

    rows: list[tuple[str, str]] = [
        ("Full Name", user.full_name),
        ("Login Email", user.email),
        ("Temporary Password", plain_password),
        ("Assigned Role", user.role.value),
        ("Program Track", track),
        ("Portal Login URL", login_url),
    ]

    table_rows = "\n".join(
        f'<tr>'
        f'<th align="left" style="padding:8px;border:1px solid #ddd;white-space:nowrap">{escape(label)}</th>'
        f'<td style="padding:8px;border:1px solid #ddd;">{escape(value)}</td>'
        f'</tr>'
        for label, value in rows
    )
    table = (
        '<table cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;border:1px solid #ddd;">'
        f'{table_rows}</table>'
    )

    html = (
        "<html><body>"
        f"<p>Hello {escape(user.full_name)},</p>"
        "<p>Your NMF Innovation Hub portal account has been created.</p>"
        f"{table}"
        "<p>This is a temporary password. For security, please change this password after your first login.</p>"
        "<p>The platform may require you to change your password after login.</p>"
        "<p>Regards,<br>NMF Innovation Hub Team</p>"
        "</body></html>"
    )

    text_lines = [
        f"Hello {user.full_name},",
        "",
        "Your NMF Innovation Hub portal account has been created.",
        "",
    ]
    for label, value in rows:
        text_lines.append(f"{label}: {value}")
    text_lines.extend([
        "",
        "This is a temporary password.",
        "For security, please change this password after your first login.",
        "The platform may require you to change your password after login.",
        "",
        "Regards,",
        "NMF Innovation Hub Team",
    ])

    return html, "\n".join(text_lines)


def notify_user_created(user: User, plain_password: str) -> None:
    """Send portal access details to a newly created user. Never raises — logs on failure."""
    subject = "NMF Innovation Hub Portal Access Created"
    logger.info(
        "Sending portal access email: user_id=%s, email=%s, role=%s",
        user.id,
        user.email,
        user.role.value,
    )
    try:
        html_body, text_body = _user_created_body(user, plain_password)
        sent = send_applicant_email(
            to_email=user.email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
    except Exception:
        logger.exception(
            "Portal access email failed unexpectedly: user_id=%s, email=%s",
            user.id,
            user.email,
        )
        return

    if sent:
        logger.info(
            "Portal access email sent: user_id=%s, email=%s",
            user.id,
            user.email,
        )
    else:
        logger.warning(
            "Portal access email not sent (SMTP unconfigured?): user_id=%s, email=%s",
            user.id,
            user.email,
        )
