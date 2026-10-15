import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum, JSON
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship, foreign
from app.database import Base
from app.models.user import ProgramTrack
from app.models.decision import IdeaDecision


class IdeaStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"
    PUBLIC_DOMAIN_REVIEW_PENDING = "PUBLIC_DOMAIN_REVIEW_PENDING"
    PUBLIC_DOMAIN_CLEARED = "PUBLIC_DOMAIN_CLEARED"
    PUBLIC_DOMAIN_REJECTED = "PUBLIC_DOMAIN_REJECTED"
    FIELD_JURY_REVIEW_PENDING = "FIELD_JURY_REVIEW_PENDING"
    FIELD_JURY_REVIEW_IN_PROGRESS = "FIELD_JURY_REVIEW_IN_PROGRESS"
    FIELD_REVIEW_CLEARED = "FIELD_REVIEW_CLEARED"
    REJECTED_BY_JURY = "REJECTED_BY_JURY"
    PROTOTYPE_REQUIRED = "PROTOTYPE_REQUIRED"
    PROTOTYPE_SUBMITTED = "PROTOTYPE_SUBMITTED"
    MENTOR_ASSIGNED = "MENTOR_ASSIGNED"
    INCUBATION_RECOMMENDED = "INCUBATION_RECOMMENDED"
    SELECTED_FOR_LOCAL_SHOWCASE = "SELECTED_FOR_LOCAL_SHOWCASE"
    SELECTED_FOR_STATE_LEVEL = "SELECTED_FOR_STATE_LEVEL"
    RECOMMENDED_FOR_NATIONAL_LEVEL = "RECOMMENDED_FOR_NATIONAL_LEVEL"
    RECOMMENDED_FOR_INTERNATIONAL_LEVEL = "RECOMMENDED_FOR_INTERNATIONAL_LEVEL"
    RECOGNITION_FUNDING_PATENT_SUPPORT = "RECOGNITION_FUNDING_PATENT_SUPPORT"
    CLOSED = "CLOSED"


class IdeaCategory(str, enum.Enum):
    AGRICULTURE = "Agriculture"
    HEALTHCARE = "Healthcare / Medical"
    EDUCATION = "Education"
    ENVIRONMENT = "Environment"
    ENERGY = "Energy"
    WATER = "Water"
    WASTE_MANAGEMENT = "Waste Management"
    ASSISTIVE_TECHNOLOGY = "Assistive Technology"
    WOMEN_SAFETY = "Women Safety"
    RURAL_DEVELOPMENT = "Rural Development"
    ELECTRONICS_IOT = "Electronics / IoT"
    MECHANICAL = "Mechanical Innovation"
    AI_SOFTWARE = "AI / Software"
    SOCIAL_INNOVATION = "Social Innovation"
    OTHERS = "Others"


class SourceType(str, enum.Enum):
    ONLINE_FORM = "ONLINE_FORM"
    OFFLINE_FORM = "OFFLINE_FORM"
    LETTER_SCAN = "LETTER_SCAN"
    DOCUMENT = "DOCUMENT"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    PROTOTYPE_PHOTO = "PROTOTYPE_PHOTO"
    DESIGN_SKETCH = "DESIGN_SKETCH"
    EMAIL_IMPORT = "EMAIL_IMPORT"
    WHATSAPP_IMPORT = "WHATSAPP_IMPORT"
    IN_PERSON = "IN_PERSON"
    OTHER = "OTHER"


# --- UPGRADE: Added in migration 0002 ---
# Problem: program_track alone cannot describe whether an idea came from a K12
# student submitting via national portal, or a local idea being promoted to
# national stage, or a team spanning both tracks. We need richer classification.

class SourceProgram(str, enum.Enum):
    """Which program/portal the idea was originally submitted through."""
    NMF_NATIONAL = "NMF_NATIONAL"        # National Innovation challenge
    NMF_LOCAL = "NMF_LOCAL"              # Local/regional innovation challenge
    NMF_K12 = "NMF_K12"                  # School/K12 innovation challenge
    IFIA_AFFILIATE = "IFIA_AFFILIATE"    # International affiliate program
    EXTERNAL_REFERRAL = "EXTERNAL_REFERRAL"  # Referred from outside NMF
    OTHER = "OTHER"


