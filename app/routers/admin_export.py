"""
Excel export for the admin/view-admin ideas + jury evaluations dashboard.

Route (under /api/v1/admin):
  GET /ideas/export.xlsx

Generated server-side (not client-side) so RBAC and idea scope are always
enforced the same way as every other admin/view-admin read endpoint — a
VIEW_ADMIN_LOCAL user can only ever export ideas within their own scope,
same as the list/detail endpoints. Accepts the same search/filter query
params as GET /admin/ideas/page so the export always matches what the
caller currently has on screen.
"""
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.evaluation import Evaluation
from app.models.idea import Idea
from app.models.jury import JuryAssignment
from app.models.user import User
from app.routers.admin import _apply_idea_list_filters, _filter_ideas_by_scope
from app.utils.dependencies import require_admin_read

router = APIRouter(prefix="/admin", tags=["admin-export"])

_IDEAS_SHEET_HEADERS = [
    "Application ID", "Idea Title", "Problem Statement", "Solution Description",
    "Applicant Name", "Email", "Phone", "Team Name", "Organization",
    "Program Track", "Visibility Scope", "Current Status", "Rejection Reason",
    "Created At", "Updated At",
]

_JURY_SHEET_HEADERS = [
    "Application ID", "Idea Title", "Jury Evaluator", "Jury Email",
    "Evaluation Status", "Score", "Recommendation", "Comment", "Evaluation Date",
]


def _cell(value):
    """openpyxl cannot write tz-aware datetimes or enum members directly."""
    if value is None:
        return None
    if hasattr(value, "value"):  # enum member
        return value.value
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


@router.get(
    "/ideas/export.xlsx",
    summary="Export ideas + jury evaluations to Excel (respects scope/filters)",
)
def export_ideas_excel(
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    current_status: Optional[str] = None,
    category: Optional[str] = None,
    program_track: Optional[str] = None,
    applicant_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = _filter_ideas_by_scope(db.query(Idea), current_user)
    query = _apply_idea_list_filters(
        query,
        search=search,
        current_status=current_status or status_filter,
        category=category,
        program_track=program_track,
        applicant_type=applicant_type,
        date_from=date_from,
        date_to=date_to,
    )
    ideas = query.order_by(Idea.created_at.desc()).all()
    idea_ids = [idea.id for idea in ideas]
    idea_by_id = {idea.id: idea for idea in ideas}

    workbook = Workbook()

    ideas_sheet = workbook.active
    ideas_sheet.title = "Ideas"
    ideas_sheet.append(_IDEAS_SHEET_HEADERS)
    for idea in ideas:
        ideas_sheet.append([
            _cell(idea.application_id),
            _cell(idea.idea_title),
            _cell(idea.problem_statement),
            _cell(idea.solution_description),
            _cell(idea.applicant_name),
            _cell(idea.email),
            _cell(idea.phone),
            _cell(idea.team_name),
            _cell(idea.organization),
            _cell(idea.program_track),
            _cell(idea.visibility_scope),
            _cell(idea.current_status),
            _cell(idea.rejection_reason),
            _cell(idea.created_at),
            _cell(idea.updated_at),
        ])

    jury_sheet = workbook.create_sheet("Jury Evaluations")
    jury_sheet.append(_JURY_SHEET_HEADERS)

    if idea_ids:
        assignments = (
            db.query(JuryAssignment, User)
            .join(User, JuryAssignment.jury_user_id == User.id)
            .filter(JuryAssignment.idea_id.in_(idea_ids))
            .order_by(JuryAssignment.assigned_at.asc())
            .all()
        )
        evaluations_by_key = {
            (evaluation.idea_id, evaluation.jury_user_id): evaluation
            for evaluation in db.query(Evaluation).filter(Evaluation.idea_id.in_(idea_ids)).all()
        }
    else:
        assignments = []
        evaluations_by_key = {}

    for assignment, juror in assignments:
        idea = idea_by_id.get(assignment.idea_id)
        evaluation = evaluations_by_key.get((assignment.idea_id, assignment.jury_user_id))
        jury_sheet.append([
            _cell(idea.application_id) if idea else assignment.idea_id,
            _cell(idea.idea_title) if idea else None,
            _cell(juror.full_name),
            _cell(juror.email),
            _cell(assignment.review_status),
            evaluation.total_score if evaluation else None,
            _cell(evaluation.recommendation) if evaluation else None,
            _cell(evaluation.remarks) if evaluation else None,
            _cell(evaluation.created_at) if evaluation else _cell(assignment.completed_at),
        ])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ideas_export.xlsx"},
    )
