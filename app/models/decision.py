import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from app.database import Base


class AdminDecision(str, enum.Enum):
    SHORTLISTED = "SHORTLISTED"
    REJECTED = "REJECTED"
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"
    PROTOTYPE_REQUIRED = "PROTOTYPE_REQUIRED"
    PROTOTYPE_APPROVED = "PROTOTYPE_APPROVED"
    MENTORSHIP_ASSIGNED = "MENTORSHIP_ASSIGNED"
    INCUBATION_RECOMMENDED = "INCUBATION_RECOMMENDED"
    SELECTED_FOR_LOCAL_SHOWCASE = "SELECTED_FOR_LOCAL_SHOWCASE"
    SELECTED_FOR_STATE_LEVEL = "SELECTED_FOR_STATE_LEVEL"
    RECOMMENDED_FOR_NATIONAL_LEVEL = "RECOMMENDED_FOR_NATIONAL_LEVEL"
    RECOMMENDED_FOR_INTERNATIONAL_LEVEL = "RECOMMENDED_FOR_INTERNATIONAL_LEVEL"
    RECOGNITION_FUNDING_PATENT_SUPPORT = "RECOGNITION_FUNDING_PATENT_SUPPORT"
    CLOSED = "CLOSED"


class IdeaDecision(Base):
    __tablename__ = "idea_decisions"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False, index=True)
    decided_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    decision = Column(
        postgresql.ENUM(AdminDecision, name="admindecision", create_type=False),
        nullable=False,
    )

    # snapshot of idea state before this decision
    old_status = Column(String(100), nullable=True)
    old_pathway_stage = Column(String(100), nullable=True)

    # applied values
    new_status = Column(String(100), nullable=True)
    new_pathway_stage = Column(String(100), nullable=True)

    # notes
    admin_note = Column(Text, nullable=True)      # internal only — never shown to inventor
    public_message = Column(Text, nullable=True)  # written to messages table for inventor

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    idea = relationship("Idea", foreign_keys=[idea_id])
    decided_by = relationship("User", foreign_keys=[decided_by_user_id])
