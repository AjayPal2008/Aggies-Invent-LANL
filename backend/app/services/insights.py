"""Aggregates for leadership: where knowledge is weak, and who is out of compliance."""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from .adaptive import assignment_flags, get_mastery
from .loader import positions as all_positions


def gap_heatmap(db: Session, people: list[models.Employee], group_by: str = "position") -> dict:
    """Average mastery of required skills, grouped by role (or equipment).

    Rows are roles (or equipment), columns are skills, cells are average mastery 0-1
    across people in that group. Low cells are where training should focus.
    """
    positions = all_positions(db)
    cells: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    counts: dict[str, int] = defaultdict(int)

    for e in people:
        mastery = get_mastery(db, e)
        known = lambda s: mastery.get(s, (e.skills or {}).get(s, 0.0))  # noqa: E731
        if group_by == "equipment":
            for a in e.assignments:
                for eq in a.training.equipment or []:
                    counts[eq] += 1
                    for s in a.training.skills or []:
                        cells[eq][s].append(known(s))
        else:
            pos = positions.get(e.position_code or "")
            if not pos:
                continue
            key = f"{pos.title} ({pos.code})"
            counts[key] += 1
            for s in pos.required_skills or []:
                cells[key][s].append(known(s))

    skills = sorted({s for row in cells.values() for s in row})
    rows = []
    for key in sorted(cells):
        values = {s: round(mean(v), 2) for s, v in cells[key].items()}
        rows.append({"group": key, "people": counts[key], "cells": values,
                     "weakest": sorted(values, key=values.get)[:3]})
    rows.sort(key=lambda r: mean(r["cells"].values()) if r["cells"] else 1)
    return {"group_by": group_by, "skills": skills, "rows": rows}


def compliance_by_division(db: Session, people: list[models.Employee]) -> list[dict]:
    """Share of required trainings that are complete and current, per division."""
    names = {d.code: d.name for d in db.scalars(select(models.Division))}
    stats: dict[str, dict] = defaultdict(lambda: {"required": 0, "current": 0, "overdue": 0, "expired": 0, "people": set(),
                                                  "safety_required": 0, "safety_current": 0})
    for e in people:
        for a in e.assignments:
            if not a.training.required:
                continue
            f = assignment_flags(a)
            s = stats[e.division_code]
            s["people"].add(e.id)
            s["required"] += 1
            ok = a.status == "completed" and not f["needs_retake"]
            s["current"] += 1 if ok else 0
            s["overdue"] += 1 if f["overdue"] else 0
            s["expired"] += 1 if f["expired"] else 0
            if a.training.category == "safety":
                s["safety_required"] += 1
                s["safety_current"] += 1 if ok else 0
    out = []
    for code, s in stats.items():
        out.append({
            "division_code": code, "division_name": names.get(code, code), "people": len(s["people"]),
            "required_assignments": s["required"], "compliant": s["current"], "overdue": s["overdue"], "expired": s["expired"],
            "compliance_rate": round(100 * s["current"] / s["required"], 1) if s["required"] else 100.0,
            "safety_compliance_rate": round(100 * s["safety_current"] / s["safety_required"], 1) if s["safety_required"] else 100.0,
        })
    return sorted(out, key=lambda r: r["compliance_rate"])
