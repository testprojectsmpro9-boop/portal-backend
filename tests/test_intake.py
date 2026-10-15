"""
Tests for the Admin Intake Desk module.

Unit tests — no DB required:
  - IntakeStatus enum completeness and values
  - CompletenessStatus enum completeness
  - INTAKE_SOURCE_TYPES excludes ONLINE_FORM, includes all others
  - IntakeSubmissionCreate requires applicant_name and raw_title
  - IntakeSubmissionOut has all expected fields
  - IntakeSubmissionUpdate is fully optional
  - _default_source_program per role
  - _default_visibility_scope per role
  - _source_program_to_track mapping (all 6 SourceProgram values)
  - _assert_program_scope: TEAM_ADMIN_GLOBAL blocked from LOCAL
  - _assert_program_scope: TEAM_ADMIN_LOCAL blocked from GLOBAL
  - _assert_program_scope: SUPER_ADMIN passes all
  - _generate_intake_id format
  - MoreInfoRequest requires missing_information_note
  - PathwayStage now has ADMIN_VERIFICATION (added for intake conversion)
"""
import pytest
from unittest.mock import MagicMock

from app.models.intake import (
    IntakeSubmission, IntakeStatus, CompletenessStatus, INTAKE_SOURCE_TYPES,
)
from app.models.idea import (
    SourceProgram, VisibilityScope, PathwayStage, SourceType, ApplicantType,
    IdeaSourceProgram, IdeaApplicantType, IdeaVisibilityScope, IdeaCategory,
)
from app.models.user import UserRole
from app.schemas.intake import (
    IntakeSubmissionCreate, IntakeSubmissionUpdate,
    IntakeSubmissionOut, MoreInfoRequest,
)
from app.routers.intake import (
    _default_source_program, _default_visibility_scope,
    _source_program_to_track, _assert_program_scope,
    _map_source_program, _map_applicant_type, _map_visibility_scope,
    _parse_raw_description, _section, _safe_category, _clean,
    GLOBAL_PROGRAMS, LOCAL_PROGRAMS,
)
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# IntakeStatus enum
# ---------------------------------------------------------------------------

def test_intake_status_values():
    values = {s.value for s in IntakeStatus}
    assert values == {
        "RAW_RECEIVED", "STANDARDIZATION_PENDING", "STANDARDIZED",
        "NEEDS_MORE_INFORMATION", "READY_FOR_REVIEW", "CONVERTED_TO_IDEA", "CLOSED",
    }
    assert len(values) == 7


def test_intake_status_order():
    # Ensure key progression states exist and are distinct
    assert IntakeStatus.RAW_RECEIVED != IntakeStatus.CONVERTED_TO_IDEA
    assert IntakeStatus.NEEDS_MORE_INFORMATION != IntakeStatus.READY_FOR_REVIEW


# ---------------------------------------------------------------------------
# CompletenessStatus enum
# ---------------------------------------------------------------------------

def test_completeness_status_values():
    values = {s.value for s in CompletenessStatus}
    assert values == {"NOT_CHECKED", "COMPLETE", "INCOMPLETE"}
    assert len(values) == 3


# ---------------------------------------------------------------------------
# INTAKE_SOURCE_TYPES
# ---------------------------------------------------------------------------

def test_intake_source_types_excludes_online_form():
    assert SourceType.ONLINE_FORM not in INTAKE_SOURCE_TYPES


def test_intake_source_types_contains_all_offline_types():
    expected = {
        SourceType.OFFLINE_FORM, SourceType.LETTER_SCAN, SourceType.DOCUMENT,
        SourceType.AUDIO, SourceType.VIDEO, SourceType.PROTOTYPE_PHOTO,
        SourceType.DESIGN_SKETCH, SourceType.EMAIL_IMPORT,
        SourceType.WHATSAPP_IMPORT, SourceType.IN_PERSON, SourceType.OTHER,
    }
    assert INTAKE_SOURCE_TYPES == expected
    assert len(INTAKE_SOURCE_TYPES) == 11


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

