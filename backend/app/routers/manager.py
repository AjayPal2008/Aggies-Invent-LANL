"""Manager dashboard endpoints. Every route requires the manager role."""
from __future__ import annotations

from collections import Counter
import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, serialize
from ..auth import require_manager, team_ids, team_of
from ..database import get_db
from ..services import adaptive, ai, insights, matching, notify
from ..safeguards import manager_cache, manager_version
from ..services.loader import load_people
from .hire import dashboard_for

router = APIRouter(prefix="/api/manager", tags=["manager"])


def fiscal_year(d: date) -> int:
    """LANL's fiscal year starts October 1."""
    return d.year + 1 if d.month >= 10 else d.year


def _target(db: Session, mgr: models.Employee, employee_id: int) -> models.Employee:
    return _targets(db, mgr, [employee_id])[0]


def _targets(db: Session, mgr: models.Employee, employee_ids: list[int]) -> list[models.Employee]:
    """Load several team members at once; 404 if any of them isn't in this manager's org."""
    allowed = team_ids(db, mgr)
    bad = [i for i in employee_ids if i not in allowed]
    if bad:
        raise HTTPException(404, f"Not on your team: {', '.join(map(str, bad[:5]))}")
    by_id = {e.id: e for e in load_people(db, set(employee_ids))}
    return [by_id[i] for i in employee_ids]


def staggered_due(deadline: date | None, index: int, total: int, weeks: int) -> date | None:
    """Spread due dates over a window that ends at the real deadline, so a big group doesn't all log in
    the night before. Nobody gets less than a week from today."""
    if deadline is None or weeks <= 0 or total <= 1:
        return deadline
    window = weeks * 7
    offset = window - round(index * window / (total - 1))
    return max(date.today() + timedelta(days=7), deadline - timedelta(days=offset))


def _row(db: Session, e: models.Employee, sub_team: dict | None = None, gaps: bool = True) -> dict:
    row = {**serialize.employee(e, private=True), "summary": matching.training_summary(e),
           "avg_score": matching.avg_score(e), "performance_index": matching.performance_index(e), "sub_team": sub_team}
    if gaps:
        row["gap_count"] = len(adaptive.knowledge_gaps(db, e))
    return row


def _cached(mgr: models.Employee, name: str, params, build, cache: bool = True):
    """Manager dashboards are read far more than they change, so each manager's numbers are cached:
    30 seconds for teams, 5 minutes for orgs over 500 people (division-level views). The manager's own
    changes (assign, due dates, reviews) clear it immediately. Builds are capped per worker."""
    from ..safeguards import REPORT_WAIT_SECONDS, report_slots

    def guarded():
        if not report_slots.acquire(timeout=REPORT_WAIT_SECONDS):
            raise HTTPException(503, "Reports are busy right now. Try again in a few seconds.", headers={"Retry-After": "5"})
        try:
            return build()
        finally:
            report_slots.release()

    if not cache:
        return guarded()
    ttl = 30 if len(team_ids(_db_of(mgr), mgr)) < 500 else 300
    return manager_cache.get((mgr.id, manager_version(mgr.id), name, params), guarded, ttl=ttl)


def _db_of(obj):
    from sqlalchemy.orm import object_session

    return object_session(obj)


def _sub_teams(mgr: models.Employee, people: list[models.Employee]) -> dict[int, models.Employee | None]:
    """Map each person to the manager's direct report they roll up to (None = reports directly).

    Each chain is walked once and remembered, so this stays linear for orgs with thousands of people.
    """
    by_id = {e.id: e for e in people}
    top_of: dict[int, models.Employee] = {}  # person id -> the direct report at the top of their chain
    for e in people:
        path, cur = [], e
        while cur.id not in top_of and cur.manager_id != mgr.id and cur.manager_id in by_id:
            path.append(cur)
            cur = by_id[cur.manager_id]
        top = top_of.get(cur.id, cur)
        top_of[cur.id] = top
        for p in path:
            top_of[p.id] = top
    return {e.id: (None if top_of[e.id] is e else top_of[e.id]) for e in people}


