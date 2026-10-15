import logging
from datetime import datetime
from html import escape
from urllib.parse import quote

from app.config import settings
from app.models.user import User
from app.services.email_service import send_applicant_email

logger = logging.getLogger(__name__)

PASSWORD_RESET_SUBJECT = "Reset your NMF Innovation Hub portal password"


def _portal_reset_url(token: str) -> str:
    return f"{settings.portal_base_url}/reset-password?token={quote(token)}"


def _password_reset_body(user: User, reset_link: str, expires_at: datetime) -> tuple[str, str]:
    html = (
        "<html><body>"
        f"<p>Hello {escape(user.full_name)},</p>"
        "<p>We received a request to reset your NMF Innovation Hub portal password.</p>"
        "<p>Click the link below to set a new password:</p>"
        f'<p><a href="{escape(reset_link)}">{escape(reset_link)}</a></p>'
        "<p>This link will expire in 30 minutes.</p>"
        "<p>If you did not request this, you can ignore this email.</p>"
        "<p>Regards,<br>NMF Innovation Hub Team</p>"
        "</body></html>"
    )
    text = "\n".join([
        f"Hello {user.full_name},",
        "",
        "We received a request to reset your NMF Innovation Hub portal password.",
        "",
        "Click the link below to set a new password:",
        reset_link,
        "",
        "This link will expire in 30 minutes.",
        "",
        "If you did not request this, you can ignore this email.",
        "",
        "Regards,",
        "NMF Innovation Hub Team",
    ])
    return html, text


def send_password_reset_email(user: User, raw_token: str, expires_at: datetime) -> bool:
    """Send password reset instructions. Never raises; logs safe context on failure."""
    reset_link = _portal_reset_url(raw_token)
    try:
        html_body, text_body = _password_reset_body(user, reset_link, expires_at)
        sent = send_applicant_email(
            to_email=user.email,
            subject=PASSWORD_RESET_SUBJECT,
            html_body=html_body,
            text_body=text_body,
        )
    except Exception:
        logger.exception(
            "Password reset email failed unexpectedly: user_id=%s, email=%s",
            user.id,
            user.email,
        )
        return False

    if not sent:
        logger.warning(
            "Password reset email not sent (SMTP unconfigured?): user_id=%s, email=%s",
            user.id,
            user.email,
        )
    return sent
