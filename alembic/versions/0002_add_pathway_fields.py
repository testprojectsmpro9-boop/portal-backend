"""Add pathway fields: source_program, applicant_type, current_pathway_stage, visibility_scope

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-09

WHAT WAS EXISTING:
  ideas table had program_track (NATIONAL_INTERNATIONAL / LOCAL_REGIONAL / K12) as the only
  classification field. Admin visibility filtering was purely program_track-based.

WHAT WE UPGRADED:
  Added 4 new nullable columns + their PostgreSQL enum types:
    - source_program      (SourceProgram)  — which NMF program/portal idea came from
    - applicant_type      (ApplicantType)  — individual / team / student / startup etc.
    - current_pathway_stage (PathwayStage) — structured pipeline level (replaces free-text stage)
    - visibility_scope    (VisibilityScope) — cross-track admin visibility override

WHY:
  program_track alone couldn't handle:
    1. K12 students submitting via national portal
    2. Local ideas promoted to national-level review
    3. Ideas visible to both GLOBAL and LOCAL admin teams simultaneously
  These scenarios needed explicit fields rather than inference from program_track.

BACKFILL LOGIC:
  Existing rows get source_program derived from program_track:
    NATIONAL_INTERNATIONAL → NMF_NATIONAL
    LOCAL_REGIONAL         → NMF_LOCAL
    K12                    → NMF_K12
  Other new fields remain NULL for existing rows (admin can set via PATCH /status).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- Create new enum types (checkfirst=True = safe if run twice) ---
    sa.Enum(
        "NMF_NATIONAL", "NMF_LOCAL", "NMF_K12", "IFIA_AFFILIATE", "EXTERNAL_REFERRAL", "OTHER",
        name="sourceprogram",
    ).create(bind, checkfirst=True)

    sa.Enum(
        "INDIVIDUAL", "TEAM", "STUDENT", "STARTUP", "NGO", "INSTITUTION", "OTHER",
        name="applicanttype",
    ).create(bind, checkfirst=True)

    sa.Enum(
        "INTAKE", "SCREENING", "LOCAL_REVIEW", "STATE_REVIEW",
        "NATIONAL_REVIEW", "INTERNATIONAL_REVIEW", "INCUBATION", "COMPLETED",
        name="pathwaystage",
    ).create(bind, checkfirst=True)

    sa.Enum(
        "LOCAL_ONLY", "GLOBAL_ONLY", "GLOBAL_AND_LOCAL", "SUPER_ADMIN_ONLY",
        name="visibilityscope",
    ).create(bind, checkfirst=True)

    # --- Add new nullable columns to ideas (create_type=False: enum already created above) ---
    op.add_column("ideas", sa.Column(
        "source_program",
        sa.Enum(name="sourceprogram", create_type=False),
        nullable=True,
    ))
    op.add_column("ideas", sa.Column(
        "applicant_type",
        sa.Enum(name="applicanttype", create_type=False),
        nullable=True,
    ))
    op.add_column("ideas", sa.Column(
        "current_pathway_stage",
        sa.Enum(name="pathwaystage", create_type=False),
        nullable=True,
    ))
    op.add_column("ideas", sa.Column(
        "visibility_scope",
        sa.Enum(name="visibilityscope", create_type=False),
        nullable=True,
    ))

    # --- Backfill source_program from program_track for existing rows ---
    bind.execute(sa.text("""
        UPDATE ideas
        SET source_program = CASE program_track
            WHEN 'NATIONAL_INTERNATIONAL' THEN 'NMF_NATIONAL'::sourceprogram
            WHEN 'LOCAL_REGIONAL'         THEN 'NMF_LOCAL'::sourceprogram
            WHEN 'K12'                    THEN 'NMF_K12'::sourceprogram
            ELSE 'OTHER'::sourceprogram
        END
        WHERE source_program IS NULL
    """))


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_column("ideas", "visibility_scope")
    op.drop_column("ideas", "current_pathway_stage")
    op.drop_column("ideas", "applicant_type")
    op.drop_column("ideas", "source_program")

    sa.Enum(name="visibilityscope").drop(bind, checkfirst=True)
    sa.Enum(name="pathwaystage").drop(bind, checkfirst=True)
    sa.Enum(name="applicanttype").drop(bind, checkfirst=True)
    sa.Enum(name="sourceprogram").drop(bind, checkfirst=True)
