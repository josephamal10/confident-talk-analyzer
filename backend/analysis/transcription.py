"""Speech-to-text with faster-whisper (CTranslate2, int8 on CPU) and word-level timestamps."""
import logging
import os
import threading

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("WHISPER_MODEL", "small.en").strip() or "small.en"
# Whisper normally cleans "um"/"uh" out of its output; a prompt written in the same
# disfluent style makes it keep them (and set "like," off with commas).
FILLER_PROMPT = "Um, well, uh, I was, like, thinking about it, you know. Hmm, okay, so."
# Whisper reports a high compression ratio when it gets stuck repeating a phrase.
LOOP_COMPRESSION_RATIO = 2.4

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            logger.info("Loading faster-whisper model %s", MODEL_NAME)
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def _decode(audio, **options):
    segments, _info = get_model().transcribe(
        audio,
        language="en",
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=True,
        **options,
    )
    return list(segments)


def _is_repetition_loop(segments):
    return any(segment.compression_ratio > LOOP_COMPRESSION_RATIO for segment in segments)


def transcribe(audio):
    """Returns (text, words); each word is {text, start, end, probability}. Both are empty if unreliable."""
    segments = _decode(audio, initial_prompt=FILLER_PROMPT, temperature=0.0)
    if _is_repetition_loop(segments):
        # The filler prompt occasionally causes a loop ("Good morning. Good morning. ...");
        # retry without it and let Whisper raise the temperature on segments that still loop.
        logger.info("Repetition loop detected; retrying without the filler prompt.")
        segments = _decode(audio, temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    if _is_repetition_loop(segments):
        return "", []

    words = [
        {
            "text": word.word.strip(),
            "start": round(word.start, 2),
            "end": round(word.end, 2),
            "probability": round(word.probability, 3),
        }
        for segment in segments
        for word in segment.words or []
        if word.word.strip()
    ]
    return " ".join(word["text"] for word in words), words
