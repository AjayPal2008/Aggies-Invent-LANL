"""Admin training library API: institutional, division and role trainings, and their source materials.

Managers can read the library (to plan roles and map positions); only admins change it.
"""
from __future__ import annotations

import shutil
import uuid
from collections import Counter
from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..assessment_rules import VALID as ASSESSMENT_TYPES
from ..auth import require_admin, require_manager
from ..config import settings
from ..database import get_db
from ..safeguards import catalog_cache
from ..services import documents, library, roles

router = APIRouter(prefix="/api/library", tags=["training library"])

CATEGORIES = {"safety", "security", "cyber", "ethics", "policy", "compliance", "culture", "environment", "export", "technical"}


def _training(db: Session, code: str) -> models.Training:
    t = db.scalar(select(models.Training).where(models.Training.code == code))
    if t is None:
        raise HTTPException(404, "Training not found")
    return t


def _materials(db: Session) -> dict[str, list[models.TrainingMaterial]]:
    out: dict[str, list] = {}
    for m in db.scalars(select(models.TrainingMaterial).where(models.TrainingMaterial.status != "removed")
                        .order_by(models.TrainingMaterial.id)):
        out.setdefault(m.training_code, []).append(m)
    return out


def _material_json(m: models.TrainingMaterial) -> dict:
    return {"id": m.id, "kind": m.kind, "title": m.title, "url": m.url if not m.url.startswith("upload:") else "",
            "status": m.status, "document_id": m.document_id, "bytes": m.bytes, "error": m.error,
            "retrieved_at": m.retrieved_at.isoformat() if m.retrieved_at else None}


def _training_json(t: models.Training, mats: list, modules: int) -> dict:
    return {"code": t.code, "title": t.title, "layer": t.layer or "unassigned", "category": t.category, "audience": t.audience,
            "frequency": t.frequency, "course_number": t.course_number, "refresher_of": t.refresher_of, "delivery": t.delivery,
            "assessment_type": t.assessment_type, "source_system": t.source_system, "source_url": t.source_url,
            "description": t.description, "skills": t.skills, "modules": modules, "lessons_status": t.lessons_status,
            "materials": [_material_json(m) for m in mats],
            "materials_ready": sum(1 for m in mats if m.document_id), "materials_total": len(mats)}


# ---- overview ---------------------------------------------------------------------------

