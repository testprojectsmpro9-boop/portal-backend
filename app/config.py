import sys
from pydantic_settings import BaseSettings
from pydantic import ValidationError
from typing import ClassVar, List


class Settings(BaseSettings):
    APP_NAME: str = "NMF-IFIA Innovation Hub API"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"

    DATABASE_URL: str

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    UPLOAD_DIR: str = "uploads"
    APPLICATION_ID_PREFIX: str = "IDEA"
    INTAKE_ID_PREFIX: str = "INTAKE"

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_FORGOT_PASSWORD_PER_15_MIN: int = 3
    RATE_LIMIT_RESET_PASSWORD_PER_15_MIN: int = 5
    RATE_LIMIT_REGISTER_PER_HOUR: int = 5
    RATE_LIMIT_PUBLIC_SUBMIT_PER_HOUR: int = 10
    RATE_LIMIT_PUBLIC_SUBMIT_WITH_FILES_PER_HOUR: int = 5
    RATE_LIMIT_TRACK_PER_HOUR: int = 20
    RATE_LIMIT_PUBLIC_INQUIRY_PER_HOUR: int = 10

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str | None = None
    SMTP_USE_SSL: bool = False
    SMTP_USE_TLS: bool = True
    SMTP_AUTH: bool = True

    SIRMV_SMTP_HOST: str | None = None
    SIRMV_SMTP_PORT: int = 587
    SIRMV_SMTP_USERNAME: str | None = None
    SIRMV_SMTP_PASSWORD: str | None = None
    SIRMV_SMTP_FROM: str | None = None
    SIRMV_SMTP_USE_SSL: bool = False
    SIRMV_SMTP_USE_TLS: bool = True
    SIRMV_SMTP_AUTH: bool = True

    ADMIN_NOTIFICATION_EMAIL: str | None = None
    INGENIOUSPARK_ADMIN_EMAIL: str | None = "ingeniouspace@gmail.com"
    SIRMV_ADMIN_EMAIL: str | None = "smvvisions@gmail.com"
    DEFAULT_ADMIN_NOTIFICATION_EMAIL: str | None = "ingeniouspace@gmail.com"
    PUBLIC_INQUIRY_NOTIFICATION_EMAIL: str | None = "ingeniouspace@gmail.com"
    PUBLIC_INQUIRY_EMAIL: str | None = "ingeniouspace@gmail.com"

    PORTAL_URL: str | None = None
    PUBLIC_SITE_URL: str | None = None

    LOCAL_PORTAL_URL: ClassVar[str] = "http://localhost:5174"
    PRODUCTION_PORTAL_URL: ClassVar[str] = "https://portal.ingeniouspark.in"

    # Production-safe defaults (always appended in any env).
    PRODUCTION_DEFAULT_ORIGINS: ClassVar[tuple[str, ...]] = (
        "https://ingeniouspark.in",
        "https://www.ingeniouspark.in",
        "https://portal.ingeniouspark.in",
        "https://portalbackend.ingeniouspark.in",
        "https://portal.sirmv-idea.org",
        "https://portalbackend.sirmv-idea.org",
    )
    # Dev-only defaults (appended ONLY when not production).
    DEVELOPMENT_DEFAULT_ORIGINS: ClassVar[tuple[str, ...]] = (
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
    )
    # Backwards-compat aggregate used in non-prod when ALLOWED_ORIGINS env not set.
    DEFAULT_ALLOWED_ORIGINS: ClassVar[tuple[str, ...]] = (
        *PRODUCTION_DEFAULT_ORIGINS,
        *DEVELOPMENT_DEFAULT_ORIGINS,
    )
    ALLOWED_ORIGINS: str = ",".join(DEFAULT_ALLOWED_ORIGINS)
    ALLOW_LOCAL_ORIGINS: bool = False

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() in {"production", "prod"}

    @property
    def portal_base_url(self) -> str:
        configured_url = (self.PORTAL_URL or "").strip().rstrip("/")
        if configured_url:
            return configured_url
        if self.is_production:
            return self.PRODUCTION_PORTAL_URL
        return self.LOCAL_PORTAL_URL

    @property
    def public_site_base_url(self) -> str:
        configured_url = (self.PUBLIC_SITE_URL or "").strip().rstrip("/")
        if configured_url:
            return configured_url
        return self.portal_base_url

    @property
    def allowed_origins_list(self) -> List[str]:
        configured_origins = [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]
        origins = [origin for origin in configured_origins if origin]

        # Always include production-safe defaults.
        for default_origin in self.PRODUCTION_DEFAULT_ORIGINS:
            if default_origin not in origins:
                origins.append(default_origin)

        # In production, strip localhost unless explicitly enabled for local
        # testing with a production-like config.
        if self.is_production and not self.ALLOW_LOCAL_ORIGINS:
            origins = [o for o in origins if "localhost" not in o and "127.0.0.1" not in o]
        else:
            for dev_origin in self.DEVELOPMENT_DEFAULT_ORIGINS:
                if dev_origin not in origins:
                    origins.append(dev_origin)

        return origins

    model_config = {"env_file": ".env", "extra": "ignore"}


try:
    settings = Settings()
except ValidationError as e:
    missing = [err["loc"][0] for err in e.errors() if err["type"] == "missing"]
    print("\n" + "=" * 60)
    print("  CONFIG ERROR: Missing required environment variables")
    print("=" * 60)
    for field in missing:
        print(f"  - {field} is not set")
    print()
    print("  Fix: create a .env file in the project root.")
    print("  Copy from .env.example:")
    print()
    print("    Copy-Item .env.example .env")
    print()
    print("  Then set these values in .env:")
    if "DATABASE_URL" in missing:
        print("    DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/nmfinventa_db")
    if "SECRET_KEY" in missing:
        print("    SECRET_KEY=your-long-random-secret-key-at-least-32-chars")
    print("=" * 60 + "\n")
    sys.exit(1)
