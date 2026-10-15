from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from fastapi import Request
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "current_password",
    "new_password",
    "confirm_password",
    "token",
    "access_token",
    "reset_token",
    "secret",
    "smtp_password",
    "file_path",
    "stored_filename",
    "stored_file_name",
}


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(sensitive in lowered for sensitive in SENSITIVE_KEYS)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return sanitize_audit_values(value)
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def sanitize_audit_values(values: Any) -> Any:
    if values is None:
        return None
    if isinstance(values, dict):
        safe: dict[str, Any] = {}
        for key, value in values.items():
            if _is_sensitive(str(key)):
                continue
            safe[str(key)] = _json_safe(value)
        return safe
    return _json_safe(values)


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return None


def _audit_table_available(db: Session) -> bool:
    with db.no_autoflush:
        connection = db.connection()
        return inspect(connection).has_table(AuditLog.__tablename__)


def record_audit_log(
    db: Session,
    actor: User | None = None,
    action: str = "",
    entity_type: str = "",
    entity_id: str | int | None = None,
    entity_display_id: str | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    try:
        if not _audit_table_available(db):
            return
        db.add(AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_role=actor.role.value if actor and actor.role else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            entity_display_id=entity_display_id,
            old_values=sanitize_audit_values(old_values),
            new_values=sanitize_audit_values(new_values),
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent") if request else None,
        ))
    except Exception:
        logger.exception("Audit logging skipped after unexpected failure: action=%s entity_type=%s", action, entity_type)
