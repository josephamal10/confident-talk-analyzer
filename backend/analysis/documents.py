"""Reference documents for read-aloud practice: text extraction from .pdf/.docx/.pptx/.txt/.md and a
quick read-aloud check of the text (length, reading time, long sentences, words to watch out for)."""
import logging
import os
import re
import zipfile
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}
# Enough for about 20 minutes of reading; longer documents are cut at a paragraph boundary.
MAX_WORDS = 3000
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
READING_WPM = 150
LONG_SENTENCE_WORDS = 30
MAX_WATCH_WORDS = 10
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+")


class DocumentError(Exception):
    pass


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _paragraphs_from_text(text):
    """Splits plain text on blank lines and rejoins lines that were wrapped mid-sentence."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text.replace("\r\n", "\n").replace("\r", "\n"))
    return [_clean(block) for block in re.split(r"\n\s*\n", text) if _clean(block)]


def _read_text_file(path):
    with open(path, "rb") as file:
        raw = file.read()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _strip_markdown(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^[ \t]{0,3}(?:#{1,6}|>|[-*+]|\d+[.)])[ \t]+", "", text, flags=re.MULTILINE)
    return re.sub(r"[*_`~]{1,3}", "", text)


def _parse_docx(path):
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > MAX_DOCX_XML_BYTES:
            raise DocumentError("That document is too large to read. Try a shorter file.")
        xml = archive.read(info)
    # Word never writes a DOCTYPE; refusing one rules out entity-expansion tricks in crafted files.
    if b"<!DOCTYPE" in xml[:4096].upper():
        raise DocumentError("That file couldn't be read. Save it again as .docx and retry.")
    root = ElementTree.fromstring(xml)
    paragraphs = []
    for paragraph in root.iter(f"{WORD_NAMESPACE}p"):
        pieces = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_NAMESPACE}t":
                pieces.append(node.text or "")
            elif node.tag in (f"{WORD_NAMESPACE}tab", f"{WORD_NAMESPACE}br"):
                pieces.append(" ")
        text = _clean("".join(pieces))
        if text:
            paragraphs.append(text)
    return paragraphs


def _parse_pdf(path):
    from pypdf import PdfReader

    paragraphs = []
    for page in PdfReader(path).pages:
        paragraphs.extend(_paragraphs_from_text(page.extract_text() or ""))
    return paragraphs


def _parse_pptx(path):
    from . import slides

    paragraphs = []
    for slide in slides._parse_pptx(path):
        paragraphs.extend(text for text in [slide["title"], *slide["lines"]] if text)
    return paragraphs


def _limit(paragraphs):
    """Keeps whole paragraphs up to MAX_WORDS (cutting the first one if it alone is longer)."""
    kept, total = [], 0
    for paragraph in paragraphs:
        words = paragraph.split()
        if total + len(words) > MAX_WORDS:
            if not kept:
                kept.append(" ".join(words[:MAX_WORDS]))
            return kept, True
        kept.append(paragraph)
        total += len(words)
    return kept, False


def parse_document(path, filename):
    """Returns {"filename", "format", "paragraphs", "text", "word_count", "truncated"}.
    Raises DocumentError for unsupported, unreadable or empty files."""
    extension = os.path.splitext(filename or "")[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentError("Upload a PDF, Word (.docx), PowerPoint (.pptx) or text file.")
    try:
        if extension == ".docx":
            paragraphs = _parse_docx(path)
        elif extension == ".pdf":
            paragraphs = _parse_pdf(path)
        elif extension == ".pptx":
            paragraphs = _parse_pptx(path)
        else:
            text = _read_text_file(path)
            paragraphs = _paragraphs_from_text(_strip_markdown(text) if extension == ".md" else text)
    except DocumentError:
        raise
    except Exception as error:
        logger.warning("Could not parse document %s: %s", filename, error)
        raise DocumentError("That file couldn't be read. Save it again (for example as PDF or .docx) and retry.") from error

    paragraphs, truncated = _limit(paragraphs)
    text = "\n\n".join(paragraphs)
    if len(text.split()) < 5:
        raise DocumentError("No readable text was found in that file. Scanned pages and images can't be read yet.")
    return {
        "filename": os.path.basename(filename),
        "format": extension[1:],
        "paragraphs": paragraphs,
        "text": text,
        "word_count": len(text.split()),
        "truncated": truncated,
    }


def _syllables(word):
    """Rough English syllable count (vowel groups, minus a silent final e)."""
    word = word.lower()
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def _readability(words, sentences):
    """Flesch reading ease (higher is easier) and a plain label for it."""
    letters = [re.sub(r"[^A-Za-z]", "", word) for word in words]
    letters = [word for word in letters if word]
    if not letters or not sentences:
        return None, None
    score = 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (sum(map(_syllables, letters)) / len(letters))
    score = round(max(0.0, min(100.0, score)))
    label = "Easy" if score >= 70 else "Standard" if score >= 50 else "Fairly hard" if score >= 30 else "Hard"
    return score, label


def _watch_words(text):
    """Things that trip readers up: figures, abbreviations and very long words, in reading order."""
    found, seen = [], set()
    for token in text.split():
        word = token.strip(".,;:!?\"'()[]")
        key = word.lower()
        if not word or key in seen:
            continue
        is_number = bool(re.search(r"\d", word))
        is_abbreviation = bool(re.fullmatch(r"[A-Z][A-Z0-9&]{1,}s?", word))
        is_long = len(word) >= 13 and word.isalpha()
        if is_number or is_abbreviation or is_long:
            seen.add(key)
            found.append(word)
            if len(found) == MAX_WATCH_WORDS:
                break
    return found


def check_document(document):
    """Instant read-aloud checks for a parsed document."""
    text = document["text"]
    words = text.split()
    sentences = [sentence for paragraph in document["paragraphs"] for sentence in SENTENCE_SPLIT.split(paragraph) if sentence.strip()]
    long_sentences = [sentence for sentence in sentences if len(sentence.split()) > LONG_SENTENCE_WORDS]
    readability, readability_label = _readability(words, sentences)
    return {
        "word_count": len(words),
        "paragraph_count": len(document["paragraphs"]),
        "sentence_count": len(sentences),
        "average_sentence_words": round(len(words) / len(sentences), 1) if sentences else None,
        "reading_seconds": round(60 * len(words) / READING_WPM),
        "readability": readability,
        "readability_label": readability_label,
        "long_sentence_count": len(long_sentences),
        "long_sentence_example": " ".join(long_sentences[0].split()[:14]) + "..." if long_sentences else None,
        "watch_words": _watch_words(text),
    }
