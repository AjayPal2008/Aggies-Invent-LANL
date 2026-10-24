"""Extract one article (--article Ionizing_radiation) or all (--article all).

Always uses Claude-only requests with a 120-second timeout; no credential files
are accessed. AI_PROVIDER does not override extraction's explicit provider.
Long texts are split at inferred plain-text headings, then at paragraphs when a
section is oversized. PDF-to-text output does not retain explicit heading markup.
"""

import argparse
import json
from pathlib import Path
import re
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.ai_client import AIClientError, EXTRACTION_TIMEOUT_SECONDS, generate, redact_secrets
from backend.prompts import AI_SCHEMA, EXTRACTION_PROMPT, MERGE_INSTRUCTION
from scripts.validate_knowledge import KNOWLEDGE_DIR, repair, validate

RAW_DIR = ROOT / "Resource_File" / "raw_text"
CHUNK_CHARS = 12000
MERGE_CHARS = 24000
DEBUG_DIR = ROOT / "Resource_File" / "debug"
METADATA = {
    "Ionizing_radiation": ("safety", True),
    "Computer_security": ("security", True),
    "Nuclear_fission": ("technical", False),
    "Nuclear_reactor": ("technical", False),
}


class ExtractionError(RuntimeError):
    pass


def split_sections(text):
    """Keep short articles whole; pack long articles on section boundaries."""
    if len(text) <= CHUNK_CHARS:
        return [text]
    blocks = re.split(r"\n\s*\n", text.strip())
    sections, current = [], []
    for block in blocks:
        heading = ("\n" not in block and len(block) <= 100 and
                   len(block.split()) <= 12 and not re.search(r"[.!?;:]$", block))
        if heading and current:
            sections.append("\n\n".join(current))
            current = []
        current.append(block)
    if current:
        sections.append("\n\n".join(current))
    chunks, pending = [], ""
    for section in sections:
        if len(section) > CHUNK_CHARS:
            if pending:
                chunks.append(pending)
                pending = ""
            # Respect paragraph boundaries first, then split oversized paragraphs.
            for paragraph in re.split(r"\n\s*\n", section):
                pieces = textwrap.wrap(paragraph, width=CHUNK_CHARS,
                                       replace_whitespace=False, drop_whitespace=False)
                for piece in pieces:
                    if pending and len(pending) + len(piece) + 2 > CHUNK_CHARS:
                        chunks.append(pending)
                        pending = ""
                    pending += ("\n\n" if pending else "") + piece
        else:
            if pending and len(pending) + len(section) + 2 > CHUNK_CHARS:
                chunks.append(pending)
                pending = ""
            pending += ("\n\n" if pending else "") + section
    if pending:
        chunks.append(pending)
    return chunks


def report(message):
    print(redact_secrets(message), flush=True)


