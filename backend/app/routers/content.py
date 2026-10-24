"""Manager endpoints for role setup: documents, AI-built courses, role plans, starting people in a role,
and reviewing interview-style assessments."""
from __future__ import annotations

import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, serialize
from ..auth import current_user, require_manager, team_ids
from ..config import settings
from ..database import get_db
from ..services import documents, roles
from ..services.loader import load_people

router = APIRouter(prefix="/api/manager", tags=["role setup"])
files_router = APIRouter(prefix="/api", tags=["files"])

DOC_KINDS = {"job_description", "requirements", "manual", "policy", "procedure", "handbook"}
COURSE_KINDS = {"manual", "policy", "procedure", "handbook"}


def upload_dir(sub: str) -> Path:
    d = Path(settings.upload_dir) / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def _position(db: Session, code: str) -> models.Position:
    pos = db.scalar(select(models.Position).where(models.Position.code == code))
    if pos is None:
        raise HTTPException(404, "Role not found")
    return pos


def _doc_json(db: Session, d: models.Document) -> dict:
    t = db.scalar(select(models.Training).where(models.Training.document_id == d.id))
    modules = list(db.scalars(select(models.CourseModule).where(models.CourseModule.training_id == t.id)
                              .order_by(models.CourseModule.position))) if t else []
    scen = len(list(db.scalars(select(models.Scenario.id).where(models.Scenario.training_id == t.id)))) if t else 0
    return {"id": d.id, "title": d.title, "filename": d.filename, "kind": d.kind, "position_code": d.position_code,
            "uploaded_at": d.uploaded_at.isoformat(), "pages": d.pages, "words": d.words, "status": d.status, "error": d.error,
            "generated_by": d.generated_by, "reading_minutes": round(d.words / 230),
            "course": {"code": t.code, "title": t.title, "summary": t.description, "assessment_type": t.assessment_type,
                       "duration_minutes": t.duration_minutes, "scenarios": scen,
                       "modules": [{"id": m.id, "title": m.title, "pages": f"{m.page_start}-{m.page_end}", "summary": m.summary,
                                    "key_points": m.key_points} for m in modules]} if t else None}


# ---- documents --------------------------------------------------------------------

