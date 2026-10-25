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
logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding notices on some government PDFs are harmless

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
    if suffix == ".pptx":
        try:
            from pptx import Presentation  # type: ignore
        except ImportError as exc:
            raise ValueError("Install python-pptx to read slide decks, or upload a PDF") from exc
        pages = []
        for slide in Presentation(str(path)).slides:  # one page per slide, speaker notes included
            parts = [sh.text_frame.text for sh in slide.shapes if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip()]
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
                parts.append("Notes: " + slide.notes_slide.notes_text_frame.text)
            pages.append(_clean("\n".join(parts)))
        return pages or [""]
    if suffix == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:
            raise ValueError("Install python-docx to read .docx files, or upload a PDF") from exc
        return _paginate([p.text for p in docx.Document(str(path)).paragraphs])
    raise ValueError("Upload a PDF, .pptx, .docx, .txt or .md file")


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


def build_course(db: Session, doc_id: int, use_ai: bool = True) -> models.Training:
    """Turn a document into modules, lessons, quizzes and scenarios. use_ai=False uses the offline builder only."""
    doc = db.get(models.Document, doc_id)
    doc.status, doc.error = "generating", ""
    db.commit()
    try:
        role = _role_title(db, doc)
        text = document_text(doc)
        if use_ai and len(text) >= MAX_CHARS:
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
        data = ai.call_json_long(prompt, COURSE_SCHEMA, max_tokens=32000) if use_ai else None
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
    if doc.training_code:  # a library material: the course becomes that training's lessons, keeping its identity
        t = db.scalar(select(models.Training).where(models.Training.code == doc.training_code))
        if t is not None:
            return _attach_modules(db, t, doc, data)
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
    return _replace_modules(db, t, doc, data)


def _attach_modules(db: Session, t: models.Training, doc: models.Document, data: dict) -> models.Training:
    """Library training: add AI modules and scenarios from its material; title, layer, schedule and
    assessment type stay as the admin set them."""
    t.document_id = doc.id
    t.lessons_status = "draft"  # learners see these only after an admin reviews and publishes them
    t.outline = "\n".join(m["title"] for m in data["modules"])
    if doc.generated_by not in ("", "offline"):  # offline "skills" are words from headings, not real skills
        t.skills = sorted(set(t.skills or []) | {s.lower().strip() for s in data.get("skills", []) if s.strip()})[:20]
    if doc.generated_by not in ("", "offline") and (not t.description or t.description == t.title):
        t.description = data["summary"]  # only an AI summary is better than the catalog's own description
    t.duration_minutes = max(t.duration_minutes or 0, int(doc.words / 230 / 3))
    db.flush()
    return _replace_modules(db, t, doc, data)


def _replace_modules(db: Session, t: models.Training, doc: models.Document, data: dict) -> models.Training:
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


DOTS = re.compile(r"\.{4,}|…{2,}|(?:\s\.){4,}")  # table-of-contents leaders
NUMWORD = r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
UNIT = re.compile(rf"^(?:module|unit|lesson|chapter|section|part|topic)\s+({NUMWORD})\b\s*[:.\-–—]?\s*(.*)$", re.IGNORECASE)
UNIT_WORD = re.compile(r"\b(?:module|unit|lesson|chapter)\s+" + NUMWORD + r"\b", re.IGNORECASE)
QUESTION_START = re.compile(r"^(?:in what|is it|are|is|what|which|how|why|when|who|where|list|name|describe|identify|explain|"
                            r"determine|verify|stop|select|choose|true or false|do|does|can|should)\b", re.IGNORECASE)


def _noise(doc: models.Document) -> set[str]:
    """Lines repeated on many pages: running headers, footers, course titles, revision stamps."""
    from collections import Counter

    counts = Counter()
    for p in doc.page_texts:
        counts.update({l.strip() for l in p.text.splitlines() if l.strip()})
    floor = max(3, int(doc.pages * 0.25))
    return {l for l, n in counts.items() if n >= floor}


def _is_toc(lines: list[str]) -> bool:
    return sum(1 for l in lines if DOTS.search(l)) >= 3 or any(l.strip().lower() in ("contents", "table of contents") for l in lines[:5])


BOILERPLATE = {"cancels/supersedes", "contact", "approved", "available online at", "initiated by", "references",
               "revision history", "table of contents", "contents", "foreword", "distribution", "caveats"}


