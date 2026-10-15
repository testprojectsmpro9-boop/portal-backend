from fastapi import Request
from sqlalchemy.orm import Session

from app.models.file_access_log import FileAccessLog
from app.models.idea import Idea
from app.models.idea_file import IdeaFile
from app.models.user import User


def record_file_access_log(
    db: Session,
    *,
    file_record: IdeaFile,
    idea: Idea,
    user: User,
    action: str,
    request: Request | None = None,
) -> FileAccessLog:
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None
    log = FileAccessLog(
        file_id=file_record.id,
        idea_id=idea.id,
        application_id=idea.application_id,
        user_id=user.id,
        user_email=user.email,
        user_role=user.role.value if user.role else None,
        action=action,
        original_filename=file_record.file_name,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(log)
    return log
