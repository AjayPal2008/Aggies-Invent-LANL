"""Fill the training library from the command line.

    python -m scripts.import_library             # load the library, download every public source, import the shared
                                                 # folder (Resource_File/library) and build lessons for new materials
    python -m scripts.import_library --no-build  # skip building lessons
    python -m scripts.import_library --ai        # build lessons with Claude (needs ANTHROPIC_API_KEY; costs tokens)
    python -m scripts.import_library --ai --only UT-62676 COM-320   # rebuild just these drafts with Claude

Only official public sources are downloaded (LANL, DOE, govinfo, OPM and the DOE computing centers' docs); files go
to UPLOAD_DIR, never into git. Safe to rerun: finished imports are reused, failed ones are retried. Built lessons
start as drafts that an admin reviews and publishes in the Training library.
"""
import argparse

from app.database import SessionLocal, init_db
from app.services import library


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="don't build lessons for newly imported materials")
    ap.add_argument("--ai", action="store_true", help="build lessons with Claude instead of the offline builder")
    ap.add_argument("--rebuild-drafts", action="store_true", help="rebuild lessons that are still drafts (never published ones)")
    ap.add_argument("--only", nargs="+", metavar="CODE", help="only (re)build these trainings' draft lessons")
    a = ap.parse_args()
    init_db()
    if a.ai:
        from app.services import ai

        if not ai.ai_enabled():
            raise SystemExit("--ai needs ANTHROPIC_API_KEY in .env (then restart: docker compose up -d --force-recreate app reports)")
    if a.only:
        with SessionLocal() as db:
            b = library.build_missing(db, use_ai=a.ai, codes=a.only, rebuild_drafts=True)
            _report(db, a.only, b)
        return
    with SessionLocal() as db:
        print("library:", library.sync_library(db))
        db.commit()
        f = library.import_folder(db)
        print(f"shared folder ({library.library_root()}): {f['imported']} imported, {f['skipped']} already there, "
              f"{f['failed']} failed, {f['unassigned']} waiting to be placed")
        for e in f["errors"]:
            print("   failed:", e["file"], "-", e["error"])
        print("downloading public sources (this can take a few minutes)…", flush=True)
        r = library.import_all(db)
        print(f"public sources: {r['imported']} imported, {r['failed']} failed")
        for e in r["errors"]:
            print("   failed:", e["training_code"], e["title"], "-", e["error"])
        if not a.no_build:
            b = library.build_missing(db, use_ai=a.ai, rebuild_drafts=a.rebuild_drafts)
            print(f"lessons built: {len(b['built'])} trainings (drafts until an admin publishes them)"
                  + (f", {len(b['failed'])} failed: {', '.join(b['failed'])}" if b["failed"] else ""))


def _report(db, codes, b):
    from app import models

    for code in codes:
        t = db.query(models.Training).filter_by(code=code).one_or_none()
        if t is None:
            print(f"   {code}: no such training")
            continue
        doc = db.get(models.Document, t.document_id) if t.document_id else None
        n = db.query(models.CourseModule).filter_by(training_id=t.id).count()
        who = "Claude" if doc and doc.generated_by not in ("", "offline", None) else "offline builder"
        status = "built" if code in b["built"] else "failed" if code in b["failed"] else "skipped (published, or no material)"
        print(f"   {code} {t.title}: {status}, {n} modules by {who}" + (f" ({doc.error})" if doc and doc.error else ""))


if __name__ == "__main__":
    main()