@router.get("/overview")
def overview(mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    return _cached(mgr, "overview", None, lambda: _overview(db, mgr))


def _overview(db: Session, mgr: models.Employee) -> dict:
    team = team_of(db, mgr)
    status = Counter()
    flags = Counter()
    for e in team:
        for a in e.assignments:
            status[a.status] += 1
            for k, v in adaptive.assignment_flags(a).items():
                flags[k] += 1 if v else 0
    fy = Counter(fiscal_year(e.hire_date) for e in team if e.hire_date)
    open_positions = list(db.scalars(select(models.Position).where(models.Position.is_open.is_(True))))
    if mgr.role != "admin":
        open_positions = [p for p in open_positions if p.hiring_manager_email in (None, mgr.email) or p.division_code == mgr.division_code]
    return {
        "manager": serialize.employee(mgr),
        "team_size": len(team),
        "new_hires": sum(1 for e in team if e.is_new_hire),
        "status": dict(status),
        "flags": dict(flags),
        "headcount_by_fiscal_year": dict(sorted(fy.items())),
        "current_fiscal_year": fiscal_year(date.today()),
        "open_positions": len(open_positions),
        "avg_completion": round(sum(matching.training_summary(e)["completion_rate"] for e in team) / len(team), 1) if team else 0,
    }


@router.get("/team")
def team(response: Response, new_hires_only: bool = False, level: int | None = None, min_level: int | None = None,
         max_level: int | None = None, sort: str = "performance", fiscal_year_hired: int | None = None, q: str = "",
         under: int | None = None, direct_only: bool = False, page: int = 0, page_size: int = 0, ids_only: bool = False,
         lite: bool = False, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """The manager's whole org (direct and indirect reports), filtered and ranked.

    under=<id> limits to one team lead's sub-team (the lead included); direct_only=true to direct reports.
    page/page_size page on the server (X-Total-Count has the total); ids_only returns every matching id
    (for "select all"); lite skips training summaries (for people pickers). Large orgs should always page.
    """
    params = (new_hires_only, level, min_level, max_level, sort, fiscal_year_hired, q.lower(), under, direct_only, lite)
    # Free-text searches aren't cached (endless variety would just fill memory).
    rows = _cached(mgr, "team", params, lambda: _team_rows(db, mgr, *params), cache=not q)
    response.headers["X-Total-Count"] = str(len(rows))
    if ids_only:
        return {"total": len(rows), "ids": [r["id"] for r in rows]}
    shown = rows[page * page_size:(page + 1) * page_size] if page_size else rows
    if not lite and len(shown) <= 200:
        # Knowledge gaps are the expensive part; work them out only for the rows being shown.
        people = {e.id: e for e in load_people(db, {r["id"] for r in shown})}
        shown = [{**r, "gap_count": len(adaptive.knowledge_gaps(db, people[r["id"]]))} for r in shown]
    return shown


def _team_rows(db, mgr, new_hires_only, level, min_level, max_level, sort, fiscal_year_hired, q, under, direct_only, lite):
    people = _filter_team(db, mgr, new_hires_only, level, min_level, max_level, fiscal_year_hired, q, under, direct_only)
    leads = _sub_teams(mgr, team_of(db, mgr))
    sub = lambda e: {"id": leads[e.id].id, "name": leads[e.id].name} if leads.get(e.id) else None  # noqa: E731
    if lite:
        rows = [{**serialize.employee(e), "sub_team": sub(e)} for e in people]
        rows.sort(key=lambda r: r["name"])
    else:
        rows = [_row(db, e, sub(e), gaps=False) for e in people]
        keys = {
            "performance": lambda r: -r["performance_index"],
            "completion": lambda r: -r["summary"]["completion_rate"],
            "overdue": lambda r: -r["summary"]["overdue"],
            "name": lambda r: r["name"],
            "hire_date": lambda r: r["hire_date"] or "",
            "level": lambda r: -r["level"],
        }
        rows.sort(key=keys.get(sort, keys["performance"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def _filter_team(db, mgr, new_hires_only=False, level=None, min_level=None, max_level=None, fiscal_year_hired=None,
                 q="", under=None, direct_only=False) -> list[models.Employee]:
    people = team_of(db, mgr)
    if under is not None:
        sub = {under} | _descendants(people, under)
        people = [e for e in people if e.id in sub]
    if direct_only:
        people = [e for e in people if e.manager_id == mgr.id]
    if q:
        needle = q.lower()
        people = [e for e in people if needle in f"{e.name} {e.email} {e.job_title} {e.employee_number}".lower()]
    if new_hires_only:
        people = [e for e in people if e.is_new_hire]
    if level is not None:
        people = [e for e in people if e.level == level]
    if min_level is not None:
        people = [e for e in people if e.level >= min_level]
    if max_level is not None:
        people = [e for e in people if e.level <= max_level]
    if fiscal_year_hired is not None:
        people = [e for e in people if e.hire_date and fiscal_year(e.hire_date) == fiscal_year_hired]
    return people


def _descendants(people: list[models.Employee], root: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for e in people:
        if e.manager_id is not None:
            children.setdefault(e.manager_id, []).append(e.id)
    out, frontier = set(), [root]
    while frontier:
        frontier = [c for f in frontier for c in children.get(f, []) if c not in out]
        out.update(frontier)
    return out


@router.get("/org")
def org(mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """The manager's direct reports, each with a roll-up of the sub-team under them."""
    return _cached(mgr, "org", None, lambda: _org(db, mgr))


def _org(db: Session, mgr: models.Employee) -> dict:
    people = team_of(db, mgr)
    ids = {e.id for e in people}
    direct = [e for e in people if e.manager_id == mgr.id or (mgr.role == "admin" and e.manager_id not in ids)]
    leads = _sub_teams(mgr, people)  # one pass: who rolls up to which direct report
    groups: dict[int, list[models.Employee]] = {}
    for e in people:
        lead = leads.get(e.id)
        if lead is not None:
            groups.setdefault(lead.id, []).append(e)
    by_id = {e.id: e for e in people}
    out = []
    for lead_id, members in groups.items():
        lead = by_id[lead_id]
        everyone = [lead, *members]
        summaries = [matching.training_summary(e) for e in everyone]
        out.append({"lead": {"id": lead.id, "name": lead.name, "job_title": lead.job_title}, "size": len(everyone),
                    "new_hires": sum(1 for e in everyone if e.is_new_hire),
                    "overdue": sum(x["overdue"] for x in summaries), "needs_retake": sum(x["needs_retake"] for x in summaries),
                    "avg_completion": round(sum(x["completion_rate"] for x in summaries) / len(summaries), 1)})
    return {"team_size": len(people), "direct_reports": len(direct), "groups": sorted(out, key=lambda g: -g["size"])[:24],
            "individual_contributors": sum(1 for e in direct if e.id not in groups)}


@router.get("/team.csv")
def export_team(mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Download the team with training status for spreadsheets and reports."""
    people = team_of(db, mgr)
    leads = _sub_teams(mgr, people)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["employee_number", "name", "email", "job_title", "level", "division", "sub_team", "hire_date", "new_hire",
                "assigned", "completed", "in_progress", "not_started", "overdue", "needs_retake", "expiring",
                "completion_rate", "avg_score", "performance_rating", "performance_index"])
    for e in sorted(people, key=lambda x: x.name):
        s = matching.training_summary(e)
        w.writerow([e.employee_number, e.name, e.email, e.job_title, e.level, e.division_code,
                    leads[e.id].name if leads.get(e.id) else "", e.hire_date or "", e.is_new_hire, s["total"], s["completed"],
                    s["in_progress"], s["not_started"], s["overdue"], s["needs_retake"], s["expiring"], s["completion_rate"],
                    matching.avg_score(e) or "", e.performance_rating or "", matching.performance_index(e)])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="team-{date.today().isoformat()}.csv"'})


@router.get("/team/{employee_id}")
def hire_view(employee_id: int, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Read-only hire view: what this person sees, plus HR fields. Managers cannot act as the hire."""
    emp = _target(db, mgr, employee_id)
    data = dashboard_for(db, emp)
    data["employee"] = serialize.employee(emp, private=True)
    data["promotion"] = matching.promotion_readiness(db, emp)
    data["read_only"] = True
    return data


class AssignIn(BaseModel):
    employee_ids: list[int]
    training_codes: list[str]
    due_date: date | None = None
    stagger_weeks: int = 0  # spread due dates over this many weeks before due_date


@router.post("/assignments")
def assign(body: AssignIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    created, skipped = [], []
    trainings = {t.code: t for t in db.scalars(select(models.Training).where(models.Training.code.in_(body.training_codes)))}
    missing = set(body.training_codes) - set(trainings)
    if missing:
        raise HTTPException(400, f"Unknown training codes: {', '.join(sorted(missing))}")
    people = _targets(db, mgr, body.employee_ids)
    for idx, emp in enumerate(people):
        eid = emp.id
        due = staggered_due(body.due_date, idx, len(people), body.stagger_weeks)
        for t in trainings.values():
            existing = next((a for a in emp.assignments if a.training_id == t.id), None)
            if existing and existing.status != "completed":
                skipped.append({"employee_id": eid, "training_code": t.code, "reason": "already assigned"})
                continue
            if existing:  # completed before: reassign as a refresher
                existing.status, existing.progress, existing.needs_retake = "not_started", 0, True
                existing.due_date = due or adaptive.default_due_date(emp, t)
                existing.assigned_by_id = mgr.id
                created.append({"employee_id": eid, "training_code": t.code, "refresher": True})
                continue
            a = models.Assignment(employee_id=emp.id, training_id=t.id, assigned_by_id=mgr.id,
                                  due_date=due or adaptive.default_due_date(emp, t),
                                  difficulty=adaptive.difficulty_for(db, emp, t))
            db.add(a)
            created.append({"employee_id": eid, "training_code": t.code})
    db.commit()
    return {"created": created, "skipped": skipped}


@router.delete("/assignments/{assignment_id}")
def unassign(assignment_id: int, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "Assignment not found")
    _target(db, mgr, a.employee_id)
    if a.status == "completed":
        raise HTTPException(400, "Completed trainings stay on record")
    db.delete(a)
    db.commit()
    return {"deleted": assignment_id}


class DueDateIn(BaseModel):
    due_date: date


@router.patch("/assignments/{assignment_id}")
def change_due_date(assignment_id: int, body: DueDateIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "Assignment not found")
    _target(db, mgr, a.employee_id)
    a.due_date = body.due_date
    db.commit()
    return serialize.assignment(a)


class BulkIn(BaseModel):
    employee_ids: list[int]
    training_codes: list[str] = []
    due_date: date | None = None
    stagger_weeks: int = 0


@router.post("/assignments/bulk-due-date")
def bulk_due_date(body: BulkIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Move the due date of these trainings (or every open assignment if none named) for these people."""
    if body.due_date is None:
        raise HTTPException(400, "due_date is required")
    changed = 0
    people = _targets(db, mgr, body.employee_ids)
    for idx, emp in enumerate(people):
        due = staggered_due(body.due_date, idx, len(people), body.stagger_weeks)
        for a in emp.assignments:
            if a.status != "completed" and (not body.training_codes or a.training.code in body.training_codes):
                a.due_date = due
                changed += 1
    db.commit()
    return {"changed": changed}


@router.post("/assignments/bulk-remove")
def bulk_remove(body: BulkIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Remove unfinished assignments of these trainings. Completed records are never deleted."""
    if not body.training_codes:
        raise HTTPException(400, "Name at least one training to remove")
    removed = 0
    for emp in _targets(db, mgr, body.employee_ids):
        for a in list(emp.assignments):
            if a.training.code in body.training_codes and a.status != "completed":
                emp.assignments.remove(a)
                removed += 1
    db.commit()
    return {"removed": removed}


@router.post("/assignments/role-requirements")
def assign_role_requirements(body: BulkIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Assign whatever each person is missing for their role: position trainings plus required trainings for that role."""
    from ..services.loader import all_trainings, positions as all_positions

    pos_by_code, trainings = all_positions(db), all_trainings(db)
    created = []
    for emp in _targets(db, mgr, body.employee_ids):
        pos = pos_by_code.get(emp.position_code or "")
        needed = set(pos.required_trainings) if pos else set()
        needed |= {t.code for t in trainings if t.required and adaptive._relevant(t, emp)}
        have = {a.training.code for a in emp.assignments}
        for t in trainings:
            if t.code in needed - have:
                emp.assignments.append(models.Assignment(training=t, assigned_by_id=mgr.id,
                                                         due_date=body.due_date or adaptive.default_due_date(emp, t)))
                created.append({"employee_id": emp.id, "training_code": t.code})
    db.commit()
    return {"created": created}


@router.get("/retraining")
def retraining(days: int = 90, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Expiring certifications, failed assessments needing a retake, and the next retraining dates."""
    return _cached(mgr, "retraining", days, lambda: _retraining(db, mgr, days))


def _retraining(db: Session, mgr: models.Employee, days: int):
    horizon = date.today() + timedelta(days=days)
    out = []
    for e in team_of(db, mgr):
        for a in e.assignments:
            f = adaptive.assignment_flags(a)
            due_soon = a.next_retraining and a.next_retraining <= horizon
            if f["needs_retake"] or f["expiring"] or f["expired"] or due_soon:
                reason = ("failed assessment" if a.needs_retake and a.best_score is not None and a.best_score < 80
                          else "expired" if f["expired"] else "expiring" if f["expiring"] else "scheduled refresher")
                out.append({"employee_id": e.id, "name": e.name, "training_code": a.training.code, "title": a.training.title,
                            "best_score": a.best_score, "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                            "next_retraining": a.next_retraining.isoformat() if a.next_retraining else None,
                            "reason": reason, "assignment_id": a.id})
    return sorted(out, key=lambda r: r["next_retraining"] or r["expires_at"] or "9999")


@router.get("/positions")
def open_positions(mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    rows = []
    for p in db.scalars(select(models.Position).where(models.Position.is_open.is_(True))):
        if mgr.role != "admin" and p.hiring_manager_email not in (None, mgr.email) and p.division_code != mgr.division_code:
            continue
        rows.append({"code": p.code, "title": p.title, "division_code": p.division_code, "level": p.level, "min_years": p.min_years,
                     "required_skills": p.required_skills, "required_trainings": p.required_trainings,
                     "prerequisites": p.prerequisites, "fiscal_year": p.fiscal_year, "headcount": p.headcount})
    return rows


@router.get("/positions/{code}/candidates")
def candidates(code: str, qualified_only: bool = False, min_level: int | None = None, max_level: int | None = None,
               new_hires_only: bool = False, scope: str = "lab", mgr: models.Employee = Depends(require_manager),
               db: Session = Depends(get_db)):
    """Rank employees for an open role by AI-inferred skills, trainings, years and performance.

    scope=lab searches every employee (internal mobility); scope=team only the manager's org.
    """
    pos = db.scalar(select(models.Position).where(models.Position.code == code))
    if pos is None:
        raise HTTPException(404, "Position not found")
    if scope == "team":
        pool = team_of(db, mgr)
    else:
        # Only load people who could meet the level requirement (one level below or higher).
        floor = min_level if min_level is not None else pos.level - 1
        stmt = select(models.Employee.id).where(models.Employee.level >= floor, models.Employee.id != mgr.id)
        if max_level is not None:
            stmt = stmt.where(models.Employee.level <= max_level)
        pool = load_people(db, set(db.scalars(stmt)))
    if new_hires_only:
        pool = [e for e in pool if e.is_new_hire]
    if min_level is not None:
        pool = [e for e in pool if e.level >= min_level]
    if max_level is not None:
        pool = [e for e in pool if e.level <= max_level]
    return {"position": {"code": pos.code, "title": pos.title, "level": pos.level, "min_years": pos.min_years,
                         "required_skills": pos.required_skills, "required_trainings": pos.required_trainings,
                         "prerequisites": pos.prerequisites},
            "candidates": matching.candidates_for(db, pos, pool, qualified_only)}


@router.get("/promotions")
def promotions(ready_only: bool = False, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    return _cached(mgr, "promotions", ready_only, lambda: _promotions(db, mgr, ready_only))


def _promotions(db: Session, mgr: models.Employee, ready_only: bool):
    rows = [matching.promotion_readiness(db, e) for e in team_of(db, mgr)]
    if ready_only:
        rows = [r for r in rows if r["ready"]]
    return sorted(rows, key=lambda r: (not r["ready"], -r["performance_index"]))


@router.post("/team/{employee_id}/infer-skills")
def infer_skills(employee_id: int, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Ask the AI to estimate this person's skills from background and training history, then save them."""
    emp = _target(db, mgr, employee_id)
    vocab = set()
    for t in db.scalars(select(models.Training)):
        vocab.update(t.skills or [])
    for p in db.scalars(select(models.Position)):
        vocab.update(p.required_skills or [])
    completed = [{"code": a.training.code, "score": a.best_score, "skills": a.training.skills}
                 for a in emp.assignments if a.status == "completed"]
    result = ai.infer_skills(emp, sorted(vocab), completed)
    skills = dict(emp.skills or {})
    for s, info in result["skills"].items():
        skills[s] = round(max(skills.get(s, 0), info["confidence"]), 3)
    emp.skills = skills
    db.commit()
    return {**result, "saved_skills": skills}


@router.get("/insights/heatmap")
def heatmap(group_by: str = "position", mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Knowledge-gap heatmap: average mastery of required skills by role or equipment."""
    if group_by not in ("position", "equipment"):
        raise HTTPException(400, "group_by must be position or equipment")
    return _cached(mgr, "heatmap", group_by, lambda: insights.gap_heatmap(db, team_of(db, mgr), group_by))


@router.get("/insights/compliance")
def compliance(mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Required-training compliance per division (safety broken out)."""
    return _cached(mgr, "compliance", None, lambda: insights.compliance_by_division(db, team_of(db, mgr)))


class ReminderIn(BaseModel):
    employee_ids: list[int] = []  # empty = everyone on the team with something due
    send: bool = False  # False = preview only


@router.post("/reminders")
def reminders(body: ReminderIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    people = _targets(db, mgr, body.employee_ids) if body.employee_ids else team_of(db, mgr)
    msgs = [m for m in (notify.build_reminder(e) for e in people) if m]
    if not body.send:
        return {"mode": "preview", "sent": 0, "messages": msgs}
    return notify.send(msgs)
