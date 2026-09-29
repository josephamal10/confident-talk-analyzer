import io
import os

import numpy as np

import app as app_module
from analysis import AnalysisError
from conftest import SAMPLE_RATE, write_wav

TRANSCRIPT = (
    "Confidence is the belief in your own abilities and decisions. It helps a person face challenges, "
    "speak clearly and take action without too much fear or doubt."
)
WORDS = [
    {"text": text, "start": round(0.5 + i * 0.4, 2), "end": round(0.8 + i * 0.4, 2), "probability": 0.9, "filler": False}
    for i, text in enumerate(TRANSCRIPT.split())
]
SPAN = WORDS[-1]["end"] - WORDS[0]["start"]
FAKE_BASE = {
    "transcription": TRANSCRIPT,
    "transcription_model": "faster-whisper/test",
    "words": WORDS,
    "pauses": [],
    "unclear_indexes": [],
    "uptalk": None,
    "timeline": [],
    "metrics": {
        "duration": SPAN + 1.0,
        "speaking_span": SPAN,
        "word_count": len(WORDS),
        "wpm": round(len(WORDS) / (SPAN / 60)),
        "filler_count": 0,
        "fillers_per_100_words": 0.0,
        "top_filler": None,
        "pause_count": 0,
        "hesitation_pause_count": 0,
        "hesitation_pauses_per_minute": 0.0,
        "longest_pause": 0.0,
        "start_delay": 0.5,
        "pitch_variation": 3.2,
        "dominance": 0.55,
        "unclear_word_share": 0.0,
        "uptalk_share": None,
    },
    "vocal_tone": {"arousal": 0.5, "dominance": 0.55, "valence": 0.5},
    "warnings": [],
    "timings_ms": {"transcription": 1},
}

COACHING = {
    "summary": "Clear answer.",
    "dimensions": [["structure", "Structure"], ["clarity", "Clarity"], ["relevance", "Relevance"], ["depth", "Depth"]],
    "content_scores": {"structure": 8, "clarity": 8, "relevance": 9, "depth": 6},
    "content_score": 7.8,
    "strengths": ["Direct"],
    "improvements": [{"issue": "Thin result", "suggestion": "Quantify the outcome."}],
    "framework": {"name": "STAR", "parts": ["Situation", "Task", "Action", "Result"], "present": ["Situation"], "missing": []},
    "on_topic": True,
    "topic_feedback": "Answers the question.",
    "improved_answer": "In my final year...",
    "improved_answer_type": "rewrite",
    "meta": {"provider": "test", "model": "test-model", "latency_ms": 5},
}


def upload(data=b"fake audio", **fields):
    return {"audio": (io.BytesIO(data), "recording.webm"), **fields}


def analyze(client, monkeypatch, **fields):
    monkeypatch.setattr(app_module, "analyze_recording", lambda path, report=None: FAKE_BASE)
    return client.post("/analyze", data=upload(**fields)).get_json()


def test_protected_routes_require_login(client):
    assert client.get("/me").status_code == 401
    assert client.get("/history").status_code == 401
    assert client.post("/analyze", data=upload()).status_code == 401


def test_register_login_logout(client):
    payload = {"name": "Ada", "email": "ada@example.com", "password": "password123"}
    assert client.post("/register", json=payload).status_code == 201
    assert client.post("/register", json={**payload, "email": "ADA@example.com"}).status_code == 409
    assert client.post("/login", json={"email": "ada@example.com", "password": "wrong-pass"}).status_code == 401

    response = client.post("/login", json={"email": "ada@example.com", "password": "password123"})
    assert response.status_code == 200
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert client.get("/me").get_json()["user"]["email"] == "ada@example.com"

    assert client.post("/logout").status_code == 200
    assert client.get("/me").status_code == 401


def test_mode_catalog(client):
    body = client.get("/modes").get_json()
    assert [mode["id"] for mode in body["modes"]][0] == "free"
    assert body["coach_available"] is False
    assert body["interview"] and body["passages"] and body["banks"]["jam_topics"]


def test_analyze_saves_to_the_logged_in_user_only(client, make_user, monkeypatch):
    make_user()
    body = analyze(client, monkeypatch, mode="free", custom_prompt="confidence")
    assert body["context"]["mode"] == "free" and body["context"]["prompt"] == "confidence"
    assert set(body["sub_scores"]) == set(app_module.modes.get_mode("free")["weights"])
    assert body["feedback"].startswith(f"Overall {body['score']}/10 ({body['delivery']}).")
    assert body["language"]["hedges"] == [] and body["reading"] is None

    history = client.get("/history").get_json()
    assert history["count"] == 1
    entry = history["history"][0]
    assert entry["mode"] == "free" and entry["delivery"] == body["delivery"] and entry["sub_scores"]

    other = app_module.app.test_client()
    make_user(other)
    assert other.get("/history").get_json()["count"] == 0


def test_interview_mode_records_the_question(client, make_user, monkeypatch):
    make_user()
    body = analyze(client, monkeypatch, mode="interview", prompt_id="behavioral-1")
    assert body["id"] > 0 and body["coach_available"] is False
    assert body["context"]["framework"]["name"] == "STAR"
    history = client.get("/history").get_json()["history"]
    assert history[-1]["topic"].startswith("Tell me about a time you faced a conflict")
    assert history[-1]["mode"] == "interview"


