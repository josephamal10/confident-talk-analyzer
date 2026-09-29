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


# What a coach would say when an area went well.
STRENGTH_NOTES = {
    "pace": "your pace was easy to follow",
    "fluency": "you spoke smoothly, with hardly any fillers",
    "pauses": "your pauses came in the right places",
    "expressiveness": "your voice had a nice rise and fall",
    "vocal_confidence": "you sounded sure of yourself",
    "language": "you said things plainly, without hedging",
    "accuracy": "you read the text accurately",
    "phrasing": "you gave each sentence room to breathe",
    "timing": "you timed it well",
    "variety": "you used a good range of words",
}


def _times(count):
    return "once" if count == 1 else "twice" if count == 2 else f"{count} times"


def improvement_tip(name, value, metrics):
    """One concrete, human-sounding tip for a sub-score; softer when the score is only slightly low."""
    minor = value >= 6
    if name == "pace":
        low, high = metrics.get("wpm_range") or DEFAULT_WPM_RANGE
        if metrics["wpm"] > high:
            return (
                f"You were going at about {metrics['wpm']} words a minute, which is on the fast side. "
                "Slow down a little and give each key point a second to land."
            )
        return (
            f"You were at about {metrics['wpm']} words a minute, a bit slow for this. "
            f"Try linking your words into phrases so it flows, somewhere around {low} to {high} a minute."
        )
    if name == "fluency":
        found = []
        if metrics.get("filler_count"):
            top = f', mostly "{metrics["top_filler"]}"' if metrics.get("top_filler") else ""
            found.append(f"{metrics['filler_count']} filler words{top}")
        if metrics.get("stutter_count"):
            found.append(f"{metrics['stutter_count']} restarted phrases")
        heard = " and ".join(found) or "a few stumbles"
        return (
            f"I heard {heard}. When you feel one coming, just pause for a beat instead. "
            "A short silence sounds far more sure of itself."
        )
    if name == "pauses":
        return (
            f"You stopped mid-sentence {_times(metrics['hesitation_pause_count'])} "
            f"(the longest gap was {metrics['longest_pause']}s). Work out your next point before you start "
            "the sentence, then say it in one go."
        )
    if name == "expressiveness":
        if minor:
            finding = "Your voice could use a little more rise and fall"
        else:
            finding = f"Your voice stayed quite flat (it moved only {metrics['pitch_variation']} semitones)"
        return f"{finding}. Pick one word in each sentence to lean on and let your tone move with it."
    if name == "vocal_confidence":
        finding = "You could sound a touch more assertive" if minor else "Your voice came across as a bit unsure"
        return f"{finding}. Speak from your chest and finish each sentence firmly instead of letting it fade."
    if name == "language":
        top = f' like "{metrics["top_hedge"]}"' if metrics.get("top_hedge") else ""
        return (
            f"You softened your points with words{top} ({_times(metrics.get('hedge_count', 0))}). "
            'Say it straight: "I will" lands better than "I think I can", and you can usually drop "just" and "maybe".'
        )
    if name == "accuracy":
        return (
            f"You read {round(100 * metrics['reading_accuracy'])}% of the text correctly "
            f"({metrics.get('reading_missed', 0)} words skipped, {metrics.get('reading_misread', 0)} misread). "
            "Slow down slightly and let your eyes stay one phrase ahead of your voice."
        )
    if name == "phrasing":
        return (
            f"You paused at only {round(100 * metrics['sentence_pause_rate'])}% of the full stops. "
            "Take a small breath at the end of every sentence so your listener can keep up."
        )
    if name == "timing":
        target, spoken = metrics["target_seconds"], round(metrics["speaking_span"])
        if spoken > target:
            advice = "Cut one point or tighten your examples so you finish on time."
        else:
            advice = "Add an example or say a bit more about one point to fill the time."
        return f"You spoke for {spoken}s and the target was {target}s. {advice}"
    return (
        f'You said "{metrics.get("top_repeated_word")}" {metrics.get("top_repeated_count")} times. '
        "Swap in a different word now and then, or move on to a fresh idea."
    )


def opening_line(overall, label):
    if label == "Too Short":
        return "That was too short to judge properly. Try talking for at least 30 seconds next time."
    if overall >= 8.5:
        return "That was a really confident take."
    if overall >= 7:
        return "Nice work, that was a solid take."
    if overall >= 5.5:
        return "Good effort. A couple of changes will make it noticeably better."
    return "Thanks for getting that recorded. Let's make the next one easier to listen to."


def build_feedback(overall, label, sub_scores, metrics, progress_note=None, topic_note=None, warnings=()):
    """Plain-language notes on the delivery: what to work on first, what went well, and any extra checks."""
    lines = [opening_line(overall, label)]
    ranked = sorted((value, name) for name, value in sub_scores.items() if value is not None)
    weakest = [(name, value) for value, name in ranked if value < 8][:2]
    if weakest:
        lines.append("The main thing to work on: " + improvement_tip(*weakest[0], metrics))
        if len(weakest) > 1:
            lines.append("After that: " + improvement_tip(*weakest[1], metrics))
    else:
        lines.append("Every area scored 8 or more. Try a longer or harder prompt next time to stretch yourself.")
    best_value, best_name = ranked[-1]
    if best_value >= 7 and best_name not in dict(weakest):
        lines.append(f"What went well: {STRENGTH_NOTES[best_name]}.")
    lines.extend(note for note in (topic_note, progress_note) if note)
    lines.extend(warnings)
    return "\n".join(lines)
