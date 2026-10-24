"""Offline-only regression tests for bank generation, review and assessment."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend import question_bank as qb
from backend.assessment import Diagnostic, grade, public_question, render_report


def fixture(articles=4, objectives=3):
    source, bank = {}, qb.new_bank()
    for n in range(articles):
        aid = f"topic-{n}"
        excerpt = f"Topic {n} principle explains how a protective barrier reduces the stated fictional hazard."
        data = {"id": aid, "title": aid, "required": n < 2,
                "source": {"name": "Wikipedia", "url": f"https://en.wikipedia.org/wiki/Topic_{n}", "license": "CC BY-SA 4.0"},
                "key_points": [{"id": "kp1", "point": excerpt, "explanation": "This is conceptual training, not an operational procedure.", "importance": 3}]}
        source[aid] = {"data": data, "raw": excerpt, "fingerprint": qb.digest(data)}
        bank["resource_fingerprints"][aid] = source[aid]["fingerprint"]
        for i in range(objectives):
            concept = {"id": f"{aid}--concept-{i}", "article_id": aid, "name": f"Concept {n}/{i}",
                       "objective": f"Explain and apply protective principle {n}/{i}.", "importance": 3,
                       "resource_point_ids": ["kp1"], "excerpt_source": "knowledge", "source_excerpt": excerpt,
                       "prerequisites": []}
            bank["concepts"].append(concept)
            for role in qb.ROLES:
                raw = raw_question(role, f"{n}-{i}", excerpt)
                qid = f"{concept['id']}--{role}-v1"
                raw.update(id=qid, article_id=aid, objective_id=concept["id"], level=qb.ROLES[role],
                           review={"status": "pending"}, attribution={**data["source"],
                           "adaptation": "AI-assisted fictional training scenario; manually review before use."})
                for container, prefix in ((raw, "a"), (raw["why"], "r")):
                    remap = {c: f"{qid}--{prefix}{j}" for j, c in enumerate("abcd", 1)}
                    container["correct_option_id"] = remap[container["correct_option_id"]]
                    for option in container["options"]:
                        option["id"] = remap[option["id"]]
                bank["questions"].append(raw)
    return source, bank


def raw_question(role, suffix, excerpt):
    return {"role": role, "fictional": True, "scenario": f"Fictional {role} situation {suffix}: a learner compares a barrier with no barrier.",
            "question": "Which conclusion follows from the principle?", "resource_point_ids": ["kp1"],
            "excerpt_source": "knowledge", "source_excerpt": excerpt,
            "options": [{"id": c, "text": f"Answer {c}", "explanation": f"Answer explanation {c}"} for c in "abcd"],
            "correct_option_id": "a" if role == "diagnostic" else "b",
            "why": {"question": "Why is it appropriate rather than the plausible alternative?",
                    "options": [{"id": c, "text": f"Reason {c}", "explanation": f"Reason explanation {c}"} for c in "abcd"],
                    "correct_option_id": "c"}}


def approve_all(bank):
    for q in bank["questions"]:
        qb.review_question(bank, q["id"], "approved", "Offline human-review fixture")


def answer(session, bank, *, correct=True, reason_correct=True, confidence="very sure"):
    public = session.next_question()
    q = next(q for q in bank["questions"] if q["id"] == public["id"])
    a = q["correct_option_id"] if correct else next(o["id"] for o in q["options"] if o["id"] != q["correct_option_id"])
    r = q["why"]["correct_option_id"] if reason_correct else next(o["id"] for o in q["why"]["options"] if o["id"] != q["why"]["correct_option_id"])
    return public, session.submit(public["id"], a, r, confidence)


class BankTests(unittest.TestCase):
    def test_fixture_structural_validation(self):
        source, bank = fixture()
        self.assertEqual(qb.bank_errors(bank, source), [])

    def test_mocked_ai_concept_map_and_three_levels(self):
        source, _ = fixture(1, 1)
        resource = source["topic-0"]
        excerpt = resource["raw"]
        mapped = {"concepts": [{"key": "protective-principle", "name": "Protective principle", "objective": "Apply a protective principle to a fictional situation.",
                               "resource_point_ids": ["kp1"], "excerpt_source": "knowledge", "source_excerpt": excerpt, "prerequisites": []}]}
        generated = {"questions": [raw_question(role, role, excerpt) for role in qb.ROLES]}
        with patch.object(qb, "generate", side_effect=[json.dumps(mapped), json.dumps(generated)]) as ai:
            bank = qb.build_bank(source, objectives_per_article=1, progress=lambda _: None)
        self.assertEqual(ai.call_count, 2)
        self.assertIn("3 is highest priority", ai.call_args_list[0].args[0])
        self.assertIn("RAW-TEXT CONTEXT", ai.call_args_list[1].args[0])
        self.assertEqual(qb.bank_errors(bank, source), [])
        self.assertEqual(len(bank["questions"]), 3)
        self.assertTrue(all(q["review"]["status"] == "pending" for q in bank["questions"]))
        with patch.object(qb, "generate", side_effect=AssertionError("Should reuse saved questions")):
            reused = qb.build_bank(source, bank, objectives_per_article=1, progress=lambda _: None)
        self.assertEqual(bank, reused)

    def test_reject_bad_evidence_options_keys_and_ids(self):
        source, bank = fixture(1, 1)
        mutations = [lambda q: q.update(source_excerpt="Invented unsupported source passage with enough characters"),
                     lambda q: q.update(resource_point_ids=["kp999"]),
                     lambda q: q["options"][1].update(text=q["options"][0]["text"]),
                     lambda q: q.update(correct_option_id="invalid"),
                     lambda q: q["why"].update(correct_option_id="invalid"),
                     lambda q: q.update(id="bad-id"), lambda q: q.update(objective_id="unknown"),
                     lambda q: q["options"][1].update(id=q["options"][0]["id"]),
                     lambda q: q["options"][0].pop("explanation")]
        for mutate in mutations:
            changed = deepcopy(bank)
            mutate(changed["questions"][0])
            self.assertTrue(qb.bank_errors(changed, source))

    def test_manual_approval_and_content_invalidation(self):
        source, bank = fixture(1, 1)
        self.assertFalse(qb.approved(bank, bank["questions"][0]))
        with self.assertRaises(qb.BankError):
            Diagnostic(bank, source)
        approve_all(bank)
        self.assertTrue(qb.approved(bank, bank["questions"][0]))
        bank["questions"][0]["options"][0]["text"] += " changed"
        self.assertFalse(qb.approved(bank, bank["questions"][0]))
        with self.assertRaises(qb.BankError):
            Diagnostic(bank, source)
        bank["questions"][0]["review"]["status"] = "rejected"
        self.assertFalse(qb.approved(bank, bank["questions"][0]))

    def test_resource_and_map_changes_invalidate_reviews(self):
        source, bank = fixture(1, 1)
        approve_all(bank)
        changed = deepcopy(bank)
        changed["concepts"][0]["objective"] += " changed"
        self.assertFalse(qb.approved(changed, changed["questions"][0]))
        source["topic-0"]["fingerprint"] = "changed"
        self.assertTrue(qb.bank_errors(bank, source))
        with self.assertRaises(qb.BankError):
            Diagnostic(bank, source)

    def test_prerequisite_cycles_rejected(self):
        source, bank = fixture(1, 2)
        for i, c in enumerate(bank["concepts"]):
            c["prerequisites"] = [{"concept_id": bank["concepts"][1-i]["id"], "rationale": "A prior principle is needed", "source_excerpt": source["topic-0"]["raw"]}]
        self.assertIn("Prerequisite cycle", qb.bank_errors(bank, source))

    def test_readable_report_labels_structural_not_factual(self):
        source, bank = fixture(1, 1)
        report = qb.review_report(bank, source)
        self.assertIn("does not establish factual correctness", report)
        self.assertIn("CORRECT", report)
        self.assertIn("pending", report)

    def test_malformed_bank_values_rejected_without_traceback(self):
        source, bank = fixture(1, 1)
        for bad in (None, [], {**bank, "concepts": None}, {**bank, "questions": [None]}):
            self.assertTrue(qb.bank_errors(bad, source))
        for field, value in (("objective_id", []), ("review", []), ("resource_point_ids", [None]), ("why", None)):
            changed = deepcopy(bank)
            changed["questions"][0][field] = value
            self.assertTrue(qb.bank_errors(changed, source))

    def test_invalid_ai_scenarios_are_retried_and_not_saved(self):
        source, bank = fixture(1, 1)
        raw = {"questions": [raw_question(role, role, source["topic-0"]["raw"]) for role in qb.ROLES]}
        raw["questions"][0]["options"][1]["text"] = raw["questions"][0]["options"][0]["text"]
        bank["questions"] = []
        with patch.object(qb, "generate", return_value=json.dumps(raw)) as ai:
            result = qb.build_bank(source, bank, objectives_per_article=1, progress=lambda _: None)
        self.assertEqual(ai.call_count, 2)
        self.assertEqual(result["questions"], [])
        self.assertTrue(result["generation_errors"])

    def test_generation_checkpoints_survive_and_clear_old_errors(self):
        source, bank = fixture(1, 1)
        bank["generation_errors"] = ["Old, resolved issue"]
        saved = []
        with patch.object(qb, "generate", side_effect=AssertionError("No calls for saved bank")):
            result = qb.build_bank(source, bank, progress=lambda _: None, checkpoint=lambda b: saved.append(deepcopy(b)))
        self.assertTrue(saved)
        self.assertEqual(result["generation_errors"], [])


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.source, self.bank = fixture()
        approve_all(self.bank)

    def test_separate_grading_and_confidence_no_points(self):
        q = self.bank["questions"][0]
        good = grade(q, q["correct_option_id"], q["why"]["correct_option_id"], "guessing")
        sure = grade(q, q["correct_option_id"], q["why"]["correct_option_id"], "very sure")
        self.assertEqual(good["answer_correct"], sure["answer_correct"])
        self.assertEqual(good["reason_correct"], sure["reason_correct"])
        with self.assertRaises(ValueError):
            grade(q, "unknown", q["why"]["correct_option_id"], "guessing")
        with self.assertRaises(ValueError):
            grade(q, q["correct_option_id"], q["why"]["correct_option_id"], "certain")

    def test_success_moves_on_without_claiming_foundation_evidence(self):
        session = Diagnostic(self.bank, self.source)
        q, result = answer(session, self.bank, confidence="guessing")
        self.assertTrue(result["branch_complete"])
        entry = next(e for e in session.report()["objectives"] if e["objective_id"] == q["objective_id"])
        self.assertEqual(entry["status"], "evidence of understanding")
        self.assertEqual(entry["evidence"]["foundation"], "not assessed")
        self.assertNotEqual(session.next_question()["objective_id"], q["objective_id"])

    def test_either_wrong_triggers_distinct_foundation_feedback_delayed(self):
        for correct, reasoning in [(False, True), (True, False), (False, False)]:
            session = Diagnostic(self.bank, self.source)
            q, response = answer(session, self.bank, correct=correct, reason_correct=reasoning)
            self.assertEqual(response, {"branch_complete": False})
            follow = session.next_question()
            self.assertEqual(follow["objective_id"], q["objective_id"])
            self.assertNotEqual(follow["id"], q["id"])
            self.assertEqual(follow["level"], "foundation")
            entry = next(e for e in session.report()["objectives"] if e["objective_id"] == q["objective_id"])
            self.assertEqual(entry["review_resources"]["excerpt"], "Withheld until diagnostic branch finishes.")
            _, finished = answer(session, self.bank)
            self.assertTrue(finished["branch_complete"])
            self.assertEqual(len(finished["feedback"]), 2)
            entry = next(e for e in session.report()["objectives"] if e["objective_id"] == q["objective_id"])
            self.assertEqual(entry["status"], "needs review")
            self.assertIn("applying", entry["observed_gap"])

    def test_foundation_failure_identifies_principle_gap(self):
        session = Diagnostic(self.bank, self.source)
        q, _ = answer(session, self.bank, correct=False)
        answer(session, self.bank, correct=False)
        entry = next(e for e in session.report()["objectives"] if e["objective_id"] == q["objective_id"])
        self.assertIn("Foundational principle", entry["observed_gap"])
        self.assertIn(q["objective_id"], session.report()["review_priority"])

    def test_coverage_budget_nonrepetition_and_no_post_training(self):
        session = Diagnostic(self.bank, self.source, initial_limit=8, budget=12)
        seen, followups = set(), {}
        while (q := session.next_question()):
            self.assertNotIn(q["id"], seen)
            seen.add(q["id"])
            if q["level"] == "foundation":
                followups[q["objective_id"]] = followups.get(q["objective_id"], 0) + 1
            answer(session, self.bank, correct=False, reason_correct=False)
        report = session.report()
        self.assertEqual(report["questions_answered"], 12)
        self.assertTrue(all(count == 1 for count in followups.values()))
        self.assertTrue(all(c["tested"] >= 2 for c in report["article_coverage"].values()))
        self.assertTrue(any(e["status"] == "not assessed" for e in report["objectives"]))
        self.assertTrue(any(e["status"] == "insufficient evidence" for e in report["objectives"]))
        self.assertTrue(all("post-training" not in qid for qid in seen))
        self.assertTrue(all(o["completion"] == "not evaluated by this diagnostic" for o in report["required_training"]))

    def test_relevant_prerequisite_foundation_probe_with_spare_budget(self):
        source, bank = fixture(1, 2)
        core, prerequisite = bank["concepts"]
        core["prerequisites"] = [{"concept_id": prerequisite["id"], "rationale": "Prior principle needed", "source_excerpt": source["topic-0"]["raw"]}]
        approve_all(bank)
        session = Diagnostic(bank, source, initial_limit=1, budget=3)
        first, _ = answer(session, bank, correct=False)
        self.assertEqual(first["objective_id"], core["id"])
        answer(session, bank)
        probe = session.next_question()
        self.assertEqual(probe["objective_id"], prerequisite["id"])
        self.assertEqual(probe["level"], "foundation")
        answer(session, bank)
        self.assertIsNone(session.next_question())
        entry = next(e for e in session.report()["objectives"] if e["objective_id"] == prerequisite["id"])
        self.assertEqual(entry["status"], "insufficient evidence")
        self.assertEqual(entry["evidence"]["application"], "not assessed")

    def test_pending_foundation_never_used(self):
        for q in self.bank["questions"]:
            if q["role"] == "follow-up":
                q["review"] = {"status": "pending"}
        session = Diagnostic(self.bank, self.source, initial_limit=1)
        q, response = answer(session, self.bank, correct=False)
        self.assertTrue(response["branch_complete"])
        entry = next(e for e in session.report()["objectives"] if e["objective_id"] == q["objective_id"])
        self.assertEqual(entry["followup_unavailable"], "no approved foundation question")

    def test_public_payload_no_keys_or_explanations(self):
        public = public_question(self.bank["questions"][0])
        text = json.dumps(public)
        for forbidden in ("correct_option_id", "explanation", "source_excerpt", "review"):
            self.assertNotIn('"' + forbidden + '":', text)

    def test_results_saved_and_reloadable_without_answer_keys(self):
        session = Diagnostic(self.bank, self.source, initial_limit=1)
        answer(session, self.bank)
        session.next_question()
        with TemporaryDirectory() as directory:
            path = session.save(Path(directory))
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["session_id"], session.session_id)
            self.assertEqual(result["questions_answered"], 1)
            self.assertNotIn("correct_option_id", path.read_text())
            self.assertIn("not certified mastery", path.with_suffix(".md").read_text())

    def test_replay_response_rejected_and_limits_enforced(self):
        session = Diagnostic(self.bank, self.source)
        q, _ = answer(session, self.bank)
        with self.assertRaises(ValueError):
            session.submit(q["id"], q["options"][0]["id"], q["why"]["options"][0]["id"], "guessing")
        for options in ({"initial_limit": 13}, {"budget": 0}, {"budget": 25}):
            with self.assertRaises(ValueError):
                Diagnostic(self.bank, self.source, **options)

    def test_priority_selection_prefers_three_over_two(self):
        source, bank = fixture(1, 2)
        resource = source["topic-0"]
        low = deepcopy(resource["data"]["key_points"][0])
        low.update(id="kp2", importance=2)
        resource["data"]["key_points"].append(low)
        resource["fingerprint"] = qb.digest(resource["data"])
        bank["resource_fingerprints"]["topic-0"] = resource["fingerprint"]
        bank["concepts"][0].update(importance=2, resource_point_ids=["kp2"])
        for q in bank["questions"]:
            if q["objective_id"] == bank["concepts"][0]["id"]:
                q["resource_point_ids"] = ["kp2"]
        approve_all(bank)
        session = Diagnostic(bank, source, initial_limit=1)
        self.assertEqual(session.next_question()["objective_id"], bank["concepts"][1]["id"])


class CommandTests(unittest.TestCase):
    def test_human_review_cli_persists_only_explicit_approval(self):
        from scripts import review_question_bank as command
        source, bank = fixture(1, 1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bank.json"
            qb.atomic_json(path, bank)
            with patch.object(command, "resources", return_value=source), patch("sys.argv", ["review", "--bank", str(path), "--interactive"]), patch(
                    "builtins.input", side_effect=["Reviewer", "APPROVE", "Facts and distractors checked", "SKIP", "QUIT"]), redirect_stdout(io.StringIO()):
                self.assertEqual(command.main(), 0)
            saved = qb.read_bank(path)
            self.assertTrue(qb.approved(saved, saved["questions"][0]))
            self.assertFalse(qb.approved(saved, saved["questions"][1]))
            self.assertTrue(path.with_suffix(".review.md").exists())

    def test_terminal_command_runs_and_saves_without_ai(self):
        from scripts import run_diagnostic as command
        source, bank = fixture(1, 1)
        approve_all(bank)
        session = Diagnostic(bank, source, initial_limit=1, budget=2)
        original_save = session.save
        with TemporaryDirectory() as directory, patch.object(command, "read_bank", return_value=bank), patch.object(
                command, "resources", return_value=source), patch.object(command, "Diagnostic", return_value=session), patch.object(
                session, "save", side_effect=lambda: original_save(Path(directory))), patch("sys.argv", ["diagnostic"]), patch(
                "builtins.input", side_effect=["1", "3", "3"]), patch.object(qb, "generate", side_effect=AssertionError("No live generation")), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(command.main(), 0)
            self.assertTrue((Path(directory) / f"{session.session_id}.json").exists())
        self.assertIn("Diagnostic branch finished", output.getvalue())
        self.assertIn("evidence of understanding", output.getvalue())


if __name__ == "__main__":
    unittest.main()
