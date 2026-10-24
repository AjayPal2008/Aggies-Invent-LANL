"""Learner endpoints for AI-built courses: modules, video and other lesson styles, role plan,
and interview-style (CASPer/MMI) assessments with typed or recorded answers."""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, serialize
from ..auth import current_user
from ..config import settings
from ..database import get_db
from ..services import adaptive, courseware, roles
from ..safeguards import cached_content
from .content import upload_dir

router = APIRouter(prefix="/api/me", tags=["learning"])

# Like CASPer: a short read, then a timed answer per question.
READ_SECONDS = 60
ANSWER_SECONDS = {"text": 210, "audio": 90}


def _training(db: Session, code: str) -> models.Training:
    t = db.scalar(select(models.Training).where(models.Training.code == code))
    if t is None:
        raise HTTPException(404, "Training not found")
    return t


@router.get("/role-plan")
def role_plan(user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    from ..services.loader import load_people

    return roles.my_plan(db, load_people(db, [user.id])[0])


@router.get("/trainings/{code}/modules")
def modules(code: str, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    t = _training(db, code)
    mods = list(db.scalars(select(models.CourseModule).where(models.CourseModule.training_id == t.id).order_by(models.CourseModule.position)))
    done = {e.payload.get("module_id") for e in db.scalars(select(models.LearningEvent).where(
        models.LearningEvent.employee_id == user.id, models.LearningEvent.kind == "module_done", models.LearningEvent.training_id == t.id))}
    return {"training": serialize.training(t, brief=True), "assessment_type": t.assessment_type, "from_document": bool(t.document_id),
            "modules": [{"id": m.id, "title": m.title, "summary": m.summary, "pages": f"{m.page_start}-{m.page_end}",
                         "objectives": m.objectives, "done": m.id in done} for m in mods]}


class ModuleLessonIn(BaseModel):
    modality: str | None = None
    difficulty: str | None = None
    request: str = ""


@router.post("/modules/{module_id}/lesson")
def module_lesson(module_id: int, body: ModuleLessonIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(models.CourseModule, module_id)
    if m is None:
        raise HTTPException(404, "Module not found")
    t = db.get(models.Training, m.training_id)
    fake = models.Training(skills=m.skills or t.skills, equipment=t.equipment, facilities=t.facilities)
    profile = adaptive.learner_profile(db, user, fake)
    if body.modality in adaptive.MODALITIES:
        profile["modality"] = body.modality
    if body.difficulty in ("intro", "intermediate", "advanced"):
        profile["difficulty"] = body.difficulty
    content = courseware.module_lesson(db, user, m, profile, body.request)
    db.add(models.LearningEvent(employee_id=user.id, training_id=t.id, kind="lesson", modality=profile["modality"],
                                payload={"module_id": m.id, "difficulty": profile["difficulty"]}))
    a = next((x for x in user.assignments if x.training_id == t.id), None)
    if a and a.status == "not_started":
        a.status, a.started_at, a.progress = "in_progress", datetime.utcnow(), max(a.progress, 5)
    db.commit()
    return content


@router.post("/trainings/{code}/video")
def training_video(code: str, body: ModuleLessonIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    """Video lesson for a catalog training that wasn't built from a document."""
    t = _training(db, code)
    profile = adaptive.learner_profile(db, user, t)
    if body.difficulty in ("intro", "intermediate", "advanced"):
        profile["difficulty"] = body.difficulty
    topics = [l.strip() for l in (t.outline or "").splitlines() if l.strip()]
    make = lambda: courseware.video_lesson(user, t.title, courseware.training_source(t), topics, profile, body.request,  # noqa: E731
                                           (t.skills or [t.category])[0])
    content = make() if body.request else cached_content(db, f"video:{t.code}:{profile['difficulty']}", make)
    content.update({"kind": "video", "difficulty": profile["difficulty"], "modality": "video"})
    db.add(models.LearningEvent(employee_id=user.id, training_id=t.id, kind="lesson", modality="video", payload={}))
    db.commit()
    return content


@router.post("/modules/{module_id}/complete")
def complete_module(module_id: int, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(models.CourseModule, module_id)
    if m is None:
        raise HTTPException(404, "Module not found")
    db.add(models.LearningEvent(employee_id=user.id, training_id=m.training_id, kind="module_done", payload={"module_id": m.id}))
    db.flush()
    total = len(list(db.scalars(select(models.CourseModule.id).where(models.CourseModule.training_id == m.training_id))))
    done = {e.payload.get("module_id") for e in db.scalars(select(models.LearningEvent).where(
        models.LearningEvent.employee_id == user.id, models.LearningEvent.kind == "module_done",
        models.LearningEvent.training_id == m.training_id))}
    a = next((x for x in user.assignments if x.training_id == m.training_id), None)
    if a and a.status != "completed":
        a.status = "in_progress"
        a.started_at = a.started_at or datetime.utcnow()
        a.progress = max(a.progress, round(90 * len(done) / max(1, total)))  # the last 10% is the assessment
    db.commit()
    return {"done": len(done), "total": total, "progress": a.progress if a else None}


# ---- interview-style assessment ------------------------------------------------------

def _own_assignment(db: Session, user: models.Employee, assignment_id: int) -> models.Assignment:
    a = db.get(models.Assignment, assignment_id)
    if a is None or a.employee_id != user.id:
        raise HTTPException(404, "Assignment not found")
    return a


def _own_session(db: Session, user: models.Employee, session_id: int) -> models.InterviewSession:
    s = db.get(models.InterviewSession, session_id)
    if s is None or s.employee_id != user.id:
        raise HTTPException(404, "Assessment not found")
    return s


@router.post("/assignments/{assignment_id}/interview")
def start_interview(assignment_id: int, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    """Start a situational assessment: 3 workplace scenarios, each with timed questions."""
    a = _own_assignment(db, user, assignment_id)
    picked = courseware.pick_scenarios(db, a.training, user, user.job_title or "a LANL employee")
    s = models.InterviewSession(assignment_id=a.id, employee_id=user.id, scenario_ids=[x.id for x in picked])
    db.add(s)
    db.commit()
    return {"session_id": s.id, "training": serialize.training(a.training, brief=True),
            "read_seconds": READ_SECONDS, "answer_seconds": ANSWER_SECONDS,
            "scenarios": [{"id": x.id, "title": x.title, "situation": x.situation, "questions": x.questions} for x in picked]}


@router.post("/interviews/{session_id}/responses")
async def save_response(session_id: int, scenario_id: int = Form(...), question_index: int = Form(...), mode: str = Form("text"),
                        transcript: str = Form(""), seconds_used: int = Form(0), audio: UploadFile | None = File(None),
                        user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_session(db, user, session_id)
    if s.status != "in_progress":
        raise HTTPException(409, "This assessment was already submitted")
    if scenario_id not in (s.scenario_ids or []):
        raise HTTPException(400, "That scenario isn't part of this assessment")
    r = next((x for x in s.responses if x.scenario_id == scenario_id and x.question_index == question_index), None)
    if r is None:
        r = models.InterviewResponse(scenario_id=scenario_id, question_index=question_index)
        s.responses.append(r)
    r.mode = "audio" if mode == "audio" else "text"
    r.transcript = transcript.strip()[:8000]
    r.seconds_used = max(0, seconds_used)
    if audio is not None and audio.filename:
        name = f"{s.id}-{scenario_id}-{question_index}-{uuid.uuid4().hex[:8]}{Path(audio.filename).suffix or '.webm'}"
        with (upload_dir("recordings") / name).open("wb") as fh:
            shutil.copyfileobj(audio.file, fh)
        r.audio_path = name
    db.commit()
    return {"saved": True, "response_id": r.id}


@router.post("/interviews/{session_id}/submit")
def submit_interview(session_id: int, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_session(db, user, session_id)
    if s.status != "in_progress":
        raise HTTPException(409, "Already submitted")
    if not s.responses:
        raise HTTPException(400, "Answer at least one question first")
    s.submitted_at = datetime.utcnow()
    result = courseware.score_interview(db, s, user.job_title or "a LANL employee")
    pct = courseware.interview_to_percent(result["overall"])
    competency = {k.lower(): v / 9 for k, v in result["competencies"].items()}
    a = s.assignment
    adaptive.complete_assessment(db, a, pct, {skill: competency.get(skill, pct / 100) for skill in a.training.skills or []},
                                 kind="interview")
    db.flush()
    courseware.score_readiness(db, s)
    db.commit()
    return interview_result(session_id, user, db)


@router.get("/interviews/{session_id}")
def interview_result(session_id: int, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_session(db, user, session_id)
    scen = {x.id: x for x in db.scalars(select(models.Scenario).where(models.Scenario.id.in_(s.scenario_ids or [0])))}
    final = s.manager_overall if s.manager_overall is not None else s.overall
    return {
        "session_id": s.id, "status": s.status, "overall": s.overall, "manager_overall": s.manager_overall, "final": final,
        "passed": final is not None and final >= settings.interview_pass, "pass_mark": settings.interview_pass,
        "competencies": s.competency_scores, "feedback": s.feedback, "scored_by": s.scored_by, "manager_notes": s.manager_notes,
        "readiness": s.readiness, "readiness_score": s.readiness_score, "readiness_detail": s.readiness_detail or {},
        "assignment": serialize.assignment(s.assignment),
        "scenarios": [{"title": scen[sid].title, "situation": scen[sid].situation,
                       "strong_response": scen[sid].strong_response if s.status != "in_progress" else [],
                       "responses": [{"question": scen[sid].questions[r.question_index] if r.question_index < len(scen[sid].questions) else "",
                                      "transcript": r.transcript, "mode": r.mode, "score": r.score, "feedback": r.feedback}
                                     for r in s.responses if r.scenario_id == sid]}
                      for sid in s.scenario_ids if sid in scen],
    }
