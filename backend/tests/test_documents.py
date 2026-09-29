import io
import zipfile

import numpy as np
import pytest

from analysis import documents, evaluation, modes, reading, relevance
from test_api import FAKE_BASE, TRANSCRIPT, analyze
from test_slides import SPECS, make_pdf, make_pptx

NEWS = (
    "Good evening, here are tonight's headlines. The city council has announced that free night buses will begin "
    "running from next Monday. The new service will operate every 30 minutes on four of the busiest routes."
)
DOCUMENT_TEXT = (
    "The council met on Tuesday to discuss the budget. Members argued for hours about road repairs.\n\n"
    f"{NEWS}\n\n"
    "In sport, the local team won again. The coach praised the players for their effort in the rain."
)


def spoken(text):
    return [{"text": word, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, word in enumerate(text.split())]


def make_docx(path, paragraphs, doctype=False):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    xml = f'<?xml version="1.0"?>{"<!DOCTYPE x>" if doctype else ""}<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


# ---------- Parsing ----------


def test_text_file_rejoins_wrapped_lines_and_hyphenation(tmp_path):
    path = tmp_path / "news.txt"
    path.write_text("Good evening, here are tonight's head-\nlines. The council\nhas announced free buses.\n\nSecond paragraph here now.", encoding="utf-8")
    document = documents.parse_document(str(path), "news.txt")
    assert document["paragraphs"] == [
        "Good evening, here are tonight's headlines. The council has announced free buses.",
        "Second paragraph here now.",
    ]
    assert document["format"] == "txt" and document["word_count"] == 16 and not document["truncated"]


def test_markdown_is_reduced_to_plain_text(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Weather today\n\nExpect **heavy rain** in the [north](http://x.test) this evening.\n\n- Carry an umbrella please", encoding="utf-8")
    assert documents.parse_document(str(path), "notes.md")["paragraphs"] == [
        "Weather today",
        "Expect heavy rain in the north this evening.",
        "Carry an umbrella please",
    ]


def test_docx_paragraphs(tmp_path):
    path = make_docx(tmp_path / "script.docx", ["Good evening and welcome.", "Here is the news for today."])
    document = documents.parse_document(str(path), "script.docx")
    assert document["paragraphs"] == ["Good evening and welcome.", "Here is the news for today."]


def test_docx_with_a_doctype_is_refused(tmp_path):
    path = make_docx(tmp_path / "evil.docx", ["Good evening and welcome to the news."], doctype=True)
    with pytest.raises(documents.DocumentError):
        documents.parse_document(str(path), "evil.docx")


def test_pdf_and_pptx_documents(tmp_path):
    pdf = make_pdf(tmp_path / "bulletin.pdf", [["Good evening, here are the headlines", "for tonight in the city."]])
    assert "Good evening, here are the headlines" in documents.parse_document(str(pdf), "bulletin.pdf")["text"]
    pptx = make_pptx(tmp_path / "talk.pptx", SPECS)
    paragraphs = documents.parse_document(str(pptx), "talk.pptx")["paragraphs"]
    assert paragraphs[0] == "Solar energy for homes" and "How panels work" in paragraphs


@pytest.mark.parametrize("name, content", [("image.png", b"\x89PNG"), ("empty.txt", b"   "), ("broken.docx", b"not a zip")])
def test_unusable_documents_raise(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(documents.DocumentError):
        documents.parse_document(str(path), name)


def test_long_documents_are_cut_at_a_paragraph(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "MAX_WORDS", 12)
    path = tmp_path / "long.txt"
    path.write_text("One two three four five six.\n\nSeven eight nine ten.\n\nEleven twelve thirteen fourteen.", encoding="utf-8")
    document = documents.parse_document(str(path), "long.txt")
    assert document["paragraphs"] == ["One two three four five six.", "Seven eight nine ten."] and document["truncated"]


def test_document_checks():
    long_sentence = " ".join(["word"] * 35) + "."
    text = f"NASA spent 2,450 dollars on the telecommunications upgrade. {long_sentence}"
    checks = documents.check_document({"text": text, "paragraphs": [text]})
    assert checks["sentence_count"] == 2 and checks["long_sentence_count"] == 1
    assert checks["watch_words"] == ["NASA", "2,450", "telecommunications"]
    assert checks["reading_seconds"] == round(60 * checks["word_count"] / documents.READING_WPM)
    assert checks["readability_label"] in {"Easy", "Standard", "Fairly hard", "Hard"}


# ---------- Finding the part that was read ----------


def test_reading_part_of_a_document_is_located_and_aligned():
    said = NEWS.replace("begin running", "start running").replace("every 30 minutes", "every thirty minutes")
    result = reading.read_from_document(DOCUMENT_TEXT, spoken(said))
    section = result["section"]
    assert section["first_words"].startswith("Good evening") and section["last_words"].endswith("busiest routes.")
    assert 0.3 < section["share"] < 0.7
    assert result["counts"]["missed"] == 0 and result["counts"]["misread"] == 1
    assert result["accuracy"] > 0.9


def test_starting_mid_sentence_counts_only_what_was_skipped():
    said = NEWS.split("The city council")[1]
    result = reading.read_from_document(DOCUMENT_TEXT, spoken("The city council" + said))
    assert result["section"]["first_words"].startswith("The city council") and result["accuracy"] == 1.0


def test_a_stray_coincidental_match_is_ignored():
    # "the local team" also appears much later in the document; it must not stretch the section there.
    weather = "Now the weather. " + " ".join(f"cloudy{i}" for i in range(50)) + "."
    text = f"{NEWS}\n\n{weather}\n\nIn sport, the local team won again."
    result = reading.read_from_document(text, spoken(NEWS + " Thanks to the local team for watching."))
    assert result["section"]["last_words"].endswith("busiest routes.")
    assert result["accuracy"] == 1.0 and "local" in result["added"]


def test_unrelated_speech_matches_no_section():
    result = reading.read_from_document(DOCUMENT_TEXT, spoken("Umbrellas are one of the most useful inventions ever made."))
    assert result["section"] is None and result["accuracy"] == 0.0 and result["counts"]["added"] == 10


@pytest.mark.parametrize(
    "accuracy, similarity, verdict",
    [(0.95, None, "same"), (0.7, None, "close"), (0.2, 0.62, "related"), (0.45, 0.1, "partial"), (0.1, 0.05, "different"),
     (0.1, None, "different")],
)
def test_match_verdict(accuracy, similarity, verdict):
    assert reading.match_verdict(accuracy, similarity)["verdict"] == verdict


def test_evaluation_reports_a_paraphrase_as_the_same_subject(monkeypatch):
    base = {**FAKE_BASE, "words": spoken("Tonight the council said buses at night will be free starting Monday."),
            "transcription": "Tonight the council said buses at night will be free starting Monday."}
    monkeypatch.setattr(relevance, "_load_failed", False)
    monkeypatch.setattr(relevance, "_load_model", lambda: object())
    monkeypatch.setattr(relevance, "embed", lambda texts: np.array([[1.0, 0.0]] + [[0.6, 0.8]] * (len(texts) - 1)))
    document = {"text": DOCUMENT_TEXT, "paragraphs": DOCUMENT_TEXT.split("\n\n")}
    context = modes.build_context({"mode": "read", "reading_style": "news"}, document={"id": 1, "filename": "n.txt", "word_count": 60})
    assert context["wpm_range"] == modes.PASSAGE_STYLES["news"]["wpm_range"] and context["prompt"] == "n.txt"
    result = evaluation.evaluate(base, modes.get_mode("read"), context, document=document)
    assert result["reading"]["match"] == {"verdict": "related", "similarity": 0.6, "message": reading.MATCH_MESSAGES["related"]}


def test_built_in_passages_get_a_verdict_too():
    context = modes.build_context({"mode": "read", "custom_script": TRANSCRIPT})
    result = evaluation.evaluate(FAKE_BASE, modes.get_mode("read"), context)
    assert result["reading"]["match"]["verdict"] == "same" and "section" not in result["reading"]


# ---------- API ----------


def upload_document(client, name="bulletin.txt", text=DOCUMENT_TEXT):
    return client.post("/documents", data={"document": (io.BytesIO(text.encode()), name)})


def test_document_upload_returns_text_and_checks(client, make_user):
    make_user()
    response = upload_document(client)
    assert response.status_code == 201
    body = response.get_json()
    assert body["filename"] == "bulletin.txt" and len(body["paragraphs"]) == 3
    assert body["checks"]["word_count"] == body["word_count"] and "30" in body["checks"]["watch_words"]


def test_document_upload_validation(client, make_user):
    assert upload_document(client).status_code == 401
    make_user()
    assert client.post("/documents", data={}).status_code == 400
    assert upload_document(client, name="picture.png").status_code == 400
    assert upload_document(client, text="   ").status_code == 400


def test_reading_from_an_uploaded_document(client, make_user, monkeypatch):
    make_user()
    text = f"Welcome to the reading test for this week.\n\n{TRANSCRIPT}\n\nThat is the end of the passage for today."
    document_id = upload_document(client, name="confidence.docx.txt", text=text).get_json()["id"]
    body = analyze(client, monkeypatch, mode="read", document_id=str(document_id), reading_style="speech")
    assert body["context"]["document"]["id"] == document_id and body["topic"] == "confidence.docx.txt"
    assert body["context"]["wpm_range"] == modes.PASSAGE_STYLES["speech"]["wpm_range"]
    assert body["reading"]["section"]["first_words"].startswith("Confidence is the belief")
    assert body["reading"]["accuracy"] == 1.0 and body["reading"]["match"]["verdict"] == "same"


def test_another_users_document_is_not_used(client, make_user, monkeypatch):
    make_user()
    document_id = upload_document(client).get_json()["id"]
    client.post("/logout")
    make_user()
    body = analyze(client, monkeypatch, mode="read", document_id=str(document_id))
    assert "document" not in body["context"] and body["reading"] is None


def test_a_misread_first_word_still_starts_the_section():
    said = NEWS.replace("Good evening", "Good morning")
    result = reading.read_from_document(DOCUMENT_TEXT, spoken(said))
    assert result["section"]["first_words"].startswith("Good evening")
    assert result["tokens"][1] == {"text": "evening,", "status": "misread", "said": "morning"}
