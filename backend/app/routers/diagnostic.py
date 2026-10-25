"""Authenticated, learner-safe diagnostic endpoints. No generation calls."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from ..auth import current_user
from ..services.diagnostic import DiagnosticError, SessionStore, get_store

router = APIRouter(prefix="/api/diagnostic", tags=["source-grounded diagnostic"])


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    randomize: bool = False
    initial_limit: int = Field(default=8, ge=1, le=12, strict=True)
    budget: int = Field(default=12, ge=1, le=24, strict=True)


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1, max_length=300)
    answer_id: str = Field(min_length=1, max_length=320)
    reason_id: str = Field(min_length=1, max_length=320)
    confidence: Literal["guessing", "somewhat sure", "very sure"] = "somewhat sure"


def run(response, function, *args):
    response.headers["Cache-Control"] = "no-store"
    try:
        return function(*args)
    except DiagnosticError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.get("/status")
def status(response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.availability)


@router.post("/sessions", status_code=201)
def start(body: StartIn, response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.start, user.id, body.initial_limit, body.budget, body.randomize)


@router.get("/sessions/{session_id}/current")
def current(session_id: str, response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.current, session_id, user.id)


@router.post("/sessions/{session_id}/answers")
def answer(session_id: str, body: AnswerIn, response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.submit, session_id, user.id, body.model_dump())


@router.get("/sessions/{session_id}/results")
def results(session_id: str, response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.results, session_id, user.id)


@router.get("/latest-completed")
def latest_completed(response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.latest_completed, user.id)


@router.get("/review-courses")
def review_courses(response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.review_courses, user.id)


@router.post("/sessions/{session_id}/review-courses/{objective_id}/complete")
def complete_review(session_id: str, objective_id: str, response: Response,
                    user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.complete_review, session_id, objective_id, user.id)


@router.post("/demo-new-hire", status_code=201)
def demo_new_hire(response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    if user.email.lower() != "hire@lanl.gov":
        raise HTTPException(403, "Only the new hire demo account can be reset")
    return run(response, store.restart_demo, user.id)


@router.get("/material-courses")
def material_courses(response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.material_courses, user.id)


@router.post("/materials/{course_id}/complete")
def complete_material(course_id: str, response: Response, user=Depends(current_user), store: SessionStore = Depends(get_store)):
    return run(response, store.complete_material, course_id, user.id)
