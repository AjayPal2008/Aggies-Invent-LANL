from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, serialize
from ..auth import create_token, current_user, email_allowed, find_by_email, verify_google_token, verify_password
from ..config import settings
from ..database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class GoogleIn(BaseModel):
    id_token: str


def _session(emp: models.Employee) -> dict:
    return {"token": create_token(emp), "user": serialize.employee(emp),
            "home": "/manager/" if emp.role in ("manager", "admin") else "/hire/"}


@router.get("/config")
def auth_config():
    return {"google_client_id": settings.google_client_id or None, "email_domains": settings.email_domains}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    from ..safeguards import limiter

    if settings.rate_limit_enabled:  # stop password guessing against one account
        ok, wait = limiter.allow(f"login-acct:{body.email.strip().lower()}", settings.rate_limit_login_per_minute)
        if not ok:
            raise HTTPException(429, "Too many sign-in attempts for this account. Wait a minute and try again.",
                                headers={"Retry-After": str(wait)})
    if not email_allowed(body.email):
        raise HTTPException(401, f"Use your company email ({', '.join(settings.email_domains)})")
    emp = find_by_email(db, body.email.strip())
    if emp is None or not verify_password(body.password, emp.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    return _session(emp)


@router.post("/google")
def google_login(body: GoogleIn, db: Session = Depends(get_db)):
    email = verify_google_token(body.id_token)
    if not email_allowed(email):
        raise HTTPException(401, "That Google account is not a company account")
    emp = find_by_email(db, email)
    if emp is None:
        raise HTTPException(403, "No employee record for this account. Ask HR to check Oracle.")
    return _session(emp)


@router.get("/me")
def me(user: models.Employee = Depends(current_user)):
    return serialize.employee(user)
