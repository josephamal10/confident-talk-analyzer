"""Read-aloud accuracy: aligns what was said with the script, word by word.

Uses a sequence alignment (difflib, like a word-level diff) to find skipped, misread and added
words, then checks whether the reader paused at the end of each sentence. Accuracy is limited by
the speech recogniser, which can "correct" small misreadings, so treat it as an estimate.

For a longer reference document the reader may read only part of it, so the part they read is
located first (from runs of matching words) and only that part is aligned.
"""
import difflib
import re
import unicodedata

# Speech recognisers write small numbers as words and larger ones as digits, so normalise both
# sides to digits before comparing.
NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20",
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
}
SENTENCE_END_PATTERN = re.compile(r"[.!?][\"')\]]*$")
MIN_SENTENCE_PAUSE_SECONDS = 0.25
STATUS_RANK = {"ok": 0, "misread": 1, "missed": 2}
# A run of this many matching words anchors where in a document the reader was.
MIN_ANCHOR_UNITS = 3
# A short anchor this far (in words) from the others is a coincidence, not the part that was read.
STRAY_ANCHOR_UNITS = 6
STRAY_GAP_UNITS = 40
# Unmatched words said at either edge extend the located part if at least this much of them matches
# the neighbouring text (a misread start/end); below it they were ad-libbed.
EDGE_MATCH_RATIO = 0.3
# An extended edge is snapped to the nearest sentence start/end within this many words.
SNAP_TOKENS = 10
# How closely the reading matched the text. Two shares are compared with these cut-offs: accuracy
# (how much of the text was read correctly) and spoken match (how much of what was said came from
# the text). A located part of a document needs at least MIN_SECTION_MATCH of the speech to come
# from it; below that a few shared words ("team won the final") are a coincidence.
# "Exactly as written" allows about one slip per 100 words either way (the speech recogniser
# makes some); the evaluation set showed looser limits calling readings with added or skipped
# words exact.
SAME_ACCURACY = 0.99
SAME_SPOKEN_MATCH = 0.99
CLOSE_ACCURACY = 0.6
PARTIAL_ACCURACY = 0.3
MIN_SECTION_MATCH = 0.3
# Semantic similarity above which a low word match still counts as "the same subject" (MiniLM:
# paraphrases of a passage score about 0.6-0.9 against it, other text on the same subject
# 0.4-0.6, unrelated text below 0.2).
RELATED_SIMILARITY = 0.4
MATCH_MESSAGES = {
    "same": "You read it exactly as written.",
    "close": "You read this text, with a few slips along the way.",
    "skipped": "What you read matches the text, but a good part of it was skipped or misread.",
    "partial": "Only parts of what you said match the text.",
    "related": "You talked about the same subject, but not in the text's words. It sounds like you paraphrased it or read a different version.",
    "different": "What you said doesn't match this text.",
}


def _pieces(token):
    """Normalised comparison units for one written token ("low-lying" -> ["low", "lying"])."""
    text = unicodedata.normalize("NFKD", token).encode("ascii", "ignore").decode().lower()
    text = text.replace("%", " percent").replace("-", " ")
    units = []
    for piece in text.split():
        piece = re.sub(r"[^a-z0-9']", "", piece.replace(",", "")).strip("'")
        if piece:
            units.append(NUMBER_WORDS.get(piece, piece))
    return units


def _script_units(tokens):
    return [(piece, token_index) for token_index, token in enumerate(tokens) for piece in _pieces(token)]


def _spoken_units(words):
    return [
        (piece, word_index)
        for word_index, word in enumerate(words)
        if not word.get("filler")
        for piece in _pieces(word["text"])
    ]


