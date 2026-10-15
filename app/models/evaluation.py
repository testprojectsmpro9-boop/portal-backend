import enum
from datetime import datetime
from sqlalchemy import Column, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from app.database import Base


class Recommendation(str, enum.Enum):
    SHORTLIST = "SHORTLIST"
    REJECT = "REJECT"
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"
    PROTOTYPE_REQUIRED = "PROTOTYPE_REQUIRED"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False, index=True)
    jury_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Scores — validated in schema before reaching here
    problem_clarity_score = Column(Float, nullable=False)        # 0–10
    novelty_score = Column(Float, nullable=False)                # 0–20
    feasibility_score = Column(Float, nullable=False)            # 0–20
    impact_score = Column(Float, nullable=False)                 # 0–20
    scalability_score = Column(Float, nullable=False)            # 0–10
    prototype_readiness_score = Column(Float, nullable=False)    # 0–10
    practical_usefulness_score = Column(Float, nullable=False)   # 0–10
    total_score = Column(Float, nullable=False)                  # auto-calculated, max 100

    remarks = Column(Text, nullable=True)
    recommendation = Column(
        postgresql.ENUM(Recommendation, name="recommendation", create_type=False),
        nullable=False,
    )
    reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    idea = relationship("Idea", foreign_keys=[idea_id])
    jury_user = relationship("User", foreign_keys=[jury_user_id])
