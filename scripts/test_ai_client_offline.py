"""Offline routing, timeout, and sanitized diagnostic checks."""

from contextlib import redirect_stderr
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from backend import ai_client as client
from scripts import extract_knowledge as extraction
from scripts.test_knowledge_pipeline import sample


class ClientTests(unittest.TestCase):
    def test_response_preserves_stop_reason_and_requested_budget(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-marker"}, clear=True), patch.object(
                client, "_post", return_value={"content": [{"type": "text", "text": "partial"}], "stop_reason": "max_tokens"}) as post:
            response = client.generate("hello", provider="claude", max_tokens=8000)
        self.assertEqual(response, "partial")
        self.assertEqual(response.stop_reason, "max_tokens")
        self.assertEqual(post.call_args.args[1]["max_tokens"], 8000)

    def test_http_error_is_visible_before_fallback_and_redacted(self):
        marker = "synthetic-credential-for-offline-check"
        body = json.dumps({"error": {"type": "not_found_error", "message": "Unknown model; " + marker}}).encode()
        error = HTTPError("https://api.anthropic.com/v1/messages", 404, "Not Found", {}, io.BytesIO(body))
        stderr = io.StringIO()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": marker, "AI_PROVIDER": "auto", "LOCAL_ENDPOINT_URL": "http://localhost/mock", "LOCAL_MODEL": "test-local"}, clear=True), patch.object(client, "_post", side_effect=[error, {"choices": [{"message": {"content": "fallback response"}}]}]) as post, redirect_stderr(stderr):
            self.assertEqual(client.generate("hello"), "fallback response")
        message = stderr.getvalue()
        self.assertIn("HTTPError", message)
        self.assertIn("not_found_error", message)
        self.assertIn("Unknown model", message)
        self.assertNotIn(marker, message)
        self.assertEqual(post.call_args_list[0].kwargs["timeout"], 30)
        self.assertEqual(post.call_args.args[0], "http://localhost/mock")
        self.assertEqual(post.call_args.args[1]["model"], "test-local")
        self.assertEqual(post.call_args.args[2], {})

    def test_forced_claude_raises_reason_without_fallback(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-marker", "AI_PROVIDER": "claude"}, clear=True), patch.object(client, "_post", side_effect=TimeoutError("request timed out synthetic-marker")) as post:
            with self.assertRaises(client.AIClientError) as caught:
                client.generate("hello", timeout=120)
        self.assertIn("TimeoutError", str(caught.exception))
        self.assertIn("request timed out", str(caught.exception))
        self.assertNotIn("synthetic-marker", str(caught.exception))
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["timeout"], 120)

    def test_extraction_forces_claude_and_long_timeout(self):
        with patch.object(extraction, "generate", return_value=json.dumps(sample())) as generate:
            extraction.request_knowledge("Title", "safety", "Text")
        self.assertEqual(generate.call_args.kwargs, {"provider": "claude", "timeout": 120, "max_tokens": 4096})


if __name__ == "__main__":
    unittest.main()
