"""Pipeline tests with the heavy models stubbed out, so they run in seconds without downloads."""
import numpy as np
import pytest

from analysis import emotion, pipeline, transcription
from analysis.audio import detect_speech
from conftest import SAMPLE_RATE, tone, write_wav

WORDS = [
    ("Um,", 0.5, 0.8),
    ("confidence", 0.9, 1.4),
    ("is", 1.5, 1.6),
    ("the", 1.7, 1.8),
    ("belief", 2.8, 3.2),  # 1.0 s mid-phrase pause before this word
    ("in", 3.3, 3.4),
    ("your", 3.5, 3.7),
    ("own,", 3.8, 4.0),
    ("like,", 4.1, 4.3),
    ("abilities.", 4.4, 5.0),
]


@pytest.fixture
def stub_models(monkeypatch):
    words = [{"text": text, "start": start, "end": end, "probability": 0.9} for text, start, end in WORDS]
    monkeypatch.setattr(transcription, "transcribe", lambda audio: (" ".join(w[0] for w in WORDS), [dict(w) for w in words]))
    monkeypatch.setattr(emotion, "predict_vocal_tone", lambda audio: {"arousal": 0.5, "dominance": 0.55, "valence": 0.5})
    monkeypatch.setattr(pipeline, "detect_speech", lambda audio: [(0.5, 1.8), (2.8, 5.0)])


def test_pipeline_end_to_end(tmp_path, stub_models):
    path = write_wav(tmp_path / "speech.wav", tone(150, 6.0))
    result = pipeline.analyze_recording(str(path))

    assert [w["filler"] for w in result["words"]] == [True] + [False] * 7 + [True, False]
    metrics = result["metrics"]
    assert metrics["filler_count"] == 2
    assert metrics["speaking_span"] == 4.5
    assert metrics["wpm"] == round(10 / (4.5 / 60))
    assert metrics["hesitation_pause_count"] == 1
    assert metrics["dominance"] == 0.55
    assert set(result["sub_scores"]) == {"pace", "fluency", "pauses", "expressiveness", "vocal_confidence"}
    assert 0 <= result["score"] <= 10
    assert result["warnings"], "a 4.5 s answer should get the 'speak longer' tip"


def test_silence_is_rejected_by_real_vad(tmp_path):
    path = write_wav(tmp_path / "silence.wav", np.zeros(SAMPLE_RATE * 3, dtype=np.float32))
    with pytest.raises(pipeline.AnalysisError) as error:
        pipeline.analyze_recording(str(path))
    assert error.value.status_code == 422


def test_noise_has_no_speech():
    noise = (np.random.default_rng(0).standard_normal(SAMPLE_RATE * 3) * 0.003).astype(np.float32)
    assert sum(end - start for start, end in detect_speech(noise)) < pipeline.MIN_SPEECH_SECONDS


def test_undecodable_file_is_rejected(tmp_path):
    path = tmp_path / "garbage.webm"
    path.write_bytes(b"not audio at all")
    with pytest.raises(pipeline.AnalysisError) as error:
        pipeline.analyze_recording(str(path))
    assert error.value.status_code == 400


def test_emotion_windows_fold_short_tail():
    ten = 10 * SAMPLE_RATE
    assert emotion._window_bounds(25 * SAMPLE_RATE) == [(0, ten), (ten, 2 * ten), (2 * ten, 25 * SAMPLE_RATE)]
    assert emotion._window_bounds(21 * SAMPLE_RATE) == [(0, ten), (ten, 21 * SAMPLE_RATE)]


def test_missing_emotion_model_disables_vocal_confidence():
    assert emotion.predict_vocal_tone(tone(150, 3.0)) is None
