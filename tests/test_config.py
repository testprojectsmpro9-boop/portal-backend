from app.config import Settings, settings
from app.services.email_service import (
    get_admin_notification_recipient,
    get_public_inquiry_recipient,
    send_email,
)


def test_settings_has_app_name():
    assert settings.APP_NAME is not None
    assert len(settings.APP_NAME) > 0


def test_settings_has_database_url():
    assert settings.DATABASE_URL is not None
    assert "postgresql" in settings.DATABASE_URL or "sqlite" in settings.DATABASE_URL


def test_settings_has_secret_key():
    assert settings.SECRET_KEY is not None
    assert len(settings.SECRET_KEY) >= 8


def test_production_email_links_use_live_portal_fallback():
    production_settings = Settings(
        APP_ENV="production",
        DATABASE_URL="sqlite:///test.db",
        SECRET_KEY="test-secret-key",
        PORTAL_URL=None,
        PUBLIC_SITE_URL=None,
    )

    assert production_settings.portal_base_url == "https://portal.ingeniouspark.in"
    assert production_settings.public_site_base_url == "https://portal.ingeniouspark.in"


def test_portal_base_url_uses_configured_portal_url():
    configured_settings = Settings(
        APP_ENV="production",
        DATABASE_URL="sqlite:///test.db",
        SECRET_KEY="test-secret-key",
        PORTAL_URL="https://portal.ingeniouspark.in/",
        PUBLIC_SITE_URL=None,
    )

    assert configured_settings.portal_base_url == "https://portal.ingeniouspark.in"


def test_development_email_links_use_local_portal_fallback():
    development_settings = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///test.db",
        SECRET_KEY="test-secret-key",
        PORTAL_URL=None,
        PUBLIC_SITE_URL=None,
    )

    assert development_settings.portal_base_url == "http://localhost:5174"
    assert development_settings.public_site_base_url == "http://localhost:5174"


def test_production_strips_local_origins_by_default():
    production_settings = Settings(
        APP_ENV="production",
        DATABASE_URL="sqlite:///test.db",
        SECRET_KEY="test-secret-key",
        ALLOW_LOCAL_ORIGINS=False,
        ALLOWED_ORIGINS="https://portal.ingeniouspark.in,http://localhost:5173",
    )

    assert "https://portal.ingeniouspark.in" in production_settings.allowed_origins_list
    assert "http://localhost:5173" not in production_settings.allowed_origins_list


def test_production_can_allow_local_origins_for_local_testing():
    production_like_local_settings = Settings(
        APP_ENV="production",
        DATABASE_URL="sqlite:///test.db",
        SECRET_KEY="test-secret-key",
        ALLOW_LOCAL_ORIGINS=True,
        ALLOWED_ORIGINS="https://portal.ingeniouspark.in,http://localhost:5173",
    )

    assert "https://portal.ingeniouspark.in" in production_like_local_settings.allowed_origins_list
    assert "http://localhost:5173" in production_like_local_settings.allowed_origins_list


def test_source_based_admin_notification_recipient_routes(monkeypatch):
    monkeypatch.setattr(settings, "INGENIOUSPARK_ADMIN_EMAIL", "ingenious@example.com")
    monkeypatch.setattr(settings, "SIRMV_ADMIN_EMAIL", "sirmv@example.com")
    monkeypatch.setattr(settings, "DEFAULT_ADMIN_NOTIFICATION_EMAIL", "default@example.com")
    monkeypatch.setattr(settings, "ADMIN_NOTIFICATION_EMAIL", "legacy@example.com")

    assert get_admin_notification_recipient("ingeniouspark") == "ingenious@example.com"
    assert get_admin_notification_recipient("sirmv-idea") == "sirmv@example.com"
    assert get_admin_notification_recipient("admin-intake") == "ingenious@example.com"
    assert get_admin_notification_recipient(None) == "default@example.com"
    assert get_admin_notification_recipient("unknown") == "default@example.com"


