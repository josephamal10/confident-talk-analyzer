import io
import os

import numpy as np

import app as app_module
from analysis import AnalysisError
from conftest import SAMPLE_RATE, write_wav

FAKE_RESULT = {
    "transcription": "Confidence is the belief in your own abilities.",
    "transcription_model": "faster-whisper/test",
    "words": [{"text": "Confidence", "start": 0.0, "end": 0.5, "filler": False}],
    "pauses": [],
    "metrics": {
        "duration": 20.0,
        "speaking_span": 18.0,
        "word_count": 45,
        "wpm": 150,
        "filler_count": 1,
        "fillers_per_100_words": 2.2,
        "top_filler": "um",
        "pause_count": 2,
        "hesitation_pause_count": 0,
        "hesitation_pauses_per_minute": 0.0,
        "longest_pause": 0.7,
        "pitch_variation": 3.2,
        "dominance": 0.55,
    },
    "vocal_tone": {"arousal": 0.5, "dominance": 0.55, "valence": 0.5},
    "sub_scores": {"pace": 10.0, "fluency": 8.7, "pauses": 10.0, "expressiveness": 8.8, "vocal_confidence": 8.6},
    "score": 9.2,
    "delivery": "Confident",
    "warnings": [],
    "timings_ms": {"transcription": 1},
}


def upload(data=b"fake audio"):
    return {"audio": (io.BytesIO(data), "recording.webm"), "topic": "confidence"}


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


def test_analyze_saves_to_the_logged_in_user_only(client, make_user, monkeypatch):
    monkeypatch.setattr(app_module, "analyze_recording", lambda path: FAKE_RESULT)
    make_user()

    body = client.post("/analyze", data=upload()).get_json()
    assert body["score"] == 9.2
    assert body["delivery"] == "Confident"
    assert body["sub_scores"]["fluency"] == 8.7
    assert body["feedback"].startswith("Overall 9.2/10 (Confident).")

    history = client.get("/history").get_json()
    assert history["count"] == 1
    assert history["history"][0]["delivery"] == "Confident"
    assert history["history"][0]["sub_scores"]["pace"] == 10.0

    other = app_module.app.test_client()
    make_user(other)
    assert other.get("/history").get_json()["count"] == 0


def test_analysis_errors_are_returned_and_upload_discarded(client, make_user, monkeypatch):
    def reject(path):
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
    response = client.post("/analyze", data={"audio": (open(path, "rb"), "recording.wav")})
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
