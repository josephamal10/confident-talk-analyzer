"""Turns delivery metrics into 0-10 sub-scores, an overall score, a delivery label and feedback.

Each sub-score is a linear ramp between a "0/10" and a "10/10" value. The anchors are heuristics
from public-speaking guidance (e.g. 120-160 WPM for presentations) calibrated on sample
recordings; they are meant to be tuned against labelled evaluation data. Each practice mode picks
the sub-scores that matter for it and how much each counts (modes.json "weights").
"""
DEFAULT_WPM_RANGE = (115, 165)
MIN_WORDS = 8

DEFAULT_WEIGHTS = {
    "pace": 0.18,
    "fluency": 0.22,
    "pauses": 0.18,
    "expressiveness": 0.12,
    "vocal_confidence": 0.15,
    "language": 0.15,
}

LABELS = {
    "pace": "Pace",
    "fluency": "Fluency",
    "pauses": "Pausing",
    "expressiveness": "Expressiveness",
    "vocal_confidence": "Vocal confidence",
    "language": "Confident language",
    "accuracy": "Reading accuracy",
    "phrasing": "Phrasing",
    "timing": "Timing",
    "variety": "Word variety",
}

# Delivery label when a sub-score is the weakest area and below 5.
WEAKNESS_LABELS = {
    "fluency": "Hesitant",
    "pauses": "Hesitant",
    "expressiveness": "Monotone",
    "vocal_confidence": "Tentative",
    "language": "Uncertain",
    "accuracy": "Inaccurate",
    "phrasing": "Run-on",
    "timing": "Off-time",
    "variety": "Repetitive",
}


def ramp(value, zero_at, full_at):
    """0 at `zero_at`, 10 at `full_at`, linear in between (works in either direction)."""
    fraction = (value - zero_at) / (full_at - zero_at)
    return round(10 * min(1.0, max(0.0, fraction)), 1)


def pace_score(wpm, wpm_range=DEFAULT_WPM_RANGE):
    low, high = wpm_range
    if wpm < low:
        return ramp(wpm, low - 55, low)
    if wpm > high:
        return ramp(wpm, high + 65, high)
    return 10.0


def fluency_score(disfluencies_per_100_words):
    return ramp(disfluencies_per_100_words, 10, 1)


def pause_score(hesitation_pauses_per_minute):
    return ramp(hesitation_pauses_per_minute, 16, 2)


def expressiveness_score(pitch_variation_semitones):
    if pitch_variation_semitones is None:
        return None
    return ramp(pitch_variation_semitones, 1.0, 3.5)


def vocal_confidence_score(dominance):
    if dominance is None:
        return None
    return ramp(dominance, 0.25, 0.60)


def language_score(hedges_per_100_words):
    return ramp(hedges_per_100_words, 6, 0.5)


def accuracy_score(accuracy):
    if accuracy is None:
        return None
    return ramp(accuracy, 0.75, 0.98)


def phrasing_score(sentence_pause_rate):
    if sentence_pause_rate is None:
        return None
    return ramp(sentence_pause_rate, 0.3, 0.85)


def timing_score(speaking_seconds, target_seconds):
    """Full marks within -10%..+5% of the target, falling to 0 at half or one and a half times it."""
    if not target_seconds:
        return None
    ratio = speaking_seconds / target_seconds
    if ratio < 0.9:
        return ramp(ratio, 0.5, 0.9)
    if ratio > 1.05:
        return ramp(ratio, 1.5, 1.05)
    return 10.0


def variety_score(repeats_per_100_words):
    return ramp(repeats_per_100_words, 8, 1)


SCORERS = {
    "pace": lambda m: pace_score(m["wpm"], m.get("wpm_range") or DEFAULT_WPM_RANGE),
    "fluency": lambda m: fluency_score(m.get("disfluencies_per_100_words", m["fillers_per_100_words"])),
    "pauses": lambda m: pause_score(m["hesitation_pauses_per_minute"]),
    "expressiveness": lambda m: expressiveness_score(m["pitch_variation"]),
    "vocal_confidence": lambda m: vocal_confidence_score(m["dominance"]),
    "language": lambda m: language_score(m.get("hedges_per_100_words", 0.0)),
    "accuracy": lambda m: accuracy_score(m.get("reading_accuracy")),
    "phrasing": lambda m: phrasing_score(m.get("sentence_pause_rate")),
    "timing": lambda m: timing_score(m["speaking_span"], m.get("target_seconds")),
    "variety": lambda m: variety_score(m.get("repeats_per_100_words", 0.0)),
}


def score_metrics(metrics, weights=DEFAULT_WEIGHTS):
    return {name: SCORERS[name](metrics) for name in weights}


