"""Mode-aware evaluation: adds the text-level checks a practice mode needs, then scores it.

The pipeline measures the recording once; this step decides what matters for the situation, e.g.
reading accuracy for read-aloud, the hesitation/repetition/deviation referee for JAM, or timing
against the target for a pitch.
"""
from collections import Counter

from . import language, reading, relevance, scoring, slides

START_DELAY_SECONDS = 3.0
# A JAM sentence this far from the topic counts as deviation. Calibrated on sample recordings:
# on-topic sentences had a median similarity of 0.63 (10th percentile 0.25), off-topic ones 0.09.
# The threshold is deliberately cautious because a false "deviation" is worse than a missed one;
# short sentences (greetings like "Good morning, everyone.") are not judged.
DEVIATION_THRESHOLD = 0.15
DEVIATION_MIN_WORDS = 5
DEDUPE_SECONDS = 1.0


def _sentences(words):
    """Groups words into sentences: (first word index, text)."""
    sentences, start = [], 0
    for index, word in enumerate(words):
        if word["text"].endswith((".", "!", "?")) or index == len(words) - 1:
            text = " ".join(w["text"] for w in words[start : index + 1] if not w.get("filler"))
            if len(text.split()) >= 3:
                sentences.append((start, text))
            start = index + 1
    return sentences


def _ordinal(number):
    return f"{number}{'th' if 10 <= number % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')}"


def jam_referee(words, pauses, stutters, repeated, topic, start_delay):
    """Just A Minute rules: every hesitation, repetition and deviation, with the time it happened."""
    events = []
    if start_delay >= START_DELAY_SECONDS:
        events.append({"type": "hesitation", "time": 0.0, "detail": f"{start_delay}s before you started"})
    for word in words:
        if word.get("filler"):
            events.append({"type": "hesitation", "time": word["start"], "detail": f'"{word["text"].strip(",.!?")}"'})
    for pause in pauses:
        if pause["kind"] == "hesitation":
            events.append({"type": "hesitation", "time": pause["start"], "detail": f"{pause['duration']}s pause"})
    for stutter in stutters:
        events.append(
            {"type": "repetition", "time": words[stutter["indexes"][0]]["start"], "detail": f'"{stutter["phrase"]}" said twice'}
        )
    for item in repeated:
        for count, index in enumerate(item["indexes"][2:], start=3):
            events.append(
                {"type": "repetition", "time": words[index]["start"], "detail": f'"{item["word"]}" for the {_ordinal(count)} time'}
            )

    sentences = [(start, text) for start, text in _sentences(words) if len(text.split()) >= DEVIATION_MIN_WORDS]
    similarities = relevance.sentence_similarities(topic, [text for _start, text in sentences])
    if similarities:
        for (first_index, text), similarity in zip(sentences, similarities):
            if similarity < DEVIATION_THRESHOLD:
                preview = " ".join(text.split()[:8]) + ("..." if len(text.split()) > 8 else "")
                events.append({"type": "deviation", "time": words[first_index]["start"], "detail": f'"{preview}"'})

    events.sort(key=lambda event: event["time"])
    # A filler and the pause right next to it are one hesitation, not two.
    deduped = []
    for event in events:
        previous = deduped[-1] if deduped else None
        if previous and previous["type"] == event["type"] == "hesitation" and event["time"] - previous["time"] < DEDUPE_SECONDS:
            continue
        deduped.append(event)
    for event in deduped:
        event["time"] = round(event["time"], 1)

    counts = Counter(event["type"] for event in deduped)
    first_word = words[0]["start"]
    clean_until = deduped[0]["time"] if deduped else words[-1]["end"]
    return {
        "events": deduped,
        "counts": {kind: counts.get(kind, 0) for kind in ("hesitation", "repetition", "deviation")},
        "clean_seconds": round(max(0.0, clean_until - first_word), 1),
        "deviation_checked": similarities is not None,
    }