@router.post("/documents")
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...), title: str = Form(""), kind: str = Form("manual"),
                          position_code: str = Form(""), build_course: bool = Form(True),
                          mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Upload a job description, requirements or internal document. Manuals, policies and procedures become courses."""
    if kind not in DOC_KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(sorted(DOC_KINDS))}")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".docx"}:
        raise HTTPException(400, "Upload a PDF, .docx, .txt or .md file")
    if position_code:
        _position(db, position_code)
    dest = upload_dir("documents") / f"{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh, length=1024 * 1024)
    if dest.stat().st_size > settings.max_upload_mb * 1024 * 1024:
        dest.unlink()
        raise HTTPException(413, f"Files over {settings.max_upload_mb} MB aren't accepted")
    try:
        doc = documents.save_document(db, dest, title or Path(file.filename).stem, kind, position_code or None, mgr.id)
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc))
    doc.filename = file.filename or dest.name
    doc.analysis = {"stored_as": dest.name}
    db.commit()
    if build_course and kind in COURSE_KINDS and doc.status != "failed":
        doc.status = "generating"
        db.commit()
        background.add_task(documents.build_course_background, doc.id)
    return _doc_json(db, doc)


@router.get("/documents")
def list_documents(position_code: str = "", mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    stmt = select(models.Document).order_by(models.Document.id.desc())
    if position_code:
        stmt = stmt.where(models.Document.position_code == position_code)
    return [_doc_json(db, d) for d in db.scalars(stmt)]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    d = db.get(models.Document, doc_id)
    if d is None:
        raise HTTPException(404, "Document not found")
    return _doc_json(db, d)


@router.post("/documents/{doc_id}/build")
def rebuild_course(doc_id: int, background: BackgroundTasks, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    d = db.get(models.Document, doc_id)
    if d is None:
        raise HTTPException(404, "Document not found")
    d.status = "generating"
    db.commit()
    background.add_task(documents.build_course_background, d.id)
    return _doc_json(db, d)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    d = db.get(models.Document, doc_id)
    if d is None:
        raise HTTPException(404, "Document not found")
    t = db.scalar(select(models.Training).where(models.Training.document_id == d.id))
    if t and db.scalar(select(models.Assignment.id).where(models.Assignment.training_id == t.id)):
        raise HTTPException(409, "People are assigned the course built from this document. Remove those assignments first.")
    if t:
        for m in db.scalars(select(models.CourseModule).where(models.CourseModule.training_id == t.id)):
            for c in db.scalars(select(models.LessonCache).where(models.LessonCache.module_id == m.id)):
                db.delete(c)
            db.delete(m)
        for s in db.scalars(select(models.Scenario).where(models.Scenario.training_id == t.id)):
            db.delete(s)
        for i in db.scalars(select(models.RolePlanItem).where(models.RolePlanItem.training_code == t.code)):
            db.delete(i)
        db.delete(t)
    stored = (d.analysis or {}).get("stored_as")
    db.delete(d)
    db.commit()
    if stored:
        (upload_dir("documents") / stored).unlink(missing_ok=True)
    return {"deleted": doc_id}


@files_router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    """The original file. Managers, or anyone assigned the course built from it."""
    d = db.get(models.Document, doc_id)
    if d is None:
        raise HTTPException(404, "Document not found")
    if user.role == "hire":
        t = db.scalar(select(models.Training).where(models.Training.document_id == d.id))
        if not t or not any(a.training_id == t.id for a in user.assignments):
            raise HTTPException(403, "Not assigned to you")
    stored = (d.analysis or {}).get("stored_as")
    path = upload_dir("documents") / stored if stored else None
    if not path or not path.exists():
        raise HTTPException(404, "Original file is no longer stored")
    return FileResponse(path, filename=d.filename)


# ---- roles ------------------------------------------------------------------------

class PositionIn(BaseModel):
    code: str | None = None
    title: str
    division_code: str
    level: int = 1
    min_years: float = 0
    required_skills: list[str] = []
    prerequisites: list[str] = []
    is_open: bool = False
    headcount: int = 1


def _pos_json(p: models.Position) -> dict:
    return {"code": p.code, "title": p.title, "division_code": p.division_code, "level": p.level, "min_years": p.min_years,
            "required_skills": p.required_skills, "required_trainings": p.required_trainings, "prerequisites": p.prerequisites,
            "is_open": p.is_open, "headcount": p.headcount, "fiscal_year": p.fiscal_year, "leadership": roles.is_leadership(p)}


@router.get("/roles")
def list_roles(mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    planned = {c for c in db.scalars(select(models.RolePlanItem.position_code))}
    docs = {}
    for d in db.scalars(select(models.Document)):
        if d.position_code:
            docs[d.position_code] = docs.get(d.position_code, 0) + 1
    out = []
    for p in db.scalars(select(models.Position).order_by(models.Position.division_code, models.Position.level)):
        out.append({**_pos_json(p), "has_plan": p.code in planned, "documents": docs.get(p.code, 0)})
    return out


@router.post("/roles")
def create_role(body: PositionIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    code = (body.code or re.sub(r"[^A-Z0-9]+", "-", f"{body.division_code}-{body.title}".upper()).strip("-"))[:32]
    if db.scalar(select(models.Position).where(models.Position.code == code)):
        raise HTTPException(409, f"Role {code} already exists")
    p = models.Position(code=code, title=body.title, division_code=body.division_code, level=body.level, min_years=body.min_years,
                        required_skills=[s.lower() for s in body.required_skills], prerequisites=body.prerequisites,
                        is_open=body.is_open, headcount=body.headcount, hiring_manager_email=mgr.email, required_trainings=[])
    db.add(p)
    db.commit()
    return _pos_json(p)


@router.patch("/roles/{code}")
def update_role(code: str, body: PositionIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    p = _position(db, code)
    p.title, p.division_code, p.level, p.min_years = body.title, body.division_code, body.level, body.min_years
    p.required_skills, p.prerequisites = [s.lower() for s in body.required_skills], body.prerequisites
    p.is_open, p.headcount = body.is_open, body.headcount
    db.commit()
    return _pos_json(p)


class AnalyzeIn(BaseModel):
    text: str = ""
    apply_skills: bool = True


@router.post("/roles/{code}/analyze")
def analyze(code: str, body: AnalyzeIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Read the role's job description and requirements; suggest skills, years, prerequisites and a plan."""
    p = _position(db, code)
    result = roles.analyze_role(db, p, body.text)
    if body.apply_skills and result.get("required_skills"):
        p.required_skills = sorted(set(result["required_skills"]))
        if result.get("min_years"):
            p.min_years = float(result["min_years"])
        if result.get("prerequisites"):
            p.prerequisites = result["prerequisites"]
        db.commit()
    return {**result, "role": _pos_json(p)}


