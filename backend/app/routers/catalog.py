"""The unified training catalog and org directory (any signed-in user)."""
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models, serialize
from ..auth import current_user
from ..database import get_db
from ..safeguards import catalog_cache

router = APIRouter(prefix="/api", tags=["catalog"], dependencies=[Depends(current_user)])


@router.get("/trainings")
def list_trainings(q: str = "", category: str = "", required: bool | None = None, delivery: str = "", source: str = "",
                   db: Session = Depends(get_db)):
    # Everyone opens the catalog at a deadline; serve the same list from memory for a minute.
    return catalog_cache.get(("trainings", q, category, required, delivery, source),
                             lambda: _list_trainings(db, q, category, required, delivery, source))


def _list_trainings(db, q, category, required, delivery, source):
    stmt = select(models.Training)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(models.Training.title.ilike(like), models.Training.code.ilike(like), models.Training.description.ilike(like)))
    if category:
        stmt = stmt.where(models.Training.category == category)
    if required is not None:
        stmt = stmt.where(models.Training.required == required)
    if delivery:
        stmt = stmt.where(models.Training.delivery == delivery)
    if source:
        stmt = stmt.where(models.Training.source_system == source)
    return [serialize.training(t, brief=True) for t in db.scalars(stmt.order_by(models.Training.code))]


@router.get("/trainings/sources")
def training_sources(db: Session = Depends(get_db)):
    """Every website trainings come from, so the catalog replaces site-hopping."""
    trainings = list(db.scalars(select(models.Training)))
    counts = Counter(t.source_system for t in trainings)
    return [{"source_system": s, "count": n} for s, n in counts.most_common()]


@router.get("/trainings/{code}")
def get_training(code: str, db: Session = Depends(get_db)):
    t = db.scalar(select(models.Training).where(models.Training.code == code))
    if t is None:
        raise HTTPException(404, "Training not found")
    return serialize.training(t)


@router.get("/divisions")
def divisions(db: Session = Depends(get_db)):
    return [{"code": d.code, "name": d.name, "parent_code": d.parent_code, "directorate": d.directorate}
            for d in db.scalars(select(models.Division).order_by(models.Division.code))]


@router.get("/positions")
def positions(open_only: bool = False, db: Session = Depends(get_db)):
    stmt = select(models.Position)
    if open_only:
        stmt = stmt.where(models.Position.is_open.is_(True))
    return [{"code": p.code, "title": p.title, "division_code": p.division_code, "level": p.level, "min_years": p.min_years,
             "required_skills": p.required_skills, "required_trainings": p.required_trainings, "prerequisites": p.prerequisites,
             "is_open": p.is_open, "fiscal_year": p.fiscal_year, "headcount": p.headcount}
            for p in db.scalars(stmt.order_by(models.Position.code))]
