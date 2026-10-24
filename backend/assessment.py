"""Deterministic, server-side diagnostic state machine; no AI grading."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import uuid
import random

from backend.question_bank import BankError, STORE, approved, atomic_json, bank_errors, digest

CONFIDENCE = ("guessing", "somewhat sure", "very sure")


def public_question(question):
    """Explicit allowlist: no answer keys, evidence excerpts, or explanations."""
    return {"id": question["id"], "article_id": question["article_id"], "objective_id": question["objective_id"],
            "level": question["level"], "fictional": True, "scenario": question["scenario"],
            "question": question["question"],
            "options": [{"id": o["id"], "text": o["text"]} for o in question["options"]],
            "why": {"question": question["why"]["question"],
                    "options": [{"id": o["id"], "text": o["text"]} for o in question["why"]["options"]]},
            "confidence_choices": list(CONFIDENCE), "attribution": question["attribution"]}


def grade(question, answer_id, reason_id, confidence):
    if answer_id not in {o["id"] for o in question["options"]}:
        raise ValueError("Unknown answer option ID")
    if reason_id not in {o["id"] for o in question["why"]["options"]}:
        raise ValueError("Unknown reasoning option ID")
    if confidence not in CONFIDENCE:
        raise ValueError("Unknown confidence value")
    return {"answer_correct": answer_id == question["correct_option_id"],
            "reason_correct": reason_id == question["why"]["correct_option_id"], "confidence": confidence}


def choose_initial(bank, initial_limit, random_seed=None):
    """Round-robin articles; priority descending and IDs break ties deterministically."""
    concepts = {c["id"]: c for c in bank["concepts"]}
    pools = {}
    for q in bank["questions"]:
        if q["role"] == "diagnostic" and approved(bank, q):
            pools.setdefault(q["article_id"], []).append(q)
    for pool in pools.values():
        pool.sort(key=lambda q: (-concepts[q["objective_id"]]["importance"], q["objective_id"]))
    if random_seed is not None:
        rng = random.Random(random_seed)
        for pool in pools.values():
            rng.shuffle(pool)
    selected = []
    while len(selected) < initial_limit:
        added = False
        for aid in sorted(pools):
            if pools[aid] and len(selected) < initial_limit:
                selected.append(pools[aid].pop(0))
                added = True
        if not added:
            break
    return selected


class Diagnostic:
    """A scenario + its Why? and confidence count as ONE budget item.

    All initial slots are reserved before follow-ups/prerequisite probes. At most
    one foundation follow-up is used per initially tested objective. Prerequisite
    foundation probes use spare budget only after all planned initial questions.
    Feedback is released only after the active diagnostic branch has ended.
    """

    def __init__(self, bank, source, *, initial_limit=8, budget=12, random_seed=None):
        if type(initial_limit) is not int or not 1 <= initial_limit <= 12:
            raise ValueError("initial_limit must be from 1 to 12")
        if type(budget) is not int or not 1 <= budget <= 24:
            raise ValueError("budget must be from 1 to 24")
        errors = bank_errors(bank, source)
        if errors:
            raise BankError("Bank failed structural checks: " + "; ".join(errors))
        self.bank, self.source = deepcopy(bank), source
        self.concepts = {c["id"]: c for c in self.bank["concepts"]}
        self.random_seed = random_seed
        self.plan = choose_initial(self.bank, min(initial_limit, budget), random_seed)
        if not self.plan:
            raise BankError("No manually approved diagnostic questions are available")
        self.initial_limit, self.budget = initial_limit, budget
        self.session_id = str(uuid.uuid4())
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.records = []
        self.position = 0
        self.current = None
        self.pending = None
        self.branch = []
        self.completed_branches = []
        self.unavailable_followups = {}
        self.prereq_targets = set()
        self.finished = False

    def _foundation(self, cid):
        used = {r["question_id"] for r in self.records}
        return next((q for q in self.bank["questions"] if q["objective_id"] == cid
                     and q["role"] == "follow-up" and q["id"] not in used and approved(self.bank, q)), None)

    def next_question(self):
        if self.current:
            return public_question(self.current)
        if len(self.records) >= self.budget:
            self.finished = True
            return None
        if self.pending:
            self.current, self.pending = self.pending, None
        elif self.position < len(self.plan):
            self.current = self.plan[self.position]
            self.position += 1
        else:
            # Probe relevant prerequisites without displacing other articles'
            # reserved initial coverage or repeating an already-tested concept.
            tested = {r["objective_id"] for r in self.records}
            candidates = sorted(self.prereq_targets - tested,
                                key=lambda cid: (-self.concepts[cid]["importance"], cid))
            for cid in candidates:
                foundation = self._foundation(cid)
                if foundation:
                    self.current = foundation
                    break
            if not self.current:
                self.finished = True
                return None
        return public_question(self.current)

    def _add_prerequisites(self, cid):
        for p in self.concepts[cid]["prerequisites"]:
            target = p["concept_id"]
            if target not in self.prereq_targets:
                self.prereq_targets.add(target)
                self._add_prerequisites(target)

    def submit(self, question_id, answer_id, reason_id, confidence):
        if not self.current or self.current["id"] != question_id:
            raise ValueError("Response does not match the current unanswered question")
        q = self.current
        grading = grade(q, answer_id, reason_id, confidence)
        record = {"question_id": q["id"], "objective_id": q["objective_id"], "article_id": q["article_id"],
                  "role": q["role"], "level": q["level"], "answer_id": answer_id, "reason_id": reason_id, **grading}
        self.records.append(record)
        self.branch.append(record)
        self.current = None
        cid = q["objective_id"]
        if q["role"] == "diagnostic" and not (grading["answer_correct"] and grading["reason_correct"]):
            self._add_prerequisites(cid)
            foundation = self._foundation(cid)
            if self.random_seed is not None and foundation and self.position < len(self.plan) and len(self.records) + len(self.plan) - self.position >= self.budget:
                self.plan.pop()  # Reserve a remaining slot for adaptive foundation evidence.
            remaining_initial = len(self.plan) - self.position
            if foundation and len(self.records) + remaining_initial < self.budget:
                self.pending = foundation
                return {"branch_complete": False}  # No grades/explanations yet.
            self.unavailable_followups[cid] = "budget exhausted/reserved for initial coverage" if foundation else "no approved foundation question"
        feedback = self._finish_branch()
        return {"branch_complete": True, "feedback": feedback}

    def _finish_branch(self):
        questions = {q["id"]: q for q in self.bank["questions"]}
        feedback = []
        for record in self.branch:
            q = questions[record["question_id"]]
            feedback.append({"question_id": q["id"], "answer_correct": record["answer_correct"],
                             "reason_correct": record["reason_correct"],
                             "answer_explanations": deepcopy(q["options"]),
                             "reason_explanations": deepcopy(q["why"]["options"]),
                             "correct_answer_id": q["correct_option_id"],
                             "correct_reason_id": q["why"]["correct_option_id"]})
        self.completed_branches.append([r["question_id"] for r in self.branch])
        self.branch = []
        return feedback

    def report(self):
        entries = []
        for concept in sorted(self.concepts.values(), key=lambda c: (c["article_id"], -c["importance"], c["id"])):
            cid = concept["id"]
            records = [r for r in self.records if r["objective_id"] == cid]
            application = next((r for r in records if r["role"] == "diagnostic"), None)
            foundation = next((r for r in records if r["level"] == "foundation"), None)
            evidence = lambda r, field: "not assessed" if r is None else "positive" if r[field] else "incorrect"
            levels = {"foundation": evidence(foundation, "answer_correct"),
                      "application": evidence(application, "answer_correct"),
                      "reasoning": evidence(application, "reason_correct"),
                      "foundation_reasoning": evidence(foundation, "reason_correct")}
            gap, status = "No responses collected.", "not assessed"
            review = "Assess this concept when time and approved questions are available."
            if application and application["answer_correct"] and application["reason_correct"]:
                status, gap = "evidence of understanding", "No application/reasoning gap observed in this scenario."
                review = "Optional later transfer check using an approved post-training scenario."
            elif application:
                status = "needs review" if foundation else "insufficient evidence"
                if foundation and not (foundation["answer_correct"] and foundation["reason_correct"]):
                    gap = "Foundational principle or its explanation needs review; application also remains uncertain."
                elif foundation:
                    gap = "Foundation response was correct; gap is in applying the principle or explaining the decision."
                else:
                    gap = "Application/reasoning response was incorrect or conflicting; foundation was not investigated."
                review = f"Review {concept['name']} using the cited points, then work through a different application and explain why alternatives fail."
            elif foundation:
                status = "insufficient evidence" if foundation["answer_correct"] and foundation["reason_correct"] else "needs review"
                gap = "Prerequisite foundation probed; application and application reasoning remain untested."
                review = f"Review the prerequisite {concept['name']} and then test its application."
            unfinished = any(r["objective_id"] == cid for r in self.branch) or bool(self.current and self.current["objective_id"] == cid)
            if unfinished:
                status, gap = ("insufficient evidence" if records else "not assessed"), "Diagnostic branch unfinished; feedback withheld."
                review = "Finish the foundation follow-up before receiving explanations."
                levels = {k: "pending" if v != "not assessed" else v for k, v in levels.items()}
            untested = [level for level in ("foundation", "application", "reasoning") if levels[level] == "not assessed"]
            entries.append({"objective_id": cid, "article_id": concept["article_id"], "name": concept["name"],
                            "objective": concept["objective"], "importance": concept["importance"], "status": status,
                            "evidence": levels, "observed_gap": gap, "recommended_review": review,
                            "untested": untested, "post_training": "not assessed",
                            "followup_unavailable": self.unavailable_followups.get(cid),
                            "confidence": [r["confidence"] for r in records],
                            "review_resources": {"resource_point_ids": concept["resource_point_ids"],
                                                 "excerpt": "Withheld until diagnostic branch finishes." if unfinished else concept["source_excerpt"],
                                                 "source": self.source[concept["article_id"]]["data"]["source"]}})
        priority = [e["objective_id"] for e in sorted(entries, key=lambda e: (-e["importance"], e["objective_id"]))
                    if e["status"] in ("needs review", "insufficient evidence")]
        obligations = [{"article_id": aid, "required": r["data"]["required"],
                        "completion": "not evaluated by this diagnostic"} for aid, r in sorted(self.source.items())]
        return {"session_id": self.session_id, "created_at": self.created_at, "finished": self.finished,
                "bank_digest": digest(self.bank), "budget": self.budget, "initial_limit": self.initial_limit,
                "questions_answered": len(self.records), "planned_initial": len(self.plan),
                "answers_correct": sum(r["answer_correct"] for r in self.records),
                "reasons_correct": sum(r["reason_correct"] for r in self.records),
                "confidence_adds_points": False, "interpretation": "Diagnostic evidence only; not certified mastery or training completion.",
                "objectives": entries, "review_priority": priority, "required_training": obligations,
                "article_coverage": {aid: {"mapped": sum(c["article_id"] == aid for c in self.concepts.values()),
                                            "tested": sum(e["article_id"] == aid and e["status"] != "not assessed" for e in entries)}
                                     for aid in sorted(self.source)},
                "responses": deepcopy(self.records), "unfinished_branch": [r["question_id"] for r in self.branch],
                "unanswered_question": self.current["id"] if self.current else None}

    def save(self, folder=STORE / "results"):
        result = self.report()
        path = Path(folder) / f"{self.session_id}.json"
        atomic_json(path, result)
        path.with_suffix(".md").write_text(render_report(result), encoding="utf-8")
        return path


def render_report(report):
    lines = ["# Diagnostic results", "", report["interpretation"],
             f"Answered {report['questions_answered']}/{report['budget']} scenario items (each includes reasoning and confidence).",
             f"Answers correct: {report['answers_correct']}; reasons correct: {report['reasons_correct']}. Confidence adds no points.",
             "", "## Topic coverage"]
    for aid, coverage in report["article_coverage"].items():
        lines.append(f"- {aid}: {coverage['tested']}/{coverage['mapped']} mapped concepts tested")
    lines += ["", "## Targeted review priority (3 is highest)"] + [f"- {cid}" for cid in report["review_priority"]]
    for entry in report["objectives"]:
        lines += ["", f"## {entry['name']} ({entry['objective_id']})", f"Status: {entry['status']}; priority {entry['importance']}",
                  f"Objective: {entry['objective']}", f"Foundation: {entry['evidence']['foundation']}; application: {entry['evidence']['application']}; reasoning: {entry['evidence']['reasoning']}",
                  f"Foundation reasoning: {entry['evidence']['foundation_reasoning']}",
                  f"Observed gap: {entry['observed_gap']}", f"Recommended review: {entry['recommended_review']}",
                  f"Untested: {', '.join(entry['untested']) or 'none of the three diagnostic components'}; post-training transfer untested.",
                  f"Follow-up limit: {entry['followup_unavailable'] or 'none encountered'}",
                  f"Review points: {', '.join(entry['review_resources']['resource_point_ids'])}",
                  f"Review excerpt: {entry['review_resources']['excerpt']}",
                  f"Source: {entry['review_resources']['source']['url']} ({entry['review_resources']['source']['license']})"]
    lines += ["", "## Required training (separate from diagnostic)"]
    lines += [f"- {o['article_id']}: required={o['required']}; {o['completion']}" for o in report["required_training"]]
    return "\n".join(lines) + "\n"
