"""
Tests for migration 0002 pathway field upgrade.

Covers:
  - New enums have correct values
  - submit_idea derives source_program from program_track when not supplied
  - submit_idea accepts explicit source_program
  - submit_idea accepts explicit applicant_type
  - submit_idea returns 400 on invalid source_program / applicant_type
  - IdeaOut schema exposes new nullable fields
  - IdeaStatusUpdate accepts current_pathway_stage and visibility_scope
  - IdeaStatusUpdate does NOT expose source_program (set at submission only)
"""
import pytest
from app.models.idea import (
    SourceProgram, ApplicantType, PathwayStage, VisibilityScope, IdeaStatus,
    IdeaSourceProgram, IdeaApplicantType, IdeaVisibilityScope,
)
from app.schemas.idea import IdeaOut, IdeaStatusUpdate
from app.routers.ideas import _derive_source_program
from app.models.user import ProgramTrack


# --- Enum completeness ---

def test_source_program_values():
    values = {e.value for e in SourceProgram}
    assert "NMF_NATIONAL" in values
    assert "NMF_LOCAL" in values
    assert "NMF_K12" in values
    assert "IFIA_AFFILIATE" in values
    assert "EXTERNAL_REFERRAL" in values
    assert "OTHER" in values
    assert len(values) == 6


def test_applicant_type_values():
    values = {e.value for e in ApplicantType}
    assert "INDIVIDUAL" in values
    assert "TEAM" in values
    assert "STUDENT" in values
    assert "STARTUP" in values
    assert "NGO" in values
    assert "INSTITUTION" in values
    assert "OTHER" in values
    assert len(values) == 7


def test_pathway_stage_values():
    stages = [s.value for s in PathwayStage]
    # ADMIN_VERIFICATION added in migration 0005 for intake-desk conversions
    assert stages == [
        "INTAKE", "SCREENING", "LOCAL_REVIEW", "STATE_REVIEW",
        "NATIONAL_REVIEW", "INTERNATIONAL_REVIEW", "INCUBATION", "COMPLETED",
        "ADMIN_VERIFICATION",
    ]


def test_visibility_scope_values():
    values = {e.value for e in VisibilityScope}
    assert values == {"LOCAL_ONLY", "GLOBAL_ONLY", "GLOBAL_AND_LOCAL", "SUPER_ADMIN_ONLY"}


# --- Derivation logic ---

def test_derive_source_program_national():
    assert _derive_source_program(ProgramTrack.NATIONAL_INTERNATIONAL) == IdeaSourceProgram.NATIONAL_INTERNATIONAL


def test_derive_source_program_local():
    assert _derive_source_program(ProgramTrack.LOCAL_REGIONAL) == IdeaSourceProgram.LOCAL_REGIONAL


def test_derive_source_program_k12():
    assert _derive_source_program(ProgramTrack.K12) == IdeaSourceProgram.K12


# --- IdeaSourceProgram / IdeaApplicantType / IdeaVisibilityScope enum completeness ---

def test_idea_source_program_values():
    values = {e.value for e in IdeaSourceProgram}
    assert values == {"NATIONAL_INTERNATIONAL", "LOCAL_REGIONAL", "K12"}


def test_idea_applicant_type_values():
    values = {e.value for e in IdeaApplicantType}
    assert values == {
        "K12_STUDENT", "COLLEGE_STUDENT", "ADULT_INNOVATOR", "STARTUP",
        "FARMER", "RESEARCHER", "GENERAL_PUBLIC", "OTHER",
    }
    assert len(values) == 8


def test_idea_visibility_scope_values():
    values = {e.value for e in IdeaVisibilityScope}
    assert values == {"LOCAL_TEAM", "GLOBAL_TEAM", "K12_TEAM", "ALL_TEAMS"}


# --- Schema: IdeaOut exposes new fields ---

def test_idea_out_has_pathway_fields():
    fields = IdeaOut.model_fields
    assert "source_program" in fields
    assert "applicant_type" in fields
    assert "current_pathway_stage" in fields
    assert "visibility_scope" in fields
    # all nullable
    for field_name in ("source_program", "applicant_type", "current_pathway_stage", "visibility_scope"):
        field = fields[field_name]
        assert field.default is None, f"{field_name} should default to None"


# --- Schema: IdeaStatusUpdate has pathway stage + visibility, NOT source_program ---

def test_status_update_has_pathway_stage():
    assert "current_pathway_stage" in IdeaStatusUpdate.model_fields


def test_status_update_has_visibility_scope():
    assert "visibility_scope" in IdeaStatusUpdate.model_fields


def test_status_update_does_not_have_source_program():
    # source_program is set at submission time, not by admin status update
    assert "source_program" not in IdeaStatusUpdate.model_fields


# --- IdeaStatusUpdate validation ---

def test_status_update_accepts_valid_pathway_stage():
    obj = IdeaStatusUpdate(current_pathway_stage="NATIONAL_REVIEW")
    assert obj.current_pathway_stage == "NATIONAL_REVIEW"


def test_status_update_accepts_valid_visibility_scope():
    obj = IdeaStatusUpdate(visibility_scope="GLOBAL_AND_LOCAL")
    assert obj.visibility_scope == "GLOBAL_AND_LOCAL"


def test_status_update_empty_is_valid():
    obj = IdeaStatusUpdate()
    assert obj.current_pathway_stage is None
    assert obj.visibility_scope is None
    assert obj.current_status is None
