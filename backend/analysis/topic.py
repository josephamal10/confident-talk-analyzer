"""Keyword-overlap check of whether a speech stays on its topic."""
import re

TOPIC_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "about", "into", "their",
    "there", "have", "will", "would", "should", "could", "what", "when", "where", "which",
    "while", "who", "whom", "why", "how", "are", "was", "were", "has", "had", "been", "being",
    "can", "just", "than", "then", "them", "they", "you", "our", "out", "all", "any", "too",
    "very", "its",
}


def extract_topic_tokens(text):
    tokens = re.findall(r"[a-zA-Z0-9']+", (text or "").lower())
    return [token for token in tokens if len(token) > 2 and token not in TOPIC_STOPWORDS]


def is_topic_related(topic, transcription):
    """Returns (related, matched_words, coverage)."""
    topic_clean = (topic or "").strip().lower()
    transcription_clean = (transcription or "").strip().lower()

    if not topic_clean:
        return True, [], 1.0
    if not transcription_clean:
        return False, [], 0.0
    # Whole-phrase match on word boundaries, so a topic like "art" doesn't match "start".
    if re.search(rf"\b{re.escape(topic_clean)}\b", transcription_clean):
        return True, extract_topic_tokens(topic_clean), 1.0

    topic_tokens = set(extract_topic_tokens(topic_clean))
    speech_tokens = set(extract_topic_tokens(transcription_clean))

    if not topic_tokens:
        return True, [], 1.0

    overlap = sorted(topic_tokens.intersection(speech_tokens))
    coverage = len(overlap) / len(topic_tokens)
    minimum_overlap = 1 if len(topic_tokens) <= 2 else 2
    related = coverage >= 0.4 or len(overlap) >= minimum_overlap
    return related, overlap, round(coverage, 2)
