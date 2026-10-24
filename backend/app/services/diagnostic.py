"""Persistent adapter around the existing Diagnostic engine (never AI grading).

Sessions live in the platform database (DATABASE_URL: SQLite locally, PostgreSQL in
the Docker stack), so every app worker and replica sees the same sessions. Setting
DIAGNOSTIC_DB_PATH keeps them in a separate SQLite file instead. Each submission
locks its session row first, which serializes duplicate submits on SQLite and
PostgreSQL alike. The snapshot and answer keys are private server data; HTTP
responses use explicit allowlists.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import secrets

from sqlalchemy import create_engine, text

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
    result = {key: deepcopy(report[key]) for key in (
        "session_id", "created_at", "finished", "budget", "initial_limit", "questions_answered",
        "planned_initial", "answers_correct", "reasons_correct", "confidence_adds_points", "interpretation",
        "objectives", "review_priority", "required_training", "article_coverage")}
    result["answer_history"] = [{k: r[k] for k in ("question_id", "answer_id", "reason_id", "answer_correct", "reason_correct", "confidence")} for r in engine.records]
    questions = {q["id"]: q for q in engine.bank["questions"]}
    for row in result["answer_history"]:
        question = questions[row["question_id"]]
        row["question"] = question["question"]
        row["answer_text"] = next(o["text"] for o in question["options"] if o["id"] == row["answer_id"])
        row["reason_text"] = next(o["text"] for o in question["why"]["options"] if o["id"] == row["reason_id"])
    return result


class _Row:
    """Row usable by column name or position, like sqlite3.Row."""

    def __init__(self, row):
        self._row = row

    def __getitem__(self, key):
        return self._row[key] if isinstance(key, int) else self._row._mapping[key]


class _Result:
    def __init__(self, result):
        self._result = result

    def fetchall(self):
        return [_Row(row) for row in self._result.fetchall()]

    def fetchone(self):
        row = self._result.fetchone() if self._result.returns_rows else None
        return _Row(row) if row is not None else None


class _Connection:
    """DB-API style execute("... ?", (params,)) on any SQLAlchemy database."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        values, counter = {}, iter(range(len(params)))

        def bind(_):
            i = next(counter)
            values[f"p{i}"] = params[i]
            return f":p{i}"

        return _Result(self._conn.execute(text(re.sub(r"\?", bind, sql)), values))


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS diagnostic_course_reviews (
        session_id TEXT NOT NULL, objective_id TEXT NOT NULL, reviewed_at TEXT NOT NULL,
        PRIMARY KEY(session_id, objective_id))""",
    """CREATE TABLE IF NOT EXISTS diagnostic_sessions (
        id TEXT PRIMARY KEY, owner INTEGER NOT NULL, snapshot TEXT NOT NULL,
        responses TEXT NOT NULL, report TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS diagnostic_submissions (
        session_id TEXT NOT NULL, question_id TEXT NOT NULL,
        request_digest TEXT NOT NULL, response TEXT NOT NULL,
        PRIMARY KEY(session_id, question_id))""",
)


class SessionStore:
    def __init__(self, path=None, bank_provider=configured_bank):
        """path=None uses the platform database; a path uses a separate SQLite file."""
        self.bank_provider = bank_provider
        if path:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(f"sqlite:///{self.path}", connect_args={"timeout": 30, "check_same_thread": False})
        else:
            from ..database import engine

            self.path, self.engine = None, engine
        with self.connection() as db:
            for statement in SCHEMA:
                db.execute(statement)

    @contextmanager
    def connection(self):
        with self.engine.begin() as conn:  # commits on success, rolls back on any error
            yield _Connection(conn)

    def restart_demo(self, owner):
        # Validate and create the replacement before deleting previous demo evidence.
        fresh = self.start(owner, 10, 10, randomize=True)
        with self.connection() as db:
            params = (owner, fresh["session_id"])
            for table in ("diagnostic_submissions", "diagnostic_course_reviews"):
                db.execute(f"DELETE FROM {table} WHERE session_id IN (SELECT id FROM diagnostic_sessions WHERE owner=? AND id<>?)", params)
            db.execute("DELETE FROM diagnostic_sessions WHERE owner=? AND id<>?", params)
        return fresh

    def availability(self):
        try:
            bank, source = self.bank_provider()
            Diagnostic(bank, source)
            return {"available": True, "message": "Manually approved diagnostic questions are available."}
        except (DiagnosticError, BankError, ValueError):
            return {"available": False, "message": SETUP_MESSAGE}

    def start(self, owner, initial_limit, budget, randomize=False):
        bank, source = self.bank_provider()
        random_seed = secrets.randbits(64) if randomize else None
        try:
            engine = Diagnostic(bank, source, initial_limit=initial_limit, budget=budget, random_seed=random_seed)
        except (BankError, ValueError):
            raise DiagnosticError(409, SETUP_MESSAGE) from None
        engine.next_question()
        snapshot = {"random_seed": random_seed, "bank": bank, "source": source, "initial_limit": initial_limit, "budget": budget,
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
                            initial_limit=snapshot["initial_limit"], budget=snapshot["budget"], random_seed=snapshot.get("random_seed"))
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
            # Lock this session's row first (SQLite takes the write lock, PostgreSQL a row lock),
            # so duplicate submits from double clicks or retries are processed one at a time.
            db.execute("UPDATE diagnostic_sessions SET owner=owner WHERE id=? AND owner=?", (session_id, owner))
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

    def review_courses(self, owner):
        latest = self.latest_completed(owner)
        if not latest["available"]:
            return {"session_id": None, "courses": []}
        report = latest["report"]
        with self.connection() as db:
            row = self.owned(db, report["session_id"], owner)
            source = json.loads(row["snapshot"])["source"]
            reviewed = {r["objective_id"] for r in db.execute(
                "SELECT objective_id FROM diagnostic_course_reviews WHERE session_id=?", (report["session_id"],)).fetchall()}
        objectives = {o["objective_id"]: o for o in report["objectives"]}
        courses = []
        for cid in report["review_priority"]:
            objective = objectives[cid]
            resource = source[objective["article_id"]]["data"]
            refs = objective["review_resources"]["resource_point_ids"]
            courses.append({"id": cid, "title": objective["name"], "article_id": objective["article_id"],
                "importance": objective["importance"], "objective": objective["objective"],
                "observed_gap": objective["observed_gap"], "recommended_review": objective["recommended_review"],
                "status": "reviewed" if cid in reviewed else "not_started",
                "source_excerpt": objective["review_resources"]["excerpt"], "attribution": resource["source"],
                "key_points": [{"id": point["id"], "point": point["point"], "explanation": point["explanation"]}
                               for point in resource["key_points"] if point["id"] in refs]})
        return {"session_id": report["session_id"], "courses": courses}

    def complete_review(self, session_id, objective_id, owner):
        from datetime import datetime, timezone
        courses = self.review_courses(owner)
        if courses["session_id"] != session_id or objective_id not in {c["id"] for c in courses["courses"]}:
            raise DiagnosticError(404, "Review course not found in your current learning path")
        with self.connection() as db:
            self.owned(db, session_id, owner)
            db.execute("INSERT INTO diagnostic_course_reviews VALUES(?,?,?) ON CONFLICT(session_id,objective_id) DO NOTHING",
                       (session_id, objective_id, datetime.now(timezone.utc).isoformat()))
        return {"status": "reviewed", "objective_id": objective_id,
                "message": "Material reviewed. Understanding requires a separate assessment."}

    def latest_completed(self, owner):
        """Owner-scoped saved evidence; independent of the browser and current bank."""
        with self.connection() as db:
            rows = db.execute("SELECT report FROM diagnostic_sessions WHERE owner=?", (owner,)).fetchall()
        reports = [json.loads(row["report"]) for row in rows]
        completed = [report for report in reports if report.get("finished")]
        if not completed:
            return {"available": False, "report": None}
        report = max(completed, key=lambda r: (r["created_at"], r["session_id"]))
        fields = ("session_id", "created_at", "questions_answered", "answers_correct", "reasons_correct",
                  "budget", "objectives", "review_priority", "article_coverage")
        return {"available": True, "report": {key: deepcopy(report[key]) for key in fields}}

    def results(self, session_id, owner):
        with self.connection() as db:
            engine = self.restore(self.owned(db, session_id, owner))
            if not engine.finished:
                raise DiagnosticError(409, "Finish the diagnostic before viewing results; branch feedback is withheld.")
            return learner_report(engine)


_stores: dict = {}


def get_store():
    key = settings.diagnostic_db_path or ""
    if key not in _stores:
        _stores[key] = SessionStore(settings.diagnostic_db_path or None)
    return _stores[key]