def _heading_text(line: str) -> str | None:
    """A clean heading, or None if the line is a TOC entry, a question, a sentence or a page stamp."""
    line = re.sub(r"\s+", " ", line).strip().rstrip(":").strip()
    if re.search(r"CFR Ch\.|\bEdition\)|^\d+ CFR\b|^Pt\. \d+", line):
        return None  # running page headers of the Code of Federal Regulations
    if re.match(r"^(chapter|section|attachment|appendix) \d+\s*-\s*[ivx\d]+$", line, re.IGNORECASE) or line.lower() in BOILERPLATE:
        return None  # page stamps ("Chapter 5 - ii") and directive front-matter fields
    sec = re.match(r"^§\s*(\d+\.\d+)\s+([A-Z][^.;]{3,80})\.?$", line)
    if sec:  # a regulation section title, e.g. "§ 850.26 Regulated areas."
        title = re.sub(r"\s+\S+-$", "", sec.group(2).strip())  # drop a word split across lines ("Substantial dam-")
        return f"§ {sec.group(1)} {title}"
    caps = re.match(r"^(?:[0-9A-Za-z]{1,3}[.)]\s+)?((?:[A-Z0-9/&,'()-]+\s+){0,10}[A-Z0-9/&'()-]{2,})\.\s+[A-Z][a-z]", line)
    if caps and len(caps.group(1)) >= 6:  # "SAFEGUARDS AND SECURITY AWARENESS. Contractor will..." keeps the heading
        small = {"And", "Or", "Of", "The", "For", "To", "In", "On", "A", "An"}
        words = caps.group(1).title().split()
        return " ".join(w.lower() if i and w in small else w for i, w in enumerate(words))
    if not line or DOTS.search(line) or line.endswith(("?", ".", ",", ";")) or len(line.split()) > 12:
        return None
    if sum(c.isdigit() for c in line) > len(line) * 0.3:
        return None
    if re.search(r"[a-z][A-Z]", line) or len(UNIT_WORD.findall(line)) > 1:
        return None  # words glued together from multi-column pages
    m = UNIT.match(line)
    if m:
        return line
    m = HEADING.match(line)
    if not m:
        return None
    text = re.sub(r"\s+", " ", m.group(1)).strip()
    if QUESTION_START.match(text):
        return None  # a numbered quiz question or instruction step, not a section
    words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) >= 4]
    if words and sum(w[0].isupper() for w in words) < len(words) * 0.6:
        return None  # sentence-case numbered lines are steps or list items; real headings are Title Case
    if text.lower().rstrip(".") in BOILERPLATE:
        return None
    return text


def _headings(doc: models.Document, noise: set[str] | None = None) -> list[tuple[int, str]]:
    noise = noise if noise is not None else _noise(doc)
    found = []
    for p in doc.page_texts:
        lines = [l for l in p.text.splitlines() if l.strip() and l.strip() not in noise]
        if _is_toc(lines):
            continue
        for line in lines:
            h = _heading_text(line)
            if h:
                found.append((p.page, h))
    seen = {}
    for page, h in found:  # keep the last occurrence (TOC entries come first)
        seen[h.lower()] = (page, h)
    return sorted(seen.values())


def _body_text(page_text: str, noise: set[str] | None = None) -> str:
    """Page text without headings, TOC lines and repeated headers/footers, so they don't get glued into sentences."""
    top = re.compile(r"^(?:chapter\s+)?\d{1,2}(?:\.\d+)*[\.:]?\s+[A-Z][^.]{2,80}$", re.IGNORECASE)
    keep = []
    for l in page_text.splitlines():
        t = l.strip()
        if not t or (noise and t in noise) or DOTS.search(t) or HEADING.match(t) or top.match(t) or UNIT.match(t):
            continue
        keep.append(t)
    return " ".join(keep)


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    out = []
    for s_ in re.split(r"(?<=[.!?])\s+(?=[A-Z])", flat):
        s_ = s_.strip()
        if not 40 <= len(s_) <= 260 or s_.endswith("?") or DOTS.search(s_) or re.search(r"\bcontents\b", s_, re.IGNORECASE):
            continue
        if sum(c.isupper() for c in s_) > len(s_) * 0.5:  # shouting headers
            continue
        out.append(s_)
    return out


