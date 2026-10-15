import enum
from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from app.database import Base


class FileType(str, enum.Enum):
    DOCUMENT = "DOCUMENT"
    OFFLINE_FORM = "OFFLINE_FORM"
    LETTER_SCAN = "LETTER_SCAN"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    PROTOTYPE_PHOTO = "PROTOTYPE_PHOTO"
    DESIGN_SKETCH = "DESIGN_SKETCH"
    OTHER = "OTHER"


class IdeaFile(Base):
    __tablename__ = "idea_files"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False, index=True)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # postgresql.ENUM with create_type=False: references existing "filetype" PG enum from migration.
    # SAEnum(FileType) sends plain VARCHAR → type mismatch. postgresql.ENUM casts correctly.
    file_type = Column(
        postgresql.ENUM(FileType, name="filetype", create_type=False),
        nullable=False,
    )
    file_name = Column(String(255), nullable=False)         # original filename from client
    stored_file_name = Column(String(255), nullable=False)  # UUID-based name on disk
    file_path = Column(String(500), nullable=False)         # relative path from UPLOAD_DIR root
    mime_type = Column(String(100), nullable=True)
    file_size = Column(BigInteger, nullable=True)           # bytes
    description = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    idea = relationship("Idea", foreign_keys=[idea_id])
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_user_id])
