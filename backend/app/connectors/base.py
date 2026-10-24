"""Shared connector plumbing.

Every connector returns plain dicts with the platform's canonical field names.
Real exports rarely use our column names, so each connector has an alias table
and also honours an optional `mapping.json` in the data directory:

    {"employees": {"Emp_No": "employee_number", "Work Email": "email"}}
"""
from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..config import settings

LIST_SEP = ";"


class ConnectorError(RuntimeError):
    pass


def _norm(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def load_mapping(entity: str) -> dict[str, str]:
    path = Path(settings.data_dir) / "mapping.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()).get(entity, {})
    except json.JSONDecodeError as exc:
        raise ConnectorError(f"mapping.json is not valid JSON: {exc}") from exc


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read a CSV or JSON file into a list of dicts."""
    if not path.exists():
        raise ConnectorError(f"Missing data file: {path}")
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        if isinstance(data, dict):  # allow {"items": [...]}
            data = next((v for v in data.values() if isinstance(v, list)), [])
        return list(data)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def find_file(stem: str) -> Path:
    base = Path(settings.data_dir)
    for ext in (".csv", ".json"):
        p = base / f"{stem}{ext}"
        if p.exists():
            return p
    return base / f"{stem}.csv"


def apply_aliases(row: dict[str, Any], aliases: dict[str, list[str]], custom: dict[str, str]) -> dict[str, Any]:
    """Rename source columns to canonical names."""
    by_norm = {_norm(k): v for k, v in row.items()}
    out: dict[str, Any] = {}
    for src, dest in custom.items():
        if src in row:
            out[dest] = row[src]
    for canonical, names in aliases.items():
        if canonical in out:
            continue
        for name in [canonical, *names]:
            if _norm(name) in by_norm:
                out[canonical] = by_norm[_norm(name)]
                break
    return out


# ---- value coercion -----------------------------------------------------------

def to_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    sep = LIST_SEP if LIST_SEP in str(value) else ","
    return [v.strip() for v in str(value).split(sep) if v.strip()]


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "required", "x"}


def to_float(value: Any, default: float | None = None) -> float | None:
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return default


def to_int(value: Any, default: int | None = None) -> int | None:
    f = to_float(value)
    return default if f is None else int(f)


def to_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value if not isinstance(value, datetime) else value.date()
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%d-%b-%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:11].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def to_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class Connector(ABC):
    """A read-only source of records."""

    name: str = "base"

    @abstractmethod
    def fetch(self) -> dict[str, list[dict[str, Any]]]:
        """Return {entity_name: [canonical records]}."""

    def health(self) -> dict[str, Any]:
        try:
            counts = {k: len(v) for k, v in self.fetch().items()}
            return {"source": self.name, "ok": True, "counts": counts}
        except Exception as exc:  # report, never crash the health page
            return {"source": self.name, "ok": False, "error": str(exc)}
