import json
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.idea import Idea, IdeaApplicantType, IdeaCategory, IdeaSourceProgram, IdeaStatus, SourceType
from app.models.idea_file import FileType, IdeaFile
from app.models.user import ProgramTrack
from app.schemas.idea import IdeaCreate, IdeaOut
from app.services.file_service import save_file, validate_file
from app.services.id_generator import generate_unique_year_id
from app.services.idea_notification_service import notify_public_idea_submission
from app.services.rate_limit import assert_rate_limit
from app.services.audit_log_service import record_audit_log
from app.utils.category import coerce_idea_category

router = APIRouter(prefix="/ideas", tags=["ideas"])


def _generate_application_id(db: Session) -> str:
    return generate_unique_year_id(
        db=db,
        model=Idea,
        column_name="application_id",
        prefix=settings.APPLICATION_ID_PREFIX,
    )


def _derive_source_program(program_track: ProgramTrack) -> IdeaSourceProgram:
    mapping = {
        ProgramTrack.NATIONAL_INTERNATIONAL: IdeaSourceProgram.NATIONAL_INTERNATIONAL,
        ProgramTrack.LOCAL_REGIONAL: IdeaSourceProgram.LOCAL_REGIONAL,
        ProgramTrack.K12: IdeaSourceProgram.K12,
    }
    return mapping.get(program_track, IdeaSourceProgram.NATIONAL_INTERNATIONAL)


def _coerce_category(value: str | None) -> IdeaCategory | None:
    return coerce_idea_category(value)


def _create_idea(payload: IdeaCreate, db: Session, commit: bool = True) -> Idea:
    try:
        program_track = ProgramTrack(payload.program_track)
    except ValueError:
        valid = [t.value for t in ProgramTrack]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid program_track '{payload.program_track}'. Valid: {valid}",
        )

    try:
        source_type = SourceType(payload.source_type)
    except ValueError:
        valid = [s.value for s in SourceType]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source_type '{payload.source_type}'. Valid: {valid}",
        )

    if payload.source_program:
        try:
            source_program = IdeaSourceProgram(payload.source_program)
        except ValueError:
            valid = [s.value for s in IdeaSourceProgram]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source_program '{payload.source_program}'. Valid: {valid}",
            )
    else:
        source_program = _derive_source_program(program_track)

    applicant_type = None
    if payload.applicant_type:
        try:
            applicant_type = IdeaApplicantType(payload.applicant_type)
        except ValueError:
            valid = [a.value for a in IdeaApplicantType]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid applicant_type '{payload.applicant_type}'. Valid: {valid}",
            )

    idea = Idea(
        application_id=_generate_application_id(db),
        applicant_name=payload.applicant_name,
        email=payload.email,
        phone=payload.phone,
        age=payload.age,
        location=payload.location,
        organization=payload.organization,
        original_language=payload.original_language,
        team_name=payload.team_name,
        team_member_count=payload.team_member_count,
        team_member_names=payload.team_member_names,
        guardian_name=payload.guardian_name,
        guardian_phone=payload.guardian_phone,
        guardian_email=payload.guardian_email,
        guardian_relationship=payload.guardian_relationship,
        guardian_consent=payload.guardian_consent,
        gender=payload.gender,
        program_track=program_track,
        source_type=source_type,
        source_program=source_program,
        applicant_type=applicant_type,
        source_platform=payload.source_platform,
        source_domain=payload.source_domain,
        source_url=payload.source_url,
        referrer_url=payload.referrer_url,
        idea_title=payload.idea_title,
        problem_statement=payload.problem_statement,
        solution_description=payload.solution_description,
        application_context=payload.application_context,
        uniqueness=payload.uniqueness,
        category=_coerce_category(payload.category),
        sub_category=payload.sub_category,
        target_users=payload.target_users,
        prototype_status=payload.prototype_status,
        support_needed=payload.support_needed,
        consent_data=payload.consent_data,
        consent_original=payload.consent_original,
        consent_contact=payload.consent_contact,
        current_status=IdeaStatus.SUBMITTED,
        is_public_tracking_enabled=True,
    )
    if commit:
        db.add(idea)
        db.commit()
        db.refresh(idea)
    return idea


@router.post("", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
def submit_idea(request: Request, payload: IdeaCreate, db: Session = Depends(get_db)):
    assert_rate_limit(
        request,
        "public-idea-submit",
        settings.RATE_LIMIT_PUBLIC_SUBMIT_PER_HOUR,
        60 * 60,
    )
    idea = _create_idea(payload, db, commit=False)
    db.add(idea)
    db.flush()
    record_audit_log(
        db,
        action="public_idea_submitted",
        entity_type="idea",
        entity_id=idea.id,
        entity_display_id=idea.application_id,
        new_values={
            "application_id": idea.application_id,
            "program_track": idea.program_track.value if idea.program_track else None,
            "source_type": idea.source_type.value if idea.source_type else None,
            "idea_title": idea.idea_title,
        },
        request=request,
    )
    db.commit()
    db.refresh(idea)
    notify_public_idea_submission(idea)
    return idea


@router.post("/with-files", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
def submit_idea_with_files(
    request: Request,
    idea_json: str = Form(..., description="JSON payload matching IdeaCreate"),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    assert_rate_limit(
        request,
        "public-idea-submit-with-files",
        settings.RATE_LIMIT_PUBLIC_SUBMIT_WITH_FILES_PER_HOUR,
        60 * 60,
    )
    try:
        payload = IdeaCreate.model_validate(json.loads(idea_json))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid idea_json: {exc.msg}",
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        )

    idea = _create_idea(payload, db, commit=False)
    db.add(idea)
    db.flush()

    uploaded_files = []
    for upload in files:
        ext, content = validate_file(upload, FileType.OTHER)
        meta = save_file(
            content=content,
            ext=ext,
            file_type=FileType.OTHER,
            application_id=idea.application_id,
            original_name=upload.filename or "upload",
            mime_type=upload.content_type,
        )
        idea_file = IdeaFile(
            idea_id=idea.id,
            uploaded_by_user_id=None,
            file_type=FileType.OTHER,
            file_name=meta["file_name"],
            stored_file_name=meta["stored_file_name"],
            file_path=meta["file_path"],
            mime_type=meta["mime_type"],
            file_size=meta["file_size"],
            description="Uploaded with public idea submission.",
        )
        db.add(idea_file)
        uploaded_files.append(idea_file)

    record_audit_log(
        db,
        action="public_idea_submitted",
        entity_type="idea",
        entity_id=idea.id,
        entity_display_id=idea.application_id,
        new_values={
            "application_id": idea.application_id,
            "program_track": idea.program_track.value if idea.program_track else None,
            "source_type": idea.source_type.value if idea.source_type else None,
            "idea_title": idea.idea_title,
            "uploaded_file_count": len(uploaded_files),
            "uploaded_files": [
                {"file_name": f.file_name, "file_type": f.file_type.value if f.file_type else None}
                for f in uploaded_files
            ],
        },
        request=request,
    )

    db.commit()
    db.refresh(idea)
    notify_public_idea_submission(idea)
    return idea


@router.get("/{application_id}", response_model=IdeaOut)
def get_idea(application_id: str, db: Session = Depends(get_db)):
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Idea details are available only through verified tracking or authenticated admin access.",
    )
