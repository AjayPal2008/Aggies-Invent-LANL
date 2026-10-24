"""Pull records from every connector and upsert them into the database.

Safe to run repeatedly: rows are matched on their natural keys (codes, employee
numbers), so a nightly sync updates instead of duplicating.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..auth import hash_password
from ..config import settings
from ..connectors import DirectoryConnector, OracleHRConnector, UTrainConnector
from . import adaptive
from .loader import prefetch


def _existing(db: Session, model, key: str) -> dict:
    """Load every row once, keyed by its natural key, instead of one SELECT per record."""
    return {getattr(o, key): o for o in db.scalars(select(model))}


def _upsert(db: Session, model, key: str, record: dict, stats: dict, existing: dict | None = None):
    if existing is None:
        obj = db.scalar(select(model).where(getattr(model, key) == record[key]))
    else:
        obj = existing.get(record[key])
    if obj is None:
        obj = model(**record)
        db.add(obj)
        if existing is not None:
            existing[record[key]] = obj
        stats["created"] += 1
    else:
        for k, v in record.items():
            setattr(obj, k, v)
        stats["updated"] += 1
    return obj


def _log(db: Session, source: str, stats: dict):
    db.add(models.SyncRun(source=source, created=stats["created"], updated=stats["updated"], errors=stats["errors"]))


def sync_directory(db: Session) -> dict:
    stats = {"created": 0, "updated": 0, "errors": []}
    data = DirectoryConnector().fetch()
    divisions, positions = _existing(db, models.Division, "code"), _existing(db, models.Position, "code")
    for rec in data["divisions"]:
        _upsert(db, models.Division, "code", rec, stats, divisions)
    for rec in data["positions"]:
        _upsert(db, models.Position, "code", rec, stats, positions)
    _log(db, "directory", stats)
    db.commit()
    return stats


def sync_trainings(db: Session) -> dict:
    stats = {"created": 0, "updated": 0, "errors": []}
    data = UTrainConnector().fetch()
    by_code = _existing(db, models.Training, "code")
    for rec in data["trainings"]:
        _upsert(db, models.Training, "code", rec, stats, by_code)
    db.flush()
    sessions = {(x.training_id, x.starts_at): x for x in db.scalars(select(models.TrainingSession))}
    for rec in data["sessions"]:
        t = by_code.get(rec["training_code"])
        if t is None:
            stats["errors"].append(f"Session for unknown training {rec['training_code']}")
            continue
        exists = sessions.get((t.id, rec["starts_at"]))
        fields = {k: v for k, v in rec.items() if k != "training_code"}
        if exists:
            for k, v in fields.items():
                setattr(exists, k, v)
            stats["updated"] += 1
        else:
            db.add(models.TrainingSession(training_id=t.id, **fields))
            stats["created"] += 1
    _log(db, "utrain", stats)
    db.commit()
    return stats


def sync_employees(db: Session) -> dict:
    stats = {"created": 0, "updated": 0, "errors": []}
    data = OracleHRConnector().fetch()
    records = data["employees"]
    manager_numbers = {r["manager_number"] for r in records if r.get("manager_number")}
    emps: dict[str, models.Employee] = {}
    existing = _existing(db, models.Employee, "employee_number")
    admins = {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}
    demo_hash = None  # bcrypt is slow on purpose; hash the shared demo password once per sync

    for rec in records:
        manager_number = rec.pop("manager_number")
        is_manager = rec.pop("is_manager") or rec["employee_number"] in manager_numbers
        skills = rec.pop("skills")
        obj = _upsert(db, models.Employee, "employee_number", rec, stats, existing)
        obj.role = "admin" if obj.email in admins else ("manager" if is_manager else "hire")
        obj.skills = {**skills, **(obj.skills or {})}
        if obj.password_hash is None:
            # Password login exists for demos and sites without SSO; production uses Google/SSO.
            demo_hash = demo_hash or hash_password(settings.demo_password)
            obj.password_hash = demo_hash
        obj._manager_number = manager_number  # resolved after every row exists
        emps[obj.employee_number] = obj
    db.flush()

    for obj in emps.values():
        mn = getattr(obj, "_manager_number", None)
        if mn and mn in emps:
            obj.manager_id = emps[mn].id
        elif mn:
            stats["errors"].append(f"{obj.employee_number}: manager {mn} not found")

    # Completion history -> assignments
    db.flush()
    prefetch(db, list(emps.values()))  # skill mastery in memory for the whole roster
    trainings = {t.code: t for t in db.scalars(select(models.Training))}
    assignments = {(a.employee_id, a.training_id): a for a in db.scalars(select(models.Assignment))}
    for h in data["history"]:
        emp, t = emps.get(h["employee_number"]), trainings.get(h["training_code"])
        if not emp or not t:
            stats["errors"].append(f"History row skipped: {h['employee_number']} / {h['training_code']}")
            continue
        a = assignments.get((emp.id, t.id))
        if a is None:
            a = models.Assignment(employee_id=emp.id, training_id=t.id, assigned_by_id=emp.manager_id, training=t)
            emp.assignments.append(a)
            assignments[(emp.id, t.id)] = a
        a.status, a.due_date, a.attempts = h["status"], h["due_date"] or a.due_date, h["attempts"] or a.attempts
        if h["status"] == "completed":
            a.progress = 100
            a.completed_at = datetime.combine(h["completed_on"], datetime.min.time()) if h["completed_on"] else datetime.utcnow()
            if h["score"] is not None:
                a.best_score = h["score"]
            adaptive.schedule_retraining(a, t)
            if h["score"] is not None:
                adaptive.record_assessment_skills(db, emp, t, h["score"])
        elif h["status"] == "in_progress":
            a.progress = max(a.progress or 0, 40)
            a.started_at = a.started_at or datetime.utcnow()
    db.flush()

    for emp in emps.values():
        adaptive.refresh_inferred_skills(db, emp)

    _log(db, "oracle_hr", stats)
    db.commit()
    db.info.clear()
    return stats


def ensure_required_assignments(db: Session) -> int:
    """Auto-assign required trainings that match each employee's position."""
    created = 0
    positions = {p.code: p for p in db.scalars(select(models.Position))}
    trainings = list(db.scalars(select(models.Training)))
    from .loader import load_people

    for emp in load_people(db, None):
        pos = positions.get(emp.position_code or "")
        needed = set(pos.required_trainings) if pos else set()
        for t in trainings:
            if t.required and (not t.job_roles or emp.position_code in t.job_roles or emp.job_title in t.job_roles or "all" in t.job_roles):
                needed.add(t.code)
        have = {a.training.code for a in emp.assignments}
        for code in needed - have:
            t = next((x for x in trainings if x.code == code), None)
            if t:
                db.add(models.Assignment(employee_id=emp.id, training_id=t.id, assigned_by_id=emp.manager_id,
                                         due_date=adaptive.default_due_date(emp, t)))
                created += 1
    db.commit()
    db.info.clear()
    return created


def sync_all(db: Session) -> dict:
    result = {"directory": sync_directory(db), "utrain": sync_trainings(db), "oracle_hr": sync_employees(db)}
    result["auto_assigned"] = ensure_required_assignments(db)
    from .library import sync_library

    result["library"] = sync_library(db)  # institutional / division / role training library
    return result
