"""Offline checks: python -m unittest scripts.test_knowledge_pipeline -v."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import extract_knowledge as extract
from scripts.validate_knowledge import validate
from scripts.validate_knowledge import repair
from backend.ai_client import GenerationResponse


def sample():
    return {
        "summary": "An introductory summary. A second sentence.", "difficulty": "beginner",
        "key_points": [{"id": f"kp{i}", "point": f"Distinct point {i}",
                        "explanation": "An explanation.", "importance": 3} for i in range(1, 6)],
        "terms": [{"term": f"Term {i}", "definition": "A definition."} for i in range(5)],
        "relationships": [{"from": "kp1", "to": "kp5", "label": "depends on"}],
        "common_misconceptions": [],
    }


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.debug = Path(temporary.name)
        patcher = patch.object(extract, "DEBUG_DIR", self.debug)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_retry_fences_and_metadata_boundary(self):
        response = sample()
        response["category"] = "AI must not set metadata"
        with patch.object(extract, "generate", side_effect=["invalid", "```json\n" + json.dumps(response) + "\n```"] ) as generate:
            result = extract.request_knowledge("Title", "safety", "Source")
        self.assertEqual(generate.call_count, 2)
        self.assertNotIn("category", result)

    def test_invalid_relationship_and_duplicates_retry(self):
        for mutation in ("point", "term"):
            response = sample()
            if mutation == "point":
                response["key_points"][1]["point"] = response["key_points"][0]["point"]
            else:
                response["terms"][1]["term"] = response["terms"][0]["term"]
            self.assertTrue(validate(response, metadata=False))
            with patch.object(extract, "generate", return_value=json.dumps(response)) as generate:
                with self.assertRaises(extract.ExtractionError):
                    extract.request_knowledge("Title", "safety", "Text")
                self.assertEqual(generate.call_count, 2)

    def test_chunk_coverage_and_limits(self):
        text = "Introduction\n\n" + "first paragraph " * 1500 + "\n\nSecond heading\n\n" + "second paragraph " * 1200
        chunks = extract.split_sections(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= extract.CHUNK_CHARS for c in chunks))
        self.assertEqual(" ".join(text.split()), " ".join(" ".join(chunks).split()))

    def test_long_article_merge_and_metadata(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "Ionizing_radiation.txt").write_text("Section\n\n" + "source words " * 2000, encoding="utf-8")
            with patch.object(extract, "generate", return_value=json.dumps(sample())) as generate, redirect_stdout(io.StringIO()):
                result = extract.extract_article("Ionizing_radiation", folder, folder / "output")
            self.assertGreaterEqual(generate.call_count, 3)
            self.assertIn("Consolidate", generate.call_args.args[0])
            self.assertEqual(result["category"], "safety")
            self.assertIs(result["required"], True)
            self.assertEqual(result["source"]["license"], "CC BY-SA 4.0")
            self.assertEqual(validate(result), [])
            self.assertEqual(json.loads((folder / "output/Ionizing_radiation.json").read_text()), result)

    def test_failed_extraction_preserves_existing_output(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "Nuclear_fission.txt").write_text("Some source text.")
            output = folder / "Nuclear_fission.json"
            output.write_text("existing output")
            with patch.object(extract, "generate", return_value="invalid"):
                with self.assertRaises(extract.ExtractionError):
                    extract.extract_article("Nuclear_fission", folder, folder)
            self.assertEqual(output.read_text(), "existing output")

    def test_missing_fields_and_invalid_types(self):
        for data in ([], {}, {**sample(), "relationships": [{"from": [], "to": "kp1", "label": "x"}]},
                     {**sample(), "key_points": [None]}):
            self.assertTrue(validate(deepcopy(data)))

    def test_truncation_raises_budget_and_debug_redacts(self):
        marker = "synthetic-debug-secret"
        truncated = GenerationResponse('{"summary":"' + marker, stop_reason="max_tokens")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": marker}, clear=True), patch.object(
                extract, "generate", side_effect=[truncated, GenerationResponse(json.dumps(sample()), stop_reason="end_turn")]) as generate, redirect_stdout(io.StringIO()) as output:
            extract.request_knowledge("Title", "safety", "Text", article="Test_article")
        self.assertEqual(generate.call_args_list[1].kwargs["max_tokens"], 8000)
        self.assertIn("at most 25 words", generate.call_args.args[0])
        self.assertIn("position", output.getvalue())
        self.assertIn("max_tokens", output.getvalue())
        self.assertNotIn(marker, output.getvalue())
        raw = (self.debug / "Test_article_extraction_attempt1.txt").read_text()
        self.assertNotIn(marker, raw)
        self.assertIn("[REDACTED]", raw)
        info = json.loads((self.debug / "Test_article_extraction_attempt1.json").read_text())
        self.assertEqual(info["stop_reason"], "max_tokens")

    def test_small_repairs_keep_valid_relationships(self):
        data = sample()
        data["key_points"].extend({"id": f"kp{i}", "point": f"Point {i}",
                                   "explanation": "Explanation", "importance": 1} for i in range(6, 11))
        data["terms"].append(deepcopy(data["terms"][0]))
        data["relationships"].append({"from": "kp1", "to": "kp99", "label": "causes"})
        changes = repair(data)
        self.assertTrue(changes)
        self.assertEqual(len(data["key_points"]), 8)
        self.assertEqual(len(data["terms"]), 5)
        self.assertEqual(len(data["relationships"]), 1)
        self.assertEqual(validate(data, metadata=False), [])

    def test_bad_section_does_not_discard_successful_section(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "Nuclear_fission.txt").write_text("Source")
            with patch.object(extract, "split_sections", return_value=["bad section", "good section"]), patch.object(
                    extract, "generate", side_effect=["invalid", "invalid", json.dumps(sample())]), redirect_stdout(io.StringIO()):
                result = extract.extract_article("Nuclear_fission", folder, folder / "output")
            self.assertTrue(result["extraction_status"]["partial"])
            self.assertEqual(result["extraction_status"]["failed_sections"], [1])
            self.assertEqual(validate(result), [])

    def test_merge_failure_uses_existing_facts(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "Nuclear_reactor.txt").write_text("Source")
            with patch.object(extract, "split_sections", return_value=["one", "two"]), patch.object(
                    extract, "generate", side_effect=[json.dumps(sample()), json.dumps(sample()), "bad", "bad"]), redirect_stdout(io.StringIO()):
                result = extract.extract_article("Nuclear_reactor", folder, folder / "output")
            self.assertTrue(result["extraction_status"]["merge_fallback"])
            self.assertEqual(validate(result), [])

    def test_observed_missing_importance_and_object_misconceptions_retry(self):
        # Reproduce the saved live response: all eight importance fields absent,
        # and two misconception/correction objects instead of string entries.
        observed = sample()
        observed["key_points"] = [{"id": f"kp{i}", "point": f"Distinct observed point {i}",
                                   "explanation": "Source-supported explanation"} for i in range(1, 9)]
        observed["common_misconceptions"] = [
            {"misconception": "All radiation is ionizing.", "correction": "Some radiation is non-ionizing."},
            {"misconception": "Radiation can always be sensed.", "correction": "Instruments are needed."},
        ]
        before = deepcopy(observed)
        repair(observed)
        self.assertEqual(observed, before)  # No fabricated ratings or object-to-string conversion.
        errors = validate(observed, metadata=False)
        self.assertEqual(sum("importance" in error for error in errors), 8)
        self.assertTrue(any("got missing" in error for error in errors))
        self.assertTrue(any("common_misconceptions[0]" in error and "dict" in error for error in errors))
        with patch.object(extract, "generate", side_effect=[GenerationResponse(json.dumps(observed), stop_reason="end_turn"),
                                                            GenerationResponse(json.dumps(sample()), stop_reason="end_turn")]) as generate, redirect_stdout(io.StringIO()):
            result = extract.request_knowledge("Ionizing radiation", "safety", "Source", article="Ionizing_radiation", stage="section 1/4")
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(generate.call_args.kwargs["max_tokens"], 4096)
        self.assertIn("got missing", generate.call_args.args[0])
        self.assertEqual(validate(result, metadata=False), [])
        self.assertTrue((self.debug / "Ionizing_radiation_section1_attempt1.txt").exists())

    def test_only_unambiguous_numeric_strings_are_normalized(self):
        data = sample()
        for point in data["key_points"]:
            point["importance"] = " 2 "
        changes = repair(data)
        self.assertTrue(changes)
        self.assertTrue(all(type(point["importance"]) is int and point["importance"] == 2 for point in data["key_points"]))
        self.assertEqual(validate(data, metadata=False), [])
        for ambiguous in (None, True, 2.0, "high", "essential", "2.0", "02", "1 or 2", "", 4):
            with self.subTest(value=ambiguous):
                data = sample()
                data["key_points"][0]["importance"] = ambiguous
                repair(data)
                self.assertEqual(type(data["key_points"][0]["importance"]), type(ambiguous))
                self.assertEqual(data["key_points"][0]["importance"], ambiguous)
                self.assertTrue(any("importance" in error for error in validate(data, metadata=False)))

    def test_malformed_content_is_not_discarded_by_repairs(self):
        data = sample()
        malformed = {"id": "kp6", "point": "Distinct malformed point", "importance": 1}
        data["key_points"].extend([malformed] + [
            {"id": f"kp{i}", "point": f"Extra {i}", "explanation": "Explanation", "importance": 1} for i in range(7, 11)])
        data["terms"].append({"term": data["terms"][0]["term"]})
        repair(data)
        self.assertIn(malformed, data["key_points"])
        self.assertEqual(len(data["terms"]), 6)
        self.assertTrue(any("explanation" in error for error in validate(data, metadata=False)))
        self.assertTrue(any("definition" in error for error in validate(data, metadata=False)))

    def test_debug_names_distinguish_sections_attempts_and_repeated_runs(self):
        for stage, attempt in [("section 1/4", 1), ("section 1/4", 2), ("section 2/4", 1), ("section 1/4", 1)]:
            with redirect_stdout(io.StringIO()):
                extract.save_debug("Ionizing_radiation", f"{stage}:{attempt}", stage=stage, attempt=attempt,
                                   reason="Invalid", stop_reason="end_turn")
        files = {p.name for p in self.debug.glob("*.txt")}
        self.assertEqual(files, {"Ionizing_radiation_section1_attempt1.txt", "Ionizing_radiation_section1_attempt2.txt",
                                 "Ionizing_radiation_section2_attempt1.txt", "Ionizing_radiation_section1_attempt1_run2.txt"})
        info = json.loads((self.debug / "Ionizing_radiation_section2_attempt1.json").read_text())
        self.assertEqual(info["section"], 2)
        self.assertEqual(info["stage_attempt"], 1)

    def test_prompt_example_matches_validator(self):
        from backend.prompts import AI_SCHEMA, EXTRACTION_PROMPT
        example, _ = json.JSONDecoder().raw_decode(AI_SCHEMA[AI_SCHEMA.index("{"):])
        self.assertEqual(validate(example, metadata=False), [])
        self.assertIn("unquoted JSON integer", EXTRACTION_PROMPT)
        self.assertIn("at most three nonempty strings", EXTRACTION_PROMPT)
        self.assertIn('"importance": 3', AI_SCHEMA)

    def test_extra_data_is_retried_without_discarding_content(self):
        invalid = json.dumps(sample()) + "\nTrailing commentary"
        with patch.object(extract, "generate", side_effect=[invalid, json.dumps(sample())]) as generate, redirect_stdout(io.StringIO()) as output:
            result = extract.request_knowledge("Title", "safety", "Source", stage="section 2/4")
        self.assertEqual(generate.call_count, 2)
        self.assertIn("Extra data", output.getvalue())
        self.assertEqual((self.debug / "Title_section2_attempt1.txt").read_text(), invalid)
        self.assertEqual(validate(result, metadata=False), [])


if __name__ == "__main__":
    unittest.main()
