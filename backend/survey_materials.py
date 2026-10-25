"""Source excerpts from local Survey & Materials PDFs, with no AI or invented facts."""
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "Resource_File" / "Survey & Materials" / "documents"
CACHE = ROOT / "Resource_File" / "cache" / "survey_materials"
log = logging.getLogger(__name__)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _title(first_page, fallback):
    text = re.sub(r"\s+", " ", first_page).strip()
    text = re.sub(r"^(?:\d+\s+)?(?:Operated|Managed) by .*?for the NNSA\s*", "", text, flags=re.I)
    text = re.sub(r"^\d+\s+", "", text)
    text = re.split(r"SAMPLE DOCUMENT|STUDENT MANUAL|Participant Guide|Live\s*#?\d|LIVE COURSE|COURSE\s*#|Course #|Test\s*#?\d|November 20|December 20", text, flags=re.I)[0]
    if text.startswith("LA-UR-") and "Title:" in text:
        text = text.split("Title:", 1)[1].split("Author", 1)[0]
    return text.strip(" :,-")[:150] or fallback


def extract_pdf(path):
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = [(page.extract_text() or "").replace("\x00", "") for page in reader.pages]
    title = _title(pages[0] if pages else "", path.stem)
    candidates = []
    seen = set()
    for page_no, page in enumerate(pages, 1):
        if page_no < 3:
            continue
        # Retain page boundaries for citations. Only complete declarative passages
        # are candidates; prompts, exercises, contents pages and answers are excluded.
        if re.search(r"table of contents|answer key|knowledge check|learning check|review questions", page, re.I):
            continue
        clean = re.sub(r"\s+", " ", page).strip()
        for sentence in re.split(r"(?<=[.!])\s+(?=[A-Z])", clean):
            if not 100 <= len(sentence) <= 650 or "?" in sentence:
                continue
            if not re.search(r"\b(is|are|means|refers to|defined as|consists of|includes)\b", sentence, re.I):
                continue
            if re.search(r"\b(instructor|quiz|test question|learning objective|copyright|www\.|https?:|page \d)\b", sentence, re.I):
                continue
            if len(re.findall(r"[A-Za-z]{3,}", sentence)) < 15:
                continue
            normalized = sentence.casefold()
            if normalized not in seen:
                seen.add(normalized)
                candidates.append((sentence, page_no))
    if not candidates:
        raise ValueError("No usable declarative passages; OCR or manual extraction is needed")
    count = min(8, len(candidates))
    selected = [candidates[round(i * (len(candidates) - 1) / max(1, count - 1))] for i in range(count)]
    points = [{"id": f"kp{i}", "point": " ".join(text.split()[:9]).rstrip(".,:;") + "…",
               "explanation": text, "importance": 2, "page": page}
              for i, (text, page) in enumerate(selected, 1)]
    article = {"id": "survey-" + path.stem, "title": title, "category": "technical",
               "summary": f"Source-based review excerpts from {title}.", "difficulty": "beginner",
               "source": {"name": f"{title} ({path.name})", "url": "", "license": "Source document; see original for usage terms"},
               "key_points": points, "terms": [], "relationships": [], "common_misconceptions": [],
               "document": path.name, "page_count": len(pages)}
    raw = "\n\n".join(pages)
    return {"data": article, "raw": raw, "fingerprint": _fingerprint({"data": article, "raw": raw})}


@lru_cache(maxsize=128)
def _load_pdf(filename, size, mtime):
    path = DOCUMENTS / filename
    cache = CACHE / (_fingerprint([filename, size, mtime, 1]) + ".json")
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    try:
        resource = extract_pdf(path)
    except ValueError as exc:
        log.warning("Skipping PDF %s: %s", filename, exc)
        resource = None
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        # Runtime mounts can be read-only; parsing still works without a cache.
        cache.write_text(json.dumps(resource, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return resource


def material_resources():
    result = {}
    for path in sorted(DOCUMENTS.glob("*.pdf")):
        try:
            stat = path.stat()
            resource = _load_pdf(path.name, stat.st_size, stat.st_mtime_ns)
            if resource is not None:
                result[resource["data"]["id"]] = resource
        except Exception as exc:
            log.warning("Cannot extract Survey & Materials PDF %s: %s", path.name, exc)
    return result


def material_courses():
    from backend.lesson_sections import lesson_sections
    return [{"id": aid, "title": r["data"]["title"], "article_id": aid, "importance": 2,
             "objective": r["data"]["summary"], "observed_gap": "Optional source-based topic; no diagnostic gap has been assessed.",
             "recommended_review": "Review the cited passages, practice each concept, then complete the topic quiz.",
             "status": "not_started", "source_excerpt": r["data"]["key_points"][0]["explanation"],
             "attribution": r["data"]["source"], "key_points": r["data"]["key_points"],
             "learning_sections": lesson_sections(r, r["data"]["key_points"]),
             "origin": "survey-materials", "progress_session": "materials", "document": r["data"]["document"]}
            for aid, r in material_resources().items()]
