from pydantic import BaseModel, field_validator
from typing import Optional, List, Dict
from datetime import datetime


class EvaluationCreate(BaseModel):
    problem_clarity_score: float     # 0–10
    novelty_score: float             # 0–20
    feasibility_score: float         # 0–20
    impact_score: float              # 0–20
    scalability_score: float         # 0–10
    prototype_readiness_score: float # 0–10
    practical_usefulness_score: float # 0–10
    remarks: Optional[str] = None
    recommendation: str
    reason: Optional[str] = None

    @field_validator("problem_clarity_score")
    @classmethod
    def check_clarity(cls, v: float) -> float:
        if not 0 <= v <= 10:
            raise ValueError("problem_clarity_score must be between 0 and 10")
        return v

    @field_validator("novelty_score")
    @classmethod
    def check_novelty(cls, v: float) -> float:
        if not 0 <= v <= 20:
            raise ValueError("novelty_score must be between 0 and 20")
        return v

    @field_validator("feasibility_score")
    @classmethod
    def check_feasibility(cls, v: float) -> float:
        if not 0 <= v <= 20:
            raise ValueError("feasibility_score must be between 0 and 20")
        return v

    @field_validator("impact_score")
    @classmethod
    def check_impact(cls, v: float) -> float:
        if not 0 <= v <= 20:
            raise ValueError("impact_score must be between 0 and 20")
        return v

    @field_validator("scalability_score")
    @classmethod
    def check_scalability(cls, v: float) -> float:
        if not 0 <= v <= 10:
            raise ValueError("scalability_score must be between 0 and 10")
        return v

    @field_validator("prototype_readiness_score")
    @classmethod
    def check_prototype_readiness(cls, v: float) -> float:
        if not 0 <= v <= 10:
            raise ValueError("prototype_readiness_score must be between 0 and 10")
        return v

    @field_validator("practical_usefulness_score")
    @classmethod
    def check_practical_usefulness(cls, v: float) -> float:
        if not 0 <= v <= 10:
            raise ValueError("practical_usefulness_score must be between 0 and 10")
        return v


class EvaluationOut(BaseModel):
    id: int
    idea_id: int
    jury_user_id: int
    problem_clarity_score: float
    novelty_score: float
    feasibility_score: float
    impact_score: float
    scalability_score: float
    prototype_readiness_score: float
    practical_usefulness_score: float
    total_score: float
    remarks: Optional[str] = None
    recommendation: str
    reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewSummaryItem(BaseModel):
    jury_user_id: int
    review_status: str
    total_score: Optional[float] = None
    recommendation: Optional[str] = None
    completed_at: Optional[datetime] = None


class EvaluationSummary(BaseModel):
    idea_id: int
    assigned_jury_count: int
    completed_review_count: int
    pending_review_count: int
    average_score: Optional[float] = None
    recommendations: Dict[str, int]
    reviews: List[ReviewSummaryItem]
