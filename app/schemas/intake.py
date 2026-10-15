from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from datetime import datetime
from app.utils.prototype_status import normalize_prototype_status
from app.utils.category import normalize_idea_category


class IntakeSubmissionBase(BaseModel):
    source_type: str
    source_program: Optional[str] = None       # derived from role if omitted
    source_platform: Optional[str] = None
    applicant_type: Optional[str] = None
    visibility_scope: Optional[str] = None     # derived from role if omitted
    original_language: Optional[str] = None
    applicant_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    organization: Optional[str] = None
    team_name: Optional[str] = None
    team_member_count: Optional[int] = None
    team_member_names: Optional[list[str]] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    guardian_email: Optional[str] = None
    guardian_relationship: Optional[str] = None
    guardian_consent: Optional[bool] = None
    raw_title: str
    raw_description: Optional[str] = None
    problem_statement: Optional[str] = None
    solution_description: Optional[str] = None
    application_context: Optional[str] = None
    uniqueness: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    target_users: Optional[str] = None
    prototype_status: Optional[str] = None
    support_needed: Optional[str] = None
    consent_data: Optional[bool] = None
    consent_original: Optional[bool] = None
    consent_contact: Optional[bool] = None
    admin_notes: Optional[str] = None
    assigned_team_user_id: Optional[int] = None

    @field_validator("prototype_status", mode="before")
    @classmethod
    def normalize_prototype_status_value(cls, value):
        return normalize_prototype_status(value)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category_value(cls, value):
        return normalize_idea_category(value)

    @field_validator("source_platform", mode="before")
    @classmethod
    def sanitize_source_platform_value(cls, value):
        if value is None:
            return None
        cleaned = str(value).strip()[:50]
        return cleaned or None

    @model_validator(mode="after")
    def validate_alignment_fields(self):
        applicant_type = (self.applicant_type or "").strip().upper()
        is_team = applicant_type in {"TEAM", "TEAM / GROUP", "TEAM_GROUP"}
        member_names = [name.strip() for name in (self.team_member_names or []) if name.strip()]

        if is_team:
            if self.team_member_count is None:
                raise ValueError("team_member_count is required for Team / Group intake submissions.")
            if self.team_member_count < 2:
                raise ValueError("team_member_count must be at least 2 for Team / Group intake submissions.")
        elif self.team_member_count is not None and self.team_member_count < 1:
            raise ValueError("team_member_count must be positive when provided.")

        self.team_member_names = member_names or None

        source_program = (self.source_program or "").strip().upper()
        is_k12_or_minor = (self.age is not None and self.age < 18) or source_program in {"NMF_K12", "K12"}
        if is_k12_or_minor:
            if not self.guardian_name or not self.guardian_name.strip():
                raise ValueError("guardian_name is required for K-12 or minor intake submissions.")
            if not self.guardian_phone or not self.guardian_phone.strip():
                raise ValueError("guardian_phone is required for K-12 or minor intake submissions.")
            if not self.guardian_relationship or not self.guardian_relationship.strip():
                raise ValueError("guardian_relationship is required for K-12 or minor intake submissions.")
            if self.guardian_consent is not True:
                raise ValueError("guardian_consent is required for K-12 or minor intake submissions.")

        return self


class IntakeSubmissionCreate(IntakeSubmissionBase):
    pass


class IntakeSubmissionUpdate(BaseModel):
    source_type: Optional[str] = None
    source_program: Optional[str] = None
    source_platform: Optional[str] = None
    applicant_type: Optional[str] = None
    visibility_scope: Optional[str] = None
    original_language: Optional[str] = None
    applicant_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    organization: Optional[str] = None
    team_name: Optional[str] = None
    team_member_count: Optional[int] = None
    team_member_names: Optional[list[str]] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    guardian_email: Optional[str] = None
    guardian_relationship: Optional[str] = None
    guardian_consent: Optional[bool] = None
    raw_title: Optional[str] = None
    raw_description: Optional[str] = None
    problem_statement: Optional[str] = None
    solution_description: Optional[str] = None
    application_context: Optional[str] = None
    uniqueness: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    target_users: Optional[str] = None
    prototype_status: Optional[str] = None
    support_needed: Optional[str] = None
    consent_data: Optional[bool] = None
    consent_original: Optional[bool] = None
    consent_contact: Optional[bool] = None
    intake_status: Optional[str] = None
    completeness_status: Optional[str] = None
    admin_notes: Optional[str] = None
    missing_information_note: Optional[str] = None
    assigned_team_user_id: Optional[int] = None

    @field_validator("source_platform", mode="before")
    @classmethod
    def sanitize_source_platform_value(cls, value):
        if value is None:
            return None
        cleaned = str(value).strip()[:50]
        return cleaned or None

    @field_validator("prototype_status", mode="before")
    @classmethod
    def normalize_prototype_status_value(cls, value):
        return normalize_prototype_status(value)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category_value(cls, value):
        return normalize_idea_category(value)


class MoreInfoRequest(BaseModel):
    missing_information_note: str


class IntakeSubmissionOut(BaseModel):
    id: int
    intake_id: str
    created_by_user_id: int
    assigned_team_user_id: Optional[int] = None
    source_type: str
    source_program: Optional[str] = None
    source_platform: Optional[str] = None
    applicant_type: Optional[str] = None
    visibility_scope: Optional[str] = None
    original_language: Optional[str] = None
    applicant_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    organization: Optional[str] = None
    team_name: Optional[str] = None
    team_member_count: Optional[int] = None
    team_member_names: Optional[list[str]] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    guardian_email: Optional[str] = None
    guardian_relationship: Optional[str] = None
    guardian_consent: Optional[bool] = None
    raw_title: str
    raw_description: Optional[str] = None
    problem_statement: Optional[str] = None
    solution_description: Optional[str] = None
    application_context: Optional[str] = None
    uniqueness: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    target_users: Optional[str] = None
    prototype_status: Optional[str] = None
    support_needed: Optional[str] = None
    consent_data: Optional[bool] = None
    consent_original: Optional[bool] = None
    consent_contact: Optional[bool] = None
    standardized_idea_id: Optional[int] = None
    intake_status: str
    completeness_status: str
    admin_notes: Optional[str] = None
    missing_information_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": False}


class IntakeConversionOut(IntakeSubmissionOut):
    """Extends IntakeSubmissionOut with the created idea's application_id so
    callers can navigate directly to the new idea after conversion."""
    created_application_id: Optional[str] = None
