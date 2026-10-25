"""The admin training library: what everyone, each division and each role must complete, and the
source materials (PDFs, slide decks) the AI builds lessons from.

Three layers, mirroring how UTrain assigns training:
  institutional  everyone at LANL (security, cyber, ethics, policy, safety); many repeat annually
  division       required by a program: Weapons, Science Technology & Engineering (STE), or Operations
  role           a role's technical and soft-skill training; roles are shared across divisions, with
                 optional division-specific additions (a Project Lead in Weapons also needs NFO Module 3)

How someone enters a role decides which layers apply:
  new hire                     institutional (initial onboarding) + division + role
  internal move, same division role only (institutional training continues on its annual cycle)
  internal move, new division  division + role

The structure comes from data/library/catalog.json (public LANL course titles, numbers and material
links). Material files are downloaded into the admin library on demand, never committed.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import BACKEND_DIR, settings
from . import documents

log = logging.getLogger(__name__)

CATALOG = BACKEND_DIR / "data" / "library" / "catalog.json"
LAYERS = ("institutional", "division", "role")
PROGRAMS = ("weapons", "ste", "operations")
ATTRIBUTION = ("Los Alamos National Laboratory public training material. Original document terms apply; no redistribution "
               "license is inferred. Lessons adapted from it are not official qualification.")


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def program_names() -> dict[str, str]:
    return {p["key"]: p["name"] for p in manifest()["programs"]}


# ---- loading the library ---------------------------------------------------------------

def sync_library(db: Session) -> dict:
    """Create library trainings, materials, divisions' programs, roles and requirements.

    Safe to run repeatedly: existing rows are kept as the admin left them; only missing ones are added.
    """
    m = manifest()
    stats = {"trainings": 0, "materials": 0, "division_requirements": 0, "roles": 0, "role_requirements": 0, "positions_mapped": 0}
    existing = {t.code: t for t in db.scalars(select(models.Training))}
    for c in m["courses"]:
        t = existing.get(c["code"])
        if t is None:
            t = models.Training(code=c["code"])
            db.add(t)
            existing[c["code"]] = t
            stats["trainings"] += 1
            t.title, t.category, t.delivery = c["title"], c["category"], c["delivery"]
            t.description = c.get("description") or c.get("note") or (
                f"Live, instructor-led course {c['number']} at the White Rock Training Center." if c["source_system"] == "White Rock Training Center"
                else c["title"])
            t.source_system, t.source_url = c["source_system"], c["source_url"]
            t.skills, t.prerequisites = c.get("skills", []), c.get("prerequisites", [])
            t.assessment_type = c.get("assessment_type", "quiz")
            t.layer, t.audience, t.frequency = c["layer"], c["audience"], c["frequency"]
            t.course_number, t.refresher_of = c.get("number", ""), c.get("refresher_of")
            t.validity_months = 12 if c["frequency"] == "annual" else None
            t.required = False  # library plans assign these by layer; the legacy auto-assign rule leaves them alone
            t.job_roles = []
            t.outline = c.get("description") or c.get("note") or ""
            t.duration_minutes = 60 if c["delivery"] == "online" else 240
    db.flush()
    have = {(x.training_code, x.url) for x in db.scalars(select(models.TrainingMaterial))}
    for c in m["courses"]:
        for mat in c.get("materials", []):
            if (c["code"], mat["url"]) not in have:
                db.add(models.TrainingMaterial(training_code=c["code"], kind=mat["kind"], title=mat["title"], url=mat["url"],
                                               status="linked"))
                have.add((c["code"], mat["url"]))
                stats["materials"] += 1
    # Public source documents for courses whose official content isn't published (DOE orders, CFR parts, OPM courses).
    codes = set(db.scalars(select(models.Training.code)))
    for code, mats in m.get("extra_materials", {}).items():
        for mat in mats:
            if code in codes and (code, mat["url"]) not in have:
                db.add(models.TrainingMaterial(training_code=code, kind=mat["kind"], title=mat["title"], url=mat["url"], status="linked"))
                have.add((code, mat["url"]))
                stats["materials"] += 1
    # Divisions belong to a program through their directorate.
    by_directorate = {d: p["key"] for p in m["programs"] for d in p["directorates"]}
    for d in db.scalars(select(models.Division)):
        if not d.program:
            d.program = by_directorate.get(d.parent_code or "") or by_directorate.get(d.code)
    if not db.scalar(select(models.DivisionRequirement.id)):
        for program, items in m["division_requirements"].items():
            for it in items:
                db.add(models.DivisionRequirement(program=program, training_code=it["code"], phase=it["phase"], reason=it["reason"]))
                stats["division_requirements"] += 1
    if not db.scalar(select(models.LibraryRole.key)):
        for r in m["roles"]:
            db.add(models.LibraryRole(key=r["key"], title=r["title"], family=r["family"], description=r["description"], programs=r["in"],
                                      skills=r.get("skills", [])))
            stats["roles"] += 1
            for it in r["requirements"]:
                db.add(models.RoleRequirement(role_key=r["key"], program=None, training_code=it["code"], kind=it["kind"],
                                              phase=it["phase"], reason=it.get("reason", "")))
                stats["role_requirements"] += 1
            for program, items in r.get("by_division", {}).items():
                for it in items:
                    db.add(models.RoleRequirement(role_key=r["key"], program=program, training_code=it["code"], kind=it["kind"],
                                                  phase=it["phase"], reason=it.get("reason", "")))
                    stats["role_requirements"] += 1
    for r in m["roles"]:  # roles created before skills were tracked get the catalog's starting list
        row = db.get(models.LibraryRole, r["key"])
        if row is not None and not row.skills and r.get("skills"):
            row.skills = r["skills"]
    stats["skills_repaired"] = repair_offline_skills(db, {c["code"]: c.get("skills", []) for c in m["courses"]})
    # Sample-catalog courses that roles use are role trainings.
    used_by_roles = set(db.scalars(select(models.RoleRequirement.training_code)))
    db.flush()
    for t in db.scalars(select(models.Training).where(models.Training.layer.is_(None))):
        if t.code in used_by_roles or t.code in {c for items in m["division_requirements"].values() for c in [i["code"] for i in items]}:
            t.layer = "role"
    for pos in db.scalars(select(models.Position)):
        if not pos.library_role:
            pos.library_role = role_for_title(pos.title)
            stats["positions_mapped"] += 1 if pos.library_role else 0
    db.commit()
    return stats


def role_for_title(title: str) -> str | None:
    t = (title or "").lower()
    for rule in manifest()["title_rules"]:
        if any(w in t for w in rule["match"]):
            return rule["role"]
    return None


def program_of(db: Session, division_code: str | None) -> str | None:
    if not division_code:
        return None
    d = db.scalar(select(models.Division).where(models.Division.code == division_code))
    return d.program if d else None


# ---- materials -------------------------------------------------------------------------

# Official public sources the library may download from: LANL, DOE/NNSA, federal regulations (govinfo),
# OPM and Commerce training material, and the DOE lab computing centers' user documentation.
OFFICIAL_HOSTS = {
    "cdn.lanl.gov", "www.energy.gov", "www.govinfo.gov", "govinfo.gov", "www.opm.gov", "grow.exim.gov",
    "www.mpi-forum.org", "numpy.org", "docs.nersc.gov", "docs.olcf.ornl.gov",
    "docs.python.org", "scikit-learn.org",
}


def allowed_url(url: str) -> bool:
    """Only https pages on official public hosts, no query or fragment. LANL's CDN only serves /files/*.pdf."""
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc not in OFFICIAL_HOSTS or p.query or p.fragment:
        return False
    if p.netloc == "cdn.lanl.gov":
        return p.path.startswith("/files/") and p.path.lower().endswith(".pdf")
    return not p.path.lower().endswith((".exe", ".zip", ".js", ".dmg", ".msi"))


