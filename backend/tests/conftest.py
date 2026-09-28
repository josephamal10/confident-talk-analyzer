import os
import tempfile
import wave

import numpy as np
import pytest

# Point the app at throwaway storage before it is imported.
_TMP = tempfile.mkdtemp(prefix="cta-tests-")
os.environ.setdefault("DATABASE_PATH", os.path.join(_TMP, "test.db"))
os.environ.setdefault("UPLOAD_FOLDER", os.path.join(_TMP, "uploads"))
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("EMOTION_MODEL_PATH", os.path.join(_TMP, "missing-model.onnx"))
# Never call a real LLM from tests, even if backend/.env has an API key.
os.environ["LLM_PROVIDER"] = "none"

import app as app_module  # noqa: E402
from analysis import relevance  # noqa: E402

# Use keyword topic matching unless a test stubs the embedding model (avoids a 90 MB download in CI).
relevance._load_failed = True

SAMPLE_RATE = 16000


def write_wav(path, samples, sample_rate=SAMPLE_RATE):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(pcm.tobytes())
    return path


def tone(frequency_hz, seconds, amplitude=0.3):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * frequency_hz * t)).astype(np.float32)


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def make_user(client):
    counter = {"n": 0}

    def _make_user(test_client=None, password="password123"):
        counter["n"] += 1
        email = f"user{counter['n']}-{os.urandom(3).hex()}@example.com"
        target = test_client or client
        target.post("/register", json={"name": "Test User", "email": email, "password": password})
        response = target.post("/login", json={"email": email, "password": password})
        assert response.status_code == 200
        return email

    return _make_user
