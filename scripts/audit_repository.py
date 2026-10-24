"""Inventory consolidation provenance and run limited, value-suppressing checks.

Never opens credential files, installed dependencies, caches, logs or databases.
This pattern scan is not a complete secret audit or a factual content review.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT.parent / "Aggies-Invent-UI"
SKIP = {".git", ".venv", "venv", ".python-packages", "node_modules", "__pycache__", ".pytest_cache", "dist", ".aws", ".ssh", "secrets"}


def git(*args, folder=ROOT):
    return subprocess.check_output(["git", "-C", str(folder), *args], text=True).strip().splitlines()


def private(path):
    parts = path.parts
    return (any(p in SKIP for p in parts) or path.name.startswith(".env") or
            path.name.lower() in ("credentials", "credentials.json", "id_rsa", "id_ed25519") or
            path.suffix.lower() in (".pem", ".key", ".pfx", ".p12") or
            any(p in ("cache", "debug", "uploads", "live") for p in parts) or
            path.suffix in (".db", ".sqlite", ".sqlite3", ".log", ".pyc") or
            re.search(r"\.(?:db|sqlite3?)-", path.name) is not None or
            any(p.startswith("scale") for p in parts))


def walk(folder):
    for path in folder.iterdir():
        relative = path.relative_to(ROOT)
        if private(relative):
            continue
        if path.is_dir():
            yield from walk(path)
        elif path.is_file():
            yield path


def main():
    baseline = git("ls-tree", "-r", "--name-only", "48e4190")
    original = git("ls-tree", "-r", "--name-only", "45803a8")
    upstream = git("ls-files", folder=UI)
    rows = []
    exclusions = {
        ".env.example": "Credential template not read/copied; new empty/placeholder-only template authored locally.",
        ".gitignore": "Combined with existing root rules; added live-data, scale-data, database and runtime exclusions.",
        ".dockerignore": "Excluded: no Docker deployment verified; preserve via source commit.",
        "Dockerfile": "Excluded: original deployment omits integrated resources/persistence and is not the verified startup.",
        "docker-compose.yml": "Excluded: original multi-replica deployment is outside the verified single-host SQLite diagnostic scope.",
        "render.yaml": "Excluded: cloud deployment is not configured/verified in this consolidation.",
        "deploy/nginx.conf.template": "Excluded with original Docker deployment; no alternate app root introduced.",
        "Ionizing_radiation.json": "Excluded duplicate/empty upstream root artifact; canonical populated JSON is under Resource_File/sample, gk info/extracted_knowledge/.",
        "Ionizing_radiation.pdf": "Combined with the existing Resource_File/sample, gk info/Ionizing_radiation.pdf; compare hashes below.",
    }
    for name in upstream:
        if name in exclusions:
            rows.append({"source": "ui", "path": name, "disposition": exclusions[name]})
            continue
        target = ("docs/UI_ORIGINAL_README.md" if name == "README.md" else
                  "docs/upstream/" + Path(name).name if name.startswith("docs/") else name)
        src, dst = UI / name, ROOT / target
        if not dst.is_file():
            raise SystemExit(f"Unaccounted upstream file: {name}")
        same = src.read_bytes() == dst.read_bytes()
        rows.append({"source": "ui", "path": name, "target": target,
                     "disposition": "identical" if same else "deliberately combined/adapted; see integration report",
                     "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest()})
    for name in original:
        if not (ROOT / name).is_file():
            raise SystemExit(f"Original backend asset missing: {name}")
        rows.append({"source": "backend-45803a8", "path": name, "target": name,
                     "disposition": "retained (root ignore rules combined)"})
    pdf_equal = ((UI / "Ionizing_radiation.pdf").read_bytes() == (ROOT / "Resource_File/sample, gk info/Ionizing_radiation.pdf").read_bytes())
    if not pdf_equal:
        raise SystemExit("Upstream duplicate PDF differs; resolve explicitly before publishing")
    files = sorted(walk(ROOT))
    patterns = {
        "Anthropic-shaped credential": re.compile(r"sk-ant-[A-Za-z0-9_-]{24,}"),
        "GitHub-shaped credential": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
        "JWT-shaped token": re.compile(r"eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),
        "private-key material": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s+[A-Za-z0-9+/=]{30,}"),
    }
    findings, leaks = [], []
    text_suffixes = {".py", ".js", ".json", ".txt", ".md", ".css", ".html", ".svg", ".yml", ".yaml", ".code-workspace"}
    for path in files:
        if path.suffix not in text_suffixes:
            continue
        content = path.read_text(encoding="utf-8")
        name = path.relative_to(ROOT).as_posix()
        for kind, pattern in patterns.items():
            if pattern.search(content):
                findings.append({"file": name, "kind": kind})  # Never output matched values.
        if path.relative_to(ROOT).parts[0] in ("hire-dashboard", "manager-dashboard", "shared"):
            if re.search(r"\b(?:answer_index|correct_option_id|correct_answer_id)\b|\bc\.correct\b", content):
                leaks.append(name)
    for path in (ROOT / "dist").rglob("*") if (ROOT / "dist").exists() else []:
        if path.is_file() and path.suffix in (".py", ".json", ".sqlite3", ".db"):
            leaks.append(path.relative_to(ROOT).as_posix())
        elif path.is_file() and path.suffix in (".js", ".html"):
            if re.search(r"\b(?:answer_index|correct_option_id|correct_answer_id)\b|\bc\.correct\b", path.read_text(encoding="utf-8")):
                leaks.append(path.relative_to(ROOT).as_posix())
    report = {"backend_source": "45803a8", "ui_source": "cf16ec04f2e8cbce5df6a71c17966e858c4c813e",
              "integration_baseline": "48e4190", "baseline_tracked_files": baseline,
              "original_backend_files": original, "upstream_dispositions": rows,
              "relevant_local_files": [p.relative_to(ROOT).as_posix() for p in files
                                       if p.name != "Aggies-Invent.code-workspace"],
              "preserved_local_workspace": "Aggies-Invent.code-workspace (ignored, unchanged)",
              "placeholder_template": ".env.example: newly authored placeholders only; excluded from content scanning by credential-path rule",
              "duplicate_pdf_identical": pdf_equal, "secret_pattern_findings": findings,
              "frontend_answer_key_findings": leaks,
              "scan_limit": "Limited high-confidence patterns only; credential files excluded; not a comprehensive secret or factual audit."}
    (ROOT / "docs/REPOSITORY_FILE_INVENTORY.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Inventory: {len(baseline)} baseline tracked files; {len(upstream)} upstream files accounted for.")
    print(f"Secret-pattern findings: {len(findings)}; frontend key/grading findings: {len(leaks)}. Values suppressed.")
    for finding in findings:
        print(f"REVIEW {finding['file']}: {finding['kind']}")
    for name in leaks:
        print(f"REVIEW frontend: {name}")
    return int(bool(findings or leaks))


if __name__ == "__main__":
    raise SystemExit(main())
