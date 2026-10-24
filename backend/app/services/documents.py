"""Turn uploaded documents (job descriptions, 200-page manuals, policies) into courses.

Pipeline:
  1. extract_pages: PDF or text -> one row per page (fast, runs during the upload request).
  2. build_course (background): the whole document goes to Claude, which returns a course:
     modules mapped to page ranges, objectives, key points, skills, and a bank of
     realistic workplace scenarios for interview-style assessments.
     Without an API key, an offline builder uses the document's own headings and
     "must / shall / required" statements.
  3. Lessons and videos for each module are generated later, per learning style
     (see courseware.py), from just that module's pages.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from . import ai

log = logging.getLogger(__name__)

MAX_CHARS = 3_000_000  # ~750k tokens; anything bigger should be split before upload
KIND_CATEGORY = {"policy": "compliance", "procedure": "safety", "manual": "technical", "requirements": "technical",
                 "job_description": "culture", "handbook": "culture"}


# ---- extraction -------------------------------------------------------------------

def extract_pages(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [_clean(p.extract_text() or "") for p in reader.pages]
    if suffix in {".txt", ".md"}:
        return _paginate(path.read_text(errors="ignore").splitlines())
    if suffix == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:
            raise ValueError("Install python-docx to read .docx files, or upload a PDF") from exc
        return _paginate([p.text for p in docx.Document(str(path)).paragraphs])
    raise ValueError("Upload a PDF, .docx, .txt or .md file")


def _paginate(lines: list[str], words_per_page: int = 450) -> list[str]:
    """Text files have no pages; group whole lines into ~450-word pseudo-pages so modules can cite ranges."""
    pages, cur, n = [], [], 0
    for line in lines:
        cur.append(line)
        n += len(line.split())
        if n >= words_per_page:
            pages.append("\n".join(cur).strip())
            cur, n = [], 0
    if cur:
        pages.append("\n".join(cur).strip())
    return pages or [""]


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def save_document(db: Session, path: Path, title: str, kind: str, position_code: str | None, uploader_id: int | None) -> models.Document:
    pages = extract_pages(path)
    doc = models.Document(title=title or path.stem, filename=path.name, kind=kind, position_code=position_code or None,
                          uploaded_by_id=uploader_id, pages=len(pages), words=sum(len(p.split()) for p in pages), status="extracted")
    doc.page_texts = [models.DocumentPage(page=i + 1, text=t) for i, t in enumerate(pages)]
    db.add(doc)
    db.commit()
    if doc.words < 30:
        doc.status, doc.error = "failed", "Almost no text found. If this is a scanned PDF, run OCR on it first."
        db.commit()
    return doc


def document_text(doc: models.Document, start: int = 1, end: int | None = None, limit: int = MAX_CHARS) -> str:
    end = end or doc.pages
    parts = [f"[Page {p.page}]\n{p.text}" for p in doc.page_texts if start <= p.page <= end]
    return "\n\n".join(parts)[:limit]


# ---- course building --------------------------------------------------------------

COURSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "category": {"type": "string", "enum": ["safety", "technical", "culture", "compliance"]},
        "assessment_type": {"type": "string", "enum": ["quiz", "situational", "both"]},
        "skills": {"type": "array", "items": {"type": "string"}},
        "modules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "page_start": {"type": "integer"},
                    "page_end": {"type": "integer"},
                    "objectives": {"type": "array", "items": {"type": "string"}},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "skills": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "summary", "page_start", "page_end", "objectives", "key_points", "skills"],
                "additionalProperties": False,
            },
        },
        "scenarios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "situation": {"type": "string"},
                    "questions": {"type": "array", "items": {"type": "string"}},
                    "competencies": {"type": "array", "items": {"type": "string"}},
                    "strong_response": {"type": "array", "items": {"type": "string"}},
                    "red_flags": {"type": "array", "items": {"type": "string"}},
                    "source_pages": {"type": "string"},
                },
                "required": ["title", "situation", "questions", "competencies", "strong_response", "red_flags", "source_pages"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "summary", "category", "assessment_type", "skills", "modules", "scenarios"],
    "additionalProperties": False,
}


def _role_title(db: Session, doc: models.Document) -> str:
    if doc.position_code:
        pos = db.scalar(select(models.Position).where(models.Position.code == doc.position_code))
        if pos:
            return pos.title
    return "an employee in this role"


def build_course(db: Session, doc_id: int) -> models.Training:
    doc = db.get(models.Document, doc_id)
    doc.status, doc.error = "generating", ""
    db.commit()
    try:
        role = _role_title(db, doc)
        text = document_text(doc)
        if len(text) >= MAX_CHARS:
            raise ValueError(f"Document is too long to process in one pass ({doc.pages} pages). Split it into parts.")
        prompt = (
            f"This is an internal LANL document ({doc.kind.replace('_', ' ')}) titled \"{doc.title}\", {doc.pages} pages. "
            f"It's being turned into a course for: {role}.\n\n"
            "Build a course so nobody has to read the whole document:\n"
            "- 4 to 12 modules in a sensible learning order, each covering a page range of the document. Together they should "
            "cover everything a person in this role needs; skip boilerplate (revision history, tables of contents).\n"
            "- For each module: a 2-3 sentence summary, 2-4 learning objectives, 3-7 key points stated plainly with the "
            "actual requirement (who, what, when), and the skills it builds (short lowercase names).\n"
            "- 6 to 10 realistic workplace scenarios for an interview-style assessment like CASPer or an MMI. Each is a "
            "specific situation this role actually faces, grounded in the document (cite pages), with 2-3 open questions "
            "(what would you do, how would you handle the people involved, what would you do differently next time). "
            "List the competencies it tests, what a strong response would consider, and red flags.\n"
            "- assessment_type: 'quiz' (multiple choice) when the material is policies, rules, procedures or technical "
            "facts, which is most documents. 'situational' (interview scenarios) only when it's mainly about leading "
            "people or making judgment calls. 'both' when the role must know the rules AND apply judgment with people.\n\n"
            f"<document>\n{text}\n</document>"
        )
        data = ai.call_json_long(prompt, COURSE_SCHEMA, max_tokens=32000)
        doc.generated_by = settings.ai_model if data else "offline"
        if not data:
            vocab = sorted({s for t in db.scalars(select(models.Training)) for s in (t.skills or [])}
                           | {s for p in db.scalars(select(models.Position)) for s in (p.required_skills or [])})
            data = offline_course(doc, role, vocab)
        training = _save_course(db, doc, data)
        doc.status = "ready"
        db.commit()
        return training
    except Exception as exc:
        log.exception("Course build failed for document %s", doc_id)
        db.rollback()
        doc = db.get(models.Document, doc_id)
        doc.status, doc.error = "failed", str(exc)[:500]
        db.commit()
        raise


def _save_course(db: Session, doc: models.Document, data: dict) -> models.Training:
    code = f"DOC-{doc.id}"
    t = db.scalar(select(models.Training).where(models.Training.code == code))
    if t is None:
        t = models.Training(code=code)
        db.add(t)
    words = doc.words
    t.title = data["title"][:300]
    t.description = data["summary"]
    t.category = data.get("category") or KIND_CATEGORY.get(doc.kind, "technical")
    t.required = True
    t.delivery = "online"
    t.source_system = "Internal documents"
    t.source_url = f"/api/documents/{doc.id}/file"
    t.duration_minutes = max(20, int(words / 230 / 3))  # about a third of the time it takes to read it
    t.skills = sorted({s.lower().strip() for s in data.get("skills", []) if s.strip()})[:20]
    t.job_roles = [doc.position_code] if doc.position_code else []
    t.outline = "\n".join(m["title"] for m in data["modules"])
    t.assessment_type = data.get("assessment_type") or "quiz"
    t.document_id = doc.id
    t.validity_months = None
    db.flush()
    for old in db.scalars(select(models.CourseModule).where(models.CourseModule.training_id == t.id)):
        for c in db.scalars(select(models.LessonCache).where(models.LessonCache.module_id == old.id)):
            db.delete(c)
        db.delete(old)
    for old in db.scalars(select(models.Scenario).where(models.Scenario.training_id == t.id)):
        db.delete(old)
    db.flush()
    for i, m in enumerate(data["modules"]):
        start = max(1, min(doc.pages, int(m["page_start"])))
        end = max(start, min(doc.pages, int(m["page_end"])))
        db.add(models.CourseModule(training_id=t.id, position=i, title=m["title"][:300], summary=m["summary"], page_start=start,
                                   page_end=end, objectives=m["objectives"], key_points=m["key_points"],
                                   skills=[s.lower() for s in m.get("skills", [])]))
    for sc in data["scenarios"]:
        db.add(models.Scenario(training_id=t.id, title=sc["title"][:300], situation=sc["situation"], questions=sc["questions"][:3],
                               competencies=sc["competencies"], strong_response=sc["strong_response"], red_flags=sc["red_flags"],
                               source_pages=str(sc.get("source_pages", ""))[:64]))
    db.flush()
    return t


# ---- offline course builder -------------------------------------------------------

HEADING = re.compile(r"^(?:(?:chapter|section|part)\s+\d+[\.:]?\s+|\d+(?:\.\d+){0,2}\.?\s+)([A-Z][^\n]{2,80})$", re.IGNORECASE)
RULE = re.compile(r"\b(must|shall|required|is responsible|are responsible|ensure|never|always|may not|prohibited)\b", re.IGNORECASE)
STOP = set("the a an and or of to in for on with by at from is are be this that these those as it its into your their".split())


def _headings(doc: models.Document) -> list[tuple[int, str]]:
    found = []
    for p in doc.page_texts:
        for line in p.text.splitlines():
            line = line.strip()
            m = HEADING.match(line)
            if m and len(line.split()) <= 12 and not line.endswith("."):
                found.append((p.page, re.sub(r"\s+", " ", m.group(1)).strip()))
    # drop table-of-contents duplicates (same heading early, then again later)
    seen, out = {}, []
    for page, h in found:
        seen[h.lower()] = (page, h)
    for page, h in sorted(seen.values()):
        out.append((page, h))
    return out


def _body_text(page_text: str) -> str:
    """Page text without heading lines, so headings don't get glued into sentences."""
    top = re.compile(r"^(?:chapter\s+)?\d{1,2}(?:\.\d+)*[\.:]?\s+[A-Z][^.]{2,80}$", re.IGNORECASE)
    return " ".join(l for l in page_text.splitlines() if not (HEADING.match(l.strip()) or top.match(l.strip())))


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", flat) if 40 <= len(s.strip()) <= 260]


