import numpy as np

from analysis.prosody import find_pauses, pitch_variation, speaking_span
from conftest import SAMPLE_RATE, tone


def word(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_speaking_span_ignores_leading_and_trailing_silence():
    assert speaking_span([word("Hello", 1.5, 2.0), word("there.", 2.1, 4.0)]) == 2.5
    assert speaking_span([]) == 0.0


def test_pause_kinds():
    words = [
        word("Nature", 0.0, 0.4),
        word("is,", 0.5, 0.8),       # 1.0 s pause after a comma -> natural
        word("everything", 1.8, 2.3),  # 0.9 s pause mid-phrase -> hesitation
        word("around", 3.2, 3.5),
        word("us.", 3.6, 3.9),
    ]
    silent_everywhere = []
    pauses = find_pauses(words, silent_everywhere, filler_indexes=set())
    assert [(p["kind"], p["duration"]) for p in pauses] == [("natural", 1.0), ("hesitation", 0.9)]
    assert pauses[1]["before_word"] == 3


def test_pause_next_to_filler_is_hesitation():
    words = [word("It", 0.0, 0.2), word("is,", 0.3, 0.5), word("uh,", 1.2, 1.4), word("good.", 1.5, 1.8)]
    pauses = find_pauses(words, [], filler_indexes={2})
    assert pauses[0]["kind"] == "hesitation"


def test_gap_covered_by_speech_is_not_a_pause():
    words = [word("one", 0.0, 0.3), word("two", 1.3, 1.6)]
    # VAD heard speech in the gap (e.g. a word Whisper skipped), so there is no real silence.
    assert find_pauses(words, speech_regions=[(0.0, 1.6)], filler_indexes=set()) == []


def test_pitch_variation_flat_vs_gliding():
    flat = tone(150, 3.0)
    seconds = 3.0
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    frequency = 110 * 2 ** (t / seconds)  # one-octave (12 semitone) glide
    glide = (0.3 * np.sin(2 * np.pi * np.cumsum(frequency) / SAMPLE_RATE)).astype(np.float32)

    assert pitch_variation(flat) < 0.3
    assert pitch_variation(glide) > 3.0


def test_pitch_variation_needs_voiced_speech():
    assert pitch_variation(np.zeros(SAMPLE_RATE * 2, dtype=np.float32)) is None
