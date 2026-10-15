from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session
from app.database import get_db
from app.utils.security import decode_access_token
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise exc
    except JWTError:
        raise exc

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if user is None:
        raise exc
    return user


def require_roles(*roles: UserRole):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required: {[r.value for r in roles]}",
            )
        return current_user
    return checker


# Role groupings for the admin permission architecture.
#
# FULL_ADMIN  — can read AND write (create/edit/delete/approve/assign/etc).
# VIEW_ADMIN  — read-only counterparts (VIEW_ADMIN_LOCAL/GLOBAL/BOTH), scoped
#               identically to their full-admin counterparts, but with no
#               access to any mutating endpoint whatsoever.
# ADMIN_READ  — FULL_ADMIN + VIEW_ADMIN. Use on GET/list/detail endpoints.
# ADMIN_WRITE — FULL_ADMIN only. Use on POST/PUT/PATCH/DELETE endpoints.
#
# `require_admin` intentionally keeps its original role set (FULL_ADMIN only)
# so every existing mutating endpoint that depends on it is unaffected by
# adding the new VIEW_ADMIN_* roles — it was never extended to include them.
# Use `require_admin_read` explicitly on read endpoints that VIEW_ADMIN
# roles must be able to reach.
FULL_ADMIN_ROLES = (UserRole.SUPER_ADMIN, UserRole.TEAM_ADMIN_GLOBAL, UserRole.TEAM_ADMIN_LOCAL)
VIEW_ADMIN_ROLES = (UserRole.VIEW_ADMIN_LOCAL, UserRole.VIEW_ADMIN_GLOBAL, UserRole.VIEW_ADMIN_BOTH)
ADMIN_READ_ROLES = FULL_ADMIN_ROLES + VIEW_ADMIN_ROLES
ADMIN_WRITE_ROLES = FULL_ADMIN_ROLES

# Shorthand role dependencies
require_super_admin = require_roles(UserRole.SUPER_ADMIN)
require_admin = require_roles(*ADMIN_WRITE_ROLES)
require_admin_read = require_roles(*ADMIN_READ_ROLES)
require_view_admin = require_roles(*VIEW_ADMIN_ROLES)
require_jury = require_roles(UserRole.JURY)
require_inventor = require_roles(UserRole.INVENTOR)
