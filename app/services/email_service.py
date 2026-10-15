import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional
from urllib.parse import parse_qs, urlparse

from app.config import settings

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _configured_email(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _setting(name: str, default=None):
    return getattr(settings, name, default)


def _setting_bool(name: str, default: bool = False) -> bool:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _setting_int(name: str, default: int) -> int:
    value = getattr(settings, name, default)
    try:
        return int(value)
    except Exception:
        return default


def _normalize_source(value: str | None) -> str:
    """
    Normalizes source values like:
    - sirmv-idea
    - SIRMV_IDEA
    - https://sirmv-idea.org/ideathon/
    - https://ingeniouspark.in/submit-idea?source_platform=sirmv-idea
    """
    if not value:
        return ""

    raw = str(value).strip().lower()
    raw = raw.replace("_", "-").replace(" ", "-")

    # If a full URL is passed, inspect domain, path and query params also.
    try:
        parsed = urlparse(raw)

        parts: list[str] = []

        if parsed.netloc:
            parts.append(parsed.netloc)

        if parsed.path:
            parts.append(parsed.path)

        if parsed.query:
            query = parse_qs(parsed.query)
            for key in ["source_platform", "source", "partner", "ref", "utm_source"]:
                for item in query.get(key, []):
                    if item:
                        parts.append(item)

        if parts:
            raw = "-".join(parts)
    except Exception:
        pass

    raw = raw.replace("_", "-").replace(" ", "-")
    raw = re.sub(r"[^a-z0-9@.\-]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")

    return raw


# ── Sender profile ────────────────────────────────────────────────────────────

@dataclass
class SmtpProfile:
    host: str
    port: int
    username: str | None
    password: str | None
    from_addr: str
    use_ssl: bool
    use_tls: bool
    auth: bool
    profile_name: str


def is_sirmv_source(source_platform: str | None) -> bool:
    """
    Return True when source_platform/source/referrer indicates a SIRMV/SMV origin.

    Supports:
    - sirmv-idea
    - sirmv
    - smvvisions
    - smvvisions@gmail.com
    - sirmv-idea.org
    - full submit URL with ?source_platform=sirmv-idea
    """
    normalized = _normalize_source(source_platform)

    if not normalized:
        return False

    exact_matches = {
        "sirmv-idea",
        "sirmv",
        "sir-mv",
        "sir-mv-idea",
        "sir-m-visvesvaraya",
        "smv",
        "smvvisions",
        "smv-visions",
        "smvvisions@gmail.com",

        # Common typo support, because sometimes it is typed like this
        "smvvisons",
        "smvvisons@gmail.com",

        "sirmv-idea.org",
        "www.sirmv-idea.org",
    }

    if normalized in exact_matches:
        return True

    strong_indicators = [
        "sirmv-idea",
        "sir-mv",
        "smvvisions",
        "smvvisons",
        "sirmv-idea.org",
    ]

    return any(indicator in normalized for indicator in strong_indicators)


def get_sender_profile(source_platform: str | None) -> SmtpProfile:
    """
    Return the SMTP profile for the given source_platform.

    SIRMV sources use the dedicated Gmail profile:
    - SIRMV_SMTP_HOST
    - SIRMV_SMTP_PORT
    - SIRMV_SMTP_USERNAME
    - SIRMV_SMTP_PASSWORD
    - SIRMV_SMTP_FROM
    - SIRMV_SMTP_USE_SSL
    - SIRMV_SMTP_USE_TLS
    - SIRMV_SMTP_AUTH

    Everything else uses the default Ingeniouspark SMTP profile.

    If SIRMV profile is not configured properly, it falls back to default SMTP.
    """
    source_is_sirmv = is_sirmv_source(source_platform)

    if source_is_sirmv:
        sirmv_host = (_setting("SIRMV_SMTP_HOST", "") or "").strip()
        sirmv_from = (_setting("SIRMV_SMTP_FROM", "") or "").strip()
        sirmv_username = (_setting("SIRMV_SMTP_USERNAME", "") or "").strip()
        sirmv_password = _setting("SIRMV_SMTP_PASSWORD", None)

        if sirmv_host and sirmv_from:
            return SmtpProfile(
                host=sirmv_host,
                port=_setting_int("SIRMV_SMTP_PORT", 587),
                username=sirmv_username or sirmv_from,
                password=sirmv_password,
                from_addr=sirmv_from,
                use_ssl=_setting_bool("SIRMV_SMTP_USE_SSL", False),
                use_tls=_setting_bool("SIRMV_SMTP_USE_TLS", True),
                auth=_setting_bool("SIRMV_SMTP_AUTH", True),
                profile_name="sirmv",
            )

        logger.warning(
            "SIRMV source detected but SIRMV SMTP profile is incomplete. "
            "source_platform=%s, SIRMV_SMTP_HOST=%s, SIRMV_SMTP_FROM=%s. "
            "Falling back to default SMTP.",
            source_platform,
            bool(sirmv_host),
            bool(sirmv_from),
        )

    default_host = (_setting("SMTP_HOST", "") or "").strip()
    default_from = (_setting("SMTP_FROM", "") or "").strip()
    default_username = (_setting("SMTP_USERNAME", "") or "").strip()
    default_password = _setting("SMTP_PASSWORD", None)

    return SmtpProfile(
        host=default_host,
        port=_setting_int("SMTP_PORT", 587),
        username=default_username or default_from,
        password=default_password,
        from_addr=default_from,
        use_ssl=_setting_bool("SMTP_USE_SSL", False),
        use_tls=_setting_bool("SMTP_USE_TLS", True),
        auth=_setting_bool("SMTP_AUTH", True),
        profile_name="default",
    )


# ── Admin recipient routing ───────────────────────────────────────────────────

def get_admin_notification_recipient(source_platform: str | None) -> str | None:
    default_recipient = (
        _configured_email(_setting("DEFAULT_ADMIN_NOTIFICATION_EMAIL", None))
        or _configured_email(_setting("ADMIN_NOTIFICATION_EMAIL", None))
    )

    ingeniouspark_recipient = (
        _configured_email(_setting("INGENIOUSPARK_ADMIN_EMAIL", None))
        or default_recipient
    )

    sirmv_recipient = (
        _configured_email(_setting("SIRMV_ADMIN_EMAIL", None))
        or default_recipient
    )

    platform = _normalize_source(source_platform)

    if is_sirmv_source(source_platform):
        return sirmv_recipient

    if platform == "ingeniouspark":
        return ingeniouspark_recipient

    if platform == "admin-intake":
        return ingeniouspark_recipient or default_recipient

    return default_recipient


# ── Core send function ────────────────────────────────────────────────────────

def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    reply_to: str | None = None,
    bcc: str | list[str] | tuple[str, ...] | None = None,
    source_platform: str | None = None,
) -> bool:
    to_email = _configured_email(to)

    if not to_email:
        logger.warning(
            "Email not sent: recipient email is empty. subject=%s, source_platform=%s",
            subject,
            source_platform,
        )
        return False

    profile = get_sender_profile(source_platform)

    if not profile.host or not profile.from_addr:
        logger.warning(
            "Email not sent: SMTP host or FROM address not configured. "
            "profile=%s, source_platform=%s, host_configured=%s, from_configured=%s",
            profile.profile_name,
            source_platform,
            bool(profile.host),
            bool(profile.from_addr),
        )
        return False

    if profile.auth and (not profile.username or not profile.password):
        logger.warning(
            "Email not sent: SMTP auth enabled but username/password missing. "
            "profile=%s, source_platform=%s, username_configured=%s, password_configured=%s",
            profile.profile_name,
            source_platform,
            bool(profile.username),
            bool(profile.password),
        )
        return False

    message = EmailMessage()
    message["From"] = profile.from_addr
    message["To"] = to_email
    message["Subject"] = subject

    cleaned_reply_to = _configured_email(reply_to)
    if cleaned_reply_to:
        message["Reply-To"] = cleaned_reply_to

    bcc_recipients: list[str] = []

    if isinstance(bcc, str):
        cleaned_bcc = _configured_email(bcc)
        if cleaned_bcc:
            bcc_recipients.append(cleaned_bcc)
    elif bcc:
        bcc_recipients = [
            email
            for item in bcc
            if (email := _configured_email(item))
        ]

    message.set_content(
        text_body or "Please view this email in an HTML-compatible client."
    )
    message.add_alternative(html_body, subtype="html")

    logger.info(
        "Sending email: profile=%s, to=%s, subject=%s, reply_to=%s, "
        "bcc_count=%s, smtp_host=%s, smtp_port=%s, ssl=%s, tls=%s, "
        "auth=%s, from=%s, source_platform=%s, normalized_source=%s, is_sirmv=%s",
        profile.profile_name,
        to_email,
        subject,
        cleaned_reply_to,
        len(bcc_recipients),
        profile.host,
        profile.port,
        profile.use_ssl,
        profile.use_tls,
        profile.auth,
        profile.from_addr,
        source_platform,
        _normalize_source(source_platform),
        is_sirmv_source(source_platform),
    )

    try:
        context = ssl.create_default_context()

        if profile.use_ssl:
            with smtplib.SMTP_SSL(
                profile.host,
                profile.port,
                timeout=15,
                context=context,
            ) as smtp:
                if profile.auth:
                    smtp.login(profile.username, profile.password)
                smtp.send_message(message, to_addrs=[to_email, *bcc_recipients])
        else:
            with smtplib.SMTP(profile.host, profile.port, timeout=15) as smtp:
                smtp.ehlo()
                if profile.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if profile.auth:
                    smtp.login(profile.username, profile.password)
                smtp.send_message(message, to_addrs=[to_email, *bcc_recipients])

        logger.info(
            "Email sent successfully: profile=%s, to=%s, subject=%s, source_platform=%s",
            profile.profile_name,
            to_email,
            subject,
            source_platform,
        )
        return True

    except Exception as exc:
        logger.exception(
            "Failed to send email: profile=%s, to=%s, subject=%s, "
            "source_platform=%s, normalized_source=%s, error=%s",
            profile.profile_name,
            to_email,
            subject,
            source_platform,
            _normalize_source(source_platform),
            exc,
        )
        return False


