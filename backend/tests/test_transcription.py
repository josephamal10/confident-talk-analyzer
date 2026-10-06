from types import SimpleNamespace

import numpy as np

from analysis import transcription
from analysis.transcription import missed_speech


def word(text, start, end):
    return {"text": text, "start": start, "end": end, "probability": 0.9}


def segment(*words):
    return SimpleNamespace(
        compression_ratio=1.2,
        words=[SimpleNamespace(word=f" {text}", start=start, end=end, probability=0.9) for text, start, end in words],
    )


def test_missed_speech_is_empty_when_words_cover_the_speech():
    words = [word("hello", 0.1, 0.6), word("there", 0.7, 1.2), word("friend", 2.0, 2.5)]
    assert missed_speech(words, [(0.0, 1.3), (1.9, 2.6)]) == []


def test_missed_speech_finds_a_skipped_start_and_ignores_short_gaps():
    words = [word("the", 16.4, 16.6), word("palace", 16.7, 17.2), word("glows", 17.9, 18.3)]
    missed = missed_speech(words, [(0.0, 18.5)])
    assert missed == [(0.0, 16.4 - transcription.WORD_PAD)]


def test_missed_speech_finds_a_whole_region_with_no_words():
    words = [word("one", 0.0, 0.4), word("two", 5.0, 5.4)]
    assert missed_speech(words, [(0.0, 0.5), (2.0, 3.5), (5.0, 5.5)]) == [(2.0, 3.5)]


def test_only_the_skipped_stretch_is_transcribed_again_without_the_prompt(monkeypatch):
    prompted = [segment(("Um,", 16.0, 16.3), ("the", 16.4, 16.6), ("palace", 16.7, 17.2))]
    # Timings within the re-transcribed slice, which starts at 0.4 s.
    piece = [segment(("Indeed,", 0.1, 0.5), ("literature", 0.6, 1.2), ("is", 1.3, 1.4), ("genius.", 1.5, 2.0))]
    calls = []

    def fake_decode(audio, model=None, **options):
        calls.append((options.get("initial_prompt"), len(audio) / 16000))
        return prompted if options.get("initial_prompt") else piece

    monkeypatch.setattr(transcription, "_decode", fake_decode)
    text, words = transcription.transcribe(np.zeros(18 * 16000), speech_regions=[(0.4, 2.5), (15.9, 17.3)])
    assert calls == [(transcription.FILLER_PROMPT, 18.0), (None, 2.1)]
    assert text == "Indeed, literature is genius. Um, the palace"
    assert (words[0]["start"], words[3]["end"]) == (0.5, 2.4)


def test_no_second_pass_when_nothing_was_skipped(monkeypatch):
    calls = []

    def fake_decode(audio, model=None, **options):
        calls.append(options.get("initial_prompt"))
        return [segment(("Um,", 0.0, 0.3), ("hello", 0.4, 0.9))]

    monkeypatch.setattr(transcription, "_decode", fake_decode)
    text, _words = transcription.transcribe(np.zeros(16000), speech_regions=[(0.0, 1.0)])
    assert text == "Um, hello"
    assert calls == [transcription.FILLER_PROMPT]
