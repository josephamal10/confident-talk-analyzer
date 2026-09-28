import pytest

from analysis.fillers import count_fillers, find_filler_spans


@pytest.mark.parametrize(
    "text, expected",
    [
        ("I like nature and I like trees.", 0),
        ("Things like trees and rivers are part of nature.", 0),
        ("What actually happened was simple.", 0),
        ("The umbrella is under the album.", 0),
        ("It was, like, amazing.", 1),
        ("Basically, the system records your voice.", 1),
        ("Um, so, uh, the project is, you know, about speech.", 3),
        ("Umm... I mean, hmm, let me think.", 3),
        ("uh uh um", 3),
        ("", 0),
    ],
)
def test_count_fillers(text, expected):
    assert count_fillers(text) == expected


def test_multi_word_filler_is_one_span():
    tokens = ["It", "is,", "you", "know,", "hard."]
    assert find_filler_spans(tokens) == [[2, 3]]