class ApplicantType(str, enum.Enum):
    """Who submitted the idea — individual, team, institution, student, etc."""
    INDIVIDUAL = "INDIVIDUAL"
    TEAM = "TEAM"
    STUDENT = "STUDENT"          # K12 or university student
    STARTUP = "STARTUP"
    NGO = "NGO"
    INSTITUTION = "INSTITUTION"  # University, school, research lab
    OTHER = "OTHER"


class PathwayStage(str, enum.Enum):
    """
    Structured progression stage for admin/jury pipeline tracking.
    Separate from current_status (which tracks workflow state) —
    this tracks which competition/showcase level the idea has reached.
    Upgraded because current_stage was a free-text field with no validation.
    """
    INTAKE = "INTAKE"
    SCREENING = "SCREENING"
    LOCAL_REVIEW = "LOCAL_REVIEW"
    STATE_REVIEW = "STATE_REVIEW"
    NATIONAL_REVIEW = "NATIONAL_REVIEW"
    INTERNATIONAL_REVIEW = "INTERNATIONAL_REVIEW"
    INCUBATION = "INCUBATION"
    COMPLETED = "COMPLETED"
    # UPGRADE (migration 0005): added for ideas created via admin intake desk conversion
    ADMIN_VERIFICATION = "ADMIN_VERIFICATION"


class VisibilityScope(str, enum.Enum):
    """
    Intake table visibility scope (NMF_* naming). Kept for intake records.
    Do NOT use on the ideas table — use IdeaVisibilityScope instead.
    """
    LOCAL_ONLY = "LOCAL_ONLY"
    GLOBAL_ONLY = "GLOBAL_ONLY"
    GLOBAL_AND_LOCAL = "GLOBAL_AND_LOCAL"
    SUPER_ADMIN_ONLY = "SUPER_ADMIN_ONLY"


# --- UPGRADE: Added in migration 0006 — ideas table uses these aligned enums ---

class IdeaSourceProgram(str, enum.Enum):
    """Ideas table source program — track-aligned values (migration 0006)."""
    NATIONAL_INTERNATIONAL = "NATIONAL_INTERNATIONAL"
    LOCAL_REGIONAL = "LOCAL_REGIONAL"
    K12 = "K12"


class IdeaApplicantType(str, enum.Enum):
    """Ideas table applicant type — richer than intake ApplicantType (migration 0006)."""
    K12_STUDENT = "K12_STUDENT"
    COLLEGE_STUDENT = "COLLEGE_STUDENT"
    ADULT_INNOVATOR = "ADULT_INNOVATOR"
    STARTUP = "STARTUP"
    FARMER = "FARMER"
    RESEARCHER = "RESEARCHER"
    GENERAL_PUBLIC = "GENERAL_PUBLIC"
    OTHER = "OTHER"


class IdeaVisibilityScope(str, enum.Enum):
    """Ideas table visibility scope — team-aligned (migration 0006). Replaces old VisibilityScope on ideas."""
    LOCAL_TEAM = "LOCAL_TEAM"
    GLOBAL_TEAM = "GLOBAL_TEAM"
    K12_TEAM = "K12_TEAM"
    ALL_TEAMS = "ALL_TEAMS"