def test_read_mode_returns_reading_alignment(client, make_user, monkeypatch):
    make_user()
    body = analyze(client, monkeypatch, mode="read", custom_script=TRANSCRIPT)
    assert body["reading"]["accuracy"] == 1.0
    assert body["sub_scores"]["accuracy"] == 10.0
    assert body["coach_available"] is False


def test_jam_mode_returns_referee(client, make_user, monkeypatch):
    make_user()
    body = analyze(client, monkeypatch, mode="jam", prompt_id="jam_topics-1")
    assert body["context"]["prompt"] == "Umbrellas" and body["referee"]["counts"]["hesitation"] == 0


def test_analysis_errors_are_returned_and_upload_discarded(client, make_user, monkeypatch):
    def reject(path, report=None):
        raise AnalysisError("No speech was detected.", 422)

    monkeypatch.setattr(app_module, "analyze_recording", reject)
    make_user()
    before = set(os.listdir(app_module.UPLOAD_FOLDER))
    response = client.post("/analyze", data=upload())
    assert response.status_code == 422
    assert response.get_json()["error"] == "No speech was detected."
    assert set(os.listdir(app_module.UPLOAD_FOLDER)) == before
    assert client.get("/history").get_json()["count"] == 0


def test_silent_recording_end_to_end(client, make_user, tmp_path):
    make_user()
    path = write_wav(tmp_path / "silence.wav", np.zeros(SAMPLE_RATE * 2, dtype=np.float32))
    with open(path, "rb") as file:
        response = client.post("/analyze", data={"audio": (file, "recording.wav")})
    assert response.status_code == 422


def test_oversized_upload_returns_json(client, make_user):
    make_user()
    limit = app_module.app.config["MAX_CONTENT_LENGTH"]
    app_module.app.config["MAX_CONTENT_LENGTH"] = 1024
    try:
        response = client.post("/analyze", data=upload(b"0" * 5000))
    finally:
        app_module.app.config["MAX_CONTENT_LENGTH"] = limit
    assert response.status_code == 413
    assert "error" in response.get_json()


def test_coach_disabled_returns_503(client, make_user, monkeypatch):
    make_user()
    record_id = analyze(client, monkeypatch, mode="interview", prompt_id="behavioral-1")["id"]
    response = client.post(f"/analyses/{record_id}/coach")
    assert response.status_code == 503
    assert response.get_json()["code"] == "coach_disabled"


def test_read_mode_is_not_coached(client, make_user, monkeypatch):
    make_user()
    record_id = analyze(client, monkeypatch, mode="read", custom_script=TRANSCRIPT)["id"]
    monkeypatch.setattr(app_module.llm, "get_config", lambda: object())
    assert client.post(f"/analyses/{record_id}/coach").status_code == 400


def test_coach_generates_once_then_serves_cached(client, make_user, monkeypatch):
    make_user()
    record_id = analyze(client, monkeypatch, mode="pitch", prompt_id="pitch_prompts-1", target_seconds="30")["id"]
    calls = []

    def fake_coach(transcript, context, analysis, config, coach_config, dimensions):
        calls.append((context["prompt"], context["target_seconds"], coach_config["dimensions"], dimensions[0]))
        return COACHING

    monkeypatch.setattr(app_module.llm, "get_config", lambda: object())
    monkeypatch.setattr(app_module.coach, "coach_answer", fake_coach)

    first = client.post(f"/analyses/{record_id}/coach").get_json()
    second = client.post(f"/analyses/{record_id}/coach").get_json()
    assert first["coach"]["content_score"] == 7.8 and first["cached"] is False
    assert second["cached"] is True and len(calls) == 1
    assert calls[0] == ("Pitch yourself for your dream internship", 30, "pitch", ("hook", "Hook"))


def test_coach_errors_pass_through_status(client, make_user, monkeypatch):
    make_user()
    record_id = analyze(client, monkeypatch, mode="interview", prompt_id="behavioral-1")["id"]

    def rate_limited(*args):
        raise app_module.llm.LLMError("Rate limited.", retryable=True, status_code=429)

    monkeypatch.setattr(app_module.llm, "get_config", lambda: object())
    monkeypatch.setattr(app_module.coach, "coach_answer", rate_limited)
    response = client.post(f"/analyses/{record_id}/coach")
    assert response.status_code == 429
    assert response.get_json() == {"error": "Rate limited.", "retryable": True}


def test_coach_is_scoped_to_the_owner(client, make_user, monkeypatch):
    make_user()
    record_id = analyze(client, monkeypatch, mode="interview", prompt_id="behavioral-1")["id"]
    other = app_module.app.test_client()
    make_user(other)
    assert other.post(f"/analyses/{record_id}/coach").status_code == 404


def test_progress_endpoint(client, make_user, monkeypatch):
    make_user()
    analyze(client, monkeypatch, mode="jam", prompt_id="jam_topics-1")
    analyze(client, monkeypatch, mode="free")
    everything = client.get("/progress").get_json()
    assert everything["sessions"] == 2 and everything["streak"] == 1
    jam_only = client.get("/progress?mode=jam").get_json()
    assert jam_only["sessions"] == 1 and jam_only["mode"] == "jam"
    assert client.get("/progress?mode=karaoke").get_json()["mode"] is None
