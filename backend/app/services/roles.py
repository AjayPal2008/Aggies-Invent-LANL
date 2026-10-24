"""Role training plans: what each role needs, tailored to how a person enters it.

A plan is a list of trainings for a position, each with:
  phase     1 = first 2 weeks, 2 = first 30 days, 3 = first 90 days
  audience  all | new_hire | internal | promotion | transfer
  skip_if_years_at_least  experienced people can skip (they can still take the assessment)

When someone starts a role, the plan is filtered for them:
  * new hires get company culture, policy and rules onboarding;
  * people promoted or transferred from inside skip onboarding they've already done
    and get transition training (e.g. leadership when moving into a lead role);
  * anything already completed and still current is skipped;
  * years of experience raise the starting difficulty.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from . import adaptive, ai
from .documents import document_text
from .loader import all_trainings

PHASE_DAYS = {1: 14, 2: 30, 3: 90}
PHASE_LABEL = {1: "First 2 weeks", 2: "First 30 days", 3: "First 90 days"}
AUDIENCES = {"all", "new_hire", "internal", "promotion", "transfer", "new_to_division"}
LEADERSHIP_WORDS = ("lead", "manager", "supervisor", "director", "leader", "superintendent", "head")


def is_leadership(pos: models.Position) -> bool:
    return pos.level >= 3 and any(w in pos.title.lower() for w in LEADERSHIP_WORDS) or pos.title.lower().startswith("group leader")


def detect_entry_path(emp: models.Employee, pos: models.Position) -> str:
    """Best guess at how someone is entering this role; managers can override."""
    tenure_days = (date.today() - emp.hire_date).days if emp.hire_date else 9999
    if tenure_days <= 120 and not emp.previous_position_code:
        return "new_hire"
    return "promotion" if pos.level > emp.level else "transfer"


def audience_matches(audience: str, entry: str, same_division: bool = True) -> bool:
    """new_to_division: new hires, and internal moves from a different division (Weapons, STE, Operations)."""
    if audience == "new_to_division":
        return entry == "new_hire" or not same_division
    return audience == "all" or audience == entry or (audience == "internal" and entry in ("promotion", "transfer"))


def _same_division(db: Session, emp: models.Employee, pos: models.Position, from_position: str | None = None) -> bool:
    from .library import program_of

    before = emp.division_code
    if from_position:
        prev = db.scalar(select(models.Position).where(models.Position.code == from_position))
        before = prev.division_code if prev else before
    a, b = program_of(db, before), program_of(db, pos.division_code)
    return a is None or b is None or a == b


# ---- default plan -------------------------------------------------------------------

def default_plan(db: Session, pos: models.Position) -> list[dict]:
    from .library import layer_items, program_of

    if pos.library_role or (program_of(db, pos.division_code) and db.scalar(select(models.LibraryRole.key))):
        # Training library: institutional + the position's division + its role, plus anything the directory
        # lists for this exact position and courses built from its documents.
        items = {i["training_code"]: i for i in layer_items(db, program_of(db, pos.division_code), pos.library_role)}
        for code in pos.required_trainings or []:
            items.setdefault(code, {"training_code": code, "phase": 2, "audience": "all", "required": True,
                                    "skip_if_years_at_least": None, "reason": f"Required for {pos.title}", "layer": "role"})
        for t in all_trainings(db):
            if t.document_id and pos.code in (t.job_roles or []) and not t.layer:
                items.setdefault(t.code, {"training_code": t.code, "phase": 2, "audience": "all", "required": True,
                                          "skip_if_years_at_least": None, "reason": "Built from this role's internal documents",
                                          "layer": "role"})
        return list(items.values())
    items: dict[str, dict] = {}

    def add(code, phase, audience, reason, required=True, skip_years=None):
        if code not in items:
            items[code] = {"training_code": code, "phase": phase, "audience": audience, "required": required,
                           "skip_if_years_at_least": skip_years, "reason": reason}

    trainings = all_trainings(db)
    relevant = lambda t: not t.job_roles or "all" in t.job_roles or pos.code in t.job_roles or pos.title in t.job_roles  # noqa: E731
    # Lab-wide onboarding: culture only for people new to the lab; safety/compliance for everyone (skipped if current).
    for t in trainings:
        if t.required and relevant(t) and not t.document_id:
            if t.category == "culture":
                add(t.code, 1, "new_hire", "Company culture and how the Lab works, for people new to LANL")
            else:
                add(t.code, 1, "all", f"Required {t.category} training (skipped automatically if already current)")
    # Role requirements from the directory.
    for code in pos.required_trainings or []:
        add(code, 2, "all", f"Required for {pos.title}")
    # Courses built from this role's documents.
    for t in trainings:
        if t.document_id and pos.code in (t.job_roles or []):
            add(t.code, 2, "all", "Built from this role's internal documents")
    # Leadership transition.
    if is_leadership(pos):
        for t in trainings:
            if ("leadership" in (t.skills or []) or "coaching" in (t.skills or [])) and relevant(t):
                add(t.code, 1 if t.category == "culture" else 2, "all", "Moving into a leadership role")
    # Skill coverage: anything that teaches a required skill not yet covered.
    covered = {s for c in items for t in trainings if t.code == c for s in (t.skills or [])}
    for skill in pos.required_skills or []:
        if skill in covered:
            continue
        for t in trainings:
            if skill in (t.skills or []) and relevant(t):
                add(t.code, 3, "all", f"Builds a required skill: {skill}", required=False, skip_years=5)
                covered.update(t.skills or [])
                break
    return list(items.values())


# ---- job description analysis --------------------------------------------------------

JD_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "level": {"type": "integer"},
        "min_years": {"type": "number"},
        "responsibilities": {"type": "array", "items": {"type": "string"}},
        "required_skills": {"type": "array", "items": {"type": "string"}},
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "plan": {"type": "array", "items": {
            "type": "object",
            "properties": {"training_code": {"type": "string"}, "phase": {"type": "integer"},
                           "audience": {"type": "string", "enum": sorted(AUDIENCES)}, "required": {"type": "boolean"},
                           "skip_if_years_at_least": {"anyOf": [{"type": "number"}, {"type": "null"}]}, "reason": {"type": "string"}},
            "required": ["training_code", "phase", "audience", "required", "skip_if_years_at_least", "reason"],
            "additionalProperties": False}},
        "uncovered_topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "level", "min_years", "responsibilities", "required_skills", "prerequisites", "plan", "uncovered_topics"],
    "additionalProperties": False,
}


def analyze_role(db: Session, pos: models.Position, pasted_text: str = "") -> dict:
    docs = list(db.scalars(select(models.Document).where(models.Document.position_code == pos.code)))
    jd = "\n\n".join(f"<{d.kind} title=\"{d.title}\">\n{document_text(d, limit=200_000)}\n</{d.kind}>"
                     for d in docs if d.kind in ("job_description", "requirements")) + (f"\n\n<notes>\n{pasted_text}\n</notes>" if pasted_text else "")
    catalog = [{"code": t.code, "title": t.title, "category": t.category, "required": t.required, "skills": t.skills,
                "roles": t.job_roles, "from_document": bool(t.document_id)} for t in all_trainings(db)]
    vocab = sorted({s for t in all_trainings(db) for s in (t.skills or [])} | set(pos.required_skills or []))
    if not jd.strip():
        return {"generated_by": "none", "error": "Upload a job description or requirements document, or paste text, first.",
                "plan": default_plan(db, pos)}
    prompt = (
        f"Analyze this LANL role and build its training plan.\nRole: {pos.title} ({pos.code}), division {pos.division_code}, level {pos.level}.\n\n"
        f"{jd}\n\nTraining catalog (choose only these codes):\n{catalog}\n\n"
        f"Skill vocabulary (prefer these names): {', '.join(vocab)}\n\n"
        "Return: a 2-sentence summary, level (1-5) and minimum years if stated, responsibilities, required skills, "
        "prerequisites (degrees, clearances, certifications), and a plan. In the plan, phase 1 = first 2 weeks, 2 = first "
        "30 days, 3 = first 90 days. Audience: 'new_hire' for Lab onboarding (culture, how LANL works) that internal people "
        "already had; 'promotion' for transition content only people stepping up need; 'internal' for both promotions and "
        "transfers; 'all' otherwise. Set skip_if_years_at_least for introductory technical training an experienced person "
        "can test out of. Give a one-line reason for each. List topics the job needs that no catalog training covers."
    )
    data = ai._call_json(prompt, JD_SCHEMA, max_tokens=8000)
    if data:
        codes = {t.code for t in all_trainings(db)}
        data["plan"] = [p for p in data["plan"] if p["training_code"] in codes]
        data["required_skills"] = [s.lower() for s in data["required_skills"]]
        data["generated_by"] = settings.ai_model
        return data
    # Offline: keyword match against the vocabulary, then the default plan.
    text = jd.lower()
    skills = [s for s in vocab if s in text or all(w in text for w in s.split())]
    years = re.search(r"(\d+)\+?\s*(?:years|yrs)", text)
    resp = [l.strip(" -•\t") for l in jd.splitlines() if l.strip().startswith(("-", "•")) and 15 < len(l) < 200][:10]
    return {"generated_by": "offline", "summary": f"{pos.title} in {pos.division_code}.", "level": pos.level,
            "min_years": float(years.group(1)) if years else pos.min_years, "responsibilities": resp,
            "required_skills": sorted(set(skills) | set(pos.required_skills or [])), "prerequisites": pos.prerequisites or [],
            "plan": default_plan(db, pos), "uncovered_topics": []}


# ---- saving, previewing, applying ---------------------------------------------------

def get_plan(db: Session, pos: models.Position) -> list[models.RolePlanItem]:
    return list(db.scalars(select(models.RolePlanItem).where(models.RolePlanItem.position_code == pos.code)
                           .order_by(models.RolePlanItem.phase, models.RolePlanItem.id)))


def save_plan(db: Session, pos: models.Position, items: list[dict]) -> list[models.RolePlanItem]:
    codes = {t.code for t in all_trainings(db)}
    for old in get_plan(db, pos):
        db.delete(old)
    db.flush()
    seen = set()
    for it in items:
        code = it["training_code"]
        if code not in codes or code in seen:
            continue
        seen.add(code)
        db.add(models.RolePlanItem(position_code=pos.code, training_code=code, phase=int(it.get("phase") or 2),
                                   audience=it.get("audience") if it.get("audience") in AUDIENCES else "all",
                                   required=bool(it.get("required", True)), skip_if_years_at_least=it.get("skip_if_years_at_least"),
                                   reason=str(it.get("reason") or "")[:500]))
    # Keep the directory's required trainings in sync with the plan's required items.
    pos.required_trainings = sorted({it["training_code"] for it in items if it.get("required", True) and it["training_code"] in codes
                                     and it.get("audience", "all") == "all"} | set(pos.required_trainings or []))
    db.flush()
    return get_plan(db, pos)


def plan_items(db: Session, pos: models.Position) -> list[dict]:
    saved = get_plan(db, pos)
    if saved:
        layers = {t.code: t.layer for t in all_trainings(db)}
        return [{"training_code": i.training_code, "phase": i.phase, "audience": i.audience, "required": i.required,
                 "skip_if_years_at_least": i.skip_if_years_at_least, "reason": i.reason,
                 "layer": layers.get(i.training_code) or "role"} for i in saved]
    return default_plan(db, pos)


def preview(db: Session, emp: models.Employee, pos: models.Position, entry: str | None, start: date | None) -> dict:
    entry = entry or detect_entry_path(emp, pos)
    start = start or date.today()
    same_division = _same_division(db, emp, pos)
    by_code = {t.code: t for t in all_trainings(db)}
    current = {a.training.code: a for a in emp.assignments}
    rows = []
    for it in plan_items(db, pos):
        t = by_code.get(it["training_code"])
        if not t:
            continue
        a = current.get(t.code)
        flags = adaptive.assignment_flags(a) if a else {}
        if not audience_matches(it["audience"], entry, same_division):
            include, why = False, {
                "new_hire": ("Institutional training: already part of their annual cycle at LANL" if it.get("layer") == "institutional"
                             else "Only for people new to the Lab"),
                "new_to_division": "Already in this division: division training was done when they joined it",
                "promotion": "Only for promotions", "transfer": "Only for transfers",
                "internal": "Only for people already at LANL"}.get(it["audience"], "Not for this path")
        elif a and a.status == "completed" and not flags.get("needs_retake"):
            include, why = False, f"Already completed {a.completed_at.date().isoformat() if a.completed_at else ''}".strip()
        elif a and a.status != "completed":
            include, why = False, "Already assigned"
        elif it.get("skip_if_years_at_least") is not None and (emp.years_experience or 0) >= it["skip_if_years_at_least"]:
            include, why = False, f"{emp.years_experience:g} years of experience; can test out"
        else:
            include, why = True, it.get("reason") or ""
        rows.append({"training_code": t.code, "title": t.title, "category": t.category, "phase": it["phase"],
                     "phase_label": PHASE_LABEL.get(it["phase"], f"Phase {it['phase']}"), "audience": it["audience"],
                     "required": it["required"], "include": include, "why": why,
                     "layer": it.get("layer") or t.layer or "role", "kind": it.get("kind"),
                     "due_date": (start + timedelta(days=PHASE_DAYS.get(it["phase"], 30))).isoformat(),
                     "assessment_type": t.assessment_type})
    warnings = []
    if (emp.years_experience or 0) < (pos.min_years or 0):
        warnings.append(f"Has {emp.years_experience:g} years of experience; the role asks for {pos.min_years:g}+")
    if emp.level < pos.level - 1:
        warnings.append(f"Currently level {emp.level}; the role is level {pos.level}")
    missing = [s_ for s_ in pos.required_skills or [] if (emp.skills or {}).get(s_, 0) < settings.mastery_threshold]
    if missing:
        warnings.append("Skills to build: " + ", ".join(missing[:5]))
    return {"warnings": warnings, "employee_id": emp.id, "name": emp.name, "current_title": emp.job_title, "current_level": emp.level,
            "years_experience": emp.years_experience, "entry_path": entry, "detected_entry_path": detect_entry_path(emp, pos),
            "start_date": start.isoformat(), "items": sorted(rows, key=lambda r: (r["phase"], not r["include"], r["title"]))}


def apply(db: Session, mgr: models.Employee, emp: models.Employee, pos: models.Position, entry: str | None, start: date | None,
          exclude: list[str] | None = None, include_extra: list[str] | None = None) -> dict:
    """Move the person into the role and assign their tailored plan."""
    p = preview(db, emp, pos, entry, start)
    by_code = {t.code: t for t in all_trainings(db)}
    wanted = [r for r in p["items"] if (r["include"] and r["training_code"] not in (exclude or []))
              or r["training_code"] in (include_extra or [])]
    if emp.position_code != pos.code:
        emp.previous_position_code = emp.position_code
    emp.position_code, emp.job_title = pos.code, pos.title
    emp.division_code = pos.division_code or emp.division_code  # moving into another division's role
    if p["entry_path"] == "promotion":
        emp.level = max(emp.level, pos.level)
    emp.entry_path, emp.role_start_date = p["entry_path"], date.fromisoformat(p["start_date"])
    have = {a.training.code: a for a in emp.assignments}
    created = []
    for r in wanted:
        t = by_code[r["training_code"]]
        a = have.get(t.code)
        if a and a.status != "completed":
            continue
        if a:  # completed but lapsed: reassign as a refresher
            a.status, a.progress, a.due_date, a.assigned_by_id = "not_started", 0, date.fromisoformat(r["due_date"]), mgr.id
        else:
            emp.assignments.append(models.Assignment(training=t, assigned_by_id=mgr.id, due_date=date.fromisoformat(r["due_date"])))
        created.append(t.code)
    # Experience is evidence: experienced people start higher on the role's skills.
    if emp.years_experience and emp.years_experience >= 2:
        prior = min(0.6, 0.2 + emp.years_experience * 0.05)
        for skill in pos.required_skills or []:
            row = adaptive._mastery_row(db, emp, skill)
            if row.observations == 0:
                row.p_known = max(row.p_known, prior)
    db.flush()
    return {"employee_id": emp.id, "name": emp.name, "entry_path": p["entry_path"], "assigned": created,
            "skipped": [{"training_code": r["training_code"], "why": r["why"]} for r in p["items"] if r not in wanted]}


def my_plan(db: Session, emp: models.Employee) -> dict | None:
    """The hire's view: their role's plan grouped by phase, matched to their assignments."""
    if not emp.position_code:
        return None
    pos = db.scalar(select(models.Position).where(models.Position.code == emp.position_code))
    if not pos:
        return None
    entry = emp.entry_path or detect_entry_path(emp, pos)
    same_division = _same_division(db, emp, pos, emp.previous_position_code)
    by_code = {a.training.code: a for a in emp.assignments}
    start = emp.role_start_date or emp.hire_date or date.today()
    phases: dict[int, list] = {}
    for it in plan_items(db, pos):
        if not audience_matches(it["audience"], entry, same_division):
            continue
        a = by_code.get(it["training_code"])
        if not a:
            continue
        phases.setdefault(it["phase"], []).append({"training_code": it["training_code"], "title": a.training.title,
                                                   "status": a.status, "assignment_id": a.id, "due_date": a.due_date.isoformat() if a.due_date else None,
                                                   "reason": it.get("reason", ""), "assessment_type": a.training.assessment_type})
    return {"position": {"code": pos.code, "title": pos.title, "level": pos.level}, "entry_path": entry,
            "role_start_date": start.isoformat(),
            "phases": [{"phase": k, "label": PHASE_LABEL.get(k, f"Phase {k}"),
                        "ends": (start + timedelta(days=PHASE_DAYS.get(k, 30))).isoformat(), "items": v,
                        "done": sum(1 for x in v if x["status"] == "completed")} for k, v in sorted(phases.items())]}
