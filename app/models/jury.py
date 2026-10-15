import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from app.database import Base


class ReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REASSIGNED = "REASSIGNED"
    CANCELLED = "CANCELLED"


class JuryProfile(Base):
    __tablename__ = "jury_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    expertise_field = Column(String(255), nullable=True)
    sub_field = Column(String(255), nullable=True)
    qualification = Column(String(255), nullable=True)
    organization = Column(String(255), nullable=True)
    experience_years = Column(Integer, nullable=True)
    max_review_capacity = Column(Integer, nullable=False, default=10)
    is_available = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", foreign_keys=[user_id])


class JuryAssignment(Base):
    __tablename__ = "jury_assignments"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False, index=True)
    jury_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    review_status = Column(
        postgresql.ENUM(ReviewStatus, name="reviewstatus", create_type=False),
        nullable=False,
        default=ReviewStatus.PENDING,
    )
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    due_date = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    idea = relationship("Idea", foreign_keys=[idea_id])
    jury_user = relationship("User", foreign_keys=[jury_user_id])
    assigned_by = relationship("User", foreign_keys=[assigned_by_user_id])
