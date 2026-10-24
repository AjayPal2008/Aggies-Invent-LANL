"""Turn database rows into JSON for the dashboards."""
from . import models
from .services.adaptive import assignment_flags


def training(t: models.Training, brief: bool = False) -> dict:
    d = {
        "id": t.id, "code": t.code, "title": t.title, "category": t.category, "required": t.required,
        "delivery": t.delivery, "source_system": t.source_system, "source_url": t.source_url,
        "duration_minutes": t.duration_minutes, "validity_months": t.validity_months, "skills": t.skills,
        "assessment_type": t.assessment_type or "quiz", "from_document": bool(t.document_id),
    }
    if not brief:
        d.update({"description": t.description, "prerequisites": t.prerequisites, "job_roles": t.job_roles,
                  "equipment": t.equipment, "facilities": t.facilities, "outline": t.outline,
                  "sessions": [session(s) for s in sorted(t.sessions, key=lambda s: s.starts_at)]})
    return d


def session(s: models.TrainingSession) -> dict:
    return {"id": s.id, "training_id": s.training_id, "starts_at": s.starts_at.isoformat(), "ends_at": s.ends_at.isoformat(),
            "location": s.location, "instructor": s.instructor, "capacity": s.capacity}


def assignment(a: models.Assignment) -> dict:
    return {
        "id": a.id, "employee_id": a.employee_id, "status": a.status, "progress": a.progress,
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
        "completed_at": a.completed_at.isoformat() if a.completed_at else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "next_retraining": a.next_retraining.isoformat() if a.next_retraining else None,
        "best_score": a.best_score, "attempts": a.attempts, "difficulty": a.difficulty,
        "session": session(a.session) if a.session else None,
        "flags": assignment_flags(a),
        "training": training(a.training, brief=True),
        "scores": [{"score": x.score, "taken_at": x.taken_at.isoformat()} for x in a.attempts_log],
    }


def employee(e: models.Employee, private: bool = False) -> dict:
    d = {
        "id": e.id, "employee_number": e.employee_number, "email": e.email, "name": e.name, "job_title": e.job_title,
        "position_code": e.position_code, "division_code": e.division_code, "level": e.level,
        "hire_date": e.hire_date.isoformat() if e.hire_date else None, "is_new_hire": e.is_new_hire,
        "years_experience": e.years_experience, "role": e.role, "learning_style": e.learning_style,
        "manager_id": e.manager_id, "manager_name": e.manager.name if e.manager else None,
        "skills": e.skills or {},
        "entry_path": e.entry_path, "previous_position_code": e.previous_position_code,
        "role_start_date": e.role_start_date.isoformat() if e.role_start_date else None,
    }
    if private:  # HR fields only go to managers/admins
        d.update({"salary": e.salary, "performance_rating": e.performance_rating, "background": e.background})
    return d