class Idea(Base):
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(String(20), unique=True, index=True, nullable=False)
    inventor_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    applicant_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(20), nullable=True)
    age = Column(Integer, nullable=True)
    location = Column(String(255), nullable=True)
    organization = Column(String(255), nullable=True)
    original_language = Column(String(50), nullable=True)
    team_name = Column(String(255), nullable=True)
    team_member_count = Column(Integer, nullable=True)
    team_member_names = Column(JSON, nullable=True)
    guardian_name = Column(String(255), nullable=True)
    guardian_phone = Column(String(20), nullable=True)
    guardian_email = Column(String(255), nullable=True)
    guardian_relationship = Column(String(100), nullable=True)
    guardian_consent = Column(Boolean, nullable=True)
    gender = Column(String(50), nullable=True)

    # EXISTING: program_track kept for backward compat — drives default visibility derivation
    program_track = Column(SAEnum(ProgramTrack), nullable=False)
    source_type = Column(SAEnum(SourceType), nullable=False, default=SourceType.ONLINE_FORM)
    source_domain = Column(String(255), nullable=True)
    # UPGRADE (migration 0021): source tracking — identifies origin platform/URL
    source_platform = Column(String(50), nullable=True)   # ingeniouspark | sirmv-idea | admin-intake | unknown
    source_url = Column(String(2000), nullable=True)       # full page URL at submission time
    referrer_url = Column(String(2000), nullable=True)     # document.referrer

    idea_title = Column(String(500), nullable=False)
    problem_statement = Column(Text, nullable=True)
    solution_description = Column(Text, nullable=True)
    application_context = Column(Text, nullable=True)
    uniqueness = Column(Text, nullable=True)
    # INTENTIONAL: no values_callable here. The live `ideacategory` Postgres
    # enum type stores member NAMES ('WATER', 'WASTE_MANAGEMENT', ...), not
    # .value strings ('Water', 'Waste Management', ...). A values_callable
    # mapping to .value was tried and caused every category read/write to
    # raise `DataError: invalid input value for enum ideacategory` — confirmed
    # against the live dev DB by inspecting pg_enum directly. Do NOT
    # reintroduce values_callable on this column. Regression-covered by
    # tests/test_models_idea.py and tests/test_category_enum_regression.py.
    category = Column(
    postgresql.ENUM(
        IdeaCategory,
        name="ideacategory",
        create_type=False,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    ),
    nullable=True,
)
    sub_category = Column(String(255), nullable=True)
    target_users = Column(Text, nullable=True)
    prototype_status = Column(String(100), nullable=True)
    support_needed = Column(Text, nullable=True)
    consent_data = Column(Boolean, nullable=True)
    consent_original = Column(Boolean, nullable=True)
    consent_contact = Column(Boolean, nullable=True)

    # EXISTING: current_stage is free-text (for custom labels), current_pathway_stage is structured enum
    current_stage = Column(String(100), nullable=True)
    current_status = Column(SAEnum(IdeaStatus), nullable=False, default=IdeaStatus.SUBMITTED)
    next_action = Column(Text, nullable=True)
    admin_message = Column(Text, nullable=True)
    is_public_tracking_enabled = Column(Boolean, default=True, nullable=False)

    # UPGRADE (migration 0002/0006): richer classification fields — all nullable so existing rows unaffected
    # source_program/applicant_type/visibility_scope use migration-0006 types (ideas-specific enums)
    source_program = Column(postgresql.ENUM(IdeaSourceProgram, name="ideasourceprogram", create_type=False), nullable=True)
    applicant_type = Column(postgresql.ENUM(IdeaApplicantType, name="ideaapplicanttype", create_type=False), nullable=True)
    current_pathway_stage = Column(SAEnum(PathwayStage), nullable=True)
    visibility_scope = Column(postgresql.ENUM(IdeaVisibilityScope, name="ideavisibilityscope", create_type=False), nullable=True)

    # UPGRADE (migration 0010): admin-controlled per-idea inventor messaging block
    inventor_messages_blocked = Column(Boolean, default=False, nullable=False)
    inventor_messages_blocked_reason = Column(Text, nullable=True)
    inventor_messages_blocked_at = Column(DateTime, nullable=True)
    inventor_messages_blocked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    inventor = relationship("User", foreign_keys=[inventor_id])
    decisions = relationship(
        IdeaDecision,
        primaryjoin=lambda: Idea.id == foreign(IdeaDecision.idea_id),
        order_by=lambda: IdeaDecision.created_at.desc(),
        viewonly=True,
    )

    _REJECTED_STATUS_VALUES = {"PUBLIC_DOMAIN_REJECTED", "REJECTED_BY_JURY"}

    @property
    def rejection_reason(self):
        """Best-effort rejection reason for the current status.

        Sourced from the most recent REJECTED decision's applicant-facing
        message (falling back to the internal admin note), and falling back
        to the generic admin_message for historical rows recorded before
        idea_decisions tracked this.
        """
        status_value = getattr(self.current_status, "value", self.current_status)
        if status_value not in self._REJECTED_STATUS_VALUES:
            return None
        for decision in self.decisions or []:
            decision_value = getattr(decision.decision, "value", decision.decision)
            if decision_value == "REJECTED":
                return decision.public_message or decision.admin_note
        return self.admin_message
