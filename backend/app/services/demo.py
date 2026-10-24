"""Load the sample role documents (DATA_DIR/documents/documents.json) on a fresh database,
build their courses, and save a role plan, so the demo works without uploading anything."""
import json
import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from . import documents, roles

log = logging.getLogger(__name__)


def load_demo_documents(db: Session) -> int:
    folder = Path(settings.data_dir) / "documents"
    manifest = folder / "documents.json"
    if not manifest.exists() or db.scalar(select(models.Document.id)):
        return 0
    store = Path(settings.upload_dir) / "documents"
    store.mkdir(parents=True, exist_ok=True)
    loaded = 0
    for item in json.loads(manifest.read_text()):
        src = folder / item["file"]
        if not src.exists():
            continue
        dest = store / f"{uuid.uuid4().hex}{src.suffix}"
        shutil.copy(src, dest)
        doc = documents.save_document(db, dest, item["title"], item["kind"], item.get("position_code"), None)
        doc.filename, doc.analysis = src.name, {"stored_as": dest.name}
        db.commit()
        if item["kind"] in ("manual", "policy", "procedure", "handbook"):
            documents.build_course(db, doc.id)
        loaded += 1
    for code in {i.get("position_code") for i in json.loads(manifest.read_text()) if i.get("position_code")}:
        pos = db.scalar(select(models.Position).where(models.Position.code == code))
        if pos and not roles.get_plan(db, pos):
            roles.save_plan(db, pos, roles.default_plan(db, pos))
    db.commit()
    log.info("Loaded %d demo documents", loaded)
    return loaded