@router.get("")
def overview(mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    mats = _materials(db)
    modules = Counter(db.scalars(select(models.CourseModule.training_id)))
    trainings = list(db.scalars(select(models.Training).order_by(models.Training.code)))
    by_layer = Counter(t.layer or "unassigned" for t in trainings)
    names = library.program_names()
    divisions: dict[str, list] = {k: [] for k in names}
    for d in db.scalars(select(models.Division).order_by(models.Division.code)):
        if d.program in divisions and d.parent_code:
            divisions[d.program].append({"code": d.code, "name": d.name, "directorate": d.directorate})
    reqs: dict[str, list] = {k: [] for k in names}
    for r in db.scalars(select(models.DivisionRequirement).order_by(models.DivisionRequirement.phase)):
        reqs.setdefault(r.program, []).append({"id": r.id, "training_code": r.training_code, "phase": r.phase, "reason": r.reason})
    return {
        "about": library.manifest()["about"], "sources": library.manifest()["sources"],
        "counts": {"trainings": len(trainings), "by_layer": dict(by_layer),
                   "materials": sum(len(v) for v in mats.values()), "materials_ready": sum(1 for v in mats.values() for m in v if m.document_id)},
        "programs": [{"key": p["key"], "name": p["name"], "description": p["description"], "divisions": divisions.get(p["key"], []),
                      "requirements": reqs.get(p["key"], [])} for p in library.manifest()["programs"]],
        "trainings": [_training_json(t, mats.get(t.code, []), modules.get(t.id, 0)) for t in trainings],
        "unassigned": [_material_json(m) for m in mats.get("", [])],
        "lessons": {"published": sum(1 for t in trainings if modules.get(t.id) and t.lessons_status != "draft"),
                    "draft": sum(1 for t in trainings if modules.get(t.id) and t.lessons_status == "draft"),
                    "ready_to_build": sum(1 for t in trainings if not modules.get(t.id) and any(m.document_id for m in mats.get(t.code, [])))},
        "roles": list_roles(mgr, db),
        "can_edit": mgr.role == "admin",
    }


# ---- trainings --------------------------------------------------------------------------

class TrainingIn(BaseModel):
    code: str | None = None
    title: str | None = None
    layer: str | None = None
    category: str | None = None
    audience: str | None = None
    frequency: str | None = None
    delivery: str | None = None
    assessment_type: str | None = None
    description: str | None = None
    course_number: str | None = None


def _apply(t: models.Training, body: TrainingIn):
    if body.layer is not None:
        if body.layer not in (*library.LAYERS, ""):
            raise HTTPException(400, "layer must be institutional, division or role")
        t.layer = body.layer or None
    if body.audience is not None:
        if body.audience not in ("all", "new_hire"):
            raise HTTPException(400, "audience must be all or new_hire")
        t.audience = body.audience
    if body.frequency is not None:
        if body.frequency not in ("once", "annual"):
            raise HTTPException(400, "frequency must be once or annual")
        t.frequency = body.frequency
        t.validity_months = 12 if body.frequency == "annual" else None
    if body.assessment_type is not None:
        if body.assessment_type not in ASSESSMENT_TYPES:
            raise HTTPException(400, "assessment_type must be quiz, situational or both")
        t.assessment_type = body.assessment_type
    if body.category is not None:
        t.category = body.category if body.category in CATEGORIES else "technical"
    for field in ("title", "delivery", "description", "course_number"):
        v = getattr(body, field)
        if v is not None:
            setattr(t, field, v)


@router.post("/trainings")
def create_training(body: TrainingIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    if not body.code or not body.title:
        raise HTTPException(400, "code and title are required")
    if db.scalar(select(models.Training).where(models.Training.code == body.code)):
        raise HTTPException(409, f"Training {body.code} already exists")
    t = models.Training(code=body.code.strip()[:32], title=body.title, source_system="Training library", source_url="",
                        required=False, job_roles=[], skills=[], prerequisites=[], delivery="online", category="technical")
    _apply(t, body)
    db.add(t)
    db.commit()
    catalog_cache.clear()
    return _training_json(t, [], 0)


@router.patch("/trainings/{code}")
def update_training(code: str, body: TrainingIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    t = _training(db, code)
    _apply(t, body)
    db.commit()
    catalog_cache.clear()
    mats = _materials(db).get(t.code, [])
    return _training_json(t, mats, len(list(db.scalars(select(models.CourseModule.id).where(models.CourseModule.training_id == t.id)))))


# ---- materials --------------------------------------------------------------------------

class ImportIn(BaseModel):
    training_code: str | None = None


def _import_job(training_code: str | None):
    from ..database import SessionLocal

    with SessionLocal() as db:
        library.import_all(db, training_code)


@router.post("/materials/import")
def import_materials(body: ImportIn, background: BackgroundTasks, admin: models.Employee = Depends(require_admin),
                     db: Session = Depends(get_db)):
    """Download linked public LANL PDFs into the library and extract their text. No AI is used."""
    q = select(models.TrainingMaterial).where(models.TrainingMaterial.document_id.is_(None), models.TrainingMaterial.kind == "pdf")
    if body.training_code:
        q = q.where(models.TrainingMaterial.training_code == body.training_code)
    pending = list(db.scalars(q))
    for m in pending:
        m.status, m.error = "importing", ""
    db.commit()
    background.add_task(_import_job, body.training_code)
    return {"queued": len(pending)}


@router.post("/trainings/{code}/materials")
async def upload_material(code: str, file: UploadFile = File(...), title: str = Form(""),
                          admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    """Attach a PDF, slide deck (.pptx), Word file or text to a training."""
    _training(db, code)
    dest = _save_upload(file)
    try:
        m = library.add_uploaded(db, code, dest, title or Path(file.filename).stem, file.filename or dest.name, admin.id)
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc))
    return _material_json(m)


def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".pptx", ".docx", ".txt", ".md"}:
        raise HTTPException(400, "Upload a PDF, .pptx, .docx, .txt or .md file")
    folder = Path(settings.upload_dir) / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"library-upload-{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh, length=1024 * 1024)
    if dest.stat().st_size > settings.max_upload_mb * 1024 * 1024:
        dest.unlink()
        raise HTTPException(413, f"Files over {settings.max_upload_mb} MB aren't accepted")
    return dest


def _material(db: Session, material_id: int) -> models.TrainingMaterial:
    m = db.get(models.TrainingMaterial, material_id)
    if m is None or m.status == "removed":
        raise HTTPException(404, "Material not found")
    return m


class MaterialIn(BaseModel):
    title: str


@router.patch("/materials/{material_id}")
def rename_material(material_id: int, body: MaterialIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    m = _material(db, material_id)
    if not body.title.strip():
        raise HTTPException(400, "Give the material a title")
    m.title = body.title.strip()[:300]
    db.commit()
    return _material_json(m)


@router.post("/materials/{material_id}/file")
async def replace_material(material_id: int, file: UploadFile = File(...), admin: models.Employee = Depends(require_admin),
                           db: Session = Depends(get_db)):
    """Upload a newer version of a material (for example this year's manual). Rebuild lessons afterwards."""
    m = _material(db, material_id)
    dest = _save_upload(file)
    try:
        library.replace_file(db, m, dest, file.filename or dest.name, admin.id)
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc))
    return _material_json(m)


