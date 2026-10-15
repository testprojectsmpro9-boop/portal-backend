from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.idea_file import FileType


class IntakeFile(Base):
    __tablename__ = "intake_files"

    id = Column(Integer, primary_key=True, index=True)
    intake_submission_id = Column(Integer, ForeignKey("intake_submissions.id"), nullable=False, index=True)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    file_type = Column(
        postgresql.ENUM(FileType, name="filetype", create_type=False),
        nullable=False,
    )
    file_name = Column(String(255), nullable=False)
    stored_file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    intake = relationship("IntakeSubmission", foreign_keys=[intake_submission_id])
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_user_id])
