from pydantic import BaseModel, EmailStr, field_validator, model_validator
from typing import Optional
from datetime import datetime
from app.schemas.file import IdeaFileOut
from app.utils.prototype_status import normalize_prototype_status
from app.utils.category import normalize_idea_category


class IdeaBase(BaseModel):
    applicant_name: str
    email: EmailStr
    phone: Optional[str] = None
    age: Optional[int] = None
    location: Optional[str] = None
    organization: Optional[str] = None
    original_language: Optional[str] = None
    team_name: Optional[str] = None
    team_member_count: Optional[int] = None
    team_member_names: Optional[list[str]] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    guardian_email: Optional[str] = None
    guardian_relationship: Optional[str] = None
    guardian_consent: Optional[bool] = None
    gender: Optional[str] = None
    program_track: str
    source_type: str = "ONLINE_FORM"
    idea_title: str
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
    # UPGRADE (0002): optional on input — router derives defaults from program_track if omitted
    source_program: Optional[str] = None
    applicant_type: Optional[str] = None
    # UPGRADE (0021): source tracking — identifies submission origin
    # source_platform: ingeniouspark | sirmv-idea | admin-intake | unknown
    source_platform: Optional[str] = None
    source_domain: Optional[str] = None
    source_url: Optional[str] = None
    referrer_url: Optional[str] = None

    @field_validator("prototype_status", mode="before")
    @classmethod
    def normalize_prototype_status_value(cls, value):
        return normalize_prototype_status(value)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category_value(cls, value):
        return normalize_idea_category(value)

    @model_validator(mode="after")
    def sanitize_source_fields(self):
        if self.source_platform:
            self.source_platform = self.source_platform.strip()[:50] or None
        if self.source_domain:
            self.source_domain = self.source_domain.strip()[:255] or None
        if self.source_url:
            self.source_url = self.source_url.strip()[:2000] or None
        if self.referrer_url:
            self.referrer_url = self.referrer_url.strip()[:2000] or None
        return self

    @model_validator(mode="after")
    def validate_team_fields(self):
        member_names = [name.strip() for name in (self.team_member_names or []) if name.strip()]
        has_team_data = bool(
            (self.team_name and self.team_name.strip())
            or self.team_member_count is not None
            or member_names
        )

        if not has_team_data:
            self.team_name = None
            self.team_member_count = None
            self.team_member_names = None
            return self

        if self.team_member_count is None:
            raise ValueError("team_member_count is required for team submissions.")
        if self.team_member_count < 2:
            raise ValueError("team_member_count must be at least 2 for team submissions.")
        if self.team_member_count > 20:
            raise ValueError("team_member_count cannot exceed 20.")
        if member_names and len(member_names) != self.team_member_count:
            raise ValueError("team_member_names must include one name for each team member.")

        self.team_name = self.team_name.strip() if self.team_name else None
        self.team_member_names = member_names or None
        return self


class IdeaCreate(IdeaBase):
    @model_validator(mode="after")
    def require_team_member_names_on_create(self):
        if self.team_name and self.team_member_count is not None:
            member_names = self.team_member_names or []
            if len(member_names) != self.team_member_count:
                raise ValueError("team_member_names must include one name for each team member.")
        return self


class IdeaOut(IdeaBase):
    # Output-only override: IdeaBase.email is a strict EmailStr for input
    # validation on new public submissions. Admin-intake-converted ideas can
    # have a blank/malformed email (business data, intentionally permissive
    # — see convert_to_idea), and re-validating as EmailStr on every read
    # would 500 instead of just displaying whatever's stored.
    email: Optional[str] = None
    id: int
    application_id: str
    current_status: str
    current_stage: Optional[str] = None
    next_action: Optional[str] = None
    admin_message: Optional[str] = None
    rejection_reason: Optional[str] = None
    is_public_tracking_enabled: bool
    # UPGRADE (0002): structured pipeline stage and visibility — null for old rows until admin sets
    current_pathway_stage: Optional[str] = None
    visibility_scope: Optional[str] = None
    # UPGRADE (0010): inventor messaging block — safe to expose; reason is inventor-facing
    inventor_messages_blocked: bool = False
    inventor_messages_blocked_reason: Optional[str] = None
    inventor_messages_blocked_at: Optional[datetime] = None
    inventor_messages_blocked_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminIdeaDetailOut(IdeaOut):
    files: list[IdeaFileOut] = []


class IdeaStatusUpdate(BaseModel):
    # EXISTING fields
    current_status: Optional[str] = None
    current_stage: Optional[str] = None
    next_action: Optional[str] = None
    admin_message: Optional[str] = None
    # UPGRADE (0002): admin can now set structured pathway stage and visibility scope
    # source_program intentionally excluded — set at submission, not by admin status update
    current_pathway_stage: Optional[str] = None
    visibility_scope: Optional[str] = None
