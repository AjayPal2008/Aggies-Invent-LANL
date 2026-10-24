"""Persistent adapter around the existing Diagnostic engine (never AI grading).

SQLite BEGIN IMMEDIATE serializes submissions across processes. The snapshot and
answer keys are private server data; HTTP responses use explicit allowlists.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys

from ..config import REPO_DIR, settings

if str(REPO_DIR) not in sys.path:
    sys.path.append(str(REPO_DIR))
from backend.assessment import Diagnostic
from backend.question_bank import BankError, approved, bank_errors, digest, read_bank, resources


class DiagnosticError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


SETUP_MESSAGE = ("Diagnostic setup needed: generate a question bank with python scripts/generate_question_bank.py, "
                 "then manually review and approve its diagnostic and foundation questions with "
                 "python scripts/review_question_bank.py --interactive. Structural validation is not factual review.")


def configured_bank():
    try:
        bank, source = read_bank(Path(settings.diagnostic_bank_path)), resources()
        if bank_errors(bank, source):
            raise BankError("Invalid or stale bank")
        return bank, source
    except (OSError, ValueError, KeyError, TypeError):
        raise DiagnosticError(409, SETUP_MESSAGE) from None


def learner_feedback(outcome):
    """Only completed-branch explanations, never explicit answer-key IDs."""
    if not outcome.get("branch_complete"):
        return []
    return [{"question_id": f["question_id"], "answer_correct": f["answer_correct"],
             "reason_correct": f["reason_correct"],
             "answers": [{"text": o["text"], "explanation": o["explanation"]} for o in f["answer_explanations"]],
             "reasons": [{"text": o["text"], "explanation": o["explanation"]} for o in f["reason_explanations"]]}
            for f in outcome.get("feedback", [])]


def learner_report(engine):
    report = engine.report()
    # Reports are served only at completion; no in-progress source/reason leaks.
    return {key: deepcopy(report[key]) for key in (
        "session_id", "created_at", "finished", "budget", "initial_limit", "questions_answered",
        "planned_initial", "answers_correct", "reasons_correct", "confidence_adds_points", "interpretation",
        "objectives", "review_priority", "required_training", "article_coverage")}


class SessionStore:
    def __init__(self, path, bank_provider=configured_bank):
        self.path, self.bank_provider = Path(path), bank_provider
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS diagnostic_sessions (
                    id TEXT PRIMARY KEY, owner INTEGER NOT NULL, snapshot TEXT NOT NULL,
                    responses TEXT NOT NULL, report TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS diagnostic_submissions (
                    session_id TEXT NOT NULL, question_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(session_id, question_id));
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def availability(self):
        try:
            bank, source = self.bank_provider()
            Diagnostic(bank, source)
            return {"available": True, "message": "Manually approved diagnostic questions are available."}
        except (DiagnosticError, BankError, ValueError):
            return {"available": False, "message": SETUP_MESSAGE}

    def start(self, owner, initial_limit, budget):
        bank, source = self.bank_provider()
        try:
            engine = Diagnostic(bank, source, initial_limit=initial_limit, budget=budget)
        except (BankError, ValueError):
            raise DiagnosticError(409, SETUP_MESSAGE) from None
        engine.next_question()
        snapshot = {"bank": bank, "source": source, "initial_limit": initial_limit, "budget": budget,
                    "session_id": engine.session_id, "created_at": engine.created_at}
        with self.connection() as db:
            db.execute("INSERT INTO diagnostic_sessions VALUES(?,?,?,?,?)", (
                engine.session_id, owner, json.dumps(snapshot), "[]", json.dumps(engine.report())))
        return self.envelope(engine)

    def restore(self, row):
        snapshot = json.loads(row["snapshot"])
        bank, source = self.bank_provider()
        if digest(bank) != digest(snapshot["bank"]) or bank_errors(bank, source):
            raise DiagnosticError(409, "The question bank or approvals changed. Start a new diagnostic after review.")
        engine = Diagnostic(snapshot["bank"], snapshot["source"],
                            initial_limit=snapshot["initial_limit"], budget=snapshot["budget"])
        engine.session_id, engine.created_at = snapshot["session_id"], snapshot["created_at"]
        for response in json.loads(row["responses"]):
            engine.next_question()
            engine.submit(**response)
        engine.next_question()
        return engine

    def owned(self, db, session_id, owner):
        row = db.execute("SELECT * FROM diagnostic_sessions WHERE id=? AND owner=?", (session_id, owner)).fetchone()
        if not row:
            raise DiagnosticError(404, "Diagnostic session not found")
        return row

    def envelope(self, engine, outcome=None):
        question = engine.next_question()
        return {"session_id": engine.session_id, "complete": engine.finished, "question": question,
                "answered": len(engine.records), "budget": engine.budget,
                "branch_complete": outcome.get("branch_complete") if outcome else None,
                "feedback": learner_feedback(outcome) if outcome else []}

    def current(self, session_id, owner):
        with self.connection() as db:
            engine = self.restore(self.owned(db, session_id, owner))
            return self.envelope(engine)

    def submit(self, session_id, owner, payload):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.owned(db, session_id, owner)
            engine = self.restore(row)
            fingerprint = digest(payload)
            previous = db.execute("SELECT * FROM diagnostic_submissions WHERE session_id=? AND question_id=?",
                                  (session_id, payload["question_id"])).fetchone()
            if previous:
                if previous["request_digest"] != fingerprint:
                    raise DiagnosticError(409, "This question was already submitted with different responses. Refresh the session.")
                return json.loads(previous["response"])
            try:
                outcome = engine.submit(**payload)
            except ValueError:
                raise DiagnosticError(409, "Invalid or stale question/option IDs. Refresh the current question.") from None
            result = self.envelope(engine, outcome)
            responses = json.loads(row["responses"]) + [payload]
            db.execute("UPDATE diagnostic_sessions SET responses=?, report=? WHERE id=?",
                       (json.dumps(responses), json.dumps(engine.report()), session_id))
            db.execute("INSERT INTO diagnostic_submissions VALUES(?,?,?,?)",
                       (session_id, payload["question_id"], fingerprint, json.dumps(result)))
            return result

    def results(self, session_id, owner):
        with self.connection() as db:
            engine = self.restore(self.owned(db, session_id, owner))
            if not engine.finished:
                raise DiagnosticError(409, "Finish the diagnostic before viewing results; branch feedback is withheld.")
            return learner_report(engine)


def get_store():
    return SessionStore(settings.diagnostic_db_path)
