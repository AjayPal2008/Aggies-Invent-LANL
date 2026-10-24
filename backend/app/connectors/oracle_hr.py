"""Employee records from Oracle HR (job title, salary, performance, experience).

file mode: data/<dir>/employees.csv (an export of the HR view)
live mode: runs ORACLE_EMPLOYEE_QUERY over python-oracledb (pip install oracledb).
Optional completion history: data/<dir>/training_history.csv
"""
from typing import Any

from ..config import settings
from .base import (Connector, ConnectorError, apply_aliases, find_file, load_mapping, read_records, to_bool, to_date,
                   to_float, to_int, to_list)

EMPLOYEE_ALIASES = {
    "employee_number": ["employee_id", "emp_id", "emp_no", "z_number", "znumber", "person_id"],
    "email": ["work_email", "email_address", "mail"],
    "name": ["full_name", "employee_name", "display_name"],
    "job_title": ["title", "position_title", "job"],
    "position_code": ["job_code", "position_id"],
    "division_code": ["division", "org_code", "org", "group"],
    "level": ["job_level", "grade", "band"],
    "hire_date": ["start_date", "date_hired", "original_hire_date"],
    "years_experience": ["years_relevant_experience", "relevant_experience_years", "experience_years", "yoe"],
    "salary": ["annual_salary", "base_salary", "pay"],
    "performance_rating": ["performance", "rating", "perf_rating", "last_rating"],
    "manager_number": ["manager_id", "supervisor_id", "manager_emp_id", "reports_to"],
    "is_manager": ["manager_flag", "supervisor_flag", "people_manager"],
    "skills": ["skill_list", "competencies"],
    "background": ["resume", "experience_summary", "prior_experience"],
    "learning_style": ["preferred_learning_style"],
}

HISTORY_ALIASES = {
    "employee_number": ["employee_id", "emp_id", "z_number"],
    "training_code": ["course_code", "course_id", "code"],
    "status": ["completion_status", "state"],
    "completed_on": ["completion_date", "completed", "date_completed"],
    "due_date": ["due", "due_on"],
    "score": ["assessment_score", "grade", "result"],
    "attempts": ["tries"],
}


def _employee(row: dict[str, Any]) -> dict[str, Any]:
    r = apply_aliases(row, EMPLOYEE_ALIASES, load_mapping("employees"))
    if not r.get("employee_number") or not r.get("email"):
        raise ConnectorError(f"Employee row needs an id and email: {row}")
    skills = to_list(r.get("skills"))
    return {
        "employee_number": str(r["employee_number"]).strip(),
        "email": str(r["email"]).strip().lower(),
        "name": str(r.get("name") or r["email"]).strip(),
        "job_title": str(r.get("job_title") or "").strip(),
        "position_code": (str(r["position_code"]).strip() or None) if r.get("position_code") else None,
        "division_code": str(r.get("division_code") or "").strip(),
        "level": to_int(r.get("level"), 1),
        "hire_date": to_date(r.get("hire_date")),
        "years_experience": to_float(r.get("years_experience"), 0.0),
        "salary": to_float(r.get("salary")),
        "performance_rating": to_float(r.get("performance_rating")),
        "manager_number": (str(r["manager_number"]).strip() or None) if r.get("manager_number") else None,
        "is_manager": to_bool(r.get("is_manager", False)),
        "skills": {s.lower(): 0.6 for s in skills},  # self-reported skills start at moderate confidence
        "background": str(r.get("background") or "").strip(),
        "learning_style": str(r.get("learning_style") or "unknown").strip().lower() or "unknown",
    }


def _history(row: dict[str, Any]) -> dict[str, Any]:
    r = apply_aliases(row, HISTORY_ALIASES, load_mapping("training_history"))
    status = str(r.get("status") or "").strip().lower().replace(" ", "_")
    if status in {"complete", "completed", "passed", "done"}:
        status = "completed"
    elif status in {"in_progress", "started", "inprogress", "enrolled"}:
        status = "in_progress"
    else:
        status = "not_started"
    return {
        "employee_number": str(r.get("employee_number") or "").strip(),
        "training_code": str(r.get("training_code") or "").strip(),
        "status": status,
        "completed_on": to_date(r.get("completed_on")),
        "due_date": to_date(r.get("due_date")),
        "score": to_float(r.get("score")),
        "attempts": to_int(r.get("attempts"), 1 if status == "completed" else 0),
    }


class OracleHRConnector(Connector):
    name = "oracle_hr"

    def _live_rows(self) -> list[dict[str, Any]]:
        try:
            import oracledb  # type: ignore
        except ImportError as exc:
            raise ConnectorError("ORACLE_MODE=live needs `pip install oracledb`") from exc
        if not settings.oracle_dsn:
            raise ConnectorError("ORACLE_MODE=live but ORACLE_DSN is empty")
        with oracledb.connect(user=settings.oracle_user, password=settings.oracle_password, dsn=settings.oracle_dsn) as conn:
            cur = conn.cursor()
            cur.execute(settings.oracle_employee_query)
            cols = [d[0].lower() for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def fetch(self):
        rows = self._live_rows() if settings.oracle_mode == "live" else read_records(find_file("employees"))
        out = {"employees": [_employee(r) for r in rows]}
        hist = find_file("training_history")
        out["history"] = [_history(r) for r in read_records(hist)] if hist.exists() else []
        return out
