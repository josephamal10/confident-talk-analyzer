import numpy as np
import pytest

from analysis import relevance

VECTORS = {
    "climate change": [1.0, 0.0, 0.0],
    "Global warming is rising fast.": [0.9, 0.1, 0.0],
    "My favourite food is biryani.": [0.0, 0.0, 1.0],
}


@pytest.fixture
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(relevance, "_load_model", lambda: ("tokenizer", "session"))

    def embed(texts):
        vectors = np.array([VECTORS.get(text, [0.1, 0.1, 0.1]) for text in texts], dtype=float)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    monkeypatch.setattr(relevance, "embed", embed)


def test_semantic_match_without_shared_keywords(fake_embeddings):
    result = relevance.topic_relevance("climate change", "Global warming is rising fast.")
    assert result["related"] and result["method"] == "embeddings" and result["similarity"] > 0.9


def test_unrelated_speech(fake_embeddings):
    result = relevance.topic_relevance("climate change", "My favourite food is biryani.")
    assert not result["related"] and result["similarity"] < 0.1


def test_threshold_is_configurable(fake_embeddings):
    speech = "My favourite food is biryani."
    assert relevance.topic_relevance("climate change", speech, threshold=-1)["related"]


def test_no_topic_returns_none():
    assert relevance.topic_relevance("  ", "anything") is None


def test_keyword_fallback_when_model_unavailable():
    # conftest marks the embedding model as unavailable.
    result = relevance.topic_relevance("nature", "Nature is everything around us.")
    assert result == {"related": True, "similarity": 1.0, "method": "keywords"}


def test_split_sentences_drops_fragments():
    assert relevance.split_sentences("Hi. Nature is everything around us. It gives us food!") == [
        "Nature is everything around us.",
        "It gives us food!",
    ]


def test_sentence_similarities(fake_embeddings):
    sims = relevance.sentence_similarities("climate change", ["Global warming is rising fast.", "My favourite food is biryani."])
    assert sims[0] > 0.9 and sims[1] < 0.1


def test_sentence_similarities_unavailable_without_model():
    assert relevance.sentence_similarities("climate change", ["Anything at all here."]) is None