def _top_level(doc: models.Document, noise: set[str] | None = None) -> list[tuple[int, str]]:
    """Top-level sections: "Module 2: Forklift Inspections", "Unit One", "Chapter 3", or "7 Risk Management" (not 7.1).

    Each section starts at its first page; its title prefers a real name over "Knowledge Check", "Review" or "Summary".
    """
    noise = noise if noise is not None else _noise(doc)
    pat = re.compile(r"^(?:chapter\s+)?(\d{1,2})[\.:]?\s+([A-Z][A-Za-z ,:&/\-]{3,80})$", re.IGNORECASE)
    filler = re.compile(r"\b(knowledge check|review|summary|quiz|test|exercise|answers?|objectives)\b", re.IGNORECASE)
    occurrences: dict[tuple, list[tuple[int, str]]] = {}
    for p in doc.page_texts:
        lines = [l.strip() for l in p.text.splitlines() if l.strip() and l.strip() not in noise]
        if _is_toc(lines) or sum(1 for l in lines if pat.match(l) or UNIT.match(l)) >= 3:
            continue
        for line in lines[:8]:  # section titles sit at the top of a page
            title = _heading_text(line)
            if not title:
                continue
            title = re.sub(r":(?=\S)", ": ", title)
            u = UNIT.match(line)
            if u:
                occurrences.setdefault(("u", u.group(1).lower()), []).append((p.page, title))
                continue
            m = pat.match(line)
            if m:
                occurrences.setdefault(("n", m.group(1)), []).append((p.page, title))

    def pick(key, occ):
        first = min(pg for pg, _ in occ)
        named = [t for _, t in occ if not filler.search(t)]
        if named:
            return first, named[0]
        u = UNIT.match(occ[0][1])
        return first, (re.sub(filler, "", occ[0][1]).strip(" :-") or occ[0][1])

    units = sorted(pick(k, v) for k, v in occurrences.items() if k[0] == "u")
    return units if len(units) >= 2 else sorted(pick(k, v) for k, v in occurrences.items())


def _skills_for(title: str, vocabulary: list[str] | None) -> list[str]:
    t = title.lower()
    hits = [v for v in (vocabulary or []) if v in t or all(w in t for w in v.split())]
    return hits[:3] or [_skill_from(title)]


def _skill_from(title: str) -> str:
    words = [w for w in re.findall(r"[a-zA-Z]+", title.lower()) if w not in STOP]
    return " ".join(words[:3]) or "role knowledge"


def offline_course(doc: models.Document, role: str, vocabulary: list[str] | None = None) -> dict:
    noise = _noise(doc)
    heads = _headings(doc, noise)
    chapters = _top_level(doc, noise)
    if len(chapters) >= 3:  # numbered chapters are the natural modules
        groups = [[c] for c in chapters]
    else:
        if len(heads) < 3:  # no usable structure: even page chunks
            step = max(1, doc.pages // 8 or 1)
            heads = [(p, f"Part {i + 1} (pages {p}-{min(doc.pages, p + step - 1)})") for i, p in enumerate(range(1, doc.pages + 1, step))]
        target = max(1, -(-len(heads) // 12))
        groups = [heads[i:i + target] for i in range(0, len(heads), target)]
    modules = []
    for gi, g in enumerate(groups):
        start = 1 if gi == 0 else g[0][0]  # the first module also covers any introduction before it
        end = (groups[gi + 1][0][0] - 1) if gi + 1 < len(groups) else doc.pages
        end = max(start, end)
        text = " ".join(_body_text(p.text, noise) for p in doc.page_texts if start <= p.page <= end)
        sents = list(dict.fromkeys(_sentences(text)))  # documents repeat themselves; keep each sentence once
        sents = [x for x in sents if not re.match(r"^(this chapter|read it|see |figure|table)\b", x, re.IGNORECASE)]
        rules = [x for x in sents if RULE.search(x)][:7] or sents[:4]
        title = g[0][1] if len(g) == 1 else f"{g[0][1]} and related topics"
        if len(g) > 1 and all(h.startswith("§ ") for _, h in g):  # regulation sections: "§§ 850.20–850.24: Baseline inventory, …"
            nums = [h.split()[1] for _, h in g]
            names = [" ".join(h.split()[2:]) for _, h in g]
            title = f"§§ {nums[0]}–{nums[-1]}: " + ", ".join(names[:3]) + (", …" if len(names) > 3 else "")
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