def save_debug(article, response, *, stage, attempt, reason, stop_reason):
    """Include section/stage and attempt; preserve existing files across runs."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    safe_article = re.sub(r"[^A-Za-z0-9_-]", "_", article)
    section = re.fullmatch(r"section (\d+)/(\d+)", stage)
    stage_name = f"section{section[1]}" if section else re.sub(r"[^A-Za-z0-9_-]", "_", stage)
    number = 1
    while True:
        suffix = "" if number == 1 else f"_run{number}"
        path = DEBUG_DIR / f"{safe_article}_{stage_name}_attempt{attempt}{suffix}.txt"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(redact_secrets(str(response)))
            break
        except FileExistsError:
            number += 1
    path.with_suffix(".json").write_text(redact_secrets(json.dumps({
        "stage": stage, "section": int(section[1]) if section else None,
        "stage_attempt": attempt, "stop_reason": stop_reason,
        "failure": reason,
    }, ensure_ascii=False, indent=2)), encoding="utf-8")
    report(f"Debug response: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


def request_knowledge(title, category, source, *, merge=False, article=None, stage="extraction"):
    prompt = AI_SCHEMA + "\n" + (MERGE_INSTRUCTION if merge else "") + EXTRACTION_PROMPT.format(
        title=title, category=category, article_text=source)
    limit = 4096
    for attempt in range(2):
        response = generate(prompt, provider="claude", timeout=EXTRACTION_TIMEOUT_SECONDS, max_tokens=limit)
        stop_reason = getattr(response, "stop_reason", None)
        errors = []
        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"\A```(?:json)?\s*\n?", "", cleaned, flags=re.I)
                cleaned = re.sub(r"\s*```\Z", "", cleaned)
            data = json.loads(cleaned)
            # Keep the original raw response for debugging even if repair succeeds.
            original_errors = validate(data, metadata=False)
            for change in repair(data):
                report(f"{stage}: {change}")
            errors = validate(data, metadata=False)
            if stop_reason == "max_tokens":
                errors.append("Response cut off: stop_reason=max_tokens")
            if original_errors or errors:
                reasons = "; ".join(dict.fromkeys(original_errors + errors))
                report(f"{stage} attempt {attempt + 1}: stop_reason={stop_reason or 'unknown'}; {reasons}")
                save_debug(article or title.replace(" ", "_"), response, stage=stage,
                           attempt=attempt + 1, reason=reasons, stop_reason=stop_reason)
            if not errors:
                # Only the AI-owned schema fields may cross the metadata boundary.
                return {k: data[k] for k in ("summary", "difficulty", "key_points", "terms", "relationships", "common_misconceptions")}
        except (ValueError, TypeError, RecursionError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                reason = f"JSON parse error: {exc.msg}; line {exc.lineno}, column {exc.colno}, position {exc.pos}"
            else:
                reason = f"JSON processing error: {type(exc).__name__}"
            errors = [reason]
            report(f"{stage} attempt {attempt + 1}: stop_reason={stop_reason or 'unknown'}; {reason}")
            save_debug(article or title.replace(" ", "_"), response, stage=stage,
                       attempt=attempt + 1, reason=reason, stop_reason=stop_reason)
        if stop_reason == "max_tokens":
            limit = 8000
            prompt += "\nThe response was truncated. Use brief one-sentence explanations (at most 25 words), short definitions (at most 15 words), and concise statements. Complete the JSON within the output budget."
        if attempt == 0:
            prompt += "\nCorrect these validation issues: " + redact_secrets("; ".join(errors))
    raise ExtractionError(f"{stage}: invalid after two attempts; see debug responses.")


def merge_results(results, title, category, *, article=None):
    """Bound merge requests using hierarchical groups; retain section provenance."""
    round_number = 0
    while len(results) > 1:
        round_number += 1
        groups, group, size = [], [], 0
        for result in results:
            length = len(json.dumps(result, ensure_ascii=False))
            if length > MERGE_CHARS:
                raise ExtractionError("A section result exceeds the merge size limit.")
            if group and size + length > MERGE_CHARS:
                groups.append(group)
                group, size = [], 0
            group.append(result)
            size += length + 30
        if group:
            groups.append(group)
        if len(groups) == len(results):
            raise ExtractionError("Section results are too large to merge within the size limit.")
        next_results = []
        for index, group in enumerate(groups, 1):
            report(f"{article or title}: merging group {index}/{len(groups)} ({len(group)} results)")
            next_results.append(group[0] if len(group) == 1 else request_knowledge(
                title, category, json.dumps({"sections": group}, ensure_ascii=False),
                merge=True, article=article, stage=f"merge_round{round_number}_group{index}"))
        results = next_results
    return results[0]


def deterministic_merge(results):
    """Select existing facts without inventing content when AI merge fails."""
    combined = {"summary": results[0]["summary"], "difficulty": results[0]["difficulty"],
                "key_points": [], "terms": [], "relationships": [], "common_misconceptions": []}
    for index, result in enumerate(results):
        prefix = f"section{index}_"
        combined["key_points"].extend({**p, "id": prefix + p["id"]} for p in result["key_points"])
        combined["relationships"].extend({**r, "from": prefix + r["from"], "to": prefix + r["to"]}
                                         for r in result["relationships"])
        combined["terms"].extend(result["terms"])
        combined["common_misconceptions"].extend(result["common_misconceptions"])
    repair(combined)
    combined["terms"] = combined["terms"][:10]
    combined["common_misconceptions"] = list(dict.fromkeys(combined["common_misconceptions"]))[:3]
    return combined


def extract_article(stem, raw_dir=RAW_DIR, output_dir=KNOWLEDGE_DIR):
    category, required = METADATA[stem]
    title = stem.replace("_", " ")
    text = (raw_dir / f"{stem}.txt").read_text(encoding="utf-8")
    if not text.strip():
        raise ExtractionError("Source article is empty.")
    chunks = split_sections(text)
    results, failed_sections = [], []
    for index, chunk in enumerate(chunks, 1):
        report(f"{stem}: section {index}/{len(chunks)} ({len(chunk):,} characters)")
        try:
            results.append(request_knowledge(title, category, chunk, article=stem,
                                             stage=f"section {index}/{len(chunks)}"))
            report(f"{stem}: section {index}/{len(chunks)} complete")
        except (AIClientError, ExtractionError) as exc:
            failed_sections.append(index)
            report(f"{stem}: section {index}/{len(chunks)} FAILED: {exc}; continuing")
    if not results:
        raise ExtractionError("No sections succeeded; existing output preserved. See progress/debug diagnostics.")
    merge_fallback = False
    try:
        result = merge_results(results, title, category, article=stem)
    except (AIClientError, ExtractionError) as exc:
        report(f"{stem}: AI merge failed: {exc}; selecting existing facts deterministically")
        result = deterministic_merge(results)
        merge_fallback = True
    article = {
        "id": stem.replace("_", "-").lower(), "title": title,
        "category": category, "required": required,
        "source": {"name": "Wikipedia", "url": f"https://en.wikipedia.org/wiki/{stem}",
                   "license": "CC BY-SA 4.0"}, **result,
    }
    article["extraction_status"] = {"partial": bool(failed_sections), "failed_sections": failed_sections,
                                    "total_sections": len(chunks), "merge_fallback": merge_fallback}
    errors = validate(article)
    if errors:
        raise ExtractionError(redact_secrets("Final validation failed: " + "; ".join(errors)))
    output_dir.mkdir(parents=True, exist_ok=True)
    # Replace only after every extraction/merge/validation step has succeeded.
    output = output_dir / f"{stem}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(article, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    report(f"{stem}: {len(results)}/{len(chunks)} sections succeeded, {len(article['key_points'])} key points, {len(article['terms'])} terms -> {output.name}" + (" (PARTIAL)" if failed_sections else ""))
    return article


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--article", choices=["all", *METADATA], default="all")
    args = parser.parse_args()
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    articles = list(METADATA) if args.article == "all" else [args.article]
    failed = 0
    for stem in articles:
        try:
            extract_article(stem)
        except (AIClientError, ExtractionError) as exc:
            failed += 1
            print(f"FAIL {stem}: {exc}", file=sys.stderr)
        except (OSError, UnicodeError):
            failed += 1
            print(f"FAIL {stem}: Cannot read input or write output.", file=sys.stderr)
    print(f"Summary: {len(articles) - failed} succeeded, {failed} failed.")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
