from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.status_history import StatusHistory


def _status_history_table_available(db: Session) -> bool:
    with db.no_autoflush:
        return inspect(db.connection()).has_table(StatusHistory.__tablename__)


def record_status_history(
    db: Session,
    idea_id: int,
    changed_by_user_id: int | None,
    old_status: str | None,
    new_status: str | None,
    old_stage: str | None = None,
    new_stage: str | None = None,
    reason: str | None = None,
    remarks: str | None = None,
) -> StatusHistory | None:
    if old_status == new_status and old_stage == new_stage:
        return None
    if not _status_history_table_available(db):
        return None
    history = StatusHistory(
        idea_id=idea_id,
        changed_by_user_id=changed_by_user_id,
        old_status=old_status,
        new_status=new_status,
        old_stage=old_stage,
        new_stage=new_stage,
        reason=reason,
        remarks=remarks,
    )
    db.add(history)
    return history
