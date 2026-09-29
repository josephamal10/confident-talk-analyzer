import pytest

from analysis import scoring


def metrics(**overrides):
    base = {
        "word_count": 60,
        "wpm": 140,
        "speaking_span": 60.0,
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


def test_pace_uses_the_mode_range():
    assert scoring.pace_score(160, (145, 175)) == 10.0
    assert scoring.pace_score(120, (145, 175)) < 10.0


def test_ramp_clamps_both_ends():
    assert scoring.ramp(-5, 0, 10) == 0.0
    assert scoring.ramp(50, 0, 10) == 10.0
    assert scoring.ramp(5, 10, 0) == 5.0


@pytest.mark.parametrize(
    "spoken, target, expected",
    [(58, 60, 10.0), (63, 60, 10.0), (30, 60, 0.0), (42, 60, 5.0), (90, 60, 0.0), (76.5, 60, 5.0)],
)
def test_timing_score(spoken, target, expected):
    assert scoring.timing_score(spoken, target) == expected


def test_timing_needs_a_target():
    assert scoring.timing_score(60, None) is None


def test_new_sub_scores():
    assert scoring.language_score(0.0) == 10.0 and scoring.language_score(6.0) == 0.0
    assert scoring.accuracy_score(0.98) == 10.0 and scoring.accuracy_score(None) is None
    assert scoring.phrasing_score(0.85) == 10.0 and scoring.phrasing_score(None) is None
    assert scoring.variety_score(1.0) == 10.0 and scoring.variety_score(8.0) == 0.0


def test_mode_weights_select_the_sub_scores():
    weights = {"accuracy": 0.5, "pace": 0.5}
    sub_scores = scoring.score_metrics(metrics(reading_accuracy=0.865), weights)
    assert set(sub_scores) == {"accuracy", "pace"}
    assert scoring.overall_score(sub_scores, 60, weights) == 7.5


def test_overall_uses_only_available_sub_scores():
    sub_scores = {"pace": 10.0, "fluency": 10.0, "pauses": 10.0, "expressiveness": None, "vocal_confidence": None}
    assert scoring.overall_score(sub_scores, word_count=60) == 10.0


def test_short_answers_are_capped():
    sub_scores = scoring.score_metrics(metrics())
    assert scoring.overall_score(sub_scores, word_count=5) == 5.0


def test_labels_follow_the_weakest_area():
    good = metrics()
    assert scoring.delivery_label(9.5, scoring.score_metrics(good), good) == "Confident"

    rushed = metrics(wpm=200)
    assert scoring.delivery_label(7.0, scoring.score_metrics(rushed), rushed) == "Rushed"

    slow = metrics(wpm=70)
    assert scoring.delivery_label(7.0, scoring.score_metrics(slow), slow) == "Cautious"

    fillers = metrics(filler_count=6, fillers_per_100_words=10.0)
    assert scoring.delivery_label(6.0, scoring.score_metrics(fillers), fillers) == "Hesitant"

    flat = metrics(pitch_variation=1.2)
    assert scoring.delivery_label(7.0, scoring.score_metrics(flat), flat) == "Monotone"

    hedging = metrics(hedges_per_100_words=6.0)
    assert scoring.delivery_label(7.0, scoring.score_metrics(hedging), hedging) == "Uncertain"

    assert scoring.delivery_label(5.0, scoring.score_metrics(good), metrics(word_count=4)) == "Too Short"


def test_feedback_targets_weakest_areas():
    m = metrics(filler_count=5, fillers_per_100_words=8.3, top_filler="um", pitch_variation=1.5)
    sub_scores = scoring.score_metrics(m)
    feedback = scoring.build_feedback(
        6.9, "Hesitant", sub_scores, m, progress_note="That's 0.5 points better.", topic_note="You stayed on topic."
    )
    lines = feedback.splitlines()
    assert lines[0] == scoring.opening_line(6.9, "Hesitant")
    assert lines[1].startswith("The main thing to work on: I heard 5 filler words") and '"um"' in lines[1]
    assert lines[2].startswith("After that: Your voice stayed quite flat")
    assert any(line.startswith("What went well: ") for line in lines)
    assert lines[-2:] == ["You stayed on topic.", "That's 0.5 points better."]


def test_feedback_reads_like_a_coach_not_a_report():
    m = metrics(wpm=200, filler_count=3, fillers_per_100_words=5.0, top_filler="like", hedges_per_100_words=4.0,
                hedge_count=3, top_hedge="maybe")
    feedback = scoring.build_feedback(5.2, "Rushed", scoring.score_metrics(m), m)
    assert not feedback.startswith("Overall")
    assert "WPM" not in feedback and "/10" not in feedback
    assert "words a minute" in feedback


@pytest.mark.parametrize(
    "score, label, expected",
    [(9.0, "Confident", "really confident"), (7.4, "Steady", "solid take"), (6.0, "Hesitant", "Good effort"),
     (3.0, "Hesitant", "Thanks for getting that recorded"), (4.0, "Too Short", "too short to judge")],
)
def test_opening_line_matches_the_score(score, label, expected):
    assert expected in scoring.opening_line(score, label)


def test_all_good_feedback_suggests_a_harder_prompt():
    m = metrics()
    feedback = scoring.build_feedback(9.6, "Confident", scoring.score_metrics(m), m)
    assert "Every area scored 8 or more" in feedback


@pytest.mark.parametrize(
    "name, extra, expected",
    [
        ("language", {"hedge_count": 4, "top_hedge": "i think"}, 'like "i think" (4 times)'),
        ("accuracy", {"reading_accuracy": 0.82, "reading_missed": 3, "reading_misread": 2}, "82% of the text"),
        ("phrasing", {"sentence_pause_rate": 0.4}, "40% of the full stops"),
        ("timing", {"target_seconds": 60, "speaking_span": 80}, "You spoke for 80s and the target was 60s"),
        ("variety", {"top_repeated_word": "basically", "top_repeated_count": 5}, '"basically" 5 times'),
        ("pauses", {"hesitation_pause_count": 1, "longest_pause": 2.4}, "mid-sentence once"),
        ("fluency", {"filler_count": 0, "stutter_count": 3}, "I heard 3 restarted phrases"),
    ],
)
def test_tips_for_new_sub_scores(name, extra, expected):
    assert expected in scoring.improvement_tip(name, 3.0, metrics(**extra))


def test_tips_soften_for_slightly_low_scores():
    assert "could sound a touch more assertive" in scoring.improvement_tip("vocal_confidence", 7.6, metrics())
    assert "came across as a bit unsure" in scoring.improvement_tip("vocal_confidence", 3.0, metrics())