def _top_level(doc: models.Document) -> list[tuple[int, str]]:
    """Headings like "7 Risk and Opportunity Management" or "Chapter 7: ..." (not 7.1)."""
    pat = re.compile(r"^(?:chapter\s+)?(\d{1,2})[\.:]?\s+([A-Z][A-Za-z ,:&/\-]{3,80})$", re.IGNORECASE)
    found = {}
    for p in doc.page_texts:
        lines = p.text.splitlines()
        if sum(1 for l in lines if pat.match(l.strip())) >= 3:
            continue  # a table of contents, not a chapter start
        for line in lines[:6]:  # chapter titles sit at the top of a page
            m = pat.match(line.strip())
            if m and m.group(1) not in found:
                found[m.group(1)] = (p.page, m.group(2).strip())
    return sorted(found.values())


def _skills_for(title: str, vocabulary: list[str] | None) -> list[str]:
    t = title.lower()
    hits = [v for v in (vocabulary or []) if v in t or all(w in t for w in v.split())]
    return hits[:3] or [_skill_from(title)]


def _skill_from(title: str) -> str:
    words = [w for w in re.findall(r"[a-zA-Z]+", title.lower()) if w not in STOP]
    return " ".join(words[:3]) or "role knowledge"


def offline_course(doc: models.Document, role: str, vocabulary: list[str] | None = None) -> dict:
    heads = _headings(doc)
    top = [(p, h) for p, h in heads if not re.match(r"^\d+\.\d", h)]
    chapters = _top_level(doc)
    if len(chapters) >= 3:  # numbered chapters are the natural modules
        groups = [[c] for c in chapters]
    else:
        if len(heads) < 3:  # no usable structure: even page chunks
            step = max(1, doc.pages // 8 or 1)
            heads = [(p, f"Part {i + 1} (pages {p}-{min(doc.pages, p + step - 1)})") for i, p in enumerate(range(1, doc.pages + 1, step))]
        target = max(1, -(-len(heads) // 12))
        groups = [heads[i:i + target] for i in range(0, len(heads), target)]
    del top
    modules = []
    for gi, g in enumerate(groups):
        start = g[0][0]
        end = (groups[gi + 1][0][0] - 1) if gi + 1 < len(groups) else doc.pages
        end = max(start, end)
        text = " ".join(_body_text(p.text) for p in doc.page_texts if start <= p.page <= end)
        sents = list(dict.fromkeys(_sentences(text)))  # documents repeat themselves; keep each sentence once
        sents = [x for x in sents if not re.match(r"^(this chapter|read it|see |figure|table)\b", x, re.IGNORECASE)]
        rules = [x for x in sents if RULE.search(x)][:7] or sents[:4]
        title = g[0][1] if len(g) == 1 else f"{g[0][1]} and related topics"
        subs = [h for p, h in heads if start <= p <= end and h != g[0][1]][:4]
        modules.append({
            "title": title[:120],
            "summary": "Covers " + (", ".join(s_.lower() for s_ in subs) if subs else title.lower()) + ".",
            "page_start": start, "page_end": end,
            "objectives": [f"Explain {h.lower()}" for h in (subs or [title])[:3]],
            "key_points": rules,
            "skills": _skills_for(title, vocabulary),
        })
    scenarios = []
    for m in modules:
        rule = next((k for k in m["key_points"] if RULE.search(k)), None)
        if not rule:
            continue
        scenarios.append({
            "title": f"Pressure to skip: {m['title'][:80]}",
            "situation": (f"You're working as {role}. It's late in the week, a deliverable is due tomorrow, and a team member tells you "
                          f"they skipped this requirement to save time: \"{rule}\" The customer is already asking for an update."),
            "questions": ["What do you do first, and why?",
                          "How do you handle the conversation with the team member and the customer?",
                          "What would you change so this doesn't happen again?"],
            "competencies": ["judgment", "communication", "accountability"],
            "strong_response": [f"follows the documented requirement ({m['title'][:60]})", "pauses or corrects the work before delivery",
                                "talks to the team member to understand why, without blaming", "is honest with the customer about the schedule",
                                "escalates or documents per procedure", "fixes the root cause (planning, training, workload)"],
            "red_flags": ["delivers anyway to meet the deadline", "hides the problem from the customer or management", "blames without listening"],
            "source_pages": f"{m['page_start']}-{m['page_end']}",
        })
    skills = sorted({s for m in modules for s in m["skills"]})
    return {
        "title": doc.title, "summary": f"Course built from {doc.title} ({doc.pages} pages) for {role}.",
        "category": KIND_CATEGORY.get(doc.kind, "technical"), "assessment_type": _offline_assessment(doc, role, modules),
        "skills": skills, "modules": modules, "scenarios": scenarios[:10],
    }


def _offline_assessment(doc: models.Document, role: str, modules: list[dict]) -> str:
    """Policies and procedures get a quiz. Handbooks for lead roles mix rules with people judgment: both."""
    from ..assessment_rules import JUDGMENT_WORDS

    if doc.kind in ("policy", "procedure", "manual", "requirements"):
        return "quiz"
    people_modules = sum(1 for m in modules if any(w in m["title"].lower() for w in (*JUDGMENT_WORDS, "team", "stakeholder")))
    leads = any(w in role.lower() for w in ("lead", "manager", "supervisor", "director"))
    return "both" if leads and people_modules else "quiz"


def build_course_background(doc_id: int):
    """Entry point for FastAPI BackgroundTasks (own DB session)."""
    from ..database import SessionLocal

    from ..safeguards import build_slots

    with build_slots, SessionLocal() as db:  # a burst of uploads queues instead of starving the server
        try:
            build_course(db, doc_id)
        except Exception:
            pass  # status and error are saved on the document