def test_intake_create_required_fields():
    fields = IntakeSubmissionCreate.model_fields
    required = [name for name, f in fields.items() if f.is_required()]
    assert "applicant_name" in required
    assert "raw_title" in required
    assert "source_type" in required


def test_intake_create_optional_fields():
    # Should not raise with only required fields
    obj = IntakeSubmissionCreate(
        source_type="OFFLINE_FORM",
        applicant_name="Test Applicant",
        raw_title="My Invention",
    )
    assert obj.applicant_name == "Test Applicant"
    assert obj.source_program is None
    assert obj.email is None


def test_intake_create_accepts_structured_fields():
    obj = IntakeSubmissionCreate(
        source_type="OFFLINE_FORM",
        applicant_name="Test Applicant",
        raw_title="My Invention",
        problem_statement="Manual sorting is slow.",
        solution_description="A low-cost sorting aid.",
        category="Waste Management",
        sub_category="School bins",
        target_users="Students",
        prototype_status="Concept",
        support_needed="Mentorship",
    )
    assert obj.problem_statement == "Manual sorting is slow."
    assert obj.solution_description == "A low-cost sorting aid."
    assert obj.category == "WASTE_MANAGEMENT"
    assert obj.prototype_status == "CONCEPT_NOTE"


def test_intake_update_all_optional():
    obj = IntakeSubmissionUpdate()
    for field in IntakeSubmissionUpdate.model_fields:
        assert getattr(obj, field) is None


def test_intake_out_fields():
    fields = set(IntakeSubmissionOut.model_fields.keys())
    required = {
        "id", "intake_id", "created_by_user_id", "source_type",
        "applicant_name", "raw_title", "intake_status", "completeness_status",
        "created_at", "updated_at",
    }
    assert required.issubset(fields)
    assert "admin_notes" in fields
    assert "missing_information_note" in fields
    assert "standardized_idea_id" in fields
    assert {
        "problem_statement", "solution_description", "category", "sub_category",
        "target_users", "prototype_status", "support_needed",
    }.issubset(fields)
    assert {
        "team_name", "team_member_count", "team_member_names",
        "guardian_name", "guardian_phone", "guardian_email", "guardian_relationship",
        "guardian_consent", "gender", "application_context", "uniqueness",
        "consent_data", "consent_original", "consent_contact",
    }.issubset(fields)


def test_intake_model_has_structured_columns():
    columns = set(IntakeSubmission.__table__.columns.keys())
    assert {
        "problem_statement", "solution_description", "category", "sub_category",
        "target_users", "prototype_status", "support_needed",
    }.issubset(columns)
    assert {
        "team_name", "team_member_count", "team_member_names",
        "guardian_name", "guardian_phone", "guardian_email", "guardian_relationship",
        "guardian_consent", "gender", "application_context", "uniqueness",
        "consent_data", "consent_original", "consent_contact",
    }.issubset(columns)


def test_intake_create_requires_team_fields_for_team_applicant():
    with pytest.raises(ValueError):
        IntakeSubmissionCreate(
            source_type="OFFLINE_FORM",
            applicant_type="TEAM",
            applicant_name="Team Applicant",
            raw_title="Team Idea",
        )


def test_intake_create_requires_guardian_fields_for_k12():
    with pytest.raises(ValueError):
        IntakeSubmissionCreate(
            source_type="OFFLINE_FORM",
            source_program="NMF_K12",
            applicant_name="Student Applicant",
            raw_title="Student Idea",
        )


