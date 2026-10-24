"""Login and role checks.

Two ways in:
  1. Company email + password (for demos and environments without SSO).
  2. Google sign-in: the browser gets a Google ID token, we verify it with Google
     and match the email to an employee record. Swap in LANL SSO (SAML/OIDC)
     the same way: verify the identity token, then look up the employee by email.

Roles: hire < manager < admin. Managers can open the hire view, hires can never
open manager routes.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .database import get_db

ROLE_RANK = {"hire": 0, "manager": 1, "admin": 2}
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    return bool(hashed) and bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(emp: models.Employee) -> str:
    payload = {
        "sub": str(emp.id),
        "role": emp.role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def email_allowed(email: str) -> bool:
    domain = email.strip().rsplit("@", 1)[-1].lower()
    return not settings.email_domains or domain in settings.email_domains


def find_by_email(db: Session, email: str) -> models.Employee | None:
    return db.scalar(select(models.Employee).where(func.lower(models.Employee.email) == email.lower().strip()))


def verify_google_token(id_token: str) -> str:
    """Return the verified email from a Google ID token."""
    if not settings.google_client_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google sign-in is not configured (set GOOGLE_CLIENT_ID)")
    resp = httpx.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token}, timeout=10)
    if resp.status_code != 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google token rejected")
    info = resp.json()
    if info.get("aud") != settings.google_client_id or info.get("email_verified") not in ("true", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google token is not for this app")
    return info["email"].lower()


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> models.Employee:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, sign in again")
    emp = db.get(models.Employee, int(payload["sub"]))
    if emp is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    return emp


def require_role(minimum: str):
    def dep(user: models.Employee = Depends(current_user)) -> models.Employee:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{minimum.title()} access required")
        return user

    return dep


require_manager = require_role("manager")
require_admin = require_role("admin")


def team_ids(db: Session, manager: models.Employee) -> set[int]:
    """Ids of everyone below this manager (direct and indirect). Admins get everyone.

    One query for the whole reporting graph, then a walk in memory, so deep orgs
    don't cost one query per level. Cached for the rest of the request.
    """
    key = f"team_ids:{manager.id}"
    if key in db.info:
        return db.info[key]
    rows = db.execute(select(models.Employee.id, models.Employee.manager_id)).all()
    if manager.role == "admin":
        ids = {r.id for r in rows if r.id != manager.id}
    else:
        children: dict[int, list[int]] = {}
        for r in rows:
            if r.manager_id is not None:
                children.setdefault(r.manager_id, []).append(r.id)
        ids, frontier = set(), [manager.id]
        while frontier:
            nxt = [c for m in frontier for c in children.get(m, []) if c not in ids]
            ids.update(nxt)
            frontier = nxt
    db.info[key] = ids
    return ids


def team_of(db: Session, manager: models.Employee) -> list[models.Employee]:
    """Everyone below this manager, with their trainings and skill data loaded in bulk."""
    from .services.loader import load_people

    return load_people(db, team_ids(db, manager))


def can_view(db: Session, viewer: models.Employee, target: models.Employee) -> bool:
    return viewer.id == target.id or viewer.role == "admin" or target.id in team_ids(db, viewer)
