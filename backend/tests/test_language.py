from analysis.language import find_hedges, find_repeated_words, find_stutters


def phrases(found):
    return [item["phrase"] for item in found]


def test_hedges_longest_phrase_wins():
    tokens = "I'm not sure, but I think it's kind of good. Maybe.".split()
    assert phrases(find_hedges(tokens)) == ["i'm not sure", "i think", "kind of", "maybe"]


def test_kind_of_as_a_noun_phrase_is_not_a_hedge():
    assert find_hedges("What kind of car is it? This sort of thing was sort of fine.".split()) == [
        {"phrase": "sort of", "indexes": [11, 12]}
    ]


def test_hedges_skip_words_already_counted_as_fillers():
    assert find_hedges("I just, like, left.".split(), skip={1}) == []


def test_curly_apostrophes_are_normalised():
    assert phrases(find_hedges(["I’m", "not", "sure."])) == ["i'm not sure"]


def test_stutters_single_and_phrase_repeats():
    found = find_stutters("It, it uses the the steps, set of steps, set of steps.".split())
    assert phrases(found)[:2] == ["it", "the"] and len(found) == 3
    assert found[0]["indexes"] == [1]
    assert phrases(find_stutters("I went, I went home.".split())) == ["i went"]


def test_normal_doubled_words_are_not_stutters():
    assert find_stutters("It was very very good, no no.".split()) == []


def test_repeated_content_words_ignore_topic_and_stopwords():
    tokens = ("Umbrellas are useful. An umbrella is useful when rain falls, useful in rain, "
              "and the rain is heavy.").split()
    repeated, extra = find_repeated_words(tokens, topic="Umbrellas")
    assert [(item["word"], item["count"]) for item in repeated] == [("useful.", 3), ("rain", 3)] or \
        {(item["word"].strip(".,"), item["count"]) for item in repeated} == {("useful", 3), ("rain", 3)}
    assert extra == 2
