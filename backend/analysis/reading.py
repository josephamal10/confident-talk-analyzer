"""Read-aloud accuracy: aligns what was said with the script, word by word.

Uses a sequence alignment (difflib, like a word-level diff) to find skipped, misread and added
words, then checks whether the reader paused at the end of each sentence. Accuracy is limited by
the speech recogniser, which can "correct" small misreadings, so treat it as an estimate.
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


def align_reading(script, words):
    """Compares the spoken words (fillers excluded) with the script.

    Returns per-script-token statuses (ok / misread / missed), added words, accuracy, word error
    rate and the share of sentence ends where the reader paused.
    """
    tokens = script.split()
    units = [(piece, token_index) for token_index, token in enumerate(tokens) for piece in _pieces(token)]
    spoken = [
        (piece, word_index)
        for word_index, word in enumerate(words)
        if not word.get("filler")
        for piece in _pieces(word["text"])
    ]
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
        "word_error_rate": round((counts["misread"] + counts["missed"] + counts["added"]) / len(units), 3),
        "sentence_boundaries": boundaries,
        "sentence_pause_rate": round(paused / boundaries, 2) if boundaries else None,
    }
