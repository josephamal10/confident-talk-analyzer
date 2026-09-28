"""Filler-word detection that tells hesitations ("um") apart from normal use of words like "like"."""
import re

HESITATION_PATTERN = re.compile(r"u+h+m*|u+m+|h+m+|e+r+m*|a+h+")
DISCOURSE_FILLERS = {"like", "actually", "basically", "literally", "you know", "i mean"}
CLAUSE_END_PATTERN = re.compile(r"[,.;:!?—…]$")


def normalize(token):
    return re.sub(r"[^a-z']", "", token.lower())


def split_clauses(tokens):
    """Groups token indexes into clauses, splitting after tokens that end in punctuation."""
    clauses, current = [], []
    for index, token in enumerate(tokens):
        current.append(index)
        if CLAUSE_END_PATTERN.search(token):
            clauses.append(current)
            current = []
    if current:
        clauses.append(current)
    return clauses


def find_filler_spans(tokens):
    """Returns each filler occurrence as a list of token indexes.

    Hesitation sounds ("um", "uhh", "hmm") always count. Discourse markers ("like", "you know",
    "actually") only count when they form a clause of their own ("it was, like, great"), so
    "I like nature" or "what actually happened" are not penalised.
    """
    spans = []
    for clause in split_clauses(tokens):
        words = [normalize(tokens[index]) for index in clause]
        if " ".join(words) in DISCOURSE_FILLERS:
            spans.append(clause)
            continue
        spans.extend([index] for index, word in zip(clause, words) if HESITATION_PATTERN.fullmatch(word))
    return spans


def count_fillers(text):
    return len(find_filler_spans((text or "").split()))
