"""Session history (detail + audio) and slide-deck endpoints."""
import io
import os

import app as app_module
from test_api import COACHING, FAKE_BASE, analyze
from test_slides import SPECS, make_pptx

DECK_REVIEW = {
    "summary": "A clear deck.",
    "dimensions": [["relevance", "Fits the topic"]],
    "scores": {"relevance": 8},
    "score": 8.0,
    "strengths": ["Clear titles"],
    "slide_feedback": [{"slide": 3, "issue": "Dense", "suggestion": "Trim it."}],
    "missing_points": [],
    "suggested_outline": ["Hook", "How it works", "Close"],
    "meta": {"provider": "test", "model": "m", "latency_ms": 1},
}


def upload_deck(client, tmp_path, name="deck.pptx", topic="Solar energy for homes", target="180"):
    path = make_pptx(tmp_path / "deck.pptx", SPECS)
    with open(path, "rb") as file:
        return client.post("/decks", data={"deck": (io.BytesIO(file.read()), name), "topic": topic, "target_seconds": target})


def test_session_detail_and_audio(client, make_user, monkeypatch):
    make_user()
    record_id = analyze(client, monkeypatch, mode="free", custom_prompt="confidence")["id"]

    detail = client.get(f"/analyses/{record_id}").get_json()
    assert detail["id"] == record_id and detail["mode"] == "free" and detail["topic"] == "confidence"
    assert detail["transcription"] == FAKE_BASE["transcription"] and detail["words"]
    assert detail["audio_url"] == f"/analyses/{record_id}/audio"

    audio = client.get(detail["audio_url"])
    assert audio.status_code == 200 and audio.data == b"fake audio" and audio.mimetype == "audio/webm"


def test_sessions_are_private(client, make_user, monkeypatch):
    make_user()
    record_id = analyze(client, monkeypatch, mode="free")["id"]
    other = app_module.app.test_client()
    make_user(other)
    assert other.get(f"/analyses/{record_id}").status_code == 404
    assert other.get(f"/analyses/{record_id}/audio").status_code == 404
    assert app_module.app.test_client().get(f"/analyses/{record_id}").status_code == 401


def test_missing_recording_file(client, make_user, monkeypatch):
    make_user()
    record_id = analyze(client, monkeypatch, mode="free")["id"]
    with app_module.app.app_context():
        filename = app_module.get_db().execute("SELECT audio_filename FROM analysis_records WHERE id = ?", (record_id,)).fetchone()[0]
    os.remove(os.path.join(app_module.UPLOAD_FOLDER, filename))
    assert client.get(f"/analyses/{record_id}").get_json()["audio_url"] is None
    assert client.get(f"/analyses/{record_id}/audio").status_code == 404


def test_tracker_redirects_to_progress_view(client):
    response = client.get("/tracker")
    assert response.status_code == 302 and response.headers["Location"].endswith("/#/progress")


def test_deck_upload_and_checks(client, make_user, tmp_path):
    make_user()
    response = upload_deck(client, tmp_path)
    assert response.status_code == 201
    deck = response.get_json()
    assert deck["filename"] == "deck.pptx" and len(deck["slides"]) == 5
    assert deck["slides"][1] == {"number": 2, "title": "Agenda", "word_count": 8, "bullets": 3, "images": 0}
    assert deck["checks"]["recommended_range"] == [2, 6] and deck["review"] is None


def test_deck_upload_rejects_bad_files(client, make_user, tmp_path):
    make_user()
    assert client.post("/decks", data={}).status_code == 400
    bad = client.post("/decks", data={"deck": (io.BytesIO(b"hello"), "notes.docx")})
    assert bad.status_code == 400 and "pptx" in bad.get_json()["error"]
    broken = client.post("/decks", data={"deck": (io.BytesIO(b"not a zip"), "deck.pptx")})
    assert broken.status_code == 400


def test_deck_review_is_cached_and_redone_when_topic_changes(client, make_user, tmp_path, monkeypatch):
    make_user()
    deck_id = upload_deck(client, tmp_path).get_json()["id"]
    calls = []

    def fake_review(outline, topic, target_seconds, checks, config):
        calls.append((topic, target_seconds, outline.splitlines()[0]))
        return DECK_REVIEW

    monkeypatch.setattr(app_module.llm, "get_config", lambda: object())
    monkeypatch.setattr(app_module.coach, "review_deck", fake_review)

    first = client.post(f"/decks/{deck_id}/review", json={}).get_json()
    again = client.post(f"/decks/{deck_id}/review", json={}).get_json()
    changed = client.post(f"/decks/{deck_id}/review", json={"topic": "Wind power", "target_seconds": 120}).get_json()
    assert first["review"]["score"] == 8.0 and again["review"] == first["review"]
    assert calls == [("Solar energy for homes", 180, "Slide 1: Solar energy for homes - Why it matters now"),
                     ("Wind power", 120, "Slide 1: Solar energy for homes - Why it matters now")]
    assert changed["topic"] == "Wind power" and changed["checks"]["recommended_range"] == [1, 4]


def test_decks_are_private(client, make_user, tmp_path):
    make_user()
    deck_id = upload_deck(client, tmp_path).get_json()["id"]
    other = app_module.app.test_client()
    make_user(other)
    assert other.post(f"/decks/{deck_id}/review", json={}).status_code == 404


def test_presentation_with_slides_feeds_the_coach(client, make_user, tmp_path, monkeypatch):
    make_user()
    deck_id = upload_deck(client, tmp_path).get_json()["id"]
    body = analyze(client, monkeypatch, mode="presentation", custom_prompt="Solar energy", deck_id=str(deck_id), target_seconds="180")
    assert body["context"]["deck"]["slide_count"] == 5
    assert body["context"]["deck"]["outline"].startswith("Slide 1: Solar energy for homes")
    assert "slides_match" in body

    captured = {}

    def fake_coach(transcript, context, analysis, config, coach_config, dimensions):
        captured.update(dimensions=dimensions, deck=context.get("deck"))
        return COACHING

    monkeypatch.setattr(app_module.llm, "get_config", lambda: object())
    monkeypatch.setattr(app_module.coach, "coach_answer", fake_coach)
    client.post(f"/analyses/{body['id']}/coach")
    assert captured["dimensions"][-1] == ("alignment", "Matches your slides") and captured["deck"]["id"] == deck_id


def test_slides_are_ignored_outside_presentation_mode(client, make_user, tmp_path, monkeypatch):
    make_user()
    deck_id = upload_deck(client, tmp_path).get_json()["id"]
    body = analyze(client, monkeypatch, mode="free", deck_id=str(deck_id))
    assert "deck" not in body["context"]
