from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.password_reset_token import PasswordResetToken
from app.models.user import ProgramTrack, User, UserRole
from app.routers.auth import _hash_reset_token
from app.services.user_notification_service import _user_created_body
from app.utils.security import create_access_token, hash_password, verify_password


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


def _seed_user(
    db_session_factory,
    email="user@example.com",
    password="OldPass123!",
    role=UserRole.INVENTOR,
    program_track=None,
    must_change_password=False,
):
    db = db_session_factory()
    try:
        user = User(
            full_name="Portal User",
            email=email,
            phone="1234567890",
            password_hash=hash_password(password),
            role=role,
            program_track=program_track,
            is_active=True,
            must_change_password=must_change_password,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _headers_for_user(user_id, email, role):
    token = create_access_token({"user_id": user_id, "email": email, "role": role.value})
    return {"Authorization": f"Bearer {token}"}


def _seed_reset_token(db_session_factory, user_id, raw_token):
    db = db_session_factory()
    try:
        token = PasswordResetToken(
            user_id=user_id,
            token_hash=_hash_reset_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        db.add(token)
        db.commit()
    finally:
        db.close()


def test_login_rate_limit_triggers_after_max_attempts(client):
    db_session_factory = _session_factory()
    try:
        _seed_user(db_session_factory, email="limited@example.com")
        for _ in range(settings.RATE_LIMIT_LOGIN_PER_MINUTE):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "limited@example.com", "password": "WrongPass123!"},
            )
            assert response.status_code == 401

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "limited@example.com", "password": "WrongPass123!"},
        )

        assert response.status_code == 429
        assert response.json()["detail"] == "Too many requests. Please try again later."
    finally:
        _clear_overrides()


def test_rate_limit_can_be_disabled(client, monkeypatch):
    db_session_factory = _session_factory()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    try:
        _seed_user(db_session_factory, email="disabled@example.com")
        for _ in range(settings.RATE_LIMIT_LOGIN_PER_MINUTE + 2):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "disabled@example.com", "password": "WrongPass123!"},
            )
            assert response.status_code == 401
    finally:
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
        _clear_overrides()


def test_public_register_rejects_weak_password(client):
    _session_factory()
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Weak User",
                "email": "weak@example.com",
                "password": "password123",
                "role": "INVENTOR",
            },
        )

        assert response.status_code == 400
        assert "letters and numbers" in response.json()["detail"]
    finally:
        _clear_overrides()


def test_public_register_sets_must_change_password_false(client):
    db_session_factory = _session_factory()
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Public User",
                "email": "public-hardening@example.com",
                "password": "ValidPass123!",
                "role": "SUPER_ADMIN",
            },
        )

        assert response.status_code == 201
        assert response.json()["must_change_password"] is False
        db = db_session_factory()
        try:
            user = db.query(User).filter(User.email == "public-hardening@example.com").one()
            assert user.must_change_password is False
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_change_password_success_clears_must_change_password_and_rotates_login(client):
    db_session_factory = _session_factory()
    try:
        user_id = _seed_user(
            db_session_factory,
            email="change@example.com",
            password="OldPass123!",
            must_change_password=True,
        )
        headers = _headers_for_user(user_id, "change@example.com", UserRole.INVENTOR)

        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "OldPass123!",
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Password has been changed successfully."

        old_login = client.post(
            "/api/v1/auth/login",
            json={"email": "change@example.com", "password": "OldPass123!"},
        )
        new_login = client.post(
            "/api/v1/auth/login",
            json={"email": "change@example.com", "password": "NewPass123!"},
        )

        assert old_login.status_code == 401
        assert new_login.status_code == 200
        assert new_login.json()["user"]["must_change_password"] is False

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_login.json()['access_token']}"})
        assert me.status_code == 200
        assert me.json()["must_change_password"] is False
    finally:
        _clear_overrides()


