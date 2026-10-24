"""Endpoints for the signed-in learner (the hire dashboard)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, serialize
from ..auth import current_user
from ..database import get_db
from ..services import adaptive, ai
from ..services.matching import training_summary
from ..safeguards import cached_content

router = APIRouter(prefix="/api/me", tags=["hire"])

SORTS = {
    "due_date": lambda a: (a.due_date or date.max),
    "title": lambda a: a.training.title.lower(),
    "status": lambda a: ["not_started", "in_progress", "completed"].index(a.status),
    "category": lambda a: a.training.category,
}


def latest_readiness(db: Session, employee_id: int) -> dict[int, dict]:
    """Most recent readiness result per assignment, in one query."""
    out = {}
    for s in db.scalars(select(models.InterviewSession).where(models.InterviewSession.employee_id == employee_id,
                                                               models.InterviewSession.readiness.is_not(None))
                        .order_by(models.InterviewSession.id)):
        out[s.assignment_id] = {"session_id": s.id, "readiness": s.readiness, "score": s.readiness_score,
                                "label": (s.readiness_detail or {}).get("label")}
    return out


def with_readiness(db: Session, emp_id: int, rows: list[dict]) -> list[dict]:
    r = latest_readiness(db, emp_id)
    return [{**a, "readiness": r.get(a["id"])} for a in rows]


def dashboard_for(db: Session, emp: models.Employee) -> dict:
    """Everything the hire dashboard shows. Also used for the manager's read-only hire view."""
    assignments = with_readiness(db, emp.id, [serialize.assignment(a) for a in emp.assignments])
    buckets = {"overdue": [], "upcoming": [], "in_progress": [], "not_started": [], "completed": [], "needs_retake": [], "expiring": []}
    for a in assignments:
        f = a["flags"]
        for key in ("overdue", "upcoming", "needs_retake", "expiring"):
            if f[key]:
                buckets[key].append(a["id"])
        buckets[a["status"]].append(a["id"])
    return {
        "employee": serialize.employee(emp),
        "summary": training_summary(emp),
        "assignments": sorted(assignments, key=lambda a: a["due_date"] or "9999"),
        "buckets": buckets,
        "gaps": adaptive.knowledge_gaps(db, emp),
        "path": adaptive.recommend_path(db, emp),
        "profile": adaptive.learner_profile(db, emp),
    }


def _own_assignment(db: Session, user: models.Employee, assignment_id: int) -> models.Assignment:
    a = db.get(models.Assignment, assignment_id)
    if a is None or a.employee_id != user.id:
        raise HTTPException(404, "Assignment not found")
    return a


def _training(db: Session, code: str) -> models.Training:
    t = db.scalar(select(models.Training).where(models.Training.code == code))
    if t is None:
        raise HTTPException(404, "Training not found")
    return t


