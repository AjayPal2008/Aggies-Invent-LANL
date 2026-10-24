"""Validate all knowledge JSON files: python scripts/validate_knowledge.py."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.ai_client import redact_secrets
KNOWLEDGE_DIR = ROOT / "Resource_File" / "extracted_knowledge"
AI_FIELDS = {"summary", "difficulty", "key_points", "terms", "relationships", "common_misconceptions"}


def repair(data):
    """Repair small structural issues in place; return human-readable changes.

    Does not invent missing content. Ambiguous duplicate IDs remain errors.
    """
    changes = []
    if not isinstance(data, dict):
        return changes
    points = data.get("key_points")
    if isinstance(points, list):
        for index, point in enumerate(points):
            if isinstance(point, dict) and isinstance(point.get("importance"), str):
                value = point["importance"].strip()
                # Exact integer spellings only; never infer labels, missing
                # ratings, decimals, booleans, or ranges.
                if value in ("1", "2", "3"):
                    point["importance"] = int(value)
                    changes.append(f"Normalized key_points[{index}].importance numeric string to integer {value}")
    if isinstance(points, list) and all(isinstance(p, dict) and isinstance(p.get("id"), str)
            and all(isinstance(p.get(k), str) and p[k].strip() for k in ("id", "point", "explanation"))
            and type(p.get("importance")) is int and p["importance"] in (1, 2, 3) for p in points):
        old_ids = [p["id"] for p in points]
        if len(set(old_ids)) == len(old_ids):
            ordered = sorted(points, key=lambda p: p["importance"], reverse=True)
            selected, seen, remap = [], set(), {}
            for point in ordered:
                signature = " ".join(str(point.get("point", "")).casefold().split()).rstrip(".!?")
                if signature in seen:
                    continue
                seen.add(signature)
                if len(selected) < 8:
                    new_id = f"kp{len(selected) + 1}"
                    remap[point["id"]] = new_id
                    selected.append({**point, "id": new_id})
            data["key_points"] = selected
            if selected != points:
                changes.append(f"Sorted/deduplicated key points and retained top {len(selected)} of {len(points)}; renumbered IDs")
            relationships = data.get("relationships")
            if isinstance(relationships, list):
                fixed = []
                for i, relationship in enumerate(relationships):
                    if isinstance(relationship, dict) and all(isinstance(relationship.get(k), str)
                            and relationship[k].strip() for k in ("from", "to", "label")):
                        missing = [relationship[k] for k in ("from", "to") if relationship[k] not in remap]
                        if missing:
                            changes.append(f"Dropped relationships[{i}]: missing key point IDs {missing!r}")
                            continue
                        relationship = {**relationship, "from": remap[relationship["from"]], "to": remap[relationship["to"]]}
                    fixed.append(relationship)
                data["relationships"] = fixed
    terms = data.get("terms")
    if isinstance(terms, list):
        distinct, seen = [], set()
        for term in terms:
            if isinstance(term, dict) and all(isinstance(term.get(k), str) and term[k].strip()
                                              for k in ("term", "definition")):
                signature = " ".join(term["term"].casefold().split())
                if signature in seen:
                    continue
                seen.add(signature)
            distinct.append(term)
        if len(distinct) != len(terms):
            changes.append(f"Deduplicated terms: {len(terms)} -> {len(distinct)}")
            data["terms"] = distinct
    return changes


def validate(data, *, metadata=True):
    """Return errors without echoing document contents or provider responses."""
    errors = []
    if not isinstance(data, dict):
        return ["Root must be an object"]
    fields = AI_FIELDS | ({"id", "title", "category", "required", "source"} if metadata else set())
    for field in sorted(fields - data.keys()):
        errors.append(f"Missing field: {field}")

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    for field in ("summary", "difficulty") + (("id", "title", "category") if metadata else ()):
        if not nonempty(data.get(field)):
            errors.append(f"{field} must be a nonempty string")
    if metadata:
        if type(data.get("required")) is not bool:
            errors.append("required must be boolean")
        source = data.get("source")
        if not isinstance(source, dict) or not all(nonempty(source.get(k)) for k in ("name", "url", "license")):
            errors.append("source must contain name, url, and license strings")
    points = data.get("key_points")
    ids = set()
    if not isinstance(points, list) or not 5 <= len(points) <= 8:
        errors.append(f"key_points must contain 5 to 8 entries (got {len(points) if isinstance(points, list) else 'non-array'})")
    if isinstance(points, list):
        importances = []
        normalized = set()
        for index, point in enumerate(points):
            if not isinstance(point, dict) or not all(nonempty(point.get(k)) for k in ("id", "point", "explanation")):
                missing = [k for k in ("id", "point", "explanation") if not isinstance(point, dict) or not nonempty(point.get(k))]
                errors.append(f"key_points[{index}] missing/invalid fields: {', '.join(missing)}")
                continue
            if point["id"] in ids:
                errors.append("Duplicate key point ID")
            ids.add(point["id"])
            signature = " ".join(point["point"].casefold().split()).rstrip(".!?")
            if signature in normalized:
                errors.append("Duplicate key point statement")
            normalized.add(signature)
            importance = point.get("importance")
            if type(importance) is not int or importance not in (1, 2, 3):
                actual = "missing" if "importance" not in point else f"{importance!r} ({type(importance).__name__})"
                errors.append(f"key_points[{index}].importance must be an integer from 1 to 3 (got {actual})")
            else:
                importances.append(importance)
        if importances != sorted(importances, reverse=True):
            errors.append("Key points must be ordered by importance")
        if ids != {f"kp{i}" for i in range(1, len(points) + 1)}:
            errors.append("Key point IDs must be sequential kp1, kp2, ...")
    terms = data.get("terms")
    if not isinstance(terms, list) or not 5 <= len(terms) <= 10:
        errors.append(f"terms must contain 5 to 10 entries (got {len(terms) if isinstance(terms, list) else 'non-array'})")
    if isinstance(terms, list):
        seen = set()
        for index, term in enumerate(terms):
            if not isinstance(term, dict) or not all(nonempty(term.get(k)) for k in ("term", "definition")):
                missing = [k for k in ("term", "definition") if not isinstance(term, dict) or not nonempty(term.get(k))]
                errors.append(f"terms[{index}] missing/invalid fields: {', '.join(missing)}")
                continue
            name = " ".join(term["term"].casefold().split())
            if name in seen:
                errors.append("Duplicate term")
            seen.add(name)
    relationships = data.get("relationships")
    if not isinstance(relationships, list):
        errors.append("relationships must be an array")
    else:
        for index, relationship in enumerate(relationships):
            if not isinstance(relationship, dict) or not all(nonempty(relationship.get(k)) for k in ("from", "to", "label")):
                errors.append("Invalid relationship fields")
            elif relationship["from"] not in ids or relationship["to"] not in ids:
                missing = [relationship[k] for k in ("from", "to") if relationship[k] not in ids]
                errors.append(f"relationships[{index}] references missing key point IDs: {missing!r}")
    misconceptions = data.get("common_misconceptions")
    if not isinstance(misconceptions, list) or len(misconceptions) > 3 or not all(nonempty(x) for x in misconceptions):
        errors.append("common_misconceptions must contain 0 to 3 nonempty strings")
        if isinstance(misconceptions, list):
            for index, value in enumerate(misconceptions):
                if not nonempty(value):
                    errors.append(f"common_misconceptions[{index}] must be a nonempty string (got {type(value).__name__})")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=KNOWLEDGE_DIR)
    args = parser.parse_args()
    files = sorted(args.folder.rglob("*.json"))
    if not files:
        print("No knowledge JSON files found; nothing validated.")
        return 1
    failed = 0
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for change in repair(data):
                print(redact_secrets(f"REPAIRED {path.name}: {change}"))
            errors = validate(data)
        except json.JSONDecodeError as exc:
            errors = [f"JSON parse error: {exc.msg}; line {exc.lineno}, column {exc.colno}, position {exc.pos}"]
        except (OSError, UnicodeError, ValueError, RecursionError):
            errors = ["Cannot read or parse JSON"]
        if errors:
            failed += 1
            print(redact_secrets(f"FAIL {path.name}: {'; '.join(errors)}"))
        else:
            print(f"OK {path.name}")
    print(f"Validated {len(files)} files: {len(files) - failed} passed, {failed} failed.")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