def test_intake_create_accepts_team_and_guardian_alignment_fields():
    obj = IntakeSubmissionCreate(
        source_type="OFFLINE_FORM",
        source_program="NMF_K12",
        applicant_type="TEAM",
        applicant_name="Student Team",
        raw_title="Student Team Idea",
        team_name="Young Makers",
        team_member_count=2,
        team_member_names=["Lead", "Member"],
        guardian_name="Parent One",
        guardian_phone="9999999999",
        guardian_relationship="Mother",
        guardian_consent=True,
        gender="Prefer not to say",
        application_context="School lab",
        uniqueness="Low-cost build",
        consent_data=True,
        consent_original=True,
        consent_contact=True,
    )

    assert obj.team_name == "Young Makers"
    assert obj.team_member_names == ["Lead", "Member"]
    assert obj.guardian_consent is True


def test_more_info_request_requires_note():
    fields = MoreInfoRequest.model_fields
    required = [n for n, f in fields.items() if f.is_required()]
    assert "missing_information_note" in required


# ---------------------------------------------------------------------------
# Default source_program per role
# ---------------------------------------------------------------------------

def test_default_source_program_global_admin():
    assert _default_source_program(UserRole.TEAM_ADMIN_GLOBAL) == SourceProgram.NMF_NATIONAL


def test_default_source_program_local_admin():
    assert _default_source_program(UserRole.TEAM_ADMIN_LOCAL) == SourceProgram.NMF_LOCAL


def test_default_source_program_super_admin():
    # Super admin gets a valid default (not None)
    result = _default_source_program(UserRole.SUPER_ADMIN)
    assert result in SourceProgram.__members__.values()


# ---------------------------------------------------------------------------
# Default visibility_scope per role
# ---------------------------------------------------------------------------

def test_default_visibility_scope_global_admin():
    assert _default_visibility_scope(UserRole.TEAM_ADMIN_GLOBAL) == VisibilityScope.GLOBAL_ONLY


def test_default_visibility_scope_local_admin():
    assert _default_visibility_scope(UserRole.TEAM_ADMIN_LOCAL) == VisibilityScope.LOCAL_ONLY


def test_default_visibility_scope_super_admin():
    result = _default_visibility_scope(UserRole.SUPER_ADMIN)
    assert result in VisibilityScope.__members__.values()


# ---------------------------------------------------------------------------
# source_program → program_track mapping
# ---------------------------------------------------------------------------

from app.models.user import ProgramTrack

def test_source_program_to_track_national():
    assert _source_program_to_track(SourceProgram.NMF_NATIONAL) == ProgramTrack.NATIONAL_INTERNATIONAL


def test_source_program_to_track_ifia():
    assert _source_program_to_track(SourceProgram.IFIA_AFFILIATE) == ProgramTrack.NATIONAL_INTERNATIONAL


def test_source_program_to_track_external():
    assert _source_program_to_track(SourceProgram.EXTERNAL_REFERRAL) == ProgramTrack.NATIONAL_INTERNATIONAL


def test_source_program_to_track_local():
    assert _source_program_to_track(SourceProgram.NMF_LOCAL) == ProgramTrack.LOCAL_REGIONAL


def test_source_program_to_track_k12():
    assert _source_program_to_track(SourceProgram.NMF_K12) == ProgramTrack.K12


def test_source_program_to_track_other():
    result = _source_program_to_track(SourceProgram.OTHER)
    assert result in (ProgramTrack.LOCAL_REGIONAL, ProgramTrack.NATIONAL_INTERNATIONAL)


# ---------------------------------------------------------------------------
# Scope assertions
# ---------------------------------------------------------------------------

def _mock_user(role: UserRole) -> MagicMock:
    u = MagicMock()
    u.role = role
    return u


def test_scope_super_admin_allowed_for_all():
    user = _mock_user(UserRole.SUPER_ADMIN)
    for sp in SourceProgram:
        _assert_program_scope(sp, user)  # must not raise


def test_scope_global_admin_allowed_for_global_programs():
    user = _mock_user(UserRole.TEAM_ADMIN_GLOBAL)
    for sp in GLOBAL_PROGRAMS:
        _assert_program_scope(sp, user)  # must not raise


