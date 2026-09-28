"""Timing and pitch features: speaking span, pauses and pitch variation."""
import numpy as np
import parselmouth

from .audio import SAMPLE_RATE
from .fillers import CLAUSE_END_PATTERN

MIN_PAUSE_SECONDS = 0.5
LONG_PAUSE_SECONDS = 2.0
MIN_VOICED_FRAMES = 100  # 1 s of voiced speech at Praat's 10 ms time step


def speaking_span(words):
    """Seconds from the first word to the last, i.e. excluding silence before and after."""
    if not words:
        return 0.0
    return max(0.0, words[-1]["end"] - words[0]["start"])


def _speech_overlap(start, end, speech_regions):
    return sum(max(0.0, min(end, region_end) - max(start, region_start)) for region_start, region_end in speech_regions)


def find_pauses(words, speech_regions, filler_indexes):
    """Silent gaps of at least MIN_PAUSE_SECONDS between consecutive words.

    A pause counts as *hesitation* when it falls mid-phrase (the previous word has no
    punctuation), sits next to a filler, or lasts LONG_PAUSE_SECONDS or more. Pauses at
    commas and sentence ends are *natural*. The VAD speech regions confirm the gap is really
    silent, so words Whisper skipped are not mistaken for pauses.
    """
    pauses = []
    for index in range(1, len(words)):
        previous, current = words[index - 1], words[index]
        gap_start, gap_end = previous["end"], current["start"]
        silence = (gap_end - gap_start) - _speech_overlap(gap_start, gap_end, speech_regions)
        if silence < MIN_PAUSE_SECONDS:
            continue

        mid_phrase = not CLAUSE_END_PATTERN.search(previous["text"])
        next_to_filler = (index - 1) in filler_indexes or index in filler_indexes
        hesitation = mid_phrase or next_to_filler or silence >= LONG_PAUSE_SECONDS
        pauses.append(
            {
                "start": round(gap_start, 2),
                "end": round(gap_end, 2),
                "duration": round(silence, 2),
                "kind": "hesitation" if hesitation else "natural",
                "before_word": index,
            }
        )
    return pauses


def _voiced_pitch(sound, floor, ceiling):
    pitch = sound.to_pitch_ac(time_step=0.01, pitch_floor=floor, pitch_ceiling=ceiling)
    frequencies = pitch.selected_array["frequency"]
    return frequencies[frequencies > 0]


def pitch_variation(audio):
    """Pitch spread in semitones, or None when there is too little voiced speech.

    Uses Praat's autocorrelation pitch tracker with the two-pass speaker range of De Looze &
    Hirst (2008) to avoid octave errors, then a robust spread: (90th - 10th percentile) / 2.56,
    which equals one standard deviation for normally distributed pitch.
    """
    sound = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=SAMPLE_RATE)
    first_pass = _voiced_pitch(sound, 60, 700)
    if len(first_pass) < MIN_VOICED_FRAMES:
        return None

    q1, q3 = np.percentile(first_pass, [25, 75])
    pitch = _voiced_pitch(sound, max(0.75 * q1, 75), min(1.5 * q3, 600))
    if len(pitch) < MIN_VOICED_FRAMES:
        return None

    semitones = 12 * np.log2(pitch / np.median(pitch))
    p10, p90 = np.percentile(semitones, [10, 90])
    return round(float((p90 - p10) / 2.56), 2)
