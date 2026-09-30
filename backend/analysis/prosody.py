"""Timing and pitch features: speaking span, pauses and pitch variation."""
import numpy as np
import parselmouth

from .audio import SAMPLE_RATE
from .fillers import CLAUSE_END_PATTERN

MIN_PAUSE_SECONDS = 0.5
LONG_PAUSE_SECONDS = 2.0
MIN_VOICED_FRAMES = 100  # 1 s of voiced speech at Praat's 10 ms time step
UPTALK_SEMITONES = 2.0
MIN_UPTALK_FRAMES = 6


def speaking_span(words):
    """Seconds from the first word to the last, i.e. excluding silence before and after."""
    if not words:
        return 0.0
    return max(0.0, words[-1]["end"] - words[0]["start"])


def _silences(words, speech_regions):
    """Silent stretches as (start, end): the gaps between VAD speech regions, or between Whisper's
    word timestamps when there are no VAD regions."""
    if speech_regions:
        return [(end, start) for (_s, end), (start, _e) in zip(speech_regions, speech_regions[1:])]
    return [(previous["end"], current["start"]) for previous, current in zip(words, words[1:])]


def find_pauses(words, speech_regions, filler_indexes):
    """Silences of at least MIN_PAUSE_SECONDS inside the speech, each placed before a word.

    The silence comes from the VAD rather than from gaps between Whisper's word timestamps:
    Whisper tends to stretch a word's start back over the silence before it, which hid about half
    of the scripted pauses in the evaluation set (see evals/). Word end times stay accurate, so a
    silence belongs before the first word that ends after it. A VAD gap with a whole word inside it
    is quiet speech the VAD missed, not a pause.

    A pause counts as *hesitation* when it falls mid-phrase (the previous word has no
    punctuation), sits next to a filler, or lasts LONG_PAUSE_SECONDS or more. Pauses at
    commas and sentence ends are *natural*.
    """
    if len(words) < 2:
        return []
    found = {}  # before_word -> [start, end, silence]
    for gap_start, gap_end in _silences(words, speech_regions):
        silence = gap_end - gap_start
        if silence < MIN_PAUSE_SECONDS or gap_start < words[0]["start"] or gap_end > words[-1]["end"]:
            continue
        if speech_regions and any(gap_start <= word["start"] and word["end"] <= gap_end for word in words):
            continue
        index = next((i for i, word in enumerate(words) if word["end"] > gap_end), None)
        if not index:
            continue
        if index in found:  # a breath split one pause into two silences
            found[index][1] = gap_end
            found[index][2] += silence
        else:
            found[index] = [gap_start, gap_end, silence]

    pauses = []
    for index, (start, end, silence) in sorted(found.items()):
        previous = words[index - 1]
        mid_phrase = not CLAUSE_END_PATTERN.search(previous["text"])
        next_to_filler = (index - 1) in filler_indexes or index in filler_indexes
        hesitation = mid_phrase or next_to_filler or silence >= LONG_PAUSE_SECONDS
        pauses.append(
            {
                "start": round(start, 2),
                "end": round(end, 2),
                "duration": round(silence, 2),
                "kind": "hesitation" if hesitation else "natural",
                "before_word": index,
            }
        )
    return pauses


def _voiced_pitch(sound, floor, ceiling):
    pitch = sound.to_pitch_ac(time_step=0.01, pitch_floor=floor, pitch_ceiling=ceiling)
    frequencies = pitch.selected_array["frequency"]
    voiced = frequencies > 0
    return pitch.xs()[voiced], frequencies[voiced]


def pitch_track(audio):
    """(times, frequencies) of voiced frames, or None when there is too little voiced speech.

    Uses Praat's autocorrelation pitch tracker with the two-pass speaker range of De Looze &
    Hirst (2008): a wide first pass finds the speaker's range, and the second pass is limited
    to it, which avoids octave errors.
    """
    sound = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=SAMPLE_RATE)
    _times, first_pass = _voiced_pitch(sound, 60, 700)
    if len(first_pass) < MIN_VOICED_FRAMES:
        return None

    q1, q3 = np.percentile(first_pass, [25, 75])
    times, frequencies = _voiced_pitch(sound, max(0.75 * q1, 75), min(1.5 * q3, 600))
    if len(frequencies) < MIN_VOICED_FRAMES:
        return None
    return times, frequencies


def pitch_variation(track):
    """Robust pitch spread in semitones: (90th - 10th percentile) / 2.56, which equals one
    standard deviation for normally distributed pitch."""
    if track is None:
        return None
    _times, frequencies = track
    semitones = 12 * np.log2(frequencies / np.median(frequencies))
    p10, p90 = np.percentile(semitones, [10, 90])
    return round(float((p90 - p10) / 2.56), 2)


def detect_uptalk(words, track, offset):
    """Statements whose final word rises in pitch by UPTALK_SEMITONES or more (experimental).

    Rising intonation at the end of a statement ("uptalk") makes it sound like a question.
    `offset` is the time of the track's first sample within the recording.
    """
    if track is None:
        return None
    times, frequencies = track
    statements, rising = 0, []
    for index, word in enumerate(words):
        if not word["text"].endswith("."):
            continue
        in_word = (times >= word["start"] - offset) & (times <= word["end"] - offset)
        contour = frequencies[in_word]
        if len(contour) < MIN_UPTALK_FRAMES:
            continue
        statements += 1
        half = len(contour) // 2
        rise = 12 * np.log2(np.median(contour[half:]) / np.median(contour[:half]))
        if rise >= UPTALK_SEMITONES:
            rising.append(index)
    return {
        "statements": statements,
        "rising_indexes": rising,
        "share": round(len(rising) / statements, 2) if statements else None,
    }


def build_timeline(words, audio, offset, windows, vocal_windows=None):
    """Pace, fillers and speaking energy per window (the same windows the emotion model scores).

    `windows` are (start, end) sample bounds relative to `offset` seconds into the recording.
    Energy is the mean of the loudest half of 30 ms frames, so pauses don't drag it down.
    """
    segments = []
    frame = int(0.03 * SAMPLE_RATE)
    for position, (start_sample, end_sample) in enumerate(windows):
        start = offset + start_sample / SAMPLE_RATE
        end = offset + end_sample / SAMPLE_RATE
        in_window = [word for word in words if start <= word["start"] < end]
        chunk = audio[start_sample:end_sample]
        frames = chunk[: len(chunk) // frame * frame].reshape(-1, frame) if len(chunk) >= frame else chunk[None, :]
        levels = np.sort(20 * np.log10(np.sqrt(np.mean(frames**2, axis=1)) + 1e-9))
        segment = {
            "start": round(start, 1),
            "end": round(end, 1),
            "wpm": round(len(in_window) * 60 / max(end - start, 1e-6)),
            "fillers": sum(1 for word in in_window if word.get("filler")),
            "energy_db": round(float(np.mean(levels[len(levels) // 2 :])), 1),
        }
        if vocal_windows and position < len(vocal_windows):
            segment["dominance"] = vocal_windows[position]["dominance"]
        segments.append(segment)
    return segments
