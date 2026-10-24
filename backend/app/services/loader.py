"""Bulk loading so pages about many people run a handful of queries, not one per person.

`load_people` fetches employees with their assignments, trainings, class sessions,
assessment attempts and managers in a few IN queries, then `prefetch` caches the
training catalog, positions and everyone's skill mastery for the request.
Functions in adaptive.py and matching.py read these caches when present.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models

CHUNK = 900  # stay under SQLite's bound-parameter limit


def _chunks(ids: list[int]):
    for i in range(0, len(ids), CHUNK):
        yield ids[i:i + CHUNK]


def people_query():
    a = selectinload(models.Employee.assignments)
    return select(models.Employee).options(
        a.selectinload(models.Assignment.training),
        a.selectinload(models.Assignment.session),
        a.selectinload(models.Assignment.attempts_log),
        selectinload(models.Employee.manager),
    )


def load_people(db: Session, ids: set[int] | list[int] | None = None) -> list[models.Employee]:
    """ids=None loads everyone (e.g. lab-wide candidate search)."""
    if ids is None:
        people = list(db.scalars(people_query()))
    else:
        people = []
        for chunk in _chunks(sorted(ids)):
            people += list(db.scalars(people_query().where(models.Employee.id.in_(chunk))))
    prefetch(db, people, everyone=ids is None)
    return people


def prefetch(db: Session, people: list[models.Employee], everyone: bool = False):
    if "trainings" not in db.info:
        db.info["trainings"] = list(db.scalars(select(models.Training)))
        db.info["positions"] = {p.code: p for p in db.scalars(select(models.Position))}
    by_emp = db.info.setdefault("mastery", {})  # employee id -> {skill: Mastery}
    need = [p.id for p in people if p.id not in by_emp]
    for eid in need:
        by_emp[eid] = {}
    stmt = select(models.Mastery)
    for chunk in ([None] if everyone else list(_chunks(need))):
        q = stmt if chunk is None else stmt.where(models.Mastery.employee_id.in_(chunk))
        for m in db.scalars(q):
            if m.employee_id in by_emp and (everyone or m.employee_id in need):
                by_emp[m.employee_id][m.skill] = m


def all_trainings(db: Session) -> list[models.Training]:
    if "trainings" in db.info:
        return db.info["trainings"]
    return list(db.scalars(select(models.Training)))


def positions(db: Session) -> dict[str, models.Position]:
    if "positions" in db.info:
        return db.info["positions"]
    return {p.code: p for p in db.scalars(select(models.Position))}