def align_reading(script, words):
    """Compares the spoken words (fillers excluded) with the script.

    Returns per-script-token statuses (ok / misread / missed), added words, accuracy, word error
    rate and the share of sentence ends where the reader paused.
    """
    tokens = script.split()
    units = _script_units(tokens)
    spoken = _spoken_units(words)
    if not units:
        return None

    unit_status = ["missed"] * len(units)
    unit_said = [None] * len(units)
    unit_word = [None] * len(units)
    added = []
    matcher = difflib.SequenceMatcher(a=[u[0] for u in units], b=[s[0] for s in spoken], autojunk=False)
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(a2 - a1):
                unit_status[a1 + offset] = "ok"
                unit_word[a1 + offset] = spoken[b1 + offset][1]
        elif tag == "replace":
            paired = min(a2 - a1, b2 - b1)
            for offset in range(paired):
                unit_status[a1 + offset] = "misread"
                unit_said[a1 + offset] = spoken[b1 + offset][0]
                unit_word[a1 + offset] = spoken[b1 + offset][1]
            added.extend(spoken[j][0] for j in range(b1 + paired, b2))
        elif tag == "insert":
            added.extend(spoken[j][0] for j in range(b1, b2))

    results = [{"text": token, "status": "ok", "said": []} for token in tokens]
    last_word = [None] * len(tokens)
    for (piece, token_index), status, said, word_index in zip(units, unit_status, unit_said, unit_word):
        result = results[token_index]
        if STATUS_RANK[status] > STATUS_RANK[result["status"]]:
            result["status"] = status
        if said:
            result["said"].append(said)
        if word_index is not None:
            last_word[token_index] = word_index
    for result in results:
        result["said"] = " ".join(result["said"]) or None

    counts = {status: unit_status.count(status) for status in ("ok", "misread", "missed")}
    counts["added"] = len(added)

    # Did the reader pause at the end of each sentence (except the last)?
    boundaries = paused = 0
    for token_index, token in enumerate(tokens[:-1]):
        word_index = last_word[token_index]
        if not SENTENCE_END_PATTERN.search(token) or word_index is None or word_index + 1 >= len(words):
            continue
        boundaries += 1
        if words[word_index + 1]["start"] - words[word_index]["end"] >= MIN_SENTENCE_PAUSE_SECONDS:
            paused += 1

    return {
        "tokens": results,
        "added": added[:20],
        "counts": counts,
        "accuracy": round(counts["ok"] / len(units), 3),
        "spoken_match": round(counts["ok"] / len(spoken), 3) if spoken else 0.0,
        "word_error_rate": round((counts["misread"] + counts["missed"] + counts["added"]) / len(units), 3),
        "sentence_boundaries": boundaries,
        "sentence_pause_rate": round(paused / boundaries, 2) if boundaries else None,
    }


def _is_stray(anchor, neighbour):
    """A short anchor far from its neighbour in the document, but not in the speech, is a coincidence."""
    earlier, later = sorted((anchor, neighbour), key=lambda block: block.a)
    document_gap = later.a - (earlier.a + earlier.size)
    spoken_gap = later.b - (earlier.b + earlier.size)
    return anchor.size < STRAY_ANCHOR_UNITS and document_gap > 3 * spoken_gap + STRAY_GAP_UNITS


def _sentence_start(tokens, index):
    return index == 0 or bool(SENTENCE_END_PATTERN.search(tokens[index - 1]))


