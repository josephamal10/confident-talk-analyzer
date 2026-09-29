"""Dimensional speech emotion recognition (arousal, dominance, valence) with ONNX Runtime.

Model: audeering's wav2vec2-large-robust-12-ft-emotion-msp-dim, trained on MSP-Podcast
(natural rather than acted speech), quantized to int8 by scripts/prepare_emotion_model.py.
License: CC BY-NC-SA 4.0. "Dominance" is how assertive and in control a voice sounds, which
the app uses as its vocal-confidence signal.
"""
import logging
import os
import threading

import numpy as np

from .audio import SAMPLE_RATE

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "emotion-w2v2-int8.onnx"
)
MODEL_PATH = os.getenv("EMOTION_MODEL_PATH", DEFAULT_MODEL_PATH)
DIMENSIONS = ("arousal", "dominance", "valence")
# The model was trained on podcast segments of about 3-11 s, and attention memory grows with
# the square of the input length, so recordings are scored in 10 s windows and averaged.
WINDOW_SECONDS = 10
MIN_WINDOW_SECONDS = 1.5

_session = None
_session_lock = threading.Lock()
_missing_model_logged = False


def get_session():
    global _session, _missing_model_logged
    with _session_lock:
        if _session is None:
            if not os.path.exists(MODEL_PATH):
                if not _missing_model_logged:
                    logger.warning(
                        "Emotion model not found at %s; run scripts/prepare_emotion_model.py. "
                        "Vocal-confidence scoring is disabled.",
                        MODEL_PATH,
                    )
                    _missing_model_logged = True
                return None
            import onnxruntime

            logger.info("Loading emotion model %s", MODEL_PATH)
            _session = onnxruntime.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
    return _session


def window_bounds(sample_count):
    window = WINDOW_SECONDS * SAMPLE_RATE
    starts = list(range(0, sample_count, window))
    # Fold a short tail into the previous window instead of scoring a fragment on its own.
    if len(starts) > 1 and sample_count - starts[-1] < MIN_WINDOW_SECONDS * SAMPLE_RATE:
        starts.pop()
    ends = starts[1:] + [sample_count]
    return list(zip(starts, ends))


def predict_vocal_tone(audio):
    """Returns {"arousal", "dominance", "valence"} (about 0..1) for the clip plus the same values per
    10 s window under "windows", or None if the model is unavailable."""
    if len(audio) < MIN_WINDOW_SECONDS * SAMPLE_RATE:
        return None
    session = get_session()
    if session is None:
        return None

    predictions, weights = [], []
    for start, end in window_bounds(len(audio)):
        window = audio[start:end].astype(np.float32)[np.newaxis, :]
        predictions.append(session.run(["logits"], {"signal": window})[0][0])
        weights.append(end - start)
    averaged = np.average(predictions, axis=0, weights=weights)
    tone = {name: round(float(value), 3) for name, value in zip(DIMENSIONS, averaged)}
    tone["windows"] = [{name: round(float(value), 3) for name, value in zip(DIMENSIONS, p)} for p in predictions]
    return tone
