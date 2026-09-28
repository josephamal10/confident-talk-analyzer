import json

import httpx
import pytest

from analysis import llm

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}
CONFIG = llm.LLMConfig("groq", "https://api.test/v1", "test-model", "secret-key", "low")


def completion(content, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 42}})


@pytest.fixture
def mock_api(monkeypatch):
    """Serves queued responses and records requests, so tests never touch the network."""
    requests, responses = [], []

    def handler(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    return requests, responses


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_config_disabled_without_keys(clean_env):
    assert llm.get_config() is None


def test_config_picks_provider_from_available_key(clean_env):
    clean_env.setenv("GROQ_API_KEY", "gsk_test")
    config = llm.get_config()
    assert (config.provider, config.base_url, config.api_key) == ("groq", "https://api.groq.com/openai/v1", "gsk_test")


def test_config_overrides_and_explicit_disable(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "g_test")
    clean_env.setenv("LLM_PROVIDER", "gemini")
    clean_env.setenv("LLM_MODEL", "custom-model")
    assert llm.get_config().model == "custom-model"
    clean_env.setenv("LLM_PROVIDER", "none")
    assert llm.get_config() is None


def test_config_ollama_needs_no_key(clean_env):
    clean_env.setenv("LLM_PROVIDER", "ollama")
    config = llm.get_config()
    assert config.api_key is None and config.base_url == "http://localhost:11434/v1"


def test_chat_json_sends_strict_schema_and_parses(mock_api):
    requests, responses = mock_api
    responses.append(completion(json.dumps({"answer": "hi"})))

    result, meta = llm.chat_json(CONFIG, [{"role": "user", "content": "hello"}], SCHEMA, "reply")

    assert result == {"answer": "hi"}
    assert meta["model"] == "test-model" and meta["usage"] == {"total_tokens": 42}
    sent = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://api.test/v1/chat/completions"
    assert requests[0].headers["Authorization"] == "Bearer secret-key"
    assert sent["response_format"]["json_schema"] == {"name": "reply", "strict": True, "schema": SCHEMA}
    assert sent["reasoning_effort"] == "low"


def test_chat_json_retries_once_on_invalid_json(mock_api):
    _requests, responses = mock_api
    responses.extend([completion("not json"), completion(json.dumps({"answer": "ok"}))])
    assert llm.chat_json(CONFIG, [], SCHEMA, "reply")[0] == {"answer": "ok"}


def test_chat_json_rejects_schema_violations(mock_api):
    _requests, responses = mock_api
    responses.extend([completion(json.dumps({"wrong": 1})), completion(json.dumps({"answer": 5}))])
    with pytest.raises(llm.LLMError) as error:
        llm.chat_json(CONFIG, [], SCHEMA, "reply")
    assert error.value.retryable


@pytest.mark.parametrize(
    "response, status_code, retryable",
    [
        (httpx.Response(429, json={}), 429, True),
        (httpx.Response(401, json={}), 502, False),
        (httpx.Response(500, json={}), 502, True),
        (httpx.ReadTimeout("slow"), 504, True),
        (httpx.ConnectError("offline"), 503, True),
    ],
)
def test_chat_json_maps_failures(mock_api, response, status_code, retryable):
    _requests, responses = mock_api
    responses.append(response)
    with pytest.raises(llm.LLMError) as error:
        llm.chat_json(CONFIG, [], SCHEMA, "reply")
    assert (error.value.status_code, error.value.retryable) == (status_code, retryable)
