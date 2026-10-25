"""Expand a review topic into structured lessons using existing source passages."""
import re
from functools import lru_cache


def _tokens(text):
    ignore = {"their", "there", "these", "those", "which", "should", "about", "other", "using", "through", "source", "review", "course", "concept", "important", "understand", "understanding"}
    return {t for t in re.findall(r"[a-z]{4,}", text.lower()) if t not in ignore}


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


@lru_cache(maxsize=64)
def _source_windows(raw):
    sentences = _sentences(re.sub(r"\s+", " ", raw).strip())
    result = []
    for i in range(0, len(sentences), 3):
        passage = " ".join(sentences[i:i + 3])
        if not 180 <= len(passage) <= 2200:
            continue
        if re.search(r"https?://|retrieved \d|all rights reserved|table of contents|answer key|knowledge check", passage, re.I):
            continue
        result.append((i, passage, _tokens(passage)))
    return result


def lesson_sections(resource, points, objective=""):
    """No model-generated elaboration: every explanation remains source-grounded."""
    article = resource["data"]
    selected = points or article["key_points"][:1]
    if not selected:
        return []
    primary = {p["id"] for p in selected}
    query = _tokens(objective + " " + " ".join(p["point"] + " " + p["explanation"] for p in selected))
    result = []

    def add(sid, title, explanation, concept, kind, page=None):
        sentences = _sentences(explanation)
        result.append({"id": sid, "title": title, "explanation": explanation,
                       "paragraphs": [" ".join(sentences[i:i + 3]) for i in range(0, len(sentences), 3)],
                       "takeaways": sentences[:3], "concept_id": concept, "kind": kind,
                       "page": page})

    for p in selected:
        add(p["id"], p["point"], p["explanation"], p["id"], "Core concept", p.get("page"))

    related = [p for p in article["key_points"] if p["id"] not in primary]
    related.sort(key=lambda p: -len(query & _tokens(p["point"] + " " + p["explanation"])))
    for p in related[:3]:
        if query & _tokens(p["point"] + " " + p["explanation"]):
            add("related-" + p["id"], p["point"], p["explanation"], selected[0]["id"], "Related source concept", p.get("page"))

    # Include longer, relevant passages instead of repeating one short summary.
    # Sentence windows preserve the original source wording and coherent boundaries.
    windows = []
    for i, passage, tokens in _source_windows(resource.get("raw", "")):
        score = len(query & tokens)
        if score >= 3:
            windows.append((score, i, passage))
    windows.sort(key=lambda x: (-x[0], x[1]))
    count = max(0, 6 - len(result))
    for _, position, passage in windows:
        if count <= 0:
            break
        if any(passage in s["explanation"] or s["explanation"] in passage for s in result):
            continue
        concept = max(selected, key=lambda p: len(_tokens(p["point"] + " " + p["explanation"]) & _tokens(passage)))
        add(f"context-{position}", "Explore further: " + " ".join(concept["point"].split()[:8]).rstrip(".,:;"), passage, concept["id"], "Source context")
        count -= 1

    terms = [t for t in article.get("terms", []) if isinstance(t, dict) and query & _tokens(t.get("term", "") + " " + t.get("definition", ""))]
    if terms:
        glossary = " ".join(f"{t['term']}: {t['definition']}" for t in terms[:5] if t.get("term") and t.get("definition"))
        if glossary:
            add("glossary", "Key terms and distinctions", glossary, selected[0]["id"], "Glossary")
    return result
