"""LANL organizational directory: divisions/groups and job positions.

file mode: data/<dir>/divisions.csv and positions.csv
live mode: GET {DIRECTORY_API_URL}/divisions and /positions returning JSON lists
           (swap in LDAP here if the directory is only exposed that way).
"""
from typing import Any

import httpx

from ..config import settings
from .base import Connector, ConnectorError, apply_aliases, find_file, load_mapping, read_records, to_bool, to_float, to_int, to_list

DIVISION_ALIASES = {
    "code": ["division_code", "org_code", "org", "division", "group_code"],
    "name": ["division_name", "org_name", "title"],
    "parent_code": ["parent", "parent_org", "directorate_code"],
    "directorate": ["directorate_name", "ald"],
    "leader_email": ["leader", "division_leader", "manager_email"],
}

POSITION_ALIASES = {
    "code": ["position_code", "job_code", "req_id", "position_id"],
    "title": ["job_title", "position_title", "name"],
    "division_code": ["division", "org_code", "org"],
    "level": ["job_level", "grade", "band"],
    "min_years": ["years_required", "min_experience", "required_years"],
    "required_skills": ["skills", "skill_requirements"],
    "required_trainings": ["trainings", "required_training_codes", "training_requirements"],
    "prerequisites": ["prereqs", "education", "clearance"],
    "is_open": ["open", "vacant", "hiring", "status"],
    "hiring_manager_email": ["hiring_manager", "manager_email"],
    "fiscal_year": ["fy", "fiscal_yr"],
    "headcount": ["openings", "positions", "count"],
}


def _division(row: dict[str, Any]) -> dict[str, Any]:
    r = apply_aliases(row, DIVISION_ALIASES, load_mapping("divisions"))
    if not r.get("code"):
        raise ConnectorError(f"Division row without a code: {row}")
    return {
        "code": str(r["code"]).strip(),
        "name": str(r.get("name") or r["code"]).strip(),
        "parent_code": (str(r["parent_code"]).strip() or None) if r.get("parent_code") else None,
        "directorate": r.get("directorate") or None,
        "leader_email": (str(r["leader_email"]).lower().strip() or None) if r.get("leader_email") else None,
    }


def _position(row: dict[str, Any]) -> dict[str, Any]:
    r = apply_aliases(row, POSITION_ALIASES, load_mapping("positions"))
    if not r.get("code"):
        raise ConnectorError(f"Position row without a code: {row}")
    open_val = r.get("is_open", "")
    return {
        "code": str(r["code"]).strip(),
        "title": str(r.get("title") or "").strip(),
        "division_code": str(r.get("division_code") or "").strip(),
        "level": to_int(r.get("level"), 1),
        "min_years": to_float(r.get("min_years"), 0.0),
        "required_skills": [s.lower() for s in to_list(r.get("required_skills"))],
        "required_trainings": to_list(r.get("required_trainings")),
        "prerequisites": to_list(r.get("prerequisites")),
        "is_open": to_bool(open_val) or str(open_val).lower() in {"open", "posted"},
        "hiring_manager_email": (str(r["hiring_manager_email"]).lower().strip() or None) if r.get("hiring_manager_email") else None,
        "fiscal_year": to_int(r.get("fiscal_year")),
        "headcount": to_int(r.get("headcount"), 1),
    }


class DirectoryConnector(Connector):
    name = "directory"

    def _raw(self) -> tuple[list[dict], list[dict]]:
        if settings.directory_mode == "live":
            if not settings.directory_api_url:
                raise ConnectorError("DIRECTORY_MODE=live but DIRECTORY_API_URL is empty")
            headers = {"Authorization": f"Bearer {settings.directory_api_token}"} if settings.directory_api_token else {}
            with httpx.Client(base_url=settings.directory_api_url, headers=headers, timeout=30) as c:
                return c.get("/divisions").raise_for_status().json(), c.get("/positions").raise_for_status().json()
        return read_records(find_file("divisions")), read_records(find_file("positions"))

    def fetch(self):
        divisions, positions = self._raw()
        return {"divisions": [_division(r) for r in divisions], "positions": [_position(r) for r in positions]}
