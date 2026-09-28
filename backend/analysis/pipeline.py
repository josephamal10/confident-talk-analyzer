"""End-to-end analysis of one recording."""
import logging
import time
from collections import Counter

from . import emotion, transcription
from .audio import SAMPLE_RATE, detect_speech, load_audio
from .fillers import find_filler_spans, normalize
from .prosody import find_pauses, pitch_variation, speaking_span
from .scoring import delivery_label, overall_score, score_metrics

logger = logging.getLogger(__name__)

MIN_SPEECH_SECONDS = 0.5
RELIABLE_SPEECH_SECONDS = 10


class AnalysisError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def warm_up():
    """Loads the models up front so the first analysis isn't slow."""
    transcription.get_model()
    emotion.get_session()


def analyze_recording(path):
    """Returns transcript, per-word timeline, metrics and scores for an audio file.

    Raises AnalysisError when the file can't be decoded or contains no usable speech.
    """
    timings = {}
    started = time.perf_counter()

    def lap(stage):
        nonlocal started
        now = time.perf_counter()
        timings[stage] = round((now - started) * 1000)
        started = now

    try:
        audio = load_audio(path)
    except Exception as error:
        raise AnalysisError("The recording could not be read. Please record again.", 400) from error
    duration = len(audio) / SAMPLE_RATE
    speech_regions = detect_speech(audio)
    lap("decode_vad")
    if sum(end - start for start, end in speech_regions) < MIN_SPEECH_SECONDS:
        raise AnalysisError("No speech was detected. Check your microphone and try again.", 422)

    text, words = transcription.transcribe(audio)
    lap("transcription")
    if not words:
        raise AnalysisError("Your speech could not be transcribed. Please speak clearly and try again.", 422)

    filler_spans = find_filler_spans([word["text"] for word in words])
    filler_indexes = {index for span in filler_spans for index in span}
    for index, word in enumerate(words):
        word["filler"] = index in filler_indexes

    span = speaking_span(words)
    minutes_spoken = span / 60 if span > 0 else 0
    pauses = find_pauses(words, speech_regions, filler_indexes)
    hesitation_pauses = [pause for pause in pauses if pause["kind"] == "hesitation"]

    speech_audio = audio[int(words[0]["start"] * SAMPLE_RATE) : int(words[-1]["end"] * SAMPLE_RATE) + 1]
    pitch = pitch_variation(speech_audio)
    lap("pitch")
    vocal_tone = emotion.predict_vocal_tone(speech_audio)
    lap("emotion")

    word_count = len(words)
    filler_texts = Counter(" ".join(normalize(words[i]["text"]) for i in filler) for filler in filler_spans)
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
        "pitch_variation": pitch,
        "dominance": vocal_tone["dominance"] if vocal_tone else None,
    }
    sub_scores = score_metrics(metrics)
    overall = overall_score(sub_scores, word_count)

    warnings = []
    if span < RELIABLE_SPEECH_SECONDS:
        warnings.append("Tip: speak for at least 15 seconds so the scores are reliable.")

    logger.info("Analyzed %.1fs recording in %s ms: score %s", duration, timings, overall)
    return {
        "transcription": text,
        "transcription_model": f"faster-whisper/{transcription.MODEL_NAME}",
        "words": words,
        "pauses": pauses,
        "metrics": metrics,
        "vocal_tone": vocal_tone,
        "sub_scores": sub_scores,
        "score": overall,
        "delivery": delivery_label(overall, sub_scores, metrics),
        "warnings": warnings,
        "timings_ms": timings,
    }
