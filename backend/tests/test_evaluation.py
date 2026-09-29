import pytest

from analysis import evaluation, modes, relevance


def make_base(spec, pauses=(), timeline=None, start_delay=None):
    """A pipeline-shaped result built from (text, start, end, filler) tuples."""
    words = [{"text": t, "start": s, "end": e, "probability": 0.9, "filler": f} for t, s, e, f in spec]
    span = words[-1]["end"] - words[0]["start"]
    fillers = sum(1 for w in words if w["filler"])
    hesitations = [p for p in pauses if p["kind"] == "hesitation"]
    return {
        "transcription": " ".join(w["text"] for w in words),
        "words": words,
        "pauses": list(pauses),
        "timeline": timeline or [],
        "uptalk": None,
        "warnings": [],
        "metrics": {
            "duration": words[-1]["end"] + 0.5,
            "speaking_span": span,
            "word_count": len(words),
            "wpm": round(len(words) / (span / 60)),
            "filler_count": fillers,
            "fillers_per_100_words": round(100 * fillers / len(words), 1),
            "top_filler": "um" if fillers else None,
            "pause_count": len(pauses),
            "hesitation_pause_count": len(hesitations),
            "hesitation_pauses_per_minute": round(len(hesitations) / (span / 60), 1),
            "longest_pause": max((p["duration"] for p in pauses), default=0.0),
            "start_delay": start_delay if start_delay is not None else words[0]["start"],
            "pitch_variation": 3.0,
            "dominance": 0.5,
        },
    }


def evenly(text, start=0.5, step=0.4, fillers=()):
    return [(word, start + i * step, start + i * step + 0.3, word.lower().strip(",.") in fillers)
            for i, word in enumerate(text.split())]


def test_sub_scores_follow_the_mode_weights():
    base = make_base(evenly("Umbrellas keep us dry when it rains and they come in many colours."))
    for mode_id in modes.MODES:
        context = modes.build_context({"mode": mode_id})
        result = evaluation.evaluate(base, modes.get_mode(mode_id), context)
        assert set(result["sub_scores"]) == set(modes.get_mode(mode_id)["weights"]), mode_id
        assert 0 <= result["score"] <= 10


def test_language_metrics_feed_fluency_and_confident_language():
    base = make_base(evenly("I think it it is kind of maybe the best plan we have for the team."))
    result = evaluation.evaluate(base, modes.get_mode("free"), modes.build_context({"mode": "free"}))
    assert result["metrics"]["hedge_count"] == 3 and result["metrics"]["top_hedge"] in {"i think", "kind of", "maybe"}
    assert result["metrics"]["stutter_count"] == 1
    assert result["sub_scores"]["language"] < 10


def test_jam_referee_flags_hesitation_repetition_and_start_delay():
    spec = evenly("Rain is great, um, rain rain makes plants grow and plants love water and plants need sun.",
                  start=3.5, fillers=("um",))
    pause = {"start": 8.0, "end": 9.2, "duration": 1.2, "kind": "hesitation", "before_word": 12}
    base = make_base(spec, pauses=[pause], start_delay=3.5)
    context = modes.build_context({"mode": "jam", "custom_prompt": "Rain"})
    result = evaluation.evaluate(base, modes.get_mode("jam"), context)

    referee = result["referee"]
    kinds = [event["type"] for event in referee["events"]]
    assert kinds[0] == "hesitation" and referee["events"][0]["detail"] == "3.5s before you started"
    assert referee["counts"]["hesitation"] >= 3
    assert any(e["detail"] == '"rain" said twice' for e in referee["events"])
    assert any(e["detail"] == '"plants" for the 3rd time' for e in referee["events"])
    assert referee["clean_seconds"] == 0.0 and referee["deviation_checked"] is False
    assert result["metrics"]["hesitation_pause_count"] == 2, "the slow start counts as a hesitation"


def test_jam_referee_flags_deviation_when_embeddings_are_available(monkeypatch):
    monkeypatch.setattr(relevance, "sentence_similarities", lambda topic, sentences: [0.5, 0.02])
    spec = evenly("Rain makes everything fresh and green. I bought new shoes at the mall.")
    result = evaluation.evaluate(make_base(spec), modes.get_mode("jam"), modes.build_context({"mode": "jam", "custom_prompt": "Rain"}))
    deviations = [e for e in result["referee"]["events"] if e["type"] == "deviation"]
    assert len(deviations) == 1 and deviations[0]["detail"].startswith('"I bought new shoes')
    assert result["referee"]["clean_seconds"] == pytest.approx(deviations[0]["time"] - 0.5, abs=0.1)


def test_read_mode_scores_accuracy_and_skips_topic_matching():
    context = modes.build_context({"mode": "read", "custom_script": "The train is late. Please wait."})
    spec = [("The", 0.5, 0.7, False), ("train", 0.8, 1.1, False), ("is", 1.2, 1.3, False),
            ("late.", 1.4, 1.8, False), ("Please", 2.3, 2.6, False), ("wait.", 2.7, 3.0, False)]
    result = evaluation.evaluate(make_base(spec), modes.get_mode("read"), context)
    assert result["reading"]["accuracy"] == 1.0 and result["sub_scores"]["accuracy"] == 10.0
    assert result["sub_scores"]["phrasing"] == 10.0
    assert result["topic_match"] is None


def test_presentation_timing_and_timeline_warnings():
    spec = evenly(" ".join(f"idea{i}" for i in range(50)), step=0.9)
    timeline = [
        {"start": 0, "end": 10, "wpm": 100, "fillers": 0, "energy_db": -20.0},
        {"start": 10, "end": 20, "wpm": 110, "fillers": 0, "energy_db": -21.0},
        {"start": 20, "end": 30, "wpm": 140, "fillers": 0, "energy_db": -25.0},
    ]
    base = make_base(spec, timeline=timeline)
    context = modes.build_context({"mode": "presentation", "custom_prompt": "Ideas", "target_seconds": "60"})
    result = evaluation.evaluate(base, modes.get_mode("presentation"), context)
    assert result["trends"] == {"pace_change": 0.4, "energy_change_db": -5.0}
    assert any("sped up by 40%" in w for w in result["warnings"])
    assert any("energy dropped" in w for w in result["warnings"])
    assert result["sub_scores"]["timing"] is not None


def test_uptalk_warning_needs_enough_statements():
    base = make_base(evenly("It works. It helps. It is fast. It is cheap."))
    base["uptalk"] = {"statements": 4, "rising_indexes": [1, 3, 7], "share": 0.75}
    result = evaluation.evaluate(base, modes.get_mode("free"), modes.build_context({"mode": "free"}))
    assert any("rising pitch" in w for w in result["warnings"])