def test_live_support_email_config_loads_with_password_present_masked():
    configured = Settings(
        APP_ENV="production",
        DATABASE_URL="sqlite:///test.db",
        SECRET_KEY="test-secret-key",
        SMTP_HOST="mail.ingeniouspark.in",
        SMTP_PORT=465,
        SMTP_FROM="support@ingeniouspark.in",
        SMTP_USERNAME="support@ingeniouspark.in",
        SMTP_PASSWORD="configured-secret",
        SMTP_USE_SSL=True,
        SMTP_USE_TLS=False,
        SMTP_AUTH=True,
        PORTAL_URL="https://portal.ingeniouspark.in",
        INGENIOUSPARK_ADMIN_EMAIL="ingeniouspace@gmail.com",
        SIRMV_ADMIN_EMAIL="smvvisions@gmail.com",
        DEFAULT_ADMIN_NOTIFICATION_EMAIL="ingeniouspace@gmail.com",
        PUBLIC_INQUIRY_NOTIFICATION_EMAIL="support@ingeniouspark.in",
        PUBLIC_INQUIRY_EMAIL="support@ingeniouspark.in",
    )

    assert configured.SMTP_HOST == "mail.ingeniouspark.in"
    assert configured.SMTP_PORT == 465
    assert configured.SMTP_FROM == "support@ingeniouspark.in"
    assert configured.SMTP_USERNAME == "support@ingeniouspark.in"
    assert bool(configured.SMTP_PASSWORD) is True
    assert configured.SMTP_USE_SSL is True
    assert configured.SMTP_USE_TLS is False
    assert configured.SMTP_AUTH is True
    assert configured.portal_base_url == "https://portal.ingeniouspark.in"
    assert configured.INGENIOUSPARK_ADMIN_EMAIL == "ingeniouspace@gmail.com"
    assert configured.SIRMV_ADMIN_EMAIL == "smvvisions@gmail.com"
    assert configured.DEFAULT_ADMIN_NOTIFICATION_EMAIL == "ingeniouspace@gmail.com"
    assert configured.PUBLIC_INQUIRY_NOTIFICATION_EMAIL == "support@ingeniouspark.in"
    assert configured.PUBLIC_INQUIRY_EMAIL == "support@ingeniouspark.in"


def test_public_inquiry_recipient_uses_support_notification_inbox(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_INQUIRY_NOTIFICATION_EMAIL", "support@ingeniouspark.in")
    monkeypatch.setattr(settings, "PUBLIC_INQUIRY_EMAIL", "legacy-inquiries@example.com")

    assert get_public_inquiry_recipient() == "support@ingeniouspark.in"


def test_public_inquiry_recipient_falls_back_to_legacy_inquiry_email(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_INQUIRY_NOTIFICATION_EMAIL", "")
    monkeypatch.setattr(settings, "PUBLIC_INQUIRY_EMAIL", "legacy-inquiries@example.com")

    assert get_public_inquiry_recipient() == "legacy-inquiries@example.com"


def test_admin_notification_recipient_falls_back_to_legacy_admin_email(monkeypatch):
    monkeypatch.setattr(settings, "INGENIOUSPARK_ADMIN_EMAIL", "")
    monkeypatch.setattr(settings, "SIRMV_ADMIN_EMAIL", "")
    monkeypatch.setattr(settings, "DEFAULT_ADMIN_NOTIFICATION_EMAIL", "")
    monkeypatch.setattr(settings, "ADMIN_NOTIFICATION_EMAIL", "legacy@example.com")

    assert get_admin_notification_recipient("ingeniouspark") == "legacy@example.com"
    assert get_admin_notification_recipient("sirmv-idea") == "legacy@example.com"
    assert get_admin_notification_recipient(None) == "legacy@example.com"


def test_email_logging_does_not_expose_smtp_password(monkeypatch, caplog):
    secret = "super-secret-app-password"
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "SMTP_FROM", None)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", secret)

    send_email("recipient@example.com", "Subject", "<p>Hello</p>")

    assert secret not in caplog.text


def test_send_email_uses_smtp_ssl_without_starttls_for_ssl_config(monkeypatch):
    events = []

    class FakeSMTP:
        def __init__(self, host, port, timeout, **kwargs):
            events.append(("connect_ssl", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            events.append(("starttls",))

        def login(self, username, password):
            events.append(("login", username, bool(password)))

        def send_message(self, message, to_addrs):
            events.append(("send_message", message["To"], message["Reply-To"], tuple(to_addrs)))

    monkeypatch.setattr(settings, "SMTP_HOST", "mail.ingeniouspark.in")
    monkeypatch.setattr(settings, "SMTP_PORT", 465)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "support@ingeniouspark.in")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "configured-secret")
    monkeypatch.setattr(settings, "SMTP_FROM", "support@ingeniouspark.in")
    monkeypatch.setattr(settings, "SMTP_USE_SSL", True)
    monkeypatch.setattr(settings, "SMTP_USE_TLS", False)
    monkeypatch.setattr(settings, "SMTP_AUTH", True)
    monkeypatch.setattr("app.services.email_service.smtplib.SMTP_SSL", FakeSMTP)

    assert send_email(
        "support@ingeniouspark.in",
        "Subject",
        "<p>Hello</p>",
        text_body="Hello",
        reply_to="applicant@example.com",
    ) is True

    assert ("connect_ssl", "mail.ingeniouspark.in", 465, 15) in events
    assert ("starttls",) not in events
    assert ("login", "support@ingeniouspark.in", True) in events
    assert ("send_message", "support@ingeniouspark.in", "applicant@example.com", ("support@ingeniouspark.in",)) in events
