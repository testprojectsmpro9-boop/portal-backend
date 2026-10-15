"""Update ideas table enum columns to ideas-specific types

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-10

WHAT WAS EXISTING:
  ideas.source_program  → old sourceprogramtype PG enum (NMF_NATIONAL, NMF_LOCAL, NMF_K12, etc.)
  ideas.applicant_type  → old applicanttypetype PG enum (INDIVIDUAL, TEAM, STUDENT, etc.)
  ideas.visibility_scope → old visibilityscopetype PG enum (LOCAL_ONLY, GLOBAL_ONLY, etc.)

WHY THIS CHANGE:
  Intake API and Ideas API use different enum naming conventions.
  Intake uses NMF_* naming (SourceProgram: NMF_NATIONAL, NMF_LOCAL, NMF_K12).
  Ideas now use track-aligned values (IdeaSourceProgram: NATIONAL_INTERNATIONAL, LOCAL_REGIONAL, K12).
  IdeaApplicantType adds richer roles: K12_STUDENT, COLLEGE_STUDENT, ADULT_INNOVATOR, FARMER, RESEARCHER, GENERAL_PUBLIC.
  IdeaVisibilityScope uses team-aligned names: LOCAL_TEAM, GLOBAL_TEAM, K12_TEAM, ALL_TEAMS.
  convert-to-idea maps Intake enums → Idea enums so both tables stay consistent.

WHAT THIS MIGRATION DOES:
  1. Creates 3 new PostgreSQL enum types:
       ideasourceprogram  (NATIONAL_INTERNATIONAL, LOCAL_REGIONAL, K12)
       ideaapplicanttype  (K12_STUDENT, COLLEGE_STUDENT, ADULT_INNOVATOR, STARTUP, FARMER, RESEARCHER, GENERAL_PUBLIC, OTHER)
       ideavisibilityscope (LOCAL_TEAM, GLOBAL_TEAM, K12_TEAM, ALL_TEAMS)
  2. Adds 3 new temporary columns on ideas:
       _source_program_new, _applicant_type_new, _visibility_scope_new
  3. Backfills the new columns from old values using CASE mapping.
  4. Drops old columns, renames new columns to the original names.
  5. Old PG enum types (sourceprogramtype, applicanttypetype, visibilityscopetype) are kept —
     they are still used by intake_submissions table.

BACKFILL RULES:
  source_program:
    NMF_NATIONAL, IFIA_AFFILIATE, EXTERNAL_REFERRAL → NATIONAL_INTERNATIONAL
    NMF_LOCAL → LOCAL_REGIONAL
    NMF_K12 → K12
    OTHER/NULL → NULL (leave null, admin can correct)
  applicant_type:
    INDIVIDUAL, TEAM → ADULT_INNOVATOR
    STUDENT (age <= 18) → K12_STUDENT  (age > 18 or unknown → COLLEGE_STUDENT)
    STARTUP → STARTUP
    NGO → GENERAL_PUBLIC
    INSTITUTION → RESEARCHER
    OTHER → OTHER
    NULL → NULL
  visibility_scope:
    GLOBAL_ONLY → GLOBAL_TEAM
    LOCAL_ONLY → LOCAL_TEAM
    GLOBAL_AND_LOCAL → ALL_TEAMS
    SUPER_ADMIN_ONLY → ALL_TEAMS
    NULL → NULL
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_ideasourceprogram = postgresql.ENUM(
    "NATIONAL_INTERNATIONAL", "LOCAL_REGIONAL", "K12",
    name="ideasourceprogram",
)

_ideaapplicanttype = postgresql.ENUM(
    "K12_STUDENT", "COLLEGE_STUDENT", "ADULT_INNOVATOR", "STARTUP",
    "FARMER", "RESEARCHER", "GENERAL_PUBLIC", "OTHER",
    name="ideaapplicanttype",
)

_ideavisibilityscope = postgresql.ENUM(
    "LOCAL_TEAM", "GLOBAL_TEAM", "K12_TEAM", "ALL_TEAMS",
    name="ideavisibilityscope",
)


def upgrade():
    bind = op.get_bind()

    # Step 1 — create new enum types (idempotent)
    _ideasourceprogram.create(bind, checkfirst=True)
    _ideaapplicanttype.create(bind, checkfirst=True)
    _ideavisibilityscope.create(bind, checkfirst=True)

    # Step 2 — add new temp columns
    bind.execute(sa.text("""
        DO $do$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = '_source_program_new'
            ) THEN
                ALTER TABLE ideas ADD COLUMN _source_program_new ideasourceprogram;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = '_applicant_type_new'
            ) THEN
                ALTER TABLE ideas ADD COLUMN _applicant_type_new ideaapplicanttype;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = '_visibility_scope_new'
            ) THEN
                ALTER TABLE ideas ADD COLUMN _visibility_scope_new ideavisibilityscope;
            END IF;
        END $do$;
    """))

    # Step 3 — backfill new columns from old values
    bind.execute(sa.text("""
        UPDATE ideas SET _source_program_new = CASE source_program::text
            WHEN 'NMF_NATIONAL'       THEN 'NATIONAL_INTERNATIONAL'::ideasourceprogram
            WHEN 'IFIA_AFFILIATE'     THEN 'NATIONAL_INTERNATIONAL'::ideasourceprogram
            WHEN 'EXTERNAL_REFERRAL'  THEN 'NATIONAL_INTERNATIONAL'::ideasourceprogram
            WHEN 'NMF_LOCAL'          THEN 'LOCAL_REGIONAL'::ideasourceprogram
            WHEN 'NMF_K12'            THEN 'K12'::ideasourceprogram
            ELSE NULL
        END
        WHERE source_program IS NOT NULL;
    """))

    bind.execute(sa.text("""
        UPDATE ideas SET _applicant_type_new = CASE
            WHEN applicant_type::text = 'STUDENT' AND age IS NOT NULL AND age <= 18
                THEN 'K12_STUDENT'::ideaapplicanttype
            WHEN applicant_type::text = 'STUDENT'
                THEN 'COLLEGE_STUDENT'::ideaapplicanttype
            WHEN applicant_type::text IN ('INDIVIDUAL', 'TEAM')
                THEN 'ADULT_INNOVATOR'::ideaapplicanttype
            WHEN applicant_type::text = 'STARTUP'
                THEN 'STARTUP'::ideaapplicanttype
            WHEN applicant_type::text = 'NGO'
                THEN 'GENERAL_PUBLIC'::ideaapplicanttype
            WHEN applicant_type::text = 'INSTITUTION'
                THEN 'RESEARCHER'::ideaapplicanttype
            WHEN applicant_type::text = 'OTHER'
                THEN 'OTHER'::ideaapplicanttype
            ELSE NULL
        END
        WHERE applicant_type IS NOT NULL;
    """))

    bind.execute(sa.text("""
        UPDATE ideas SET _visibility_scope_new = CASE visibility_scope::text
            WHEN 'GLOBAL_ONLY'       THEN 'GLOBAL_TEAM'::ideavisibilityscope
            WHEN 'LOCAL_ONLY'        THEN 'LOCAL_TEAM'::ideavisibilityscope
            WHEN 'GLOBAL_AND_LOCAL'  THEN 'ALL_TEAMS'::ideavisibilityscope
            WHEN 'SUPER_ADMIN_ONLY'  THEN 'ALL_TEAMS'::ideavisibilityscope
            ELSE NULL
        END
        WHERE visibility_scope IS NOT NULL;
    """))

    # Step 4 — drop old columns, rename new columns
    bind.execute(sa.text("""
        DO $do$
        BEGIN
            -- source_program
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = 'source_program'
            ) THEN
                ALTER TABLE ideas DROP COLUMN source_program;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = '_source_program_new'
            ) THEN
                ALTER TABLE ideas RENAME COLUMN _source_program_new TO source_program;
            END IF;

            -- applicant_type
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = 'applicant_type'
            ) THEN
                ALTER TABLE ideas DROP COLUMN applicant_type;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = '_applicant_type_new'
            ) THEN
                ALTER TABLE ideas RENAME COLUMN _applicant_type_new TO applicant_type;
            END IF;

            -- visibility_scope
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = 'visibility_scope'
            ) THEN
                ALTER TABLE ideas DROP COLUMN visibility_scope;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ideas' AND column_name = '_visibility_scope_new'
            ) THEN
                ALTER TABLE ideas RENAME COLUMN _visibility_scope_new TO visibility_scope;
            END IF;
        END $do$;
    """))


def downgrade():
    # Restore old enum types and columns (data loss: new values not mappable back)
    bind = op.get_bind()

    # Re-create old enum types if missing (they may still exist from intake_submissions)
    _old_sourceprogram = postgresql.ENUM(
        "NMF_NATIONAL", "NMF_LOCAL", "NMF_K12", "IFIA_AFFILIATE", "EXTERNAL_REFERRAL", "OTHER",
        name="sourceprogramtype",
    )
    _old_applicanttype = postgresql.ENUM(
        "INDIVIDUAL", "TEAM", "STUDENT", "STARTUP", "NGO", "INSTITUTION", "OTHER",
        name="applicanttypetype",
    )
    _old_visibilityscope = postgresql.ENUM(
        "LOCAL_ONLY", "GLOBAL_ONLY", "GLOBAL_AND_LOCAL", "SUPER_ADMIN_ONLY",
        name="visibilityscopetype",
    )
    _old_sourceprogram.create(bind, checkfirst=True)
    _old_applicanttype.create(bind, checkfirst=True)
    _old_visibilityscope.create(bind, checkfirst=True)

    # Add temp old-style columns
    bind.execute(sa.text("""
        ALTER TABLE ideas
            ADD COLUMN IF NOT EXISTS _sp_old sourceprogramtype,
            ADD COLUMN IF NOT EXISTS _at_old applicanttypetype,
            ADD COLUMN IF NOT EXISTS _vs_old visibilityscopetype;
    """))

    # Best-effort reverse backfill
    bind.execute(sa.text("""
        UPDATE ideas SET _sp_old = CASE source_program::text
            WHEN 'NATIONAL_INTERNATIONAL' THEN 'NMF_NATIONAL'::sourceprogramtype
            WHEN 'LOCAL_REGIONAL'         THEN 'NMF_LOCAL'::sourceprogramtype
            WHEN 'K12'                    THEN 'NMF_K12'::sourceprogramtype
            ELSE NULL
        END WHERE source_program IS NOT NULL;
    """))

    bind.execute(sa.text("""
        UPDATE ideas SET _vs_old = CASE visibility_scope::text
            WHEN 'GLOBAL_TEAM' THEN 'GLOBAL_ONLY'::visibilityscopetype
            WHEN 'LOCAL_TEAM'  THEN 'LOCAL_ONLY'::visibilityscopetype
            WHEN 'K12_TEAM'    THEN 'LOCAL_ONLY'::visibilityscopetype
            WHEN 'ALL_TEAMS'   THEN 'GLOBAL_AND_LOCAL'::visibilityscopetype
            ELSE NULL
        END WHERE visibility_scope IS NOT NULL;
    """))

    bind.execute(sa.text("""
        UPDATE ideas SET _at_old = CASE applicant_type::text
            WHEN 'ADULT_INNOVATOR' THEN 'INDIVIDUAL'::applicanttypetype
            WHEN 'K12_STUDENT'     THEN 'STUDENT'::applicanttypetype
            WHEN 'COLLEGE_STUDENT' THEN 'STUDENT'::applicanttypetype
            WHEN 'STARTUP'         THEN 'STARTUP'::applicanttypetype
            WHEN 'RESEARCHER'      THEN 'INSTITUTION'::applicanttypetype
            WHEN 'GENERAL_PUBLIC'  THEN 'INDIVIDUAL'::applicanttypetype
            WHEN 'FARMER'          THEN 'INDIVIDUAL'::applicanttypetype
            WHEN 'OTHER'           THEN 'OTHER'::applicanttypetype
            ELSE NULL
        END WHERE applicant_type IS NOT NULL;
    """))

    bind.execute(sa.text("""
        DO $do$
        BEGIN
            ALTER TABLE ideas DROP COLUMN IF EXISTS source_program;
            ALTER TABLE ideas RENAME COLUMN _sp_old TO source_program;
            ALTER TABLE ideas DROP COLUMN IF EXISTS applicant_type;
            ALTER TABLE ideas RENAME COLUMN _at_old TO applicant_type;
            ALTER TABLE ideas DROP COLUMN IF EXISTS visibility_scope;
            ALTER TABLE ideas RENAME COLUMN _vs_old TO visibility_scope;
        END $do$;
    """))

    _ideasourceprogram.drop(bind, checkfirst=True)
    _ideaapplicanttype.drop(bind, checkfirst=True)
    _ideavisibilityscope.drop(bind, checkfirst=True)
