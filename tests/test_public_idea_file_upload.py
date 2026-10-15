import json
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.idea import Idea
from app.models.idea_file import IdeaFile
from app.models.user import User


ID_RE = re.compile(r"^IDEA-\d{4}-[A-Z0-9]{6}$")


def _client_with_db(client):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Idea.__table__, IdeaFile.__table__])

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestingSessionLocal


def _payload():
    return {
        "applicant_name": "Public Applicant",
        "email": "public-upload@example.com",
        "phone": "9999999999",
        "program_track": "LOCAL_REGIONAL",
        "source_type": "ONLINE_FORM",
        "source_program": "LOCAL_REGIONAL",
        "idea_title": "Water sensor",
        "problem_statement": "Water leaks are missed.",
        "solution_description": "A low-cost sensor.",
        "target_users": "Homes",
        "prototype_status": "SKETCH_AVAILABLE",
    }


def test_public_idea_submit_without_files_still_works(client, monkeypatch):
    _client_with_db(client)
    monkeypatch.setattr("app.routers.ideas.notify_public_idea_submission", lambda idea: None)
    try:
        payload = _payload()
        payload["prototype_status"] = "Sketch / drawing available"
        response = client.post("/api/v1/ideas", json=payload)
        assert response.status_code == 201
        assert ID_RE.match(response.json()["application_id"])
        assert response.json()["prototype_status"] == "SKETCH_AVAILABLE"
    finally:
        app.dependency_overrides.clear()


def test_public_idea_submit_with_files_creates_file_record(client, tmp_path, monkeypatch):
    SessionLocal = _client_with_db(client)
    monkeypatch.setattr("app.routers.ideas.notify_public_idea_submission", lambda idea: None)
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))

    try:
        response = client.post(
            "/api/v1/ideas/with-files",
            data={"idea_json": json.dumps(_payload())},
            files=[("files", ("proof.pdf", b"pdf-content", "application/pdf"))],
        )
        assert response.status_code == 201
        application_id = response.json()["application_id"]
        assert ID_RE.match(application_id)
        assert response.json()["prototype_status"] == "SKETCH_AVAILABLE"

        db = SessionLocal()
        try:
            idea = db.query(Idea).filter(Idea.application_id == application_id).one()
            idea_file = db.query(IdeaFile).filter(IdeaFile.idea_id == idea.id).one()
            assert idea_file.uploaded_by_user_id is None
            assert idea_file.file_name == "proof.pdf"
            assert idea_file.file_path.startswith(f"ideas/{application_id}")
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()


def test_public_idea_submit_with_invalid_file_extension_rejected(client, tmp_path, monkeypatch):
    _client_with_db(client)
    monkeypatch.setattr("app.routers.ideas.notify_public_idea_submission", lambda idea: None)
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))

    try:
        response = client.post(
            "/api/v1/ideas/with-files",
            data={"idea_json": json.dumps(_payload())},
            files=[("files", ("malware.exe", b"bad", "application/octet-stream"))],
        )
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()
