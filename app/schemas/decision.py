from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models.decision import AdminDecision

_VALID_PATHWAY_STAGES = (
    "INTAKE, SCREENING, LOCAL_REVIEW, STATE_REVIEW, NATIONAL_REVIEW, "
    "INTERNATIONAL_REVIEW, INCUBATION, COMPLETED, ADMIN_VERIFICATION"
)


class DecisionCreate(BaseModel):
    decision: AdminDecision
    admin_note: Optional[str] = Field(None, description="Internal note — never shown to inventor")
    public_message: Optional[str] = Field(None, description="Message sent to inventor (optional)")
    notify_applicant: bool = Field(True, description="Send applicant email when public_message is present")
    # override auto-derived values if provided
    new_status: Optional[str] = Field(
        None,
        description="Override the auto-derived idea status (e.g. FIELD_REVIEW_CLEARED)",
        examples=["FIELD_REVIEW_CLEARED"],
    )
    new_pathway_stage: Optional[str] = Field(
        None,
        description=(
            f"Override the auto-derived pathway stage. "
            f"Valid values: {_VALID_PATHWAY_STAGES}"
        ),
        examples=["SCREENING"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "decision": "SHORTLISTED",
                    "admin_note": "Strong idea, clear problem statement.",
                    "public_message": "Congratulations! Your idea has been shortlisted for jury review.",
                },
                {
                    "decision": "NEEDS_MORE_INFORMATION",
                    "public_message": "Please provide more details about your prototype.",
                    "new_pathway_stage": "ADMIN_VERIFICATION",
                },
                {
                    "decision": "SELECTED_FOR_STATE_LEVEL",
                    "public_message": "Your idea has been selected for the state-level showcase.",
                    "new_pathway_stage": "STATE_REVIEW",
                },
            ]
        }
    }


class DecisionOut(BaseModel):
    id: int
    idea_id: int
    decided_by_user_id: int
    decision: str
    old_status: Optional[str]
    old_pathway_stage: Optional[str]
    new_status: Optional[str]
    new_pathway_stage: Optional[str]
    admin_note: Optional[str]
    public_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
