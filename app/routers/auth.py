from datetime import datetime, timedelta
import hashlib
import hmac
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserInToken,
)
from app.schemas.user import UserCreate, UserOut
from app.services.auth_service import authenticate_user
from app.services.audit_log_service import record_audit_log
from app.services.password_reset_service import send_password_reset_email
from app.services.rate_limit import assert_rate_limit
from app.utils.security import (
    PASSWORD_POLICY_MESSAGE,
    create_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.utils.dependencies import get_current_user
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

PASSWORD_RESET_EXPIRE_MINUTES = 30
FORGOT_PASSWORD_MESSAGE = "If an account exists, a reset link has been sent."
RESET_PASSWORD_SUCCESS_MESSAGE = "Password has been reset successfully."
INVALID_RESET_TOKEN_MESSAGE = "Invalid or expired reset token."
CHANGE_PASSWORD_SUCCESS_MESSAGE = "Password has been changed successfully."


def _validate_new_password(password: str) -> None:
    try:
        validate_password_strength(password)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PASSWORD_POLICY_MESSAGE,
        )


def _token_user(user: User) -> UserInToken:
    return UserInToken(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role.value,
        program_track=user.program_track.value if user.program_track else None,
        must_change_password=user.must_change_password,
    )


def _hash_reset_token(raw_token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


@router.post("/login", response_model=TokenResponse)
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    assert_rate_limit(
        request,
        "auth-login",
        settings.RATE_LIMIT_LOGIN_PER_MINUTE,
        60,
        str(payload.email),
    )
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token({
        "user_id": user.id,
        "email": user.email,
        "role": user.role.value,
    })
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=_token_user(user),
    )


@router.post("/token", include_in_schema=False)
def token_swagger(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 form endpoint used exclusively by Swagger Authorize. username = email."""
    assert_rate_limit(
        request,
        "auth-token",
        settings.RATE_LIMIT_LOGIN_PER_MINUTE,
        60,
        form_data.username,
    )
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token({
        "user_id": user.id,
        "email": user.email,
        "role": user.role.value,
    })
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    assert_rate_limit(
        request,
        "auth-forgot-password",
        settings.RATE_LIMIT_FORGOT_PASSWORD_PER_15_MIN,
        15 * 60,
        str(payload.email),
    )
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.is_active:
        return MessageResponse(message=FORGOT_PASSWORD_MESSAGE)

    now = datetime.utcnow()
    raw_token = _generate_reset_token()
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_reset_token(raw_token),
        expires_at=now + timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES),
    )

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    db.add(reset_token)
    db.commit()

    try:
        send_password_reset_email(user, raw_token, reset_token.expires_at)
    except Exception:
        logger.exception(
            "Password reset email failed unexpectedly after token creation: user_id=%s",
            user.id,
        )

    return MessageResponse(message=FORGOT_PASSWORD_MESSAGE)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    assert_rate_limit(
        request,
        "auth-reset-password",
        settings.RATE_LIMIT_RESET_PASSWORD_PER_15_MIN,
        15 * 60,
        payload.token,
    )
    if payload.new_password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirm password do not match.",
        )
    _validate_new_password(payload.new_password)

    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == _hash_reset_token(payload.token),
    ).first()

    now = datetime.utcnow()
    if (
        not reset_token
        or reset_token.used_at is not None
        or reset_token.expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_RESET_TOKEN_MESSAGE,
        )

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_RESET_TOKEN_MESSAGE,
        )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    reset_token.used_at = now
    record_audit_log(
        db,
        actor=user,
        action="password_reset_success",
        entity_type="user",
        entity_id=user.id,
        entity_display_id=user.email,
        new_values={"must_change_password": user.must_change_password},
        request=request,
    )
    db.commit()

    return MessageResponse(message=RESET_PASSWORD_SUCCESS_MESSAGE)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirm password do not match.",
        )
    _validate_new_password(payload.new_password)

    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    if verify_password(payload.new_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password.",
        )

    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    record_audit_log(
        db,
        actor=current_user,
        action="password_changed",
        entity_type="user",
        entity_id=current_user.id,
        entity_display_id=current_user.email,
        new_values={"must_change_password": current_user.must_change_password},
        request=request,
    )
    db.commit()
    return MessageResponse(message=CHANGE_PASSWORD_SUCCESS_MESSAGE)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)):
    assert_rate_limit(
        request,
        "auth-register",
        settings.RATE_LIMIT_REGISTER_PER_HOUR,
        60 * 60,
    )
    _validate_new_password(payload.password)
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=UserRole.INVENTOR,
        program_track=None,
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
