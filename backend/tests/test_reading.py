from analysis.reading import align_reading


def spoken(*items):
    """Builds word dicts from (text, start, end) tuples."""
    return [{"text": text, "start": start, "end": end, "filler": text.lower().strip(",.") in {"um", "uh"}} for text, start, end in items]


def test_perfect_reading():
    words = spoken(("The", 0.0, 0.2), ("train", 0.3, 0.6), ("is", 0.7, 0.8), ("late.", 0.9, 1.2), ("Sorry.", 1.6, 2.0))
    result = align_reading("The train is late. Sorry.", words)
    assert result["accuracy"] == 1.0 and result["word_error_rate"] == 0.0
    assert [t["status"] for t in result["tokens"]] == ["ok"] * 5
    assert result["sentence_pause_rate"] == 1.0


def test_skipped_misread_and_added_words():
    words = spoken(("The", 0.0, 0.2), ("brain", 0.3, 0.6), ("late", 0.7, 1.0), ("very", 1.1, 1.3))
    result = align_reading("The train is late.", words)
    statuses = {t["text"]: (t["status"], t["said"]) for t in result["tokens"]}
    assert statuses["train"] == ("misread", "brain")
    assert statuses["is"] == ("missed", None)
    assert result["added"] == ["very"]
    assert result["counts"] == {"ok": 2, "misread": 1, "missed": 1, "added": 1}
    assert result["accuracy"] == 0.5


def test_fillers_are_ignored_and_numbers_match_either_form():
    words = spoken(("Um,", 0.0, 0.2), ("It's", 0.3, 0.5), ("20", 0.6, 0.8), ("minutes", 0.9, 1.2), ("late.", 1.3, 1.6))
    result = align_reading("It's twenty minutes late.", words)
    assert result["accuracy"] == 1.0


def test_hyphenated_and_accented_words():
    words = spoken(("low", 0.0, 0.2), ("lying", 0.3, 0.5), ("cafe", 0.6, 0.9))
    assert align_reading("low-lying café", words)["accuracy"] == 1.0


def test_no_pause_at_full_stop_is_detected():
    words = spoken(("It", 0.0, 0.2), ("rained.", 0.3, 0.6), ("We", 0.65, 0.8), ("stayed.", 0.9, 1.2))
    result = align_reading("It rained. We stayed.", words)
    assert result["sentence_boundaries"] == 1 and result["sentence_pause_rate"] == 0.0


def test_empty_script():
    assert align_reading("   ", spoken(("hello", 0.0, 0.3))) is None