@router.post("/materials/{material_id}/refresh")
def refresh_material(material_id: int, background: BackgroundTasks, admin: models.Employee = Depends(require_admin),
                     db: Session = Depends(get_db)):
    """Download the official PDF again from its public link (when LANL publishes a new revision)."""
    m = _material(db, material_id)
    if m.url.startswith("upload:") or not library.allowed_url(m.url):
        raise HTTPException(400, "Only materials linked to an official public source can be downloaded again")
    m.document_id, m.status, m.error = None, "linked", ""
    db.commit()
    background.add_task(_refresh_job, m.id)
    return {"id": m.id, "status": "downloading"}


def _refresh_job(material_id: int):
    from ..database import SessionLocal

    with SessionLocal() as db:
        if (m := db.get(models.TrainingMaterial, material_id)) is not None:
            library.import_material(db, m)


@router.delete("/materials/{material_id}")
def delete_material(material_id: int, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    """Remove a material from its training. Catalog links are hidden (not re-added on the next sync); uploads are deleted."""
    m = _material(db, material_id)
    if m.url.startswith("upload:"):
        db.delete(m)  # the admin's own upload
    else:
        m.document_id, m.status, m.sha256, m.bytes = None, "removed", "", 0
    db.commit()
    return {"deleted": material_id}


@router.post("/trainings/{code}/build")
def build_lessons(code: str, background: BackgroundTasks, admin: models.Employee = Depends(require_admin),
                  db: Session = Depends(get_db)):
    """Turn the training's richest material into modules, video lessons, quizzes and scenarios."""
    t = _training(db, code)
    doc = library.primary_document(db, t.code)
    if doc is None:
        raise HTTPException(409, "Import or upload a material with readable text first")
    doc.training_code, doc.status = t.code, "generating"
    db.commit()
    background.add_task(documents.build_course_background, doc.id)
    return {"training_code": t.code, "document_id": doc.id, "pages": doc.pages, "status": "generating"}


@router.get("/trainings/{code}/modules")
def review_modules(code: str, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    """The built modules with their source pages, for review before publishing."""
    t = _training(db, code)
    mods = list(db.scalars(select(models.CourseModule).where(models.CourseModule.training_id == t.id).order_by(models.CourseModule.position)))
    return {"code": t.code, "lessons_status": t.lessons_status, "document_id": t.document_id,
            "modules": [{"id": m.id, "title": m.title, "pages": f"{m.page_start}-{m.page_end}", "summary": m.summary,
                         "objectives": m.objectives, "key_points": m.key_points} for m in mods]}


class PublishIn(BaseModel):
    reviewed: bool = False
    publish: bool = True


class PublishAllIn(BaseModel):
    reviewed: bool = False
    codes: list[str] | None = None


@router.post("/publish-all")
def publish_all(body: PublishAllIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    """Publish every draft that has built lessons (or just `codes`), after the admin confirms review."""
    if not body.reviewed:
        raise HTTPException(400, "Confirm you reviewed the draft lessons before publishing them")
    built = set(db.scalars(select(models.CourseModule.training_id)))
    done = []
    for t in db.scalars(select(models.Training).where(models.Training.lessons_status == "draft")):
        if t.id in built and (not body.codes or t.code in body.codes):
            t.lessons_status = "published"
            done.append(t.code)
    db.commit()
    catalog_cache.clear()
    return {"published": done}


def _build_all_job():
    from ..database import SessionLocal

    with SessionLocal() as db:
        library.build_missing(db)


@router.post("/build-all")
def build_all(background: BackgroundTasks, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    """Build draft lessons (offline builder) for every training that has material but no lessons yet."""
    built = set(db.scalars(select(models.CourseModule.training_id)))
    todo = sorted({m.training_code for v in _materials(db).values() for m in v if m.document_id and m.training_code}
                  - {t.code for t in db.scalars(select(models.Training)) if t.id in built})
    background.add_task(_build_all_job)
    return {"queued": todo}


class PlaceIn(BaseModel):
    training_code: str


@router.post("/materials/{material_id}/place")
def place_material(material_id: int, body: PlaceIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    """Attach a material (for example one from the shared folder's unassigned/) to a training."""
    m = _material(db, material_id)
    _training(db, body.training_code)
    if db.scalar(select(models.TrainingMaterial.id).where(models.TrainingMaterial.training_code == body.training_code,
                                                          models.TrainingMaterial.url == m.url, models.TrainingMaterial.id != m.id)):
        raise HTTPException(409, "That training already has this material")
    m.training_code = body.training_code
    if m.document_id:
        doc = db.get(models.Document, m.document_id)
        if doc and not doc.training_code:
            doc.training_code = body.training_code
    db.commit()
    return _material_json(m)


@router.post("/trainings/{code}/publish")
def publish_lessons(code: str, body: PublishIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    """Make reviewed lessons visible to learners (or take them back to draft)."""
    t = _training(db, code)
    if body.publish and not body.reviewed:
        raise HTTPException(400, "Confirm you reviewed the modules against the source pages before publishing")
    if body.publish and not db.scalar(select(models.CourseModule.id).where(models.CourseModule.training_id == t.id)):
        raise HTTPException(409, "Build lessons first")
    t.lessons_status = "published" if body.publish else "draft"
    db.commit()
    catalog_cache.clear()
    return {"code": t.code, "lessons_status": t.lessons_status}


# ---- divisions ----------------------------------------------------------------------------

class RequirementIn(BaseModel):
    training_code: str
    phase: int = 1
    reason: str = ""
    kind: str = "technical"
    program: str | None = None  # for role requirements: None = every division


@router.post("/divisions/{program}/requirements")
def add_division_requirement(program: str, body: RequirementIn, admin: models.Employee = Depends(require_admin),
                             db: Session = Depends(get_db)):
    if program not in library.PROGRAMS:
        raise HTTPException(404, "Unknown division")
    _training(db, body.training_code)
    if db.scalar(select(models.DivisionRequirement).where(models.DivisionRequirement.program == program,
                                                          models.DivisionRequirement.training_code == body.training_code)):
        raise HTTPException(409, "Already required in this division")
    r = models.DivisionRequirement(program=program, training_code=body.training_code, phase=body.phase, reason=body.reason)
    db.add(r)
    db.commit()
    return {"id": r.id, "program": program, "training_code": r.training_code, "phase": r.phase, "reason": r.reason}


@router.delete("/divisions/requirements/{req_id}")
def remove_division_requirement(req_id: int, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(models.DivisionRequirement, req_id)
    if r is None:
        raise HTTPException(404, "Not found")
    db.delete(r)
    db.commit()
    return {"deleted": req_id}


# ---- roles ------------------------------------------------------------------------------

@router.get("/roles")
def list_roles(mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    reqs: dict[str, list] = {}
    for r in db.scalars(select(models.RoleRequirement).order_by(models.RoleRequirement.phase)):
        reqs.setdefault(r.role_key, []).append({"id": r.id, "training_code": r.training_code, "program": r.program,
                                                "kind": r.kind, "phase": r.phase, "reason": r.reason})
    positions: dict[str, list] = {}
    for p in db.scalars(select(models.Position)):
        if p.library_role:
            positions.setdefault(p.library_role, []).append({"code": p.code, "title": p.title, "division_code": p.division_code})
    return [{"key": r.key, "title": r.title, "family": r.family, "description": r.description, "programs": r.programs,
             "skills": r.skills or [], "has_job_description": bool(r.job_description),
             "requirements": reqs.get(r.key, []), "positions": positions.get(r.key, [])}
            for r in db.scalars(select(models.LibraryRole).order_by(models.LibraryRole.family, models.LibraryRole.title))]


class RoleIn(BaseModel):
    key: str | None = None
    title: str
    family: str = ""
    description: str = ""
    programs: list[str] = []
    skills: list[str] | None = None
    job_description: str | None = None


@router.post("/roles")
def create_role(body: RoleIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    import re

    key = body.key or re.sub(r"[^a-z0-9]+", "-", body.title.lower()).strip("-")[:48]
    if db.get(models.LibraryRole, key):
        raise HTTPException(409, f"Role {key} already exists")
    r = models.LibraryRole(key=key, title=body.title, family=body.family, description=body.description,
                           programs=[p for p in body.programs if p in library.PROGRAMS])
    db.add(r)
    db.commit()
    return {"key": r.key, "title": r.title}


@router.patch("/roles/{key}")
def update_role(key: str, body: RoleIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(models.LibraryRole, key)
    if r is None:
        raise HTTPException(404, "Role not found")
    r.title, r.family, r.description = body.title, body.family, body.description
    r.programs = [p for p in body.programs if p in library.PROGRAMS]
    if body.skills is not None:
        r.skills = sorted({x.strip().lower() for x in body.skills if x.strip()})
    if body.job_description is not None:
        r.job_description = body.job_description
    db.commit()
    return {"key": r.key, "title": r.title, "programs": r.programs, "skills": r.skills}


@router.post("/roles/{key}/requirements")
def add_role_requirement(key: str, body: RequirementIn, admin: models.Employee = Depends(require_admin),
                         db: Session = Depends(get_db)):
    if db.get(models.LibraryRole, key) is None:
        raise HTTPException(404, "Role not found")
    _training(db, body.training_code)
    if body.program not in (None, *library.PROGRAMS):
        raise HTTPException(400, "program must be weapons, ste, operations or empty for every division")
    if body.kind not in ("technical", "soft"):
        raise HTTPException(400, "kind must be technical or soft")
    if db.scalar(select(models.RoleRequirement).where(models.RoleRequirement.role_key == key, models.RoleRequirement.program == body.program,
                                                      models.RoleRequirement.training_code == body.training_code)):
        raise HTTPException(409, "Already required for this role")
    r = models.RoleRequirement(role_key=key, program=body.program, training_code=body.training_code, kind=body.kind,
                               phase=body.phase, reason=body.reason)
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.delete("/roles/requirements/{req_id}")
def remove_role_requirement(req_id: int, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(models.RoleRequirement, req_id)
    if r is None:
        raise HTTPException(404, "Not found")
    db.delete(r)
    db.commit()
    return {"deleted": req_id}


class PositionRoleIn(BaseModel):
    library_role: str | None


@router.patch("/positions/{code}")
def map_position(code: str, body: PositionRoleIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Which library role a position uses (managers set this for the roles they hire into)."""
    p = db.scalar(select(models.Position).where(models.Position.code == code))
    if p is None:
        raise HTTPException(404, "Position not found")
    if body.library_role and db.get(models.LibraryRole, body.library_role) is None:
        raise HTTPException(400, "Unknown library role")
    p.library_role = body.library_role
    db.commit()
    return {"code": p.code, "library_role": p.library_role}


# ---- what someone would get ------------------------------------------------------------------

class PathIn(BaseModel):
    program: str | None = None
    role_key: str | None = None
    entry_path: str = "new_hire"  # new_hire | promotion | transfer
    from_program: str | None = None  # for internal moves: the division they're coming from


def _path(db: Session, program: str | None, role_key: str | None, entry_path: str, from_program: str | None) -> dict:
    same = entry_path == "new_hire" or not from_program or from_program == program
    by_code = {t.code: t for t in db.scalars(select(models.Training))}
    rows = []
    for it in library.layer_items(db, program, role_key):
        t = by_code[it["training_code"]]
        include = roles.audience_matches(it["audience"], entry_path, same)
        why = it["reason"] if include else ("Institutional training continues on its annual cycle" if it["layer"] == "institutional"
                                            else "Already in this division" if it["layer"] == "division" else "Not for this path")
        rows.append({**it, "title": t.title, "category": t.category, "frequency": t.frequency, "course_number": t.course_number,
                     "delivery": t.delivery, "duration_minutes": t.duration_minutes, "assessment_type": t.assessment_type,
                     "skills": t.skills or [], "include": include, "why": why, "phase_label": roles.PHASE_LABEL.get(it["phase"], "")})
    layers = {k: sum(1 for r in rows if r["layer"] == k and r["include"]) for k in library.LAYERS}
    return {"program": program, "role_key": role_key, "entry_path": entry_path, "same_division": same,
            "included": sum(1 for r in rows if r["include"]), "by_layer": layers, "items": rows}


@router.post("/path")
def training_path(body: PathIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Preview the trainings for a division + role, for a new hire vs an internal move."""
    return _path(db, body.program, body.role_key, body.entry_path, body.from_program)


# ---- role directory: one page per role for managers -----------------------------------------

def _role(db: Session, key: str) -> models.LibraryRole:
    r = db.get(models.LibraryRole, key)
    if r is None:
        raise HTTPException(404, "Role not found")
    return r


@router.get("/roles/{key}/detail")
def role_detail(key: str, program: str | None = None, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Everything a manager needs for one role in one division: job description, skills, and the exact
    trainings to assign for a new hire, a promotion within the division, or a move from another division."""
    r = _role(db, key)
    if program and program not in library.PROGRAMS:
        raise HTTPException(400, "program must be weapons, ste or operations")
    program = program or (r.programs[0] if r.programs else None)
    positions = [p for p in db.scalars(select(models.Position).where(models.Position.library_role == key))
                 if not program or library.program_of(db, p.division_code) == program]
    jds = [{"id": d.id, "title": d.title, "position_code": d.position_code, "pages": d.pages}
           for d in db.scalars(select(models.Document).where(models.Document.position_code.in_([p.code for p in positions] or [""]),
                                                             models.Document.kind == "job_description"))]
    paths = {"new_hire": _path(db, program, key, "new_hire", None),
             "promotion": _path(db, program, key, "promotion", program),
             "transfer": _path(db, program, key, "transfer", next((x for x in library.PROGRAMS if x != program), None))}
    skills: dict[str, set] = {}
    for s_ in r.skills or []:
        skills.setdefault(s_.lower(), set()).add("Role")
    for p in positions:
        for s_ in p.required_skills or []:
            skills.setdefault(s_.lower(), set()).add(p.title)
    for it in paths["new_hire"]["items"]:
        if it["layer"] == "role":
            for s_ in it["skills"]:
                skills.setdefault(s_.lower(), set()).add(it["training_code"])
    return {"key": r.key, "title": r.title, "family": r.family, "description": r.description, "job_description": r.job_description,
            "programs": r.programs, "program": program, "program_names": library.program_names(),
            "skills": [{"skill": k, "from": sorted(v)} for k, v in sorted(skills.items())],
            "positions": [{"code": p.code, "title": p.title, "division_code": p.division_code, "level": p.level,
                           "min_years": p.min_years, "prerequisites": p.prerequisites, "is_open": p.is_open} for p in positions],
            "job_descriptions": jds, "paths": paths, "can_edit": mgr.role == "admin"}


class RoleAssignIn(BaseModel):
    program: str | None = None
    entry_path: str = "new_hire"
    from_program: str | None = None
    employee_ids: list[int]
    start_date: date | None = None
    exclude: list[str] = []
    position_code: str | None = None  # also move them into this position


@router.post("/roles/{key}/assign")
def assign_role(key: str, body: RoleAssignIn, mgr: models.Employee = Depends(require_manager), db: Session = Depends(get_db)):
    """Assign the role's training list to the people a manager hired or is promoting into it."""
    from datetime import timedelta

    from ..auth import team_ids
    from .content import _people

    _role(db, key)
    if body.entry_path not in ("new_hire", "promotion", "transfer"):
        raise HTTPException(400, "entry_path must be new_hire, promotion or transfer")
    if not body.employee_ids:
        raise HTTPException(400, "Pick at least one person")
    start = body.start_date or date.today()
    path = _path(db, body.program, key, body.entry_path, body.from_program if body.entry_path != "new_hire" else None)
    wanted = [i for i in path["items"] if i["include"] and i["training_code"] not in body.exclude]
    by_code = {t.code: t for t in db.scalars(select(models.Training).where(models.Training.code.in_([i["training_code"] for i in wanted] or [""])))}
    pos = None
    if body.position_code:
        pos = db.scalar(select(models.Position).where(models.Position.code == body.position_code))
        if pos is None or pos.library_role != key:
            raise HTTPException(400, "That position doesn't use this role")
    team = team_ids(db, mgr)
    out = []
    for e in _people(db, mgr, body.employee_ids, allow_lab=True):
        if e.id not in team and mgr.role != "admin":
            e.manager_id = mgr.id  # they join this manager's team
        if pos is not None:
            if e.position_code != pos.code:
                e.previous_position_code = e.position_code
            e.position_code, e.job_title, e.division_code = pos.code, pos.title, pos.division_code or e.division_code
        e.entry_path, e.role_start_date = body.entry_path, start
        have = {a.training.code: a for a in e.assignments}
        created, already = [], []
        for it in wanted:
            t = by_code[it["training_code"]]
            due = start + timedelta(days=roles.PHASE_DAYS.get(it["phase"], 30))
            a = have.get(t.code)
            if a and a.status != "completed":
                already.append(t.code)
                continue
            if a:
                a.status, a.progress, a.due_date, a.assigned_by_id = "not_started", 0, due, mgr.id
            else:
                e.assignments.append(models.Assignment(training=t, assigned_by_id=mgr.id, due_date=due))
            created.append(t.code)
        out.append({"employee_id": e.id, "name": e.name, "assigned": created, "already_assigned": already})
    db.commit()
    db.info.clear()
    return {"role_key": key, "entry_path": body.entry_path, "trainings": len(wanted), "people": out}


class AnnualIn(BaseModel):
    due_date: date
    stagger_weeks: int = 4
    codes: list[str] = []


@router.post("/annual-cycle")
def run_annual_cycle(body: AnnualIn, admin: models.Employee = Depends(require_admin), db: Session = Depends(get_db)):
    """Assign this year's annual institutional trainings to everyone who isn't current, spreading due dates."""
    return library.annual_cycle(db, body.due_date, body.stagger_weeks, body.codes or None)
