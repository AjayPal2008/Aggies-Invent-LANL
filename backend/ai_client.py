"""Claude-first generation with an OpenAI-compatible local fallback.

Set AI_PROVIDER to auto (default), claude, or local in the terminal.
Set LOCAL_ENDPOINT_URL and LOCAL_MODEL for the OpenAI-compatible local server.
Forced modes call only the selected provider. Forced local needs no Claude key.
No credential files are accessed. Only Python's standard library is required.
"""

CLAUDE_MODEL = "claude-sonnet-5-5"
LOCAL_ENDPOINT_URL = ""  # TODO: Set your local /v1/chat/completions URL here.
LOCAL_MODEL = "local-model"  # TODO: Set the model identifier your local server uses.
TIMEOUT_SECONDS = 30
EXTRACTION_TIMEOUT_SECONDS = 120
MAX_TOKENS = 4096

import json
import os
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


class AIClientError(RuntimeError):
    """A sanitized configuration or generation error."""


class GenerationResponse(str):
    """String-compatible response carrying provider completion metadata."""

    def __new__(cls, text, *, stop_reason=None):
        response = super().__new__(cls, text)
        response.stop_reason = stop_reason
        return response


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward Claude authentication headers to a redirected host.
        return None


def _post(url: str, payload: dict, headers: dict, *, timeout: float = TIMEOUT_SECONDS) -> dict:
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    with build_opener(_NoRedirects()).open(request, timeout=timeout) as response:
        return json.load(response)


def redact_secrets(message: str) -> str:
    """Redact credentials in diagnostics/debug text without accessing files."""
    return _redact(message, os.environ.get("ANTHROPIC_API_KEY"))


def _redact(message: str, key: str | None) -> str:
    if key:
        for value in (key, key.strip(), quote(key, safe=""), json.dumps(key)[1:-1]):
            if value:
                message = message.replace(value, "[REDACTED]")
    message = re.sub(r"sk-ant-[A-Za-z0-9_-]+", "[REDACTED]", message)
    message = re.sub(r"(?i)((?:x-api-key|authorization|ANTHROPIC_API_KEY)\s*[:=]\s*)[^\r\n,;]+",
                     r"\1[REDACTED]", message)
    return message


def _sanitize(message: str, key: str | None) -> str:
    return " ".join(_redact(message, key).split())[:1500]


def _claude_failure(exc: Exception, key: str) -> str:
    # HTTPError.__str__ omits the API's useful JSON error message. Read only
    # the error response body, never request headers or credential files.
    detail = str(exc)
    if isinstance(exc, HTTPError):
        detail = f"HTTP {exc.code}: {exc.reason}"
        try:
            error = json.loads(exc.read(65536)).get("error", {})
            if isinstance(error, dict):
                kind, message = error.get("type"), error.get("message")
                if isinstance(kind, str) and isinstance(message, str):
                    detail += f"; {kind}: {message}"
        except Exception:
            pass
        finally:
            exc.close()
    return _sanitize(f"Claude {type(exc).__name__}: {detail}", key)


def _claude(prompt: str, key: str, timeout: float, max_tokens: int) -> str:
    data = _post("https://api.anthropic.com/v1/messages", {
        "model": CLAUDE_MODEL, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }, {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=timeout)
    text = "\n".join(block["text"] for block in data["content"] if block.get("type") == "text")
    if not text.strip():
        raise ValueError("Empty response")
    return GenerationResponse(text, stop_reason=data.get("stop_reason"))


def _local(prompt: str) -> str:
    endpoint = os.environ.get("LOCAL_ENDPOINT_URL", LOCAL_ENDPOINT_URL)
    if not endpoint:
        raise AIClientError("Set LOCAL_ENDPOINT_URL and LOCAL_MODEL in the terminal.")
    data = _post(endpoint, {
        "model": os.environ.get("LOCAL_MODEL", LOCAL_MODEL), "max_tokens": MAX_TOKENS, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }, {})  # Claude credentials are never sent to the local endpoint.
    text = data["choices"][0]["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty response")
    return text


def generate(prompt: str, *, provider: str | None = None,
             timeout: float = TIMEOUT_SECONDS, max_tokens: int = MAX_TOKENS) -> str:
    """Return response text; auto falls back on Claude errors/timeouts.

    provider overrides AI_PROVIDER for a single call. Missing Claude credentials
    are a configuration error in auto/claude mode, rather than a fallback trigger.
    timeout controls Claude requests; extraction supplies 120 seconds. Claude
    failures include sanitized diagnostics; forced claude never falls back.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise AIClientError("Provide a non-empty prompt.")
    if not isinstance(timeout, (int, float)) or not 0 < timeout < float("inf"):
        raise AIClientError("timeout must be a positive finite number of seconds.")
    if type(max_tokens) is not int or max_tokens < 1:
        raise AIClientError("max_tokens must be a positive integer.")
    mode = provider if provider is not None else os.environ.get("AI_PROVIDER", "auto")
    if mode not in ("auto", "claude", "local"):
        raise AIClientError("AI_PROVIDER must be auto, claude, or local.")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if mode != "local" and (not key or not key.strip()):
        raise AIClientError("Set ANTHROPIC_API_KEY in the terminal before using Claude.")

    text = None
    failure = None
    if mode != "local":
        try:
            text = _claude(prompt, key, timeout, max_tokens)
        except Exception as exc:
            failure = _claude_failure(exc, key)
        if text is None and mode == "claude":
            raise AIClientError(failure) from None
        if failure:
            print(f"{failure}; falling back to local model.", file=sys.stderr)
    if text is None:
        if not os.environ.get("LOCAL_ENDPOINT_URL", LOCAL_ENDPOINT_URL):
            raise AIClientError("Local endpoint is not configured. Set LOCAL_ENDPOINT_URL and LOCAL_MODEL in the terminal.")
        try:
            text = _local(prompt)
        except Exception:
            pass
        if text is None:
            raise AIClientError("Local model request failed or timed out.") from None
    # Guard even against a provider returning the credential in response text.
    return GenerationResponse(_redact(text, key), stop_reason=getattr(text, "stop_reason", None))
