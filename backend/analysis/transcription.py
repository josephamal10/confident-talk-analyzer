"""Speech-to-text with faster-whisper (CTranslate2, int8 on CPU) and word-level timestamps."""
import logging
import os
import threading

from faster_whisper import WhisperModel

from .audio import SAMPLE_RATE, detect_speech
from .runtime import cpu_threads

logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("WHISPER_MODEL", "small.en").strip() or "small.en"
# Whisper normally cleans "um"/"uh" out of its output; a prompt written in the same
# disfluent style makes it keep them (and set "like," off with commas).
FILLER_PROMPT = "Um, well, uh, I was, like, thinking about it, you know. Hmm, okay, so."
# Whisper reports a high compression ratio when it gets stuck repeating a phrase.
LOOP_COMPRESSION_RATIO = 2.4
RETRY_TEMPERATURES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
# Detected speech this long with no word in it means Whisper skipped it. Word timings are a
# little loose, so each word is taken to cover WORD_PAD seconds either side.
MISSED_SPEECH_SECONDS = 1.0
WORD_PAD = 0.3

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            logger.info("Loading faster-whisper model %s", MODEL_NAME)
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=cpu_threads())
    return _model


def _decode(audio, model=None, **options):
    segments, _info = (model or get_model()).transcribe(
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


def _words(segments):
    return [
        {
            "text": word.word.strip(),
            "start": round(float(word.start), 2),
            "end": round(float(word.end), 2),
            "probability": round(float(word.probability), 3),
        }
        for segment in segments
        for word in segment.words or []
        if word.word.strip()
    ]


def missed_speech(words, speech_regions):
    """Stretches of detected speech, at least MISSED_SPEECH_SECONDS long, that no word covers."""
    covered = sorted((word["start"] - WORD_PAD, word["end"] + WORD_PAD) for word in words)
    missed = []
    for start, end in speech_regions:
        cursor = start
        for word_start, word_end in covered:
            if word_end <= cursor or word_start >= end:
                continue
            if word_start - cursor >= MISSED_SPEECH_SECONDS:
                missed.append((cursor, word_start))
            cursor = max(cursor, word_end)
        if end - cursor >= MISSED_SPEECH_SECONDS:
            missed.append((cursor, end))
    return missed


def transcribe(audio, model=None, filler_prompt=True, speech_regions=None):
    """Returns (text, words); each word is {text, start, end, probability}. Both are empty if unreliable.

    `model` overrides the app's model (the evaluation compares several); `filler_prompt=False`
    measures what the filler-keeping prompt costs in accuracy. `speech_regions` (from
    audio.detect_speech) is detected when not given.
    """
    prompt = FILLER_PROMPT if filler_prompt else None
    segments = _decode(audio, model, initial_prompt=prompt, temperature=0.0)
    if _is_repetition_loop(segments):
        # The filler prompt occasionally causes a loop ("Good morning. Good morning. ...");
        # retry without it and let Whisper raise the temperature on segments that still loop.
        logger.info("Repetition loop detected; retrying without the filler prompt.")
        prompt = None
        segments = _decode(audio, model, temperature=RETRY_TEMPERATURES)
    if _is_repetition_loop(segments):
        return "", []
    words = _words(segments)

    if prompt:
        # The prompt can also make Whisper jump over whole sentences (seen on Indian-accented
        # speech: the first 16 seconds of a recording dropped). Transcribe just those stretches
        # again without it, keeping the prompted words, and their fillers, everywhere else.
        regions = detect_speech(audio) if speech_regions is None else speech_regions
        missed = missed_speech(words, regions)
        if missed:
            logger.info("Whisper skipped %.1f s of speech; filling it in without the filler prompt.",
                        sum(end - start for start, end in missed))
            for start, end in missed:
                piece = _decode(audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)], model, temperature=0.0)
                if not _is_repetition_loop(piece):
                    words += [{**word, "start": round(word["start"] + start, 2), "end": round(word["end"] + start, 2)}
                              for word in _words(piece)]
            words.sort(key=lambda word: word["start"])
    return " ".join(word["text"] for word in words), words
