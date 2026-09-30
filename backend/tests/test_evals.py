"""The evaluation suite's own building blocks: script markup, metrics and the dataset files."""
import pytest

from evals import markup, metrics
from evals.dataset import load_manifest, own_clips, synthetic_clips


# ---------- Markup ----------


def test_markup_labels_fillers_hedges_and_pauses():
    script = markup.parse("So, {um} <I think> [1.0] we should go. It was, {you know}, fine. [2.5] Done.")
    assert script.tokens == ["So,", "um", "I", "think", "we", "should", "go.", "It", "was,", "you", "know,", "fine.", "Done."]
    assert script.fillers == [[1], [9, 10]]
    assert script.hedges == [[2, 3]]
    assert [(p.after, p.seconds, p.kind) for p in script.pauses] == [(3, 1.0, "hesitation"), (11, 2.5, "hesitation")]


@pytest.mark.parametrize(
    "text, kind",
    [
        ("We left. [1.0] Then it rained.", "natural"),  # after a full stop, under two seconds
        ("We left. [2.0] Then it rained.", "hesitation"),  # long pauses always count
        ("We left [0.8] early.", "hesitation"),  # mid-phrase
        ("Well, {um} [0.8] yes.", "hesitation"),  # next to a filler
        ("We left [pause] early.", "hesitation"),  # own recordings: length unknown
    ],
)
def test_pause_kind_follows_the_pipeline_rules(text, kind):
    assert markup.parse(text).pauses[0].kind == kind


def test_ssml_and_reading_text():
    ssml = markup.to_ssml("Hello, {um} [1.2] world & friends.")
    assert '<break time="1200ms"/>' in ssml and "world &amp; friends." in ssml and "Hello, um" in ssml
    assert markup.to_reading_text("It was, {like}, great [1.5] fun.") == "It was, like, great (pause) fun."
    assert markup.to_reading_text("Stop [1.5] here.", show_seconds=True) == "Stop (pause 1.5 s) here."


def test_a_pause_cannot_start_a_script():
    with pytest.raises(ValueError):
        markup.parse("[1.0] Hello.")


# ---------- Metrics ----------


def test_word_error_rate_counts_substitutions_deletions_and_insertions():
    reference = metrics.words("the cat sat on the mat".split())
    assert metrics.wer(reference, reference) == 0.0
    assert metrics.edit_counts(reference, metrics.words("the dog sat on mat today".split())) == (1, 1, 1)
    assert metrics.wer(reference, metrics.words("the dog sat on mat today".split())) == pytest.approx(3 / 6)
    assert metrics.words(["Five,", "5.", "--"]) == ["5", "5"]


def test_span_matching_through_an_alignment():
    reference = "well um I think it was uh fine".split()
    hypothesis = "well um i think it was fine okay".split()
    mapping = metrics.align(reference, hypothesis)
    assert mapping[1] == 1 and mapping[2] == 2
    # "um" found, "uh" missed; "okay" wrongly flagged.
    assert metrics.match_spans([[1], [6]], [[1], [7]], mapping) == (1, 1, 1)


def test_interval_matching_is_one_to_one_with_tolerance():
    pairs, false_positives, false_negatives = metrics.match_intervals([(1.0, 2.0), (5.0, 6.0)], [(2.2, 2.6), (1.1, 1.9), (9.0, 9.5)], 0.3)
    assert pairs == [(0, 1)] and false_positives == 2 and false_negatives == 1


def test_prf_iou_summary_and_rank_correlation():
    assert metrics.prf(8, 2, 0) == {"precision": 0.8, "recall": 1.0, "f1": pytest.approx(0.889, abs=1e-3), "tp": 8, "fp": 2, "fn": 0}
    assert metrics.prf(0, 0, 0)["f1"] is None and metrics.prf(0, 3, 2)["f1"] == 0.0
    assert metrics.iou((0, 10), (5, 15)) == pytest.approx(5 / 15) and metrics.iou((0, 10), None) == 0.0
    assert metrics.summary([3, 1, 2])["median"] == 2 and metrics.summary([])["mean"] is None
    assert metrics.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert metrics.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


# ---------- Dataset files ----------


def test_every_synthetic_clip_parses_and_has_its_labels():
    clips = synthetic_clips()
    assert len(clips) >= 50 and len({clip.id for clip in clips}) == len(clips)
    for clip in clips:
        assert clip.script.tokens, clip.id
        if clip.category == "topic":
            assert clip.topic and clip.on_topic is not None, clip.id
        if clip.category in ("reading", "document"):
            assert clip.expect.get("verdict"), clip.id
        if clip.category == "document":
            assert clip.document and "section" in clip.expect, clip.id
        if clip.category == "jam":
            assert {"deviations", "repetitions"} <= set(clip.expect), clip.id


def test_reading_labels_match_the_scripts():
    manifest = load_manifest()
    library = manifest["passages"]["library"].split()
    for clip in synthetic_clips(manifest):
        if clip.category == "reading" and "missed" in clip.expect:
            said = clip.script.tokens
            # Word counts must balance: passage - missed + added == what is said.
            assert len(library) - clip.expect["missed"] + clip.expect["added"] == len(said), clip.id


def test_own_recordings_reuse_synthetic_labels():
    clips = own_clips()
    assert len(clips) == 10 and all(clip.expect["same_as"] for clip in clips)
    assert all(clip.source == "own" for clip in clips)
