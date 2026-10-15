from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User, UserRole
from app.routers.auth import _hash_reset_token
from app.utils.security import hash_password, verify_password


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, PasswordResetToken.__table__])

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestingSessionLocal


def _clear_overrides():
    app.dependency_overrides.clear()


def _seed_user(db_session_factory, email="portal-user@example.com", password="OldPass123!", is_active=True):
    db = db_session_factory()
    try:
        user = User(
            full_name="Portal User",
            email=email,
            phone="1234567890",
            password_hash=hash_password(password),
            role=UserRole.INVENTOR,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id, user.password_hash
    finally:
        db.close()


def _seed_reset_token(db_session_factory, user_id, raw_token, expires_at, used_at=None):
    db = db_session_factory()
    try:
        token = PasswordResetToken(
            user_id=user_id,
            token_hash=_hash_reset_token(raw_token),
            expires_at=expires_at,
            used_at=used_at,
        )
        db.add(token)
        db.commit()
        db.refresh(token)
        return token.id
    finally:
        db.close()


def test_forgot_password_returns_generic_success_for_existing_email(client, monkeypatch):
    db_session_factory = _session_factory()
    sent_tokens: list[str] = []
    try:
        _seed_user(db_session_factory)
        monkeypatch.setattr(
            "app.routers.auth.send_password_reset_email",
            lambda user, raw_token, expires_at: sent_tokens.append(raw_token) or True,
        )

        response = client.post("/api/v1/auth/forgot-password", json={"email": "portal-user@example.com"})

        assert response.status_code == 200
        assert response.json() == {"message": "If an account exists, a reset link has been sent."}
        assert len(sent_tokens) == 1
        assert "password_hash" not in response.text
    finally:
        _clear_overrides()


def test_forgot_password_returns_generic_success_for_unknown_email(client, monkeypatch):
    db_session_factory = _session_factory()
    sent_tokens: list[str] = []
    try:
        monkeypatch.setattr(
            "app.routers.auth.send_password_reset_email",
            lambda user, raw_token, expires_at: sent_tokens.append(raw_token) or True,
        )

        response = client.post("/api/v1/auth/forgot-password", json={"email": "missing@example.com"})

        assert response.status_code == 200
        assert response.json() == {"message": "If an account exists, a reset link has been sent."}
        assert sent_tokens == []
        assert "password_hash" not in response.text
    finally:
        _clear_overrides()


def test_reset_password_succeeds_with_valid_token_and_changes_hash(client, monkeypatch):
    db_session_factory = _session_factory()
    sent_tokens: list[str] = []
    try:
        user_id, old_hash = _seed_user(db_session_factory)
        monkeypatch.setattr(
            "app.routers.auth.send_password_reset_email",
            lambda user, raw_token, expires_at: sent_tokens.append(raw_token) or True,
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "portal-user@example.com"})

        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": sent_tokens[0],
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
        )

        assert response.status_code == 200
        assert response.json() == {"message": "Password has been reset successfully."}
        assert "password_hash" not in response.text

        db = db_session_factory()
        try:
            user = db.query(User).filter(User.id == user_id).one()
            token = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).one()
            assert user.password_hash != old_hash
            assert verify_password("NewPass123!", user.password_hash)
            assert token.used_at is not None
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_reset_password_rejects_expired_token(client):
    db_session_factory = _session_factory()
    try:
        user_id, _ = _seed_user(db_session_factory)
        _seed_reset_token(db_session_factory, user_id, "expired-token", datetime.utcnow() - timedelta(minutes=1))

        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "expired-token",
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
        )

        assert response.status_code == 400
    finally:
        _clear_overrides()


def test_reset_password_rejects_used_token(client):
    db_session_factory = _session_factory()
    try:
        user_id, _ = _seed_user(db_session_factory)
        _seed_reset_token(
            db_session_factory,
            user_id,
            "used-token",
            datetime.utcnow() + timedelta(minutes=30),
            used_at=datetime.utcnow(),
        )

        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "used-token",
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
        )

        assert response.status_code == 400
    finally:
        _clear_overrides()


def test_reset_password_rejects_mismatched_passwords(client):
    db_session_factory = _session_factory()
    try:
        user_id, _ = _seed_user(db_session_factory)
        _seed_reset_token(db_session_factory, user_id, "valid-token", datetime.utcnow() + timedelta(minutes=30))

        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "valid-token",
                "new_password": "NewPass123!",
                "confirm_password": "Different123!",
            },
        )

        assert response.status_code == 400
    finally:
        _clear_overrides()


def test_raw_token_is_not_stored_in_database(client, monkeypatch):
    db_session_factory = _session_factory()
    sent_tokens: list[str] = []
    try:
        _seed_user(db_session_factory)
        monkeypatch.setattr(
            "app.routers.auth.send_password_reset_email",
            lambda user, raw_token, expires_at: sent_tokens.append(raw_token) or True,
        )

        client.post("/api/v1/auth/forgot-password", json={"email": "portal-user@example.com"})

        db = db_session_factory()
        try:
            stored_token = db.query(PasswordResetToken).one()
            assert stored_token.token_hash != sent_tokens[0]
            assert sent_tokens[0] not in stored_token.token_hash
        finally:
            db.close()
    finally:
        _clear_overrides()
