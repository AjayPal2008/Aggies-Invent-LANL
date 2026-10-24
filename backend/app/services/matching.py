"""Role fit, promotion readiness and ranking for the manager dashboard."""
from __future__ import annotations

from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from .adaptive import assignment_flags
from .loader import positions


def _completed_codes(emp: models.Employee) -> set[str]:
    return {a.training.code for a in emp.assignments if a.status == "completed" and not assignment_flags(a)["needs_retake"]}


def avg_score(emp: models.Employee) -> float | None:
    scores = [a.best_score for a in emp.assignments if a.best_score is not None]
    return round(mean(scores), 1) if scores else None


def training_summary(emp: models.Employee) -> dict:
    counts = {"not_started": 0, "in_progress": 0, "completed": 0, "overdue": 0, "expiring": 0, "needs_retake": 0}
    for a in emp.assignments:
        counts[a.status] = counts.get(a.status, 0) + 1
        f = assignment_flags(a)
        for k in ("overdue", "expiring", "needs_retake"):
            counts[k] += 1 if f[k] else 0
    total = len(emp.assignments)
    counts["total"] = total
    counts["completion_rate"] = round(counts["completed"] / total * 100, 1) if total else 0.0
    return counts


def performance_index(emp: models.Employee) -> float:
    """0-100 composite used for ranking: assessments 50%, HR rating 30%, completion 20%."""
    s = avg_score(emp)
    perf = (emp.performance_rating or 3) / 5 * 100
    comp = training_summary(emp)["completion_rate"]
    return round(0.5 * (s if s is not None else 70) + 0.3 * perf + 0.2 * comp, 1)


def role_fit(emp: models.Employee, pos: models.Position) -> dict:
    skills = emp.skills or {}
    req = pos.required_skills or []
    skill_cov = mean(min(1.0, skills.get(s, 0) / settings.mastery_threshold) for s in req) if req else 1.0
    have = _completed_codes(emp)
    req_t = pos.required_trainings or []
    missing_trainings = [c for c in req_t if c not in have]
    train_cov = 1 - len(missing_trainings) / len(req_t) if req_t else 1.0
    meets_years = (emp.years_experience or 0) >= (pos.min_years or 0)
    level_ok = emp.level >= pos.level - 1
    missing_skills = [s for s in req if skills.get(s, 0) < settings.mastery_threshold]
    score = 100 * (0.45 * skill_cov + 0.25 * train_cov + 0.15 * (1 if meets_years else (emp.years_experience or 0) / max(pos.min_years, 1))
                   + 0.15 * performance_index(emp) / 100)
    return {
        "employee_id": emp.id,
        "name": emp.name,
        "job_title": emp.job_title,
        "level": emp.level,
        "years_experience": emp.years_experience,
        "fit_score": round(score, 1),
        "skill_coverage": round(skill_cov * 100, 1),
        "training_coverage": round(train_cov * 100, 1),
        "meets_years": meets_years,
        "meets_level": level_ok,
        "meets_requirements": meets_years and level_ok and not missing_trainings and not missing_skills,
        "missing_skills": missing_skills,
        "missing_trainings": missing_trainings,
        "performance_index": performance_index(emp),
    }


def candidates_for(db: Session, pos: models.Position, pool: list[models.Employee], only_qualified: bool = False) -> list[dict]:
    rows = [role_fit(e, pos) for e in pool if e.position_code != pos.code]
    if only_qualified:
        rows = [r for r in rows if r["meets_requirements"]]
    return sorted(rows, key=lambda r: -r["fit_score"])


def promotion_readiness(db: Session, emp: models.Employee) -> dict:
    """Is this person ready for the next level in their track?"""
    # Closest higher-level role in the same division (divisions don't always define every level).
    higher = [p for p in positions(db).values() if p.division_code == emp.division_code and p.level > emp.level]
    next_pos = min(higher, key=lambda p: (p.level, not p.is_open)) if higher else None
    summary = training_summary(emp)
    s = avg_score(emp)
    checks = {
        "performance_rating >= 4": (emp.performance_rating or 0) >= 4,
        "no overdue trainings": summary["overdue"] == 0,
        "average assessment >= 85": s is not None and s >= 85,
    }
    fit = None
    if next_pos:
        fit = role_fit(emp, next_pos)
        checks[f"{next_pos.min_years:g}+ years experience"] = fit["meets_years"]
        checks["next-level trainings complete"] = not fit["missing_trainings"]
    ready = all(checks.values())
    return {
        "employee_id": emp.id,
        "name": emp.name,
        "current_level": emp.level,
        "job_title": emp.job_title,
        "next_position": {"code": next_pos.code, "title": next_pos.title, "level": next_pos.level} if next_pos else None,
        "ready": ready,
        "checks": checks,
        "fit": fit,
        "performance_index": performance_index(emp),
    }