def test_scope_global_admin_blocked_from_local_programs():
    user = _mock_user(UserRole.TEAM_ADMIN_GLOBAL)
    for sp in LOCAL_PROGRAMS:
        with pytest.raises(HTTPException) as exc:
            _assert_program_scope(sp, user)
        assert exc.value.status_code == 403


def test_scope_local_admin_allowed_for_local_programs():
    user = _mock_user(UserRole.TEAM_ADMIN_LOCAL)
    for sp in LOCAL_PROGRAMS:
        _assert_program_scope(sp, user)  # must not raise


def test_scope_local_admin_blocked_from_global_programs():
    user = _mock_user(UserRole.TEAM_ADMIN_LOCAL)
    for sp in GLOBAL_PROGRAMS:
        with pytest.raises(HTTPException) as exc:
            _assert_program_scope(sp, user)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# GLOBAL_PROGRAMS and LOCAL_PROGRAMS are disjoint
# ---------------------------------------------------------------------------

def test_scope_sets_are_disjoint():
    assert GLOBAL_PROGRAMS.isdisjoint(LOCAL_PROGRAMS)


# ---------------------------------------------------------------------------
# PathwayStage has ADMIN_VERIFICATION (added in migration 0005)
# ---------------------------------------------------------------------------

def test_pathway_stage_has_admin_verification():
    assert "ADMIN_VERIFICATION" in {s.value for s in PathwayStage}


# ---------------------------------------------------------------------------
# _map_source_program
# ---------------------------------------------------------------------------

def test_map_source_program_national():
    assert _map_source_program(SourceProgram.NMF_NATIONAL) == IdeaSourceProgram.NATIONAL_INTERNATIONAL


def test_map_source_program_ifia():
    assert _map_source_program(SourceProgram.IFIA_AFFILIATE) == IdeaSourceProgram.NATIONAL_INTERNATIONAL


def test_map_source_program_external():
    assert _map_source_program(SourceProgram.EXTERNAL_REFERRAL) == IdeaSourceProgram.NATIONAL_INTERNATIONAL


def test_map_source_program_local():
    assert _map_source_program(SourceProgram.NMF_LOCAL) == IdeaSourceProgram.LOCAL_REGIONAL


def test_map_source_program_k12():
    assert _map_source_program(SourceProgram.NMF_K12) == IdeaSourceProgram.K12


def test_map_source_program_other():
    result = _map_source_program(SourceProgram.OTHER)
    assert result in (IdeaSourceProgram.LOCAL_REGIONAL, IdeaSourceProgram.NATIONAL_INTERNATIONAL)


# ---------------------------------------------------------------------------
# _map_applicant_type (age-aware)
# ---------------------------------------------------------------------------

def test_map_applicant_type_student_under_18():
    assert _map_applicant_type(ApplicantType.STUDENT, 15) == IdeaApplicantType.K12_STUDENT


def test_map_applicant_type_student_exactly_18():
    assert _map_applicant_type(ApplicantType.STUDENT, 18) == IdeaApplicantType.K12_STUDENT


def test_map_applicant_type_student_over_18():
    assert _map_applicant_type(ApplicantType.STUDENT, 22) == IdeaApplicantType.COLLEGE_STUDENT


def test_map_applicant_type_student_no_age():
    assert _map_applicant_type(ApplicantType.STUDENT, None) == IdeaApplicantType.COLLEGE_STUDENT


def test_map_applicant_type_individual():
    assert _map_applicant_type(ApplicantType.INDIVIDUAL, None) == IdeaApplicantType.ADULT_INNOVATOR


def test_map_applicant_type_team():
    assert _map_applicant_type(ApplicantType.TEAM, None) == IdeaApplicantType.ADULT_INNOVATOR


def test_map_applicant_type_startup():
    assert _map_applicant_type(ApplicantType.STARTUP, None) == IdeaApplicantType.STARTUP


