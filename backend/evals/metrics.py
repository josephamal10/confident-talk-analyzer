"""Metrics for the evaluation: word error rate, word alignment, precision/recall and summaries."""
import difflib
import re
import statistics

from analysis.fillers import HESITATION_PATTERN
from analysis.reading import NUMBER_WORDS


def norm(token):
    """Comparison form of a word: lower case, no punctuation, numbers as digits ("Five," -> "5")."""
    word = re.sub(r"[^a-z0-9']", "", token.lower().replace("’", "'").replace(",", "")).strip("'")
    return NUMBER_WORDS.get(word, word)


def words(tokens):
    """Normalised words, dropping tokens that were only punctuation."""
    return [word for word in (norm(token) for token in tokens) if word]


def is_hesitation(token):
    return bool(HESITATION_PATTERN.fullmatch(norm(token)))


def edit_counts(reference, hypothesis):
    """(substitutions, deletions, insertions) for the minimum word edit between two word lists."""
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    # Each cell holds (total, substitutions, deletions, insertions).
    previous = [(j, 0, 0, j) for j in range(cols)]
    for i in range(1, rows):
        current = [(i, 0, i, 0)]
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                current.append(previous[j - 1])
                continue
            sub, dele, ins = previous[j - 1], previous[j], current[j - 1]
            best = min(
                (sub[0] + 1, sub[1] + 1, sub[2], sub[3]),
                (dele[0] + 1, dele[1], dele[2] + 1, dele[3]),
                (ins[0] + 1, ins[1], ins[2], ins[3] + 1),
            )
            current.append(best)
        previous = current
    _total, substitutions, deletions, insertions = previous[-1]
    return substitutions, deletions, insertions


def wer(reference, hypothesis):
    """Word error rate of two word lists (already normalised)."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return sum(edit_counts(reference, hypothesis)) / len(reference)


def align(reference_tokens, hypothesis_tokens):
    """Maps reference token indexes to hypothesis token indexes (equal and substituted words pair up)."""
    ref = [norm(token) for token in reference_tokens]
    hyp = [norm(token) for token in hypothesis_tokens]
    mapping = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False).get_opcodes():
        if tag in ("equal", "replace"):
            for offset in range(min(i2 - i1, j2 - j1)):
                mapping[i1 + offset] = j1 + offset
    return mapping


def match_spans(reference_spans, hypothesis_spans, mapping):
    """Span-level matching through a word alignment. A reference span is found when any of its words
    maps onto a word of a hypothesis span. Returns (true positives, false positives, false negatives)."""
    hypothesis_owner = {index: number for number, span in enumerate(hypothesis_spans) for index in span}
    matched_hypothesis = set()
    true_positives = 0
    for span in reference_spans:
        owners = {hypothesis_owner[mapping[i]] for i in span if i in mapping and mapping[i] in hypothesis_owner}
        if owners:
            true_positives += 1
            matched_hypothesis |= owners
    false_positives = len(hypothesis_spans) - len(matched_hypothesis)
    return true_positives, false_positives, len(reference_spans) - true_positives


def match_intervals(true_intervals, predicted_intervals, tolerance=0.3):
    """One-to-one matching of time intervals that overlap (within `tolerance` seconds).
    Returns (matched pairs as (true index, predicted index), false positives, false negatives)."""
    pairs, used = [], set()
    for t_index, (t_start, t_end) in enumerate(true_intervals):
        candidates = [
            (abs((p_start + p_end) / 2 - (t_start + t_end) / 2), p_index)
            for p_index, (p_start, p_end) in enumerate(predicted_intervals)
            if p_index not in used and p_start <= t_end + tolerance and p_end >= t_start - tolerance
        ]
        if candidates:
            _distance, p_index = min(candidates)
            used.add(p_index)
            pairs.append((t_index, p_index))
    return pairs, len(predicted_intervals) - len(used), len(true_intervals) - len(pairs)


def prf(true_positives, false_positives, false_negatives):
    """Precision, recall and F1 (None where undefined)."""
    precision = true_positives / (true_positives + false_positives) if true_positives + false_positives else None
    recall = true_positives / (true_positives + false_negatives) if true_positives + false_negatives else None
    if precision is None or recall is None:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": true_positives, "fp": false_positives, "fn": false_negatives}


def iou(a, b):
    """Overlap of two half-open ranges [start, end) as intersection over union."""
    if not a or not b:
        return 0.0
    intersection = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return intersection / union if union else 0.0


def summary(values):
    """Mean, median, 95th percentile and max of a list of numbers."""
    values = sorted(value for value in values if value is not None)
    if not values:
        return {"n": 0, "mean": None, "median": None, "p95": None, "max": None}
    p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
    return {"n": len(values), "mean": statistics.fmean(values), "median": statistics.median(values), "p95": p95, "max": values[-1]}


def spearman(xs, ys):
    """Rank correlation of two equal-length lists (no tie correction; ties get their average rank)."""
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                result[order[k]] = (i + j) / 2
            i = j + 1
        return result

    if len(xs) < 2:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None