@router.get("/roles/{code}/plan")
def get_plan(code: str, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    p = _position(db, code)
    saved = bool(roles.get_plan(db, p))
    by_code = {t.code: t for t in db.scalars(select(models.Training))}
    items = [{**i, "title": by_code[i["training_code"]].title, "category": by_code[i["training_code"]].category,
              "assessment_type": by_code[i["training_code"]].assessment_type, "from_document": bool(by_code[i["training_code"]].document_id)}
             for i in roles.plan_items(db, p) if i["training_code"] in by_code]
    return {"role": _pos_json(p), "saved": saved, "items": items, "phases": roles.PHASE_LABEL}


class PlanIn(BaseModel):
    items: list[dict]


@router.put("/roles/{code}/plan")
def put_plan(code: str, body: PlanIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    p = _position(db, code)
    roles.save_plan(db, p, body.items)
    db.commit()
    return get_plan(code, mgr, db)


class StartIn(BaseModel):
    employee_ids: list[int]
    entry_paths: dict[str, str] = {}  # employee id -> new_hire | promotion | transfer
    start_date: date | None = None
    exclude: dict[str, list[str]] = {}  # employee id -> training codes to leave out
    include: dict[str, list[str]] = {}  # employee id -> skipped codes to add back


def _people(db: Session, mgr: models.Employee, ids: list[int], allow_lab: bool) -> list[models.Employee]:
    """Team members, or for hiring/promotions, anyone in the lab the manager is bringing into their role."""
    allowed = team_ids(db, mgr)
    if not allow_lab:
        bad = [i for i in ids if i not in allowed]
        if bad:
            raise HTTPException(404, f"Not on your team: {bad[:5]}")
    people = {e.id: e for e in load_people(db, set(ids))}
    missing = [i for i in ids if i not in people]
    if missing:
        raise HTTPException(404, f"Unknown employees: {missing[:5]}")
    return [people[i] for i in ids]


@router.post("/roles/{code}/preview")
def preview_start(code: str, body: StartIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """What each person would get if they started this role, and why things are skipped."""
    p = _position(db, code)
    return [roles.preview(db, e, p, body.entry_paths.get(str(e.id)), body.start_date)
            for e in _people(db, mgr, body.employee_ids, allow_lab=True)]


@router.post("/roles/{code}/start")
def start_role(code: str, body: StartIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Move people into this role (new hires, promotions, transfers) and assign their tailored plan."""
    p = _position(db, code)
    out = []
    for e in _people(db, mgr, body.employee_ids, allow_lab=True):
        if e.id not in team_ids(db, mgr) and mgr.role != "admin":
            e.manager_id = mgr.id  # they join this manager's team
        out.append(roles.apply(db, mgr, e, p, body.entry_paths.get(str(e.id)), body.start_date,
                               body.exclude.get(str(e.id)), body.include.get(str(e.id))))
    db.commit()
    db.info.clear()
    return out


@router.get("/people/search")
def search_people(q: str, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Find anyone in the lab (for promotions and transfers into a role)."""
    if len(q.strip()) < 2:
        return []
    like = f"%{q.strip()}%"
    stmt = select(models.Employee).where((models.Employee.name.ilike(like)) | (models.Employee.email.ilike(like))
                                         | (models.Employee.employee_number.ilike(like))).limit(25)
    team = team_ids(db, mgr)
    return [{**serialize.employee(e), "on_team": e.id in team} for e in db.scalars(stmt)]


class AssessmentIn(BaseModel):
    assessment_type: str


@router.patch("/trainings/{code}/assessment")
def set_assessment(code: str, body: AssessmentIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Choose how a training is assessed: quiz (policies, rules, facts), situational interview (leading people,
    judgment calls), or both."""
    from ..assessment_rules import VALID
    from ..safeguards import catalog_cache

    if body.assessment_type not in VALID:
        raise HTTPException(400, "assessment_type must be quiz, situational or both")
    t = db.scalar(select(models.Training).where(models.Training.code == code))
    if t is None:
        raise HTTPException(404, "Training not found")
    t.assessment_type = body.assessment_type
    db.commit()
    catalog_cache.clear()
    return {"code": t.code, "assessment_type": t.assessment_type}


# ---- interview review -------------------------------------------------------------

def _session_json(db: Session, s: models.InterviewSession, detail: bool = False) -> dict:
    emp = db.get(models.Employee, s.employee_id)
    t = s.assignment.training
    d = {"id": s.id, "employee_id": emp.id, "name": emp.name, "job_title": emp.job_title, "training_code": t.code,
         "training_title": t.title, "status": s.status, "started_at": s.started_at.isoformat(),
         "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None, "overall": s.overall,
         "manager_overall": s.manager_overall, "final": s.manager_overall if s.manager_overall is not None else s.overall,
         "scored_by": s.scored_by, "competencies": s.competency_scores,
         "readiness": s.readiness, "readiness_score": s.readiness_score, "readiness_detail": s.readiness_detail or {}}
    if detail:
        scen = {x.id: x for x in db.scalars(select(models.Scenario).where(models.Scenario.id.in_(s.scenario_ids or [0])))}
        d["feedback"], d["manager_notes"] = s.feedback, s.manager_notes
        d["scenarios"] = [{"id": sid, "title": scen[sid].title, "situation": scen[sid].situation, "questions": scen[sid].questions,
                           "strong_response": scen[sid].strong_response, "red_flags": scen[sid].red_flags,
                           "responses": [{"id": r.id, "question_index": r.question_index, "mode": r.mode, "transcript": r.transcript,
                                          "seconds_used": r.seconds_used, "score": r.score, "feedback": r.feedback,
                                          "has_audio": bool(r.audio_path)} for r in s.responses if r.scenario_id == sid]}
                          for sid in s.scenario_ids if sid in scen]
    return d


@router.get("/interviews")
def list_interviews(status: str = "", mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    ids = team_ids(db, mgr)
    stmt = select(models.InterviewSession).where(models.InterviewSession.status != "in_progress").order_by(models.InterviewSession.id.desc())
    if status:
        stmt = stmt.where(models.InterviewSession.status == status)
    return [_session_json(db, s) for s in db.scalars(stmt) if s.employee_id in ids][:200]


@router.get("/interviews/{session_id}")
def get_interview(session_id: int, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    s = db.get(models.InterviewSession, session_id)
    if s is None or s.employee_id not in team_ids(db, mgr):
        raise HTTPException(404, "Not found")
    return _session_json(db, s, detail=True)


class ReviewIn(BaseModel):
    overall: float | None = None
    notes: str = ""


@router.post("/interviews/{session_id}/review")
def review_interview(session_id: int, body: ReviewIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Confirm or override the AI score. The override drives pass/fail and retraining."""
    from ..services import adaptive
    from ..services.courseware import interview_to_percent

    s = db.get(models.InterviewSession, session_id)
    if s is None or s.employee_id not in team_ids(db, mgr):
        raise HTTPException(404, "Not found")
    if body.overall is not None:
        if not 1 <= body.overall <= 9:
            raise HTTPException(400, "Score must be between 1 and 9")
        s.manager_overall = body.overall
        a = s.assignment
        # The manager's score replaces the AI's for this attempt; status and retraining follow from it.
        attempt = next((x for x in sorted(a.attempts_log, key=lambda x: x.id, reverse=True) if x.kind == "interview"), None)
        if attempt is not None:
            attempt.score = interview_to_percent(body.overall)
        adaptive.apply_scores(a)
    s.manager_notes, s.status, s.reviewed_by_id = body.notes, "reviewed", mgr.id
    from ..services.courseware import score_readiness

    db.flush()
    score_readiness(db, s)  # readiness follows the manager's score
    db.commit()
    return _session_json(db, s, detail=True)


@router.get("/interviews/responses/{response_id}/audio")
def interview_audio(response_id: int, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    r = db.get(models.InterviewResponse, response_id)
    if r is None:
        raise HTTPException(404, "Not found")
    s = db.get(models.InterviewSession, r.session_id)
    if s.employee_id not in team_ids(db, mgr) or not r.audio_path:
        raise HTTPException(404, "Not found")
    return FileResponse(upload_dir("recordings") / r.audio_path)
