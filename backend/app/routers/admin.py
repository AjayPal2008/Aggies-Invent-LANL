"""Data integration: run syncs, check connectors, upload exports."""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..auth import require_admin
from ..config import settings
from ..connectors import all_connectors
from ..connectors.base import ConnectorError
from ..database import get_db
from ..database import engine
from ..safeguards import ai_guard, catalog_cache, metrics
from ..services import sync

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

UPLOADABLE = {"divisions", "positions", "trainings", "training_sessions", "employees", "training_history", "mapping"}


@router.get("/connectors")
def connectors():
    return {"modes": {"directory": settings.directory_mode, "utrain": settings.utrain_mode, "oracle_hr": settings.oracle_mode},
            "data_dir": settings.data_dir, "health": [c.health() for c in all_connectors()]}


@router.post("/sync")
def run_sync(source: str = "all", db: Session = Depends(get_db)):
    fns = {"all": sync.sync_all, "directory": sync.sync_directory, "utrain": sync.sync_trainings, "oracle_hr": sync.sync_employees}
    if source not in fns:
        raise HTTPException(400, f"source must be one of {', '.join(fns)}")
    try:
        result = fns[source](db)
        catalog_cache.clear()
        return result
    except ConnectorError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))


@router.get("/sync-runs")
def sync_runs(db: Session = Depends(get_db)):
    return [{"source": r.source, "started_at": r.started_at.isoformat(), "created": r.created, "updated": r.updated,
             "errors": r.errors[:20]} for r in db.scalars(select(models.SyncRun).order_by(models.SyncRun.id.desc()).limit(50))]


@router.post("/upload/{entity}")
async def upload(entity: str, file: UploadFile = File(...)):
    """Drop in a CSV/JSON export (e.g. trainings_nucleus.csv for another training site)."""
    stem = entity if entity in UPLOADABLE or entity.startswith("trainings_") else None
    if stem is None:
        raise HTTPException(400, f"entity must be one of {', '.join(sorted(UPLOADABLE))} or trainings_<site>")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".json"}:
        raise HTTPException(400, "Upload a .csv or .json file")
    dest = Path(settings.data_dir) / f"{stem}{suffix}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    return {"saved": str(dest), "next": "POST /api/admin/sync to load it"}


@router.get("/metrics")
def get_metrics():
    """This worker's traffic, latency, AI and cache numbers. Each worker reports its own."""
    import os

    pool = engine.pool
    return {**metrics.snapshot(), "worker_pid": os.getpid(), "ai": ai_guard.state(),
            "db_pool": {"status": pool.status()} if hasattr(pool, "status") else {}}