def locate_reading(script, words):
    """Finds the part of a longer text that was read aloud. Returns (first_token, end_token), or None
    if no run of words matches the text at all."""
    tokens = script.split()
    units = _script_units(tokens)
    spoken = _spoken_units(words)
    if not units or not spoken:
        return None
    matcher = difflib.SequenceMatcher(a=[u[0] for u in units], b=[s[0] for s in spoken], autojunk=False)
    anchors = [block for block in matcher.get_matching_blocks() if block.size >= MIN_ANCHOR_UNITS]
    if not anchors:
        return None
    while len(anchors) > 1 and _is_stray(anchors[0], anchors[1]):
        anchors.pop(0)
    while len(anchors) > 1 and _is_stray(anchors[-1], anchors[-2]):
        anchors.pop()

    first, last = anchors[0], anchors[-1]
    pieces = [u[0] for u in units]
    said = [s[0] for s in spoken]
    # Words said before the first anchor (or after the last) were probably read just before (after)
    # it, as long as they resemble the text there; otherwise they were ad-libbed, not read.
    before, after = said[: first.b], said[last.b + last.size :]
    extend_start = _resembles(pieces[max(0, first.a - len(before)) : first.a], before)
    extend_end = _resembles(pieces[last.a + last.size : last.a + last.size + len(after)], after)
    start_unit = max(0, first.a - len(before)) if extend_start else first.a
    end_unit = min(len(units), last.a + last.size + len(after)) if extend_end else last.a + last.size
    start, end = units[start_unit][1], units[end_unit - 1][1] + 1
    first_anchor, last_anchor = units[first.a][1], units[last.a + last.size - 1][1] + 1

    # An extended edge is only an estimate, and readers start and stop at sentence boundaries, so
    # snap it to the nearest boundary close by. An edge that is an anchor is exact.
    if extend_start:
        starts = [
            i for i in range(max(0, start - SNAP_TOKENS), min(first_anchor, start + SNAP_TOKENS) + 1) if _sentence_start(tokens, i)
        ]
        if starts:
            start = min(starts, key=lambda i: abs(i - start))
    if extend_end:
        ends = [
            i for i in range(max(last_anchor, end - SNAP_TOKENS), min(len(tokens), end + SNAP_TOKENS) + 1)
            if i == len(tokens) or SENTENCE_END_PATTERN.search(tokens[i - 1])
        ]
        if ends:
            end = min(ends, key=lambda i: abs(i - end))
    return start, end


def _resembles(text_pieces, said_pieces):
    """Whether unanchored spoken words look like a (mis)reading of the neighbouring text."""
    if not said_pieces or not text_pieces:
        return False
    return difflib.SequenceMatcher(a=text_pieces, b=said_pieces, autojunk=False).ratio() >= EDGE_MATCH_RATIO


def read_from_document(text, words):
    """Aligns the reading with the part of the document that was read. The result also has a
    "section" (where the reading was, and what share of the document) or None if nothing matched."""
    tokens = text.split()
    span = locate_reading(text, words)
    result = align_reading(" ".join(tokens[span[0] : span[1]]), words) if span else None
    if result is None or result["spoken_match"] < MIN_SECTION_MATCH:
        return {
            "tokens": [],
            "added": [],
            "counts": {"ok": 0, "misread": 0, "missed": 0, "added": len(_spoken_units(words))},
            "accuracy": 0.0,
            "spoken_match": 0.0,
            "word_error_rate": 1.0,
            "sentence_boundaries": 0,
            "sentence_pause_rate": None,
            "section": None,
        }
    start, end = span
    result["section"] = {
        "start": start,
        "end": end,
        "total_words": len(tokens),
        "share": round((end - start) / len(tokens), 3),
        "first_words": " ".join(tokens[start : start + 6]),
        "last_words": " ".join(tokens[max(start, end - 6) : end]),
    }
    return result


def needs_similarity(reading_result):
    """The semantic check only matters when little of what was said came from the text."""
    return reading_result["spoken_match"] < CLOSE_ACCURACY


def match_verdict(accuracy, spoken_match, similarity=None):
    """How closely a reading matched the text: same, close, skipped (read from it but missed a lot),
    partial, related (same subject in other words) or different. `similarity` is the transcript's
    semantic similarity to the text, when needs_similarity() asked for it."""
    if accuracy >= SAME_ACCURACY and spoken_match >= SAME_SPOKEN_MATCH:
        verdict = "same"
    elif accuracy >= CLOSE_ACCURACY and spoken_match >= CLOSE_ACCURACY:
        verdict = "close"
    elif spoken_match >= CLOSE_ACCURACY:
        verdict = "skipped"
    elif similarity is not None and similarity >= RELATED_SIMILARITY:
        verdict = "related"
    elif spoken_match >= PARTIAL_ACCURACY:
        verdict = "partial"
    else:
        verdict = "different"
    return {"verdict": verdict, "similarity": similarity, "message": MATCH_MESSAGES[verdict]}