# ── Convenience wrappers ──────────────────────────────────────────────────────

def send_admin_notification(
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    source_platform: str | None = None,
) -> bool:
    recipient = get_admin_notification_recipient(source_platform)

    if not recipient:
        logger.warning(
            "Admin notification not sent: no admin recipient configured. "
            "source_platform=%s, normalized_source=%s, is_sirmv=%s",
            source_platform,
            _normalize_source(source_platform),
            is_sirmv_source(source_platform),
        )
        return False

    return send_email(
        recipient,
        subject,
        html_body,
        text_body,
        source_platform=source_platform,
    )


def send_applicant_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    bcc: str | list[str] | tuple[str, ...] | None = None,
    source_platform: str | None = None,
) -> bool:
    return send_email(
        to_email,
        subject,
        html_body,
        text_body,
        bcc=bcc,
        source_platform=source_platform,
    )


def get_public_inquiry_recipient() -> str | None:
    return (
        _configured_email(_setting("PUBLIC_INQUIRY_NOTIFICATION_EMAIL", None))
        or _configured_email(_setting("PUBLIC_INQUIRY_EMAIL", None))
    )


def send_public_inquiry_notification(
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    reply_to: str | None = None,
) -> bool:
    recipient = get_public_inquiry_recipient()

    if not recipient:
        logger.warning("Public inquiry notification not sent: no recipient configured.")
        return False

    # Public inquiries always use the default Ingeniouspark SMTP profile.
    return send_email(
        recipient,
        subject,
        html_body,
        text_body,
        reply_to=reply_to,
    )