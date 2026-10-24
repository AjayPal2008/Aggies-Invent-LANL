"""Fill the training library from the command line (no AI involved).

    python -m scripts.import_library            # load the library structure and import every linked public PDF
    python -m scripts.import_library --build    # also build offline lessons for trainings with materials

Only official public LANL PDFs (https://cdn.lanl.gov/files/*.pdf) are downloaded; files go to UPLOAD_DIR,
never into git. Safe to rerun: finished imports are reused, failed ones are retried.
"""
import argparse

from app.database import SessionLocal, init_db
from app.services import documents, library


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="build lessons from each training's richest material")
    a = ap.parse_args()
    init_db()
    with SessionLocal() as db:
        print("library:", library.sync_library(db))
        r = library.import_all(db)
        print(f"materials: {r['imported']} imported, {r['failed']} failed")
        for e in r["errors"]:
            print("   failed:", e["training_code"], e["title"], "-", e["error"])
        if a.build:
            from sqlalchemy import select
            from app import models

            codes = sorted({m.training_code for m in db.scalars(select(models.TrainingMaterial).where(models.TrainingMaterial.document_id.is_not(None)))})
            for code in codes:
                doc = library.primary_document(db, code)
                if doc:
                    doc.training_code = code
                    db.commit()
                    documents.build_course(db, doc.id)
                    print("   lessons built:", code)


if __name__ == "__main__":
    main()
