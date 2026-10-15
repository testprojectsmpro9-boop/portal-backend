"""
IntakeSubmission model — Admin Intake Desk.

Stores offline/non-standard submissions received by admin team before they
are standardized and converted into formal Idea records.

WHAT THIS IS:
  A staging table. An intake record is NOT an idea yet. It holds raw
  submission data (from offline form, letter scan, WhatsApp, in-person, etc.)
  until an admin standardizes it and converts it via POST /convert-to-idea.

RELATIONSHIP TO ideas TABLE:
  intake_submissions.standardized_idea_id → ideas.id (set on conversion)
"""
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.idea import SourceType, SourceProgram, ApplicantType, VisibilityScope


class IntakeStatus(str, enum.Enum):
    RAW_RECEIVED = "RAW_RECEIVED"                       # just arrived, not yet looked at
    STANDARDIZATION_PENDING = "STANDARDIZATION_PENDING" # admin started but not done
    STANDARDIZED = "STANDARDIZED"                       # fields filled, awaiting completeness check
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"   # admin flagged gaps
    READY_FOR_REVIEW = "READY_FOR_REVIEW"               # complete and ready for pipeline
    CONVERTED_TO_IDEA = "CONVERTED_TO_IDEA"             # idea record created, intake closed
    CLOSED = "CLOSED"                                   # rejected / duplicate / withdrawn


class CompletenessStatus(str, enum.Enum):
    NOT_CHECKED = "NOT_CHECKED"   # default until admin reviews
    COMPLETE = "COMPLETE"         # all required fields present
    INCOMPLETE = "INCOMPLETE"     # missing key info, needs follow-up


# Intake source types — same values as SourceType but ONLINE_FORM excluded.
# ONLINE_FORM is for self-service web submissions; intake desk handles everything else.
INTAKE_SOURCE_TYPES = frozenset([
    SourceType.OFFLINE_FORM, SourceType.LETTER_SCAN, SourceType.DOCUMENT,
    SourceType.AUDIO, SourceType.VIDEO, SourceType.PROTOTYPE_PHOTO,
    SourceType.DESIGN_SKETCH, SourceType.EMAIL_IMPORT,
    SourceType.WHATSAPP_IMPORT, SourceType.IN_PERSON, SourceType.OTHER,
])


class IntakeSubmission(Base):
    __tablename__ = "intake_submissions"

    id = Column(Integer, primary_key=True, index=True)
    intake_id = Column(String(20), unique=True, index=True, nullable=False)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_team_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Reuse existing PostgreSQL enums from migrations 0001/0002 — create_type=False
    source_type = Column(
        postgresql.ENUM(SourceType, name="sourcetype", create_type=False),
        nullable=False,
    )
    source_program = Column(
        postgresql.ENUM(SourceProgram, name="sourceprogram", create_type=False),
        nullable=True, index=True,
    )
    applicant_type = Column(
        postgresql.ENUM(ApplicantType, name="applicanttype", create_type=False),
        nullable=True,
    )
    visibility_scope = Column(
        postgresql.ENUM(VisibilityScope, name="visibilityscope", create_type=False),
        nullable=True,
    )
    source_platform = Column(String(50), nullable=True)

    original_language = Column(String(50), nullable=True)
    applicant_name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)        # nullable — may be unknown on intake
    age = Column(Integer, nullable=True)
    gender = Column(String(50), nullable=True)
    location = Column(String(255), nullable=True)
    organization = Column(String(255), nullable=True)
    team_name = Column(String(255), nullable=True)
    team_member_count = Column(Integer, nullable=True)
    team_member_names = Column(JSON, nullable=True)
    guardian_name = Column(String(255), nullable=True)
    guardian_phone = Column(String(20), nullable=True)
    guardian_email = Column(String(255), nullable=True)
    guardian_relationship = Column(String(100), nullable=True)
    guardian_consent = Column(Boolean, nullable=True)

    raw_title = Column(String(500), nullable=False)
    raw_description = Column(Text, nullable=True)
    problem_statement = Column(Text, nullable=True)
    solution_description = Column(Text, nullable=True)
    application_context = Column(Text, nullable=True)
    uniqueness = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    sub_category = Column(String(255), nullable=True)
    target_users = Column(Text, nullable=True)
    prototype_status = Column(String(100), nullable=True)
    support_needed = Column(Text, nullable=True)
    consent_data = Column(Boolean, nullable=True)
    consent_original = Column(Boolean, nullable=True)
    consent_contact = Column(Boolean, nullable=True)

    # Set when this intake is converted to a formal idea
    standardized_idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=True)

    # New PostgreSQL enums created in migration 0005
    intake_status = Column(
        postgresql.ENUM(IntakeStatus, name="intakestatus", create_type=False),
        nullable=False,
        default=IntakeStatus.RAW_RECEIVED,
    )
    completeness_status = Column(
        postgresql.ENUM(CompletenessStatus, name="completenessstatus", create_type=False),
        nullable=False,
        default=CompletenessStatus.NOT_CHECKED,
    )

    admin_notes = Column(Text, nullable=True)
    missing_information_note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    created_by = relationship("User", foreign_keys=[created_by_user_id])
    assigned_to = relationship("User", foreign_keys=[assigned_team_user_id])
    standardized_idea = relationship("Idea", foreign_keys=[standardized_idea_id])
