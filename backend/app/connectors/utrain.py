"""Training catalog: UTrain plus the other LANL sites trainings live on.

The point of this connector is to pull every training into one catalog and keep
`source_system` + `source_url` so people can still jump to the original site.

file mode: data/<dir>/trainings.csv and training_sessions.csv
           Extra files named trainings_<site>.csv are merged in too, so each
           training website can be exported separately.
live mode: GET {UTRAIN_API_URL}/courses and /sessions returning JSON lists.
"""
from pathlib import Path
from typing import Any

import httpx

from ..assessment_rules import choose as choose_assessment
from ..config import settings
from .base import (Connector, ConnectorError, apply_aliases, find_file, load_mapping, read_records, to_bool, to_datetime,
                   to_int, to_list)

TRAINING_ALIASES = {
    "code": ["course_code", "course_id", "course_number", "item_id", "id"],
    "title": ["course_title", "name", "course_name"],
    "description": ["summary", "course_description", "desc"],
    "category": ["type", "course_category", "subject"],
    "required": ["mandatory", "is_required", "requirement"],
    "delivery": ["delivery_method", "format", "modality"],
    "source_system": ["system", "source", "site"],
    "source_url": ["url", "link", "course_url"],
    "duration_minutes": ["duration", "length_minutes", "minutes"],
    "validity_months": ["recert_months", "expires_months", "retrain_months", "valid_for_months"],
    "skills": ["competencies", "topics_skills", "skill_tags"],
    "prerequisites": ["prereqs", "prerequisite_codes"],
    "job_roles": ["roles", "applicable_roles", "positions", "job_codes"],
    "equipment": ["equipment_tags", "tools"],
    "facilities": ["facility", "facility_tags", "buildings", "locations"],
    "outline": ["topics", "syllabus", "objectives"],
    "assessment_type": ["assessment", "assessment_method", "evaluation"],
}

SESSION_ALIASES = {
    "training_code": ["course_code", "course_id", "code"],
    "starts_at": ["start", "start_time", "start_datetime", "date"],
    "ends_at": ["end", "end_time", "end_datetime"],
    "location": ["room", "building", "venue"],
    "instructor": ["trainer", "teacher"],
    "capacity": ["seats", "max_seats"],
}

CATEGORY_MAP = {
    "esh": "safety", "safety": "safety", "rad": "safety", "radiation": "safety", "security": "compliance",
    "compliance": "compliance", "ethics": "compliance", "culture": "culture", "onboarding": "culture",
    "company culture": "culture", "technical": "technical", "engineering": "technical", "computing": "technical",
}


def _training(row: dict[str, Any], default_source: str) -> dict[str, Any]:
    r = apply_aliases(row, TRAINING_ALIASES, load_mapping("trainings"))
    if not r.get("code"):
        raise ConnectorError(f"Training row without a code: {row}")
    cat = str(r.get("category") or "technical").strip().lower()
    delivery = str(r.get("delivery") or "online").strip().lower().replace("-", "_").replace(" ", "_")
    if delivery in {"classroom", "instructor_led", "ilt", "in_person", "inperson", "hands_on"}:
        delivery = "in_person"
    elif delivery not in {"online", "hybrid"}:
        delivery = "online"
    outline = r.get("outline") or ""
    if isinstance(outline, list):
        outline = "\n".join(outline)
    return {
        "code": str(r["code"]).strip(),
        "title": str(r.get("title") or r["code"]).strip(),
        "description": str(r.get("description") or "").strip(),
        "category": CATEGORY_MAP.get(cat, cat if cat in {"safety", "technical", "culture", "compliance"} else "technical"),
        "required": to_bool(r.get("required", False)),
        "delivery": delivery,
        "source_system": str(r.get("source_system") or default_source).strip(),
        "source_url": str(r.get("source_url") or "").strip(),
        "duration_minutes": to_int(r.get("duration_minutes"), 60),
        "validity_months": to_int(r.get("validity_months")),
        "skills": [s.lower() for s in to_list(r.get("skills"))],
        "prerequisites": to_list(r.get("prerequisites")),
        "job_roles": to_list(r.get("job_roles")),
        "equipment": to_list(r.get("equipment")),
        "facilities": to_list(r.get("facilities")),
        "outline": str(outline).replace(";", "\n").strip(),
        "assessment_type": choose_assessment(r.get("assessment_type"), [x.lower() for x in to_list(r.get("skills"))], str(r.get("title") or "")),
    }


def _session(row: dict[str, Any]) -> dict[str, Any]:
    r = apply_aliases(row, SESSION_ALIASES, load_mapping("training_sessions"))
    starts, ends = to_datetime(r.get("starts_at")), to_datetime(r.get("ends_at"))
    if not r.get("training_code") or not starts:
        raise ConnectorError(f"Session row needs a training code and start time: {row}")
    return {
        "training_code": str(r["training_code"]).strip(),
        "starts_at": starts,
        "ends_at": ends or starts,
        "location": str(r.get("location") or "").strip(),
        "instructor": str(r.get("instructor") or "").strip(),
        "capacity": to_int(r.get("capacity"), 20),
    }


class UTrainConnector(Connector):
    name = "utrain"

    def fetch(self):
        if settings.utrain_mode == "live":
            if not settings.utrain_api_url:
                raise ConnectorError("UTRAIN_MODE=live but UTRAIN_API_URL is empty")
            headers = {"Authorization": f"Bearer {settings.utrain_api_token}"} if settings.utrain_api_token else {}
            with httpx.Client(base_url=settings.utrain_api_url, headers=headers, timeout=30) as c:
                courses = c.get("/courses").raise_for_status().json()
                sessions = c.get("/sessions").raise_for_status().json()
            return {"trainings": [_training(r, "UTrain") for r in courses], "sessions": [_session(r) for r in sessions]}

        trainings = [_training(r, "UTrain") for r in read_records(find_file("trainings"))]
        # Other training websites exported as trainings_<site>.csv
        for extra in sorted(Path(settings.data_dir).glob("trainings_*.*")):
            if extra.stem == "training_sessions" or extra.suffix.lower() not in {".csv", ".json"}:
                continue
            site = extra.stem.removeprefix("trainings_").replace("_", " ").title()
            trainings += [_training(r, site) for r in read_records(extra)]
        session_file = find_file("training_sessions")
        sessions = [_session(r) for r in read_records(session_file)] if session_file.exists() else []
        return {"trainings": trainings, "sessions": sessions}
