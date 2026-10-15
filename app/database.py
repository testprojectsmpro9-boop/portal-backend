import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.exc import OperationalError
from app.config import settings

logger = logging.getLogger(__name__)


engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def test_connection() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection successful.")
    except OperationalError as e:
        logger.error("=" * 60)
        logger.error("  DATABASE CONNECTION FAILED")
        logger.error("=" * 60)
        logger.error("  Could not connect to PostgreSQL.")
        logger.error("  Check that:")
        logger.error("    1. PostgreSQL is running")
        logger.error("    2. DATABASE_URL in .env is correct")
        logger.error("    3. Database exists (CREATE DATABASE nmfinventa_db;)")
        logger.error(f"  Error: {e}")
        logger.error("=" * 60)
        raise


def create_tables() -> None:
    # WARNING: Do NOT call this on app startup.
    # Schema is owned by Alembic. create_all() cannot create PostgreSQL enum types
    # (pathwaystage, intakestatus, etc.) that migrations define — it will raise
    # UndefinedObject errors. This function is kept only for isolated unit test
    # fixtures that spin up a fresh SQLite/mock DB without Alembic.
    import app.models.user           # noqa: F401
    import app.models.idea           # noqa: F401
    import app.models.message        # noqa: F401
    import app.models.jury           # noqa: F401
    import app.models.evaluation     # noqa: F401
    import app.models.decision       # noqa: F401
    import app.models.status_history # noqa: F401
    import app.models.public_inquiry # noqa: F401
    import app.models.audit_log      # noqa: F401
    import app.models.file_access_log # noqa: F401
    import app.models.intake_file    # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready (dev/test use only).")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