def _download(url: str, target: Path, expect: str = "pdf") -> int:
    """Download an official source. Redirects are followed only to other official hosts."""
    if not allowed_url(url):
        raise ValueError("Only official public sources (LANL, DOE, govinfo, OPM, lab computing docs) can be imported")
    size, limit = 0, settings.max_upload_mb * 1024 * 1024
    for _ in range(6):
        with httpx.stream("GET", url, timeout=60, follow_redirects=False,
                          headers={"User-Agent": "LANL-Adaptive-Training/1.0 (+training library import)"}) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                nxt = str(r.url.join(r.headers.get("location", "")))
                if urlsplit(nxt).scheme != "https" or urlsplit(nxt).netloc not in OFFICIAL_HOSTS:
                    raise ValueError(f"Redirected to an unapproved site: {urlsplit(nxt).netloc}")
                url = nxt
                continue
            r.raise_for_status()
            with target.open("wb") as fh:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ValueError(f"File is larger than {settings.max_upload_mb} MB")
                    fh.write(chunk)
            break
    else:
        raise ValueError("Too many redirects")
    with target.open("rb") as fh:
        head = fh.read(512)
    if expect == "pdf" and not head.startswith(b"%PDF-"):
        raise ValueError("The download wasn't a PDF")
    if expect == "web" and b"<" not in head:
        raise ValueError("The download wasn't a web page")
    return size


