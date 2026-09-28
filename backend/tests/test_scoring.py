import pytest

from analysis import scoring


def metrics(**overrides):
    base = {
        "word_count": 60,
        "wpm": 140,
        "filler_count": 0,
        "fillers_per_100_words": 0.0,
        "top_filler": None,
        "hesitation_pause_count": 0,
        "hesitation_pauses_per_minute": 0.0,
        "longest_pause": 0.0,
        "pitch_variation": 3.5,
        "dominance": 0.6,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("wpm, expected", [(140, 10.0), (115, 10.0), (60, 0.0), (87.5, 5.0), (230, 0.0), (197.5, 5.0)])
def test_pace_score(wpm, expected):
    assert scoring.pace_score(wpm) == expected


def test_ramp_clamps_both_ends():
    assert scoring.ramp(-5, 0, 10) == 0.0
    assert scoring.ramp(50, 0, 10) == 10.0
    assert scoring.ramp(5, 10, 0) == 5.0


def test_overall_uses_only_available_sub_scores():
    sub_scores = {"pace": 10.0, "fluency": 10.0, "pauses": 10.0, "expressiveness": None, "vocal_confidence": None}
    assert scoring.overall_score(sub_scores, word_count=60) == 10.0


def test_short_answers_are_capped():
    sub_scores = scoring.score_metrics(metrics())
    assert scoring.overall_score(sub_scores, word_count=5) == 5.0


def test_labels():
    good = metrics()
    assert scoring.delivery_label(9.5, scoring.score_metrics(good), good) == "Confident"

    rushed = metrics(wpm=200)
    assert scoring.delivery_label(7.0, scoring.score_metrics(rushed), rushed) == "Rushed"

    fillers = metrics(filler_count=6, fillers_per_100_words=10.0)
    assert scoring.delivery_label(6.0, scoring.score_metrics(fillers), fillers) == "Hesitant"

    flat = metrics(pitch_variation=1.2)
    assert scoring.delivery_label(7.0, scoring.score_metrics(flat), flat) == "Monotone"

    assert scoring.delivery_label(5.0, scoring.score_metrics(good), metrics(word_count=4)) == "Too Short"


def test_feedback_targets_weakest_areas():
    m = metrics(filler_count=5, fillers_per_100_words=8.3, top_filler="um", pitch_variation=1.5)
    sub_scores = scoring.score_metrics(m)
    feedback = scoring.build_feedback(6.9, "Hesitant", sub_scores, m, topic_note="Topic check: ok.")
    lines = feedback.splitlines()
    assert lines[0] == "Overall 6.9/10 (Hesitant)."
    assert lines[1].startswith("Fluency: 5 filler words") and '"um"' in lines[1]
    assert lines[2].startswith("Expressiveness:") and "sounds flat" in lines[2]
    assert lines[-1] == "Topic check: ok."


def test_tips_soften_for_slightly_low_scores():
    assert "could sound more assertive" in scoring.improvement_tip("vocal_confidence", 7.6, metrics())
    assert "sounds tentative" in scoring.improvement_tip("vocal_confidence", 3.0, metrics())