@router.get("/dashboard")
def my_dashboard(user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    from ..services.loader import load_people

    return dashboard_for(db, load_people(db, [user.id])[0])  # trainings + skills in a few queries, not one per item


@router.get("/assignments")
def my_assignments(category: str = "", required: bool | None = None, status: str = "", flag: str = "", sort: str = "due_date",
                   user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    items = user.assignments
    if category:
        items = [a for a in items if a.training.category == category]
    if required is not None:
        items = [a for a in items if a.training.required == required]
    if status:
        items = [a for a in items if a.status == status]
    if flag:
        items = [a for a in items if adaptive.assignment_flags(a).get(flag)]
    items = sorted(items, key=SORTS.get(sort, SORTS["due_date"]))
    return with_readiness(db, user.id, [serialize.assignment(a) for a in items])


@router.get("/calendar")
def my_calendar(start: date | None = None, end: date | None = None, user: models.Employee = Depends(current_user)):
    """Registered sessions, open sessions for assigned in-person trainings, and due dates."""
    start = start or date.today() - timedelta(days=7)
    end = end or date.today() + timedelta(days=90)
    events = []
    for a in user.assignments:
        t = a.training
        if a.due_date and start <= a.due_date <= end and a.status != "completed":
            events.append({"type": "due", "date": a.due_date.isoformat(), "title": f"Due: {t.title}", "assignment_id": a.id,
                           "training_code": t.code, "overdue": adaptive.assignment_flags(a)["overdue"]})
        if t.delivery in ("in_person", "hybrid") and a.status != "completed":
            for s in t.sessions:
                if start <= s.starts_at.date() <= end:
                    events.append({"type": "registered" if a.session_id == s.id else "available", "date": s.starts_at.date().isoformat(),
                                   "title": t.title, "assignment_id": a.id, "training_code": t.code, **serialize.session(s)})
    return sorted(events, key=lambda e: (e["date"], e.get("starts_at", "")))


class RegisterIn(BaseModel):
    session_id: int


@router.post("/assignments/{assignment_id}/register")
def register_session(assignment_id: int, body: RegisterIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    a = _own_assignment(db, user, assignment_id)
    s = db.get(models.TrainingSession, body.session_id)
    if s is None or s.training_id != a.training_id:
        raise HTTPException(400, "That session isn't for this training")
    taken = len(list(db.scalars(select(models.Assignment).where(models.Assignment.session_id == s.id))))
    if taken >= s.capacity and a.session_id != s.id:
        raise HTTPException(409, "Session is full")
    a.session_id = s.id
    db.commit()
    return serialize.assignment(a)


class ProgressIn(BaseModel):
    progress: float = Field(ge=0, le=100)


@router.post("/assignments/{assignment_id}/progress")
def update_progress(assignment_id: int, body: ProgressIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    a = _own_assignment(db, user, assignment_id)
    if a.status == "completed":
        return serialize.assignment(a)
    a.progress = max(a.progress, body.progress)
    if a.status == "not_started":
        a.status, a.started_at = "in_progress", datetime.utcnow()
    db.commit()
    return serialize.assignment(a)


class ProfileIn(BaseModel):
    learning_style: str


@router.patch("/profile")
def update_profile(body: ProfileIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    user.learning_style = body.learning_style.lower()
    db.commit()
    return serialize.employee(user)


@router.get("/gaps")
def my_gaps(user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    return adaptive.knowledge_gaps(db, user)


@router.get("/path")
def my_path(user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    return adaptive.recommend_path(db, user)


# ---- AI learning ------------------------------------------------------------------

class LessonIn(BaseModel):
    request: str = ""  # e.g. "explain it with an analogy", "focus on the glovebox part"
    modality: str | None = None  # override the engine's pick
    difficulty: str | None = None


@router.post("/trainings/{code}/lesson")
def generate_lesson(code: str, body: LessonIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    t = _training(db, code)
    profile = adaptive.learner_profile(db, user, t)
    if body.modality in adaptive.MODALITIES:
        profile["modality"] = body.modality
    if body.difficulty in ("intro", "intermediate", "advanced"):
        profile["difficulty"] = body.difficulty
    if body.request:  # a personal request always gets fresh content
        lesson = ai.generate_lesson(user, t, profile, body.request)
    else:
        lesson = cached_content(db, f"lesson:{t.code}:{profile['modality']}:{profile['difficulty']}",
                                lambda: ai.generate_lesson(user, t, profile))
    db.add(models.LearningEvent(employee_id=user.id, training_id=t.id, kind="lesson", modality=profile["modality"],
                                payload={"difficulty": profile["difficulty"], "request": body.request, "generated_by": lesson.get("generated_by")}))
    a = next((x for x in user.assignments if x.training_id == t.id), None)
    if a and a.status == "not_started":
        a.status, a.started_at, a.progress = "in_progress", datetime.utcnow(), max(a.progress, 10)
    if a:
        a.difficulty = profile["difficulty"]
    db.commit()
    return lesson


class PracticeIn(BaseModel):
    count: int = Field(default=5, ge=1, le=15)
    focus_skills: list[str] = []


@router.post("/trainings/{code}/practice")
def practice(code: str, body: PracticeIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    t = _training(db, code)
    profile = adaptive.learner_profile(db, user, t)
    if t.document_id and t.lessons_status != "draft":  # courses built from documents quiz on the document's own rules
        from ..services import courseware

        return cached_content(db, f"practice:{t.code}:{profile['difficulty']}:{body.count}",
                              lambda: courseware.document_quiz(db, user, t, profile, body.count), variants=3)
    if body.focus_skills:
        return ai.practice_questions(user, t, profile, body.count, body.focus_skills)
    # Three stored sets per training and level, served at random: fresh enough, and cheap at peak.
    return cached_content(db, f"practice:{t.code}:{profile['difficulty']}:{body.count}",
                          lambda: ai.practice_questions(user, t, profile, body.count), variants=3)


class AnswerIn(BaseModel):
    training_code: str
    skill: str
    correct: bool
    modality: str = "quiz"  # quiz | simulation | exercise | visual | text
    question: str = ""


@router.post("/answer")
def record_answer(body: AnswerIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    """Every practice answer, simulation choice or exercise check feeds the adaptive engine."""
    t = _training(db, body.training_code)
    p = adaptive.record_answer(db, user, t, body.skill, body.correct, body.modality, body.question)
    adaptive.refresh_inferred_skills(db, user)
    db.commit()
    return {"skill": body.skill.lower(), "mastery": round(p, 3), "difficulty": adaptive.difficulty_for(db, user, t),
            "pacing": adaptive.pacing_for(db, user), "next_modality": adaptive.best_modality(db, user, t)}


@router.post("/assignments/{assignment_id}/assessment")
def start_assessment(assignment_id: int, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    """Issue a graded assessment. Answers stay on the server."""
    a = _own_assignment(db, user, assignment_id)
    profile = adaptive.learner_profile(db, user, a.training)
    if a.training.document_id and a.training.lessons_status != "draft":
        from ..services import courseware

        qs = courseware.document_quiz(db, user, a.training, profile, n=10)
    else:
        qs = ai.practice_questions(user, a.training, profile, n=8, focus_skills=a.training.skills or None)
    ev = models.LearningEvent(employee_id=user.id, training_id=a.training_id, kind="assessment_issued",
                              payload={"assignment_id": a.id, "questions": qs["questions"]})
    db.add(ev)
    db.commit()
    return {"assessment_id": ev.id, "generated_by": qs["generated_by"],
            "questions": [{"question": q["question"], "options": q["options"], "skill": q["skill"]} for q in qs["questions"]]}


class SubmitIn(BaseModel):
    answers: list[int]


@router.post("/assessments/{assessment_id}/submit")
def submit_assessment(assessment_id: int, body: SubmitIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    ev = db.get(models.LearningEvent, assessment_id)
    if ev is None or ev.employee_id != user.id or ev.kind != "assessment_issued":
        raise HTTPException(404, "Assessment not found")
    if ev.payload.get("submitted"):
        raise HTTPException(409, "Already submitted")
    qs = ev.payload["questions"]
    if len(body.answers) != len(qs):
        raise HTTPException(400, f"Expected {len(qs)} answers")
    per_skill: dict[str, list[int]] = {}
    review = []
    for q, ans in zip(qs, body.answers):
        ok = ans == q["answer_index"]
        per_skill.setdefault(q["skill"], []).append(1 if ok else 0)
        review.append({"question": q["question"], "your_answer": ans, "correct_answer": q["answer_index"], "correct": ok,
                       "explanation": q["explanation"], "skill": q["skill"]})
    score = round(100 * sum(r["correct"] for r in review) / len(review), 1)
    a = _own_assignment(db, user, ev.payload["assignment_id"])
    adaptive.complete_assessment(db, a, score, {s: sum(v) / len(v) for s, v in per_skill.items()})
    ev.payload = {**ev.payload, "submitted": True, "score": score}
    db.commit()
    return {"score": score, "passed": a.status == "completed", "review": review, "assignment": serialize.assignment(a),
            "gaps": adaptive.knowledge_gaps(db, user)}


class ChatIn(BaseModel):
    message: str
    training_code: str | None = None
    history: list[dict] = []


@router.post("/tutor")
def tutor(body: ChatIn, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    t = _training(db, body.training_code) if body.training_code else None
    profile = adaptive.learner_profile(db, user, t)
    out = ai.tutor_reply(user, t, profile, body.history, body.message)
    db.add(models.LearningEvent(employee_id=user.id, training_id=t.id if t else None, kind="chat", payload={"message": body.message[:1000]}))
    db.commit()
    return out


# ---- accessibility settings ---------------------------------------------------------

A11Y_CHOICES = {
    "textScale": {1, 1.25, 1.5, 1.75, 2},
    "contrast": {"standard", "high-light", "high-dark"},
    "colorVision": {"standard", "cvd"},
    "font": {"standard", "readable"},
    "speechRate": {0.75, 1, 1.25, 1.5},
    "captions": {"on", "off"},
    "captionSize": {1, 1.5, 2},
    "captionStyle": {"standard", "high-contrast"},
    "extraTime": {0, 1, 1.5, 2},
}
A11Y_FLAGS = {"spacing", "underline", "targets", "reduceMotion", "readAloud", "showTranscript"}


@router.get("/accessibility")
def get_accessibility(user: models.Employee = Depends(current_user)):
    """The signed-in person's accessibility settings. Never shown to managers."""
    return user.accessibility or {}


@router.put("/accessibility")
def put_accessibility(body: dict, user: models.Employee = Depends(current_user), db: Session = Depends(get_db)):
    clean = {}
    for k, v in body.items():
        if k in A11Y_CHOICES and v in A11Y_CHOICES[k]:
            clean[k] = v
        elif k in A11Y_FLAGS and (isinstance(v, bool) or v is None):
            clean[k] = v
    user.accessibility = clean
    db.commit()
    return clean
