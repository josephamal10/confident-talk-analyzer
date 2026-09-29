"""Minimal client for OpenAI-compatible chat APIs (Groq, Google Gemini, Ollama) with structured JSON output.

There is no vendor SDK: one HTTP call through httpx, so switching provider is only configuration.
Responses are requested as strict JSON Schema output and validated again locally, because not
every provider enforces the schema.
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from jsonschema import ValidationError, validate

logger = logging.getLogger(__name__)

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "api_key_env": "GROQ_API_KEY",
        "reasoning_effort": "low",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.8-flash",
        "api_key_env": "GEMINI_API_KEY",
        "reasoning_effort": "low",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "api_key_env": None,
        "reasoning_effort": None,
    },
}
TIMEOUT_SECONDS = 45

# Tests replace this with httpx.MockTransport to run without network access.
_transport = None


class LLMError(Exception):
    """The request failed. `retryable` means trying again later may work (rate limit, timeout)."""

    def __init__(self, message, retryable=False, status_code=502):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    base_url: str
    model: str
    api_key: Optional[str]
    reasoning_effort: Optional[str]


def get_config():
    """Builds the config from LLM_* / provider key env vars; returns None when no LLM is configured.

    LLM_PROVIDER picks a preset (groq, gemini, ollama); without it the first provider whose API
    key is set is used. LLM_MODEL, LLM_BASE_URL and LLM_API_KEY override the preset, which also
    allows any other OpenAI-compatible server.
    """
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider in ("none", "disabled", "off"):
        return None
    if not provider:
        provider = next(
            (name for name, preset in PROVIDERS.items() if preset["api_key_env"] and os.getenv(preset["api_key_env"])),
            "",
        )
        if not provider:
            return None

    preset = PROVIDERS.get(provider, {"base_url": None, "model": None, "api_key_env": None, "reasoning_effort": None})
    api_key = os.getenv("LLM_API_KEY") or (os.getenv(preset["api_key_env"]) if preset["api_key_env"] else None)
    base_url = os.getenv("LLM_BASE_URL") or preset["base_url"]
    model = os.getenv("LLM_MODEL") or preset["model"]
    if not base_url or not model or (preset["api_key_env"] and not api_key):
        return None
    return LLMConfig(provider, base_url.rstrip("/"), model, api_key, preset["reasoning_effort"])


def _post(config, body):
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=_transport) as client:
            response = client.post(f"{config.base_url}/chat/completions", json=body, headers=headers)
    except httpx.TimeoutException as error:
        raise LLMError("The AI coach timed out. Please try again.", retryable=True, status_code=504) from error
    except httpx.HTTPError as error:
        raise LLMError("Could not reach the AI coach service.", retryable=True, status_code=503) from error

    if response.status_code == 429:
        raise LLMError(
            "The AI coach hit its free-tier rate limit. Try again in a minute.", retryable=True, status_code=429
        )
    if response.status_code in (401, 403):
        logger.error("LLM provider rejected the API key (HTTP %s).", response.status_code)
        raise LLMError("The AI coach is misconfigured on the server.")
    if response.status_code >= 400:
        logger.warning("LLM request failed with HTTP %s: %s", response.status_code, response.text[:500])
        raise LLMError("The AI coach could not process this answer.", retryable=response.status_code >= 500)
    return response.json()


def chat_json(config, messages, schema, schema_name, max_tokens=1500, temperature=0.1):
    """Sends a chat request and returns (parsed_json, meta). Retries once if the JSON is invalid."""
    body = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    if config.reasoning_effort:
        body["reasoning_effort"] = config.reasoning_effort

    for attempt in (1, 2):
        started = time.perf_counter()
        data = _post(config, body)
        latency_ms = round((time.perf_counter() - started) * 1000)
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        try:
            result = json.loads(content)
            validate(result, schema)
        except (json.JSONDecodeError, ValidationError) as error:
            logger.warning("LLM returned invalid JSON (attempt %s): %s", attempt, str(error)[:200])
            continue
        meta = {
            "provider": config.provider,
            "model": config.model,
            "latency_ms": latency_ms,
            "usage": data.get("usage"),
        }
        logger.info("LLM %s/%s answered in %s ms, usage %s", config.provider, config.model, latency_ms, data.get("usage"))
        return result, meta
    raise LLMError("The AI coach returned an invalid response. Please try again.", retryable=True)