def _timeline_trends(timeline):
    """Compares the first and last third of the talk (needs at least three windows)."""
    if len(timeline) < 3:
        return None
    third = max(1, len(timeline) // 3)
    first, last = timeline[:third], timeline[-third:]

    def mean(segments, key):
        return sum(segment[key] for segment in segments) / len(segments)

    first_wpm = mean(first, "wpm")
    return {
        "pace_change": round((mean(last, "wpm") - first_wpm) / first_wpm, 2) if first_wpm else 0.0,
        "energy_change_db": round(mean(last, "energy_db") - mean(first, "energy_db"), 1),
    }


def evaluate(base, mode, context, deck=None, document=None):
    """Returns metrics, sub-scores, overall score, label and mode-specific checks for one recording.

    `deck` is a parsed slide deck (presentation mode) to check the speech against; `document` is a
    parsed reference document (read-aloud) the speaker read part or all of.
    """
    words = base["words"]
    tokens = [word["text"] for word in words]
    filler_indexes = {index for index, word in enumerate(words) if word.get("filler")}
    checks = set(mode.get("checks", []))
    metrics = dict(base["metrics"])
    word_count = metrics["word_count"]
    minutes = metrics["speaking_span"] / 60 if metrics["speaking_span"] else 0

    hedges = language.find_hedges(tokens, filler_indexes)
    stutters = language.find_stutters(tokens, filler_indexes)
    repeated, repeated_extra = language.find_repeated_words(tokens, filler_indexes, context.get("prompt", ""))
    top_hedge = Counter(hedge["phrase"] for hedge in hedges).most_common(1)
    metrics.update(
        {
            "wpm_range": context["wpm_range"],
            "target_seconds": context.get("target_seconds"),
            "hedge_count": len(hedges),
            "hedges_per_100_words": round(100 * len(hedges) / word_count, 1),
            "top_hedge": top_hedge[0][0] if top_hedge else None,
            "stutter_count": len(stutters),
            "disfluencies_per_100_words": round(100 * (metrics["filler_count"] + len(stutters)) / word_count, 1),
            "repeats_per_100_words": round(100 * repeated_extra / word_count, 1),
            "top_repeated_word": repeated[0]["word"] if repeated else None,
            "top_repeated_count": repeated[0]["count"] if repeated else 0,
        }
    )
    # In JAM and snap talk a slow start is a hesitation too.
    if "start_delay" in checks and metrics["start_delay"] >= START_DELAY_SECONDS:
        metrics["hesitation_pause_count"] += 1
        if minutes:
            metrics["hesitation_pauses_per_minute"] = round(metrics["hesitation_pause_count"] / minutes, 1)

    reading_result = None
    if "reading" in checks and (document or context.get("script")):
        if document:
            reading_result = reading.read_from_document(document["text"], words)
            passages = document["paragraphs"]
        else:
            reading_result = reading.align_reading(context["script"], words)
            passages = [context["script"]]
        if reading_result:
            similarity = None
            if reading.needs_similarity(reading_result):
                similarity = relevance.best_passage_similarity(passages, base["transcription"])
            reading_result["match"] = reading.match_verdict(reading_result["accuracy"], reading_result["spoken_match"], similarity)
            metrics.update(
                {
                    "reading_accuracy": reading_result["accuracy"],
                    "reading_missed": reading_result["counts"]["missed"],
                    "reading_misread": reading_result["counts"]["misread"],
                    "sentence_pause_rate": reading_result["sentence_pause_rate"],
                }
            )

    topic_match = None
    if mode["prompt"]["kind"] != "passage":
        loose = mode["prompt"].get("match") == "loose"
        threshold = relevance.QUESTION_THRESHOLD if loose else relevance.TOPIC_THRESHOLD
        topic_match = relevance.topic_relevance(context.get("prompt"), base["transcription"], threshold)

    referee = None
    if "jam_referee" in checks:
        referee = jam_referee(words, base["pauses"], stutters, repeated, context.get("prompt", ""), metrics["start_delay"])

    trends = _timeline_trends(base["timeline"]) if "timeline" in checks else None
    slides_match = None
    if deck:
        spoken = [(words[start]["start"], text) for start, text in _sentences(words)]
        slides_match = slides.match_speech_to_slides(spoken, deck["slides"])

    weights = mode["weights"]
    sub_scores = scoring.score_metrics(metrics, weights)
    overall = scoring.overall_score(sub_scores, word_count, weights)
    warnings = list(base["warnings"])
    if trends and trends["pace_change"] >= 0.2:
        warnings.append(
            f"You sped up by about {round(100 * trends['pace_change'])}% towards the end. "
            "Keep the same calm pace right to the finish."
        )
    if trends and trends["energy_change_db"] <= -3:
        warnings.append("Your energy dipped in the last part. Save a strong point for the end so you finish with punch.")
    uptalk = base.get("uptalk")
    if slides_match and slides_match["coverage"] < 0.6:
        missed = [slide["title"] for slide in slides_match["slides"] if not slide["covered"]]
        warnings.append(f"You skipped {len(missed)} of your slides ({', '.join(missed[:3])}).")
    if uptalk and uptalk["statements"] >= 3 and uptalk["share"] >= 0.4:
        warnings.append(
            "A lot of your statements ended on a rising pitch, which can make them sound like questions. "
            "Let your voice drop at the end of a statement. (This check is experimental.)"
        )

    return {
        "metrics": metrics,
        "sub_scores": sub_scores,
        "score": overall,
        "delivery": scoring.delivery_label(overall, sub_scores, metrics),
        "warnings": warnings,
        "topic_match": topic_match,
        "language": {"hedges": hedges, "stutters": stutters, "repeated": repeated},
        "reading": reading_result,
        "referee": referee,
        "trends": trends,
        "slides_match": slides_match,
    }