def test_change_password_rejects_wrong_current_password(client):
    db_session_factory = _session_factory()
    try:
        user_id = _seed_user(db_session_factory, email="wrong-current@example.com")
        headers = _headers_for_user(user_id, "wrong-current@example.com", UserRole.INVENTOR)

        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "BadPass123!",
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
            headers=headers,
        )

        assert response.status_code == 400
    finally:
        _clear_overrides()


def test_change_password_rejects_mismatch_weak_and_same_password(client):
    db_session_factory = _session_factory()
    try:
        user_id = _seed_user(db_session_factory, email="rejects@example.com", password="OldPass123!")
        headers = _headers_for_user(user_id, "rejects@example.com", UserRole.INVENTOR)

        mismatch = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "OldPass123!",
                "new_password": "NewPass123!",
                "confirm_password": "OtherPass123!",
            },
            headers=headers,
        )
        weak = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "OldPass123!",
                "new_password": "password123",
                "confirm_password": "password123",
            },
            headers=headers,
        )
        same = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "OldPass123!",
                "new_password": "OldPass123!",
                "confirm_password": "OldPass123!",
            },
            headers=headers,
        )

        assert mismatch.status_code == 400
        assert weak.status_code == 400
        assert same.status_code == 400
    finally:
        _clear_overrides()


def test_reset_password_rejects_weak_password_and_success_clears_flag(client):
    db_session_factory = _session_factory()
    try:
        user_id = _seed_user(
            db_session_factory,
            email="reset-hardening@example.com",
            must_change_password=True,
        )
        _seed_reset_token(db_session_factory, user_id, "weak-token")

        weak = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "weak-token",
                "new_password": "password123",
                "confirm_password": "password123",
            },
        )

        assert weak.status_code == 400

        _seed_reset_token(db_session_factory, user_id, "strong-token")
        strong = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "strong-token",
                "new_password": "ResetPass123!",
                "confirm_password": "ResetPass123!",
            },
        )

        assert strong.status_code == 200
        db = db_session_factory()
        try:
            user = db.query(User).filter(User.id == user_id).one()
            assert user.must_change_password is False
            assert verify_password("ResetPass123!", user.password_hash)
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_admin_created_user_requires_password_change(client):
    db_session_factory = _session_factory()
    try:
        admin_id = _seed_user(
            db_session_factory,
            email="super-hardening@example.com",
            role=UserRole.SUPER_ADMIN,
        )
        headers = _headers_for_user(admin_id, "super-hardening@example.com", UserRole.SUPER_ADMIN)

        response = client.post(
            "/api/v1/admin/users",
            json={
                "full_name": "Created User",
                "email": "admin-created-hardening@example.com",
                "phone": "1234567890",
                "password": "CreatedPass123!",
                "role": "INVENTOR",
                "program_track": "NATIONAL_INTERNATIONAL",
            },
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["must_change_password"] is True
    finally:
        _clear_overrides()


def test_admin_create_user_rejects_weak_password(client):
    db_session_factory = _session_factory()
    try:
        admin_id = _seed_user(db_session_factory, email="super-weak@example.com", role=UserRole.SUPER_ADMIN)
        headers = _headers_for_user(admin_id, "super-weak@example.com", UserRole.SUPER_ADMIN)

        response = client.post(
            "/api/v1/admin/users",
            json={
                "full_name": "Weak Created",
                "email": "weak-created@example.com",
                "phone": "1234567890",
                "password": "admin123",
                "role": "INVENTOR",
                "program_track": "NATIONAL_INTERNATIONAL",
            },
            headers=headers,
        )

        assert response.status_code == 400
    finally:
        _clear_overrides()


def test_user_creation_email_mentions_temporary_password_and_change_password():
    user = User(
        id=1,
        full_name="Created User",
        email="created@example.com",
        password_hash="not-used",
        role=UserRole.INVENTOR,
        program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
        is_active=True,
        must_change_password=True,
    )

    html, text = _user_created_body(user, "TempPass123!")

    assert "Temporary Password" in html
    assert "Temporary Password" in text
    assert "change this password after your first login" in html
    assert "change this password after your first login" in text
