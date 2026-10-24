"""Email reminders for overdue, retake and expiring trainings.

EMAIL_MODE:
  preview (default) - build the emails and return them, send nothing
  resend            - send with Resend (RESEND_API_KEY, free tier available)
  smtp              - send through an SMTP relay (e.g. the lab's mail server)
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from .. import models
from ..config import settings
from .adaptive import assignment_flags

log = logging.getLogger(__name__)


def build_reminder(emp: models.Employee) -> dict | None:
    lines = []
    for a in emp.assignments:
        f = assignment_flags(a)
        t = a.training
        if f["overdue"]:
            lines.append(f"- OVERDUE: {t.title} ({t.code}), was due {a.due_date}")
        elif f["needs_retake"]:
            lines.append(f"- Retake needed: {t.title} ({t.code})" + (f", by {a.next_retraining}" if a.next_retraining else ""))
        elif f["expiring"]:
            lines.append(f"- Expiring {a.expires_at}: {t.title} ({t.code})")
        elif f["upcoming"]:
            lines.append(f"- Due {a.due_date}: {t.title} ({t.code})")
    if not lines:
        return None
    body = (f"Hi {emp.name.split()[0]},\n\nHere's what needs your attention in your LANL training plan:\n\n" + "\n".join(lines)
            + f"\n\nOpen your plan: {settings.public_url}/hire/\n\nThis reminder was sent by the LANL Adaptive Training Platform.")
    return {"to": emp.email, "subject": f"Training reminder: {len(lines)} item{'s' if len(lines) != 1 else ''} need attention", "body": body}


def send(messages: list[dict]) -> dict:
    mode = settings.email_mode
    if mode == "preview" or not messages:
        return {"mode": "preview", "sent": 0, "messages": messages}
    sent, errors = 0, []
    for m in messages:
        try:
            if mode == "resend":
                httpx.post("https://api.resend.com/emails", timeout=15,
                           headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                           json={"from": settings.email_from, "to": [m["to"]], "subject": m["subject"], "text": m["body"]}).raise_for_status()
            elif mode == "smtp":
                msg = EmailMessage()
                msg["From"], msg["To"], msg["Subject"] = settings.email_from, m["to"], m["subject"]
                msg.set_content(m["body"])
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                    if settings.smtp_user:
                        s.starttls()
                        s.login(settings.smtp_user, settings.smtp_password)
                    s.send_message(msg)
            else:
                raise ValueError(f"Unknown EMAIL_MODE {mode}")
            sent += 1
        except Exception as exc:  # report per message, keep going
            log.warning("Email to %s failed: %s", m["to"], exc)
            errors.append({"to": m["to"], "error": str(exc)})
    return {"mode": mode, "sent": sent, "errors": errors, "messages": [{"to": m["to"], "subject": m["subject"]} for m in messages]}
