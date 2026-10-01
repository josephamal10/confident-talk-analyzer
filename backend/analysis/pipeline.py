"""Signal-level analysis of one recording: transcript, timing, pitch and vocal tone.

Mode-specific checks and scoring happen afterwards in evaluation.py.
"""
import logging
import time
from collections import Counter

from . import emotion, transcription
from .audio import SAMPLE_RATE, detect_speech, load_audio
from .fillers import find_filler_spans, normalize
from .prosody import build_timeline, detect_uptalk, find_pauses, pitch_track, pitch_variation, speaking_span

logger = logging.getLogger(__name__)

MIN_SPEECH_SECONDS = 0.5
RELIABLE_SPEECH_SECONDS = 10
# Words the recogniser was unsure about; often mumbled or unclear speech.
UNCLEAR_WORD_PROBABILITY = 0.45


class AnalysisError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def warm_up():
    """Loads the models up front so the first analysis isn't slow."""
    transcription.get_model()
    emotion.get_session()


def analyze_recording(path, on_stage=None):
    """Returns the transcript with a per-word timeline plus timing, pitch and vocal-tone measurements.

    `on_stage(name)` is called as each stage starts (decode, transcribe, prosody, tone), so callers can
    report progress. Raises AnalysisError when the file can't be decoded or contains no usable speech.
    """
    report = on_stage or (lambda _stage: None)
    timings = {}
    started = time.perf_counter()

    def lap(stage):
        nonlocal started
        now = time.perf_counter()
        timings[stage] = round((now - started) * 1000)
        started = now

    report("decode")
    try:
        audio = load_audio(path)
    except Exception as error:
        raise AnalysisError("The recording could not be read. Please record again.", 400) from error
    duration = len(audio) / SAMPLE_RATE
    speech_regions = detect_speech(audio)
    lap("decode_vad")
    if sum(end - start for start, end in speech_regions) < MIN_SPEECH_SECONDS:
        raise AnalysisError("No speech was detected. Check your microphone and try again.", 422)

    report("transcribe")
    text, words = transcription.transcribe(audio, speech_regions=speech_regions)
    lap("transcription")
    if not words:
        raise AnalysisError("Your speech could not be transcribed. Please speak clearly and try again.", 422)

    report("prosody")
    filler_spans = find_filler_spans([word["text"] for word in words])
    filler_indexes = {index for span in filler_spans for index in span}
    for index, word in enumerate(words):
        word["filler"] = index in filler_indexes

    span = speaking_span(words)
    minutes_spoken = span / 60 if span > 0 else 0
    pauses = find_pauses(words, speech_regions, filler_indexes)
    hesitation_pauses = [pause for pause in pauses if pause["kind"] == "hesitation"]

    offset = words[0]["start"]
    speech_audio = audio[int(offset * SAMPLE_RATE) : int(words[-1]["end"] * SAMPLE_RATE) + 1]
    track = pitch_track(speech_audio)
    uptalk = detect_uptalk(words, track, offset)
    lap("pitch")
    report("tone")
    vocal_tone = emotion.predict_vocal_tone(speech_audio)
    lap("emotion")
    timeline = build_timeline(
        words, speech_audio, offset, emotion.window_bounds(len(speech_audio)), (vocal_tone or {}).get("windows")
    )

    word_count = len(words)
    filler_texts = Counter(" ".join(normalize(words[i]["text"]) for i in filler) for filler in filler_spans)
    unclear = [i for i, word in enumerate(words) if not word["filler"] and word["probability"] < UNCLEAR_WORD_PROBABILITY]
    metrics = {
        "duration": round(duration, 2),
        "speaking_span": round(span, 2),
        "word_count": word_count,
        "wpm": round(word_count / minutes_spoken) if minutes_spoken else 0,
        "filler_count": len(filler_spans),
        "fillers_per_100_words": round(100 * len(filler_spans) / word_count, 1),
        "top_filler": filler_texts.most_common(1)[0][0] if filler_texts else None,
        "pause_count": len(pauses),
        "hesitation_pause_count": len(hesitation_pauses),
        "hesitation_pauses_per_minute": round(len(hesitation_pauses) / minutes_spoken, 1) if minutes_spoken else 0,
        "longest_pause": max((pause["duration"] for pause in pauses), default=0.0),
        "start_delay": round(offset, 1),
        "pitch_variation": pitch_variation(track),
        "dominance": vocal_tone["dominance"] if vocal_tone else None,
        "unclear_word_share": round(len(unclear) / word_count, 2),
        "uptalk_share": uptalk["share"] if uptalk else None,
    }

    warnings = []
    if span < RELIABLE_SPEECH_SECONDS:
        warnings.append("Talk for at least 15 seconds next time so the scores are more reliable.")

    logger.info("Analyzed %.1fs recording in %s ms", duration, timings)
    return {
        "transcription": text,
        "transcription_model": f"faster-whisper/{transcription.MODEL_NAME}",
        "words": words,
        "pauses": pauses,
        "unclear_indexes": unclear,
        "uptalk": uptalk,
        "timeline": timeline,
        "metrics": metrics,
        "vocal_tone": {key: value for key, value in vocal_tone.items() if key != "windows"} if vocal_tone else None,
        "warnings": warnings,
        "timings_ms": timings,
    }