def overall_score(sub_scores, word_count, weights=DEFAULT_WEIGHTS):
    """Weighted mean of the available sub-scores; very short answers are capped at 5."""
    available = {name: value for name, value in sub_scores.items() if value is not None and name in weights}
    total_weight = sum(weights[name] for name in available)
    score = sum(weights[name] * value for name, value in available.items()) / total_weight
    if word_count < MIN_WORDS:
        score = min(score, 5.0)
    return round(score, 1)


def delivery_label(overall, sub_scores, metrics):
    if metrics["word_count"] < MIN_WORDS:
        return "Too Short"
    scored = {name: value for name, value in sub_scores.items() if value is not None}
    if overall >= 8 and min(scored.values()) >= 6:
        return "Confident"
    weakest = min(scored, key=scored.get)
    if scored[weakest] >= 5:
        return "Steady"
    if weakest == "pace":
        return "Rushed" if metrics["wpm"] > (metrics.get("wpm_range") or DEFAULT_WPM_RANGE)[1] else "Cautious"
    return WEAKNESS_LABELS[weakest]


def improvement_tip(name, value, metrics):
    """A concrete tip for one sub-score; the wording softens for scores that are only slightly low."""
    minor = value >= 6
    if name == "pace":
        low, high = metrics.get("wpm_range") or DEFAULT_WPM_RANGE
        if metrics["wpm"] > high:
            return f"Pace: {metrics['wpm']} WPM is fast. Slow down and pause briefly after key points."
        return f"Pace: {metrics['wpm']} WPM is slow. Aim for {low}-{high} WPM by linking your phrases together."
    if name == "fluency":
        top = f', mostly "{metrics["top_filler"]}"' if metrics.get("top_filler") else ""
        stutters = f" and {metrics['stutter_count']} repeated starts" if metrics.get("stutter_count") else ""
        return (
            f"Fluency: {metrics['filler_count']} filler words ({metrics['fillers_per_100_words']}% of words){top}"
            f"{stutters}. Replace them with a short silent pause."
        )
    if name == "pauses":
        return (
            f"Pausing: {metrics['hesitation_pause_count']} hesitation pauses mid-sentence "
            f"(longest {metrics['longest_pause']}s). Decide your next point before you start the sentence."
        )
    if name == "expressiveness":
        if minor:
            finding = f"your pitch varied by {metrics['pitch_variation']} semitones. A little more variety would help"
        else:
            finding = f"your pitch varied by only {metrics['pitch_variation']} semitones, which sounds flat"
        return f"Expressiveness: {finding}. Stress key words and let your tone rise and fall."
    if name == "vocal_confidence":
        verdict = "could sound more assertive" if minor else "sounds tentative"
        return (
            f"Vocal confidence: your voice {verdict}. Speak from the chest and finish sentences firmly "
            "instead of trailing off."
        )
    if name == "language":
        top = f', such as "{metrics["top_hedge"]}"' if metrics.get("top_hedge") else ""
        return (
            f"Confident language: {metrics.get('hedge_count', 0)} hedging words{top}. "
            'Say "I will" rather than "I think I can", and drop "just" and "maybe".'
        )
    if name == "accuracy":
        return (
            f"Reading accuracy: {round(100 * metrics['reading_accuracy'])}% of the script read correctly "
            f"({metrics.get('reading_missed', 0)} skipped, {metrics.get('reading_misread', 0)} misread). "
            "Slow down slightly and let your eyes run one phrase ahead of your voice."
        )
    if name == "phrasing":
        return (
            f"Phrasing: you paused at only {round(100 * metrics['sentence_pause_rate'])}% of full stops. "
            "Take a short breath at the end of every sentence."
        )
    if name == "timing":
        target, spoken = metrics["target_seconds"], round(metrics["speaking_span"])
        direction = "Trim a point or tighten your examples" if spoken > target else "Add an example or expand a point"
        return f"Timing: you spoke for {spoken}s against a {target}s target. {direction} to land on time."
    return (
        f'Word variety: you repeated "{metrics.get("top_repeated_word")}" {metrics.get("top_repeated_count")} times. '
        "Use a synonym or move on to a new idea."
    )


def build_feedback(overall, label, sub_scores, metrics, progress_note=None, topic_note=None, warnings=()):
    lines = [f"Overall {overall}/10 ({label})."]
    ranked = sorted((value, name) for name, value in sub_scores.items() if value is not None)
    weakest = [(name, value) for value, name in ranked if value < 8][:2]
    if weakest:
        lines.extend(improvement_tip(name, value, metrics) for name, value in weakest)
    else:
        lines.append("Every area scored 8 or higher. Try a longer or harder prompt to stretch yourself.")
    best_value, best_name = ranked[-1]
    if best_value >= 7 and best_name not in dict(weakest):
        lines.append(f"Strength: {LABELS[best_name].lower()} ({best_value}/10).")
    lines.extend(note for note in (progress_note, topic_note) if note)
    lines.extend(warnings)
    return "\n".join(lines)
