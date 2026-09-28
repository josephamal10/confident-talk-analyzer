"""Turns delivery metrics into 0-10 sub-scores, an overall score, a delivery label and feedback.

Each sub-score is a linear ramp between a "0/10" and a "10/10" value. The anchors are
heuristics from public-speaking guidance (e.g. 120-160 WPM for presentations) calibrated on
sample recordings; they are meant to be tuned against labelled evaluation data.
"""
IDEAL_WPM = (115, 165)
RUSHED_WPM = 185
SLOW_WPM = 100
MIN_WORDS = 8

WEIGHTS = {
    "pace": 0.20,
    "fluency": 0.25,
    "pauses": 0.20,
    "expressiveness": 0.15,
    "vocal_confidence": 0.20,
}

LABELS = {
    "pace": "Pace",
    "fluency": "Fluency",
    "pauses": "Pausing",
    "expressiveness": "Expressiveness",
    "vocal_confidence": "Vocal confidence",
}


def ramp(value, zero_at, full_at):
    """0 at `zero_at`, 10 at `full_at`, linear in between (works in either direction)."""
    fraction = (value - zero_at) / (full_at - zero_at)
    return round(10 * min(1.0, max(0.0, fraction)), 1)


def pace_score(wpm):
    if wpm < IDEAL_WPM[0]:
        return ramp(wpm, 60, IDEAL_WPM[0])
    if wpm > IDEAL_WPM[1]:
        return ramp(wpm, 230, IDEAL_WPM[1])
    return 10.0


def fluency_score(fillers_per_100_words):
    return ramp(fillers_per_100_words, 10, 1)


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


def score_metrics(metrics):
    return {
        "pace": pace_score(metrics["wpm"]),
        "fluency": fluency_score(metrics["fillers_per_100_words"]),
        "pauses": pause_score(metrics["hesitation_pauses_per_minute"]),
        "expressiveness": expressiveness_score(metrics["pitch_variation"]),
        "vocal_confidence": vocal_confidence_score(metrics["dominance"]),
    }


def overall_score(sub_scores, word_count):
    """Weighted mean of the available sub-scores; very short answers are capped at 5."""
    available = {name: value for name, value in sub_scores.items() if value is not None}
    total_weight = sum(WEIGHTS[name] for name in available)
    score = sum(WEIGHTS[name] * value for name, value in available.items()) / total_weight
    if word_count < MIN_WORDS:
        score = min(score, 5.0)
    return round(score, 1)


def delivery_label(overall, sub_scores, metrics):
    if metrics["word_count"] < MIN_WORDS:
        return "Too Short"
    if metrics["wpm"] > RUSHED_WPM:
        return "Rushed"
    if sub_scores["fluency"] < 5 or sub_scores["pauses"] < 5:
        return "Hesitant"
    if metrics["wpm"] < SLOW_WPM:
        return "Cautious"
    if sub_scores["expressiveness"] is not None and sub_scores["expressiveness"] < 4:
        return "Monotone"
    if sub_scores["vocal_confidence"] is not None and sub_scores["vocal_confidence"] < 4:
        return "Tentative"
    if overall >= 8:
        return "Confident"
    return "Steady"


def improvement_tip(name, value, metrics):
    """A concrete tip for one sub-score; the wording softens for scores that are only slightly low."""
    minor = value >= 6
    if name == "pace":
        if metrics["wpm"] > IDEAL_WPM[1]:
            return f"Pace: {metrics['wpm']} WPM is fast. Slow down and pause briefly after key points."
        return f"Pace: {metrics['wpm']} WPM is slow. Aim for 120-160 WPM by linking your phrases together."
    if name == "fluency":
        top = f', mostly "{metrics["top_filler"]}"' if metrics["top_filler"] else ""
        return (
            f"Fluency: {metrics['filler_count']} filler words ({metrics['fillers_per_100_words']}% of words){top}. "
            "Replace them with a short silent pause."
        )
    if name == "pauses":
        return (
            f"Pausing: {metrics['hesitation_pause_count']} hesitation pauses mid-sentence "
            f"(longest {metrics['longest_pause']}s). Decide your next point before you start the sentence."
        )
    if name == "expressiveness":
        verdict = "a little more variety would help" if minor else "which sounds flat"
        return (
            f"Expressiveness: your pitch varied by {metrics['pitch_variation']} semitones; {verdict}. "
            "Stress key words and let your tone rise and fall."
        )
    verdict = "could sound more assertive" if minor else "sounds tentative"
    return (
        f"Vocal confidence: your voice {verdict}. Speak from the chest and finish sentences firmly "
        "instead of trailing off."
    )


def build_feedback(overall, label, sub_scores, metrics, progress_note=None, topic_note=None, warnings=()):
    lines = [f"Overall {overall}/10 ({label})."]
    ranked = sorted((value, name) for name, value in sub_scores.items() if value is not None)
    weakest = [(name, value) for value, name in ranked if value < 8][:2]
    if weakest:
        lines.extend(improvement_tip(name, value, metrics) for name, value in weakest)
    else:
        lines.append("Every area scored 8 or higher. Try a longer or unscripted topic to stretch yourself.")
    best_value, best_name = ranked[-1]
    if best_value >= 7 and best_name not in dict(weakest):
        lines.append(f"Strength: {LABELS[best_name].lower()} ({best_value}/10).")
    lines.extend(note for note in (progress_note, topic_note) if note)
    lines.extend(warnings)
    return "\n".join(lines)
