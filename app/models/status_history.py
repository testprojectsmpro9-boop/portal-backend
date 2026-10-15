from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class StatusHistory(Base):
    __tablename__ = "status_history"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False, index=True)
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    old_status = Column(String(100), nullable=True)
    new_status = Column(String(100), nullable=True)
    old_stage = Column(String(100), nullable=True)
    new_stage = Column(String(100), nullable=True)

    reason = Column(String(255), nullable=True)
    remarks = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    idea = relationship("Idea", foreign_keys=[idea_id])
    changed_by = relationship("User", foreign_keys=[changed_by_user_id])