def test_map_applicant_type_ngo():
    assert _map_applicant_type(ApplicantType.NGO, None) == IdeaApplicantType.GENERAL_PUBLIC


def test_map_applicant_type_institution():
    assert _map_applicant_type(ApplicantType.INSTITUTION, None) == IdeaApplicantType.RESEARCHER


def test_map_applicant_type_other():
    assert _map_applicant_type(ApplicantType.OTHER, None) == IdeaApplicantType.OTHER


def test_map_applicant_type_none():
    assert _map_applicant_type(None, None) == IdeaApplicantType.GENERAL_PUBLIC


# ---------------------------------------------------------------------------
# _map_visibility_scope (K12 source_program → K12_TEAM)
# ---------------------------------------------------------------------------

def test_map_visibility_scope_k12_source_always_k12_team():
    # K12 source overrides any visibility_scope
    for vs in list(VisibilityScope) + [None]:
        result = _map_visibility_scope(SourceProgram.NMF_K12, vs)
        assert result == IdeaVisibilityScope.K12_TEAM, f"Expected K12_TEAM for vs={vs}"


def test_map_visibility_scope_global_only():
    assert _map_visibility_scope(SourceProgram.NMF_NATIONAL, VisibilityScope.GLOBAL_ONLY) == IdeaVisibilityScope.GLOBAL_TEAM


def test_map_visibility_scope_local_only():
    assert _map_visibility_scope(SourceProgram.NMF_LOCAL, VisibilityScope.LOCAL_ONLY) == IdeaVisibilityScope.LOCAL_TEAM


def test_map_visibility_scope_global_and_local():
    assert _map_visibility_scope(SourceProgram.NMF_NATIONAL, VisibilityScope.GLOBAL_AND_LOCAL) == IdeaVisibilityScope.ALL_TEAMS


def test_map_visibility_scope_super_admin_only():
    assert _map_visibility_scope(SourceProgram.NMF_NATIONAL, VisibilityScope.SUPER_ADMIN_ONLY) == IdeaVisibilityScope.ALL_TEAMS


def test_map_visibility_scope_none_defaults_to_local():
    assert _map_visibility_scope(SourceProgram.NMF_LOCAL, None) == IdeaVisibilityScope.LOCAL_TEAM


# ---------------------------------------------------------------------------
# raw_description parsing for convert-to-idea
# ---------------------------------------------------------------------------

def test_parse_raw_description_sections():
    raw = (
        "Problem: Waste is not segregated properly.\n\n"
        "Solution: Smart box separates waste.\n\n"
        "Category: Waste Management\n\n"
        "Sub-category: School bins\n\n"
        "Target Users / Beneficiaries: Students and community\n\n"
        "Prototype Status: Concept\n\n"
        "Support Needed: Mentorship, Technical Support"
    )
    sections = _parse_raw_description(raw)
    assert _section(sections, "Problem") == "Waste is not segregated properly."
    assert _section(sections, "Solution") == "Smart box separates waste."
    assert _section(sections, "Category") == "Waste Management"
    assert _section(sections, "Sub-category") == "School bins"
    assert _section(sections, "Target Users / Beneficiaries") == "Students and community"
    assert _section(sections, "Prototype Status") == "Concept"
    assert _section(sections, "Support Needed") == "Mentorship, Technical Support"


def test_safe_category_maps_unknown_to_others():
    assert _safe_category("Waste Management") == IdeaCategory.WASTE_MANAGEMENT
    assert _safe_category("WASTE_MANAGEMENT") == IdeaCategory.WASTE_MANAGEMENT
    assert _safe_category("Technology") == IdeaCategory.AI_SOFTWARE
    assert _safe_category("Not A Category") == IdeaCategory.OTHERS


def test_clean_strips_and_maps_empty_to_none():
    assert _clean("  value  ") == "value"
    assert _clean("   ") is None
    assert _clean(None) is None