def html_to_text(html: str) -> str:
    """Readable text from a documentation page: headings and paragraphs, without menus, scripts or footers."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form", "button"}
        BLOCK = {"p", "div", "li", "tr", "br", "section", "article", "pre", "table", "dd", "dt"}

        def __init__(self):
            super().__init__()
            self.out, self.skip = [], 0

        def handle_starttag(self, tag, attrs):
            if tag in self.SKIP:
                self.skip += 1
            elif tag in {"h1", "h2", "h3", "h4"}:
                self.out.append("\n\n")
            elif tag in self.BLOCK:
                self.out.append("\n")

        def handle_endtag(self, tag):
            if tag in self.SKIP and self.skip:
                self.skip -= 1
            elif tag in {"h1", "h2", "h3", "h4"}:
                self.out.append("\n")

        def handle_data(self, data):
            if not self.skip:
                self.out.append(data)

    p = P()
    p.feed(html)
    lines = [" ".join(l.split()) for l in "".join(p.out).splitlines()]
    text, blank = [], False
    for l in lines:
        if l:
            text.append(l)
            blank = False
        elif not blank:
            text.append("")
            blank = True
    return "\n".join(text).strip()


def import_material(db: Session, mat: models.TrainingMaterial) -> models.TrainingMaterial:
    """Download a linked public PDF into the library and extract its text (no AI involved)."""
    if mat.document_id or mat.kind not in ("pdf", "web"):
        return mat
    folder = Path(settings.upload_dir) / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (f"library-{mat.id}.pdf" if mat.kind == "pdf" else f"library-{mat.id}.html")
    try:
        size = _download(mat.url, target, mat.kind)
        if mat.kind == "web":  # keep the readable text of the page, not its HTML
            text = html_to_text(target.read_text(errors="ignore"))
            target.unlink(missing_ok=True)
            target = target.with_suffix(".txt")
            target.write_text(f"{mat.title}\nSource: {mat.url}\n\n{text}")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        twin = db.scalar(select(models.TrainingMaterial).where(models.TrainingMaterial.sha256 == digest,
                                                               models.TrainingMaterial.document_id.is_not(None)))
        if twin:  # same file already imported for another training (e.g. the NFO brochure)
            target.unlink(missing_ok=True)
            mat.document_id = twin.document_id
        else:
            doc = documents.save_document(db, target, mat.title, "manual", None, None)
            doc.filename, doc.training_code = Path(urlsplit(mat.url).path).name, mat.training_code
            doc.analysis = {"stored_as": target.name, "source_url": mat.url, "attribution": ATTRIBUTION}
            mat.document_id = doc.id
            if doc.status == "failed":
                mat.error = doc.error
        mat.sha256, mat.bytes, mat.retrieved_at = digest, size, datetime.utcnow()
        mat.status, mat.error = ("imported", mat.error) if mat.document_id else ("failed", mat.error)
    except Exception as exc:  # report per material, keep going
        target.unlink(missing_ok=True)
        mat.status, mat.error = "failed", str(exc)[:400]
    db.commit()
    return mat


def import_all(db: Session, training_code: str | None = None) -> dict:
    q = select(models.TrainingMaterial).where(models.TrainingMaterial.document_id.is_(None), models.TrainingMaterial.kind.in_(["pdf", "web"]),
                                              models.TrainingMaterial.status != "removed")
    if training_code:
        q = q.where(models.TrainingMaterial.training_code == training_code)
    results = {"imported": 0, "failed": 0, "errors": []}
    for mat in list(db.scalars(q)):
        import_material(db, mat)
        if mat.status == "imported":
            results["imported"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({"training_code": mat.training_code, "title": mat.title, "error": mat.error})
    return results


def add_uploaded(db: Session, training_code: str, path: Path, title: str, filename: str, uploader_id: int | None) -> models.TrainingMaterial:
    """An admin-uploaded PDF, slide deck, Word file or text file for a training."""
    kind = {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx"}.get(path.suffix.lower(), "text")
    doc = documents.save_document(db, path, title, "manual", None, uploader_id)
    doc.filename, doc.training_code = filename, training_code
    doc.analysis = {"stored_as": path.name}
    mat = models.TrainingMaterial(training_code=training_code, kind=kind, title=title, url=f"upload:{path.name}",
                                  status="uploaded" if doc.status != "failed" else "failed", document_id=doc.id,
                                  sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size,
                                  retrieved_at=datetime.utcnow(), error=doc.error)
    db.add(mat)
    db.commit()
    return mat


def replace_file(db: Session, mat: models.TrainingMaterial, path: Path, filename: str, uploader_id: int | None) -> models.TrainingMaterial:
    """Swap in a newer file for a material. A catalog link keeps its URL (so the library doesn't re-add it) but uses the new file."""
    kind = {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx"}.get(path.suffix.lower(), "text")
    doc = documents.save_document(db, path, mat.title, "manual", None, uploader_id)
    doc.filename, doc.training_code = filename, mat.training_code
    doc.analysis = {"stored_as": path.name, "replaces_material": mat.id}
    linked = not mat.url.startswith("upload:")
    mat.kind, mat.document_id, mat.error = kind, doc.id, doc.error
    mat.status = "failed" if doc.status == "failed" else ("replaced" if linked else "uploaded")
    if not linked:
        mat.url = f"upload:{path.name}"
    mat.sha256, mat.bytes, mat.retrieved_at = hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size, datetime.utcnow()
    db.commit()
    return mat


def primary_document(db: Session, training_code: str) -> models.Document | None:
    """The material the AI builds the course from: the admin's own uploads and shared-folder files first (newest
    first), then the catalog's sources in the order listed (the main source comes first)."""
    mats = list(db.scalars(select(models.TrainingMaterial).where(
        models.TrainingMaterial.training_code == training_code, models.TrainingMaterial.document_id.is_not(None),
        models.TrainingMaterial.status != "removed").order_by(models.TrainingMaterial.id)))
    own = [m for m in mats if m.url.startswith(("upload:", "folder:")) or m.status == "replaced"]
    for m in [*reversed(own), *[m for m in mats if m not in own]]:
        d = db.get(models.Document, m.document_id)
        if d and d.status != "failed" and d.words >= 30:
            return d
    return None


# ---- plans by layer --------------------------------------------------------------------

def layer_items(db: Session, program: str | None, role_key: str | None) -> list[dict]:
    """Every library training for a program + role, tagged with its layer and who it applies to.

    audience: new_hire (institutional onboarding), new_to_division (division layer), all (role layer)
    """
    trainings = {t.code: t for t in db.scalars(select(models.Training).where(models.Training.layer.is_not(None)))}
    known = set(db.scalars(select(models.Training.code)))
    items: dict[str, dict] = {}

    refreshers = {t.code for t in trainings.values() if t.refresher_of}

    def add(code, phase, audience, layer, reason, kind=None):
        # Refresher courses come round on the annual cycle; onboarding starts with the initial course.
        if code in items or code not in known or code in refreshers:
            return
        items[code] = {"training_code": code, "phase": phase, "audience": audience, "required": True,
                       "skip_if_years_at_least": None, "reason": reason, "layer": layer, "kind": kind}

    for t in sorted(trainings.values(), key=lambda t: t.code):
        if t.layer == "institutional":
            add(t.code, 1, "new_hire", "institutional",
                "Required for everyone at LANL" + (", then every year" if t.frequency == "annual" else ""))
    if program:
        name = program_names().get(program, program)
        for r in db.scalars(select(models.DivisionRequirement).where(models.DivisionRequirement.program == program)
                            .order_by(models.DivisionRequirement.phase)):
            add(r.training_code, r.phase, "new_to_division", "division", f"{name}: {r.reason}" if r.reason else f"Required in {name}")
    if role_key:
        role = db.get(models.LibraryRole, role_key)
        for r in db.scalars(select(models.RoleRequirement).where(models.RoleRequirement.role_key == role_key)
                            .order_by(models.RoleRequirement.program.is_(None).desc(), models.RoleRequirement.phase)):
            if r.program not in (None, program):
                continue
            label = role.title if role else role_key
            where = f" in {program_names().get(program, program)}" if r.program else ""
            add(r.training_code, r.phase, "all", "role",
                r.reason or f"{label}{where}: {'soft skill' if r.kind == 'soft' else 'technical'} training", r.kind)
    return list(items.values())


def annual_cycle(db: Session, due: date, stagger_weeks: int = 0, codes: list[str] | None = None) -> dict:
    """Assign this year's institutional annual trainings to everyone who isn't current, spreading due dates."""
    from .adaptive import assignment_flags
    from .loader import load_people

    q = select(models.Training).where(models.Training.layer == "institutional", models.Training.frequency == "annual")
    trainings = [t for t in db.scalars(q) if not codes or t.code in codes]
    people = sorted(load_people(db, None), key=lambda e: (e.division_code, e.name))
    created = refreshed = current = 0
    window = stagger_weeks * 7
    for i, emp in enumerate(people):
        offset = window - round(i * window / max(1, len(people) - 1)) if window else 0
        when = max(date.today() + timedelta(days=7), due - timedelta(days=offset))
        have = {a.training_id: a for a in emp.assignments}
        for t in trainings:
            a = have.get(t.id)
            if a is None:
                emp.assignments.append(models.Assignment(training=t, due_date=when))
                created += 1
            elif a.status == "completed" and not assignment_flags(a)["needs_retake"] and a.expires_at and a.expires_at > due:
                current += 1
            elif a.status == "completed":
                a.status, a.progress, a.due_date = "not_started", 0, when
                refreshed += 1
    db.commit()
    return {"trainings": [t.code for t in trainings], "people": len(people), "assigned": created, "reopened": refreshed,
            "already_current": current}


# ---- the shared library folder (committed, so every teammate gets the same files) ------------

FOLDER_TYPES = {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx", ".txt": "text", ".md": "text"}
UNASSIGNED = "unassigned"


def library_root() -> Path:
    return Path(settings.library_dir)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def import_folder(db: Session, root: Path | None = None) -> dict:
    """Import every file in the shared library folder: <root>/<TRAINING-CODE>/<file>, or <root>/unassigned/<file>.

    Safe to rerun: a file already in the library (same contents) is skipped, and one an admin deleted stays deleted.
    Files in an unknown training folder are imported as unassigned so an admin can place them.
    """
    import shutil

    root = root or library_root()
    out = {"imported": 0, "skipped": 0, "failed": 0, "unassigned": 0, "errors": []}
    if not root.is_dir():
        return out
    codes = set(db.scalars(select(models.Training.code)))
    known = {(m.training_code, m.sha256) for m in db.scalars(select(models.TrainingMaterial)) if m.sha256}
    by_path = {m.url: m for m in db.scalars(select(models.TrainingMaterial).where(models.TrainingMaterial.url.like("folder:%")))}
    folder = Path(settings.upload_dir) / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    for path in sorted(root.rglob("*")):
        if (not path.is_file() or path.suffix.lower() not in FOLDER_TYPES or path.name.startswith(".")
                or path.stem.upper() == "README"):
            continue
        rel = path.relative_to(root)
        code = rel.parts[0] if len(rel.parts) > 1 else UNASSIGNED
        code = code if code in codes else ""  # "" = waiting for an admin to place it
        url = f"folder:{rel.as_posix()}"
        try:
            digest = _sha(path)
            if url in by_path or (code, digest) in known:
                out["skipped"] += 1
                continue
            twin = db.scalar(select(models.TrainingMaterial).where(models.TrainingMaterial.sha256 == digest,
                                                                   models.TrainingMaterial.document_id.is_not(None)))
            title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
            if twin:  # the same file already belongs to another training: share its stored copy
                doc_id, error = twin.document_id, ""
            else:
                dest = folder / f"library-folder-{digest[:16]}{path.suffix.lower()}"
                shutil.copyfile(path, dest)
                doc = documents.save_document(db, dest, title, "manual", None, None)
                doc.filename, doc.training_code = path.name, code or None
                doc.analysis = {"stored_as": dest.name, "library_folder": rel.as_posix()}
                doc_id, error = doc.id, doc.error
            m = models.TrainingMaterial(training_code=code, kind=FOLDER_TYPES[path.suffix.lower()], title=title, url=url,
                                        status="failed" if error else "imported", document_id=doc_id, sha256=digest,
                                        bytes=path.stat().st_size, retrieved_at=datetime.utcnow(), error=error or "")
            db.add(m)
            db.commit()
            by_path[url], known = m, known | {(code, digest)}
            out["imported"] += 1
            out["unassigned"] += 0 if code else 1
        except Exception as exc:  # report per file, keep going
            db.rollback()
            out["failed"] += 1
            out["errors"].append({"file": rel.as_posix(), "error": str(exc)[:300]})
    return out


def export_to_folder(db: Session, root: Path | None = None) -> dict:
    """Copy every material uploaded on this machine into the shared folder, by training, so it can be committed."""
    import re
    import shutil

    root = root or library_root()
    out = {"copied": 0, "already_there": 0, "missing": 0, "files": []}
    present = {_sha(p) for p in root.rglob("*") if p.is_file()} if root.is_dir() else set()
    for m in db.scalars(select(models.TrainingMaterial).where(models.TrainingMaterial.url.like("upload:%"),
                                                              models.TrainingMaterial.status != "removed")):
        doc = db.get(models.Document, m.document_id) if m.document_id else None
        stored = (doc.analysis or {}).get("stored_as") if doc else None
        src = Path(settings.upload_dir) / "documents" / stored if stored else None
        if not src or not src.exists():
            out["missing"] += 1
            continue
        if m.sha256 in present:
            out["already_there"] += 1
            continue
        name = re.sub(r"[^A-Za-z0-9._ -]+", "", m.title).strip()[:120] or src.stem
        dest = root / (m.training_code or UNASSIGNED) / f"{name}{src.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        n = 2
        while dest.exists():
            dest = dest.with_name(f"{name} ({n}){src.suffix.lower()}")
            n += 1
        shutil.copyfile(src, dest)
        present.add(m.sha256)
        out["copied"] += 1
        out["files"].append(dest.relative_to(root).as_posix())
    return out


def build_missing(db: Session, use_ai: bool = False, codes: list[str] | None = None, rebuild_drafts: bool = False) -> dict:
    """Build lessons for every library training that has readable material but no lessons yet (offline by default).
    rebuild_drafts also rebuilds unpublished drafts; published lessons are never touched."""
    out = {"built": [], "failed": []}
    built_ids = set(db.scalars(select(models.CourseModule.training_id)))
    have = {t.code for t in db.scalars(select(models.Training))
            if t.id in built_ids and not (rebuild_drafts and t.lessons_status == "draft")}
    wanted = sorted({m.training_code for m in db.scalars(select(models.TrainingMaterial).where(
        models.TrainingMaterial.document_id.is_not(None), models.TrainingMaterial.status != "removed")) if m.training_code})
    for code in wanted:
        if code in have or (codes and code not in codes):
            continue
        doc = primary_document(db, code)
        if doc is None:
            continue
        doc.training_code = code
        db.commit()
        try:
            documents.build_course(db, doc.id, use_ai=use_ai)
            (out["built"] if doc.status == "ready" else out["failed"]).append(code)
        except Exception:
            out["failed"].append(code)
    return out


_EXCERPTS: dict[str, tuple[float, str]] = {}


def excerpt_for(training_code: str, limit: int = 12000) -> str:
    """source_excerpt with its own session and a 10-minute cache (used while building prompts)."""
    import time

    from ..database import SessionLocal

    hit = _EXCERPTS.get(training_code)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    try:
        with SessionLocal() as db:
            text = source_excerpt(db, training_code, limit)
    except Exception:
        text = ""
    _EXCERPTS[training_code] = (time.time(), text)
    return text


def source_excerpt(db: Session, training_code: str, limit: int = 12000) -> str:
    """The start of a training's richest library material, so lessons for unbuilt trainings still come from the PDF."""
    doc = primary_document(db, training_code)
    if doc is None:
        return ""
    return f"Source: {doc.title} ({doc.pages} pages)\n" + documents.document_text(doc, 1, doc.pages, limit)


def repair_offline_skills(db: Session, catalog_skills: dict[str, list[str]]) -> int:
    """Older offline builds merged heading words ("part pages", "u s c") into training skills. Restore the source
    skills (catalog or training CSV) for trainings whose lessons weren't built by the AI."""
    import csv
    import glob

    orig = {k: [s.lower() for s in v] for k, v in catalog_skills.items()}
    for f in glob.glob(str(Path(settings.data_dir) / "trainings*.csv")):
        with open(f, newline="") as fh:
            for r in csv.DictReader(fh):
                tags = (r.get("skill_tags") or "").replace(";", ",").replace("|", ",")
                orig.setdefault(r.get("course_code", ""), [x.strip().lower() for x in tags.split(",") if x.strip()])
    fixed = 0
    for t in db.scalars(select(models.Training).where(models.Training.document_id.is_not(None))):
        doc = db.get(models.Document, t.document_id)
        want = orig.get(t.code)
        if want is not None and doc is not None and doc.generated_by in ("", "offline", None) and sorted(t.skills or []) != sorted(want):
            t.skills = want
            fixed += 1
    return fixed
