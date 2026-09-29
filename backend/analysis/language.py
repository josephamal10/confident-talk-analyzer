"""Word-level checks on the transcript: hedging language, stutters and over-repeated words."""
from collections import defaultdict

from .fillers import normalize

# Qualifiers and softeners that make a speaker sound unsure of their own point.
HEDGE_PHRASES = (
    "i'm not sure", "i don't know", "i feel like", "a little bit", "i think", "i guess", "i suppose",
    "not sure", "kind of", "sort of", "maybe", "probably", "perhaps", "hopefully", "just", "sorry",
)
# "kind of" / "sort of" after these words is a noun phrase ("what kind of car"), not a hedge.
NOUN_PHRASE_PRECEDERS = {"what", "this", "that", "the", "any", "every", "some", "all", "one", "same", "which", "a"}
# Stutter-like repeats that are normal English.
ALLOWED_REPEATS = {"very", "really", "no", "bye", "so", "had", "that"}

STOPWORDS = set(
    """a about above after again against all also am an and any are as at be because been before being
    below between both but by can could did do does doing down during each even ever every few for from
    further get gets got had has have having he her here hers him his how i if in into is it its itself
    just let like make many me might more most much must my no nor not now of off on once one only or
    other our ours out over own really same say says said see she should so some such than that the their
    them then there these they thing things this those through to too under until up us very was way we
    well were what when where which while who whom why will with would yes yet you your yours i'm it's
    that's there's don't can't won't we're they're you're i've we've they've i'll we'll i'd let's""".split()
)


def _stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def find_hedges(tokens, skip=frozenset()):
    """Returns hedge occurrences as {"phrase", "indexes"}; `skip` holds indexes already tagged as fillers."""
    words = [normalize(token) for token in tokens]
    phrases = sorted((phrase.split() for phrase in HEDGE_PHRASES), key=len, reverse=True)
    hedges, index = [], 0
    while index < len(words):
        for phrase in phrases:
            end = index + len(phrase)
            if words[index:end] != phrase or any(i in skip for i in range(index, end)):
                continue
            if phrase[-1] == "of" and index > 0 and words[index - 1] in NOUN_PHRASE_PRECEDERS:
                continue
            hedges.append({"phrase": " ".join(phrase), "indexes": list(range(index, end))})
            index = end - 1
            break
        index += 1
    return hedges


def _repeat_size(words, index, skip):
    """Length of a phrase (3, 2 or 1 words) starting at `index` that is immediately said again, else 0."""
    for size in (3, 2, 1):
        first, second = words[index : index + size], words[index + size : index + 2 * size]
        if len(second) < size or first != second or not all(first):
            continue
        if any(i in skip for i in range(index, index + 2 * size)):
            continue
        if size == 1 and first[0] in ALLOWED_REPEATS:
            continue
        return size
    return 0


def find_stutters(tokens, skip=frozenset()):
    """Immediate repeats of one to three words ("the the", "I went, I went"). Indexes point at the repeat."""
    words = [normalize(token) for token in tokens]
    stutters, index = [], 0
    while index < len(words):
        size = _repeat_size(words, index, skip)
        if size:
            stutters.append(
                {"phrase": " ".join(words[index : index + size]), "indexes": list(range(index + size, index + 2 * size))}
            )
            index += size
        else:
            index += 1
    return stutters


def find_repeated_words(tokens, skip=frozenset(), topic="", min_count=3):
    """Content words used `min_count` or more times, ignoring stopwords and the topic's own words.

    Returns (repeated, extra) where extra counts the occurrences beyond the allowed ones.
    """
    topic_words = {_stem(normalize(word)) for word in topic.split()}
    occurrences = defaultdict(list)
    for index, token in enumerate(tokens):
        word = normalize(token)
        if index in skip or len(word) < 3 or word in STOPWORDS:
            continue
        stem = _stem(word)
        if stem in topic_words:
            continue
        occurrences[stem].append(index)

    repeated = [
        {"word": normalize(tokens[indexes[0]]), "count": len(indexes), "indexes": indexes}
        for indexes in occurrences.values()
        if len(indexes) >= min_count
    ]
    repeated.sort(key=lambda item: -item["count"])
    extra = sum(item["count"] - (min_count - 1) for item in repeated)
    return repeated, extra
