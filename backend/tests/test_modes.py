import pytest

from analysis import modes, scoring


def test_every_mode_is_consistent():
    catalog = modes.public_catalog()
    assert [mode["id"] for mode in catalog["modes"]][0] == "free", "free practice comes first"
    assert len(catalog["modes"]) == 8
    for mode in modes.MODES.values():
        assert abs(sum(mode["weights"].values()) - 1.0) < 1e-6, mode["id"]
        assert set(mode["weights"]) <= set(scoring.SCORERS)
        if mode.get("coach"):
            assert mode["coach"]["dimensions"] in modes.COACH_DIMENSIONS
        bank = mode["prompt"].get("bank")
        if mode["prompt"]["kind"] not in ("question", "passage"):
            assert modes.BANK_ITEMS[bank], mode["id"]


def test_catalog_contents():
    catalog = modes.public_catalog()
    ids = [q["id"] for category in catalog["interview"] for q in category["questions"]]
    assert len(ids) == len(set(ids)) == len(modes.INTERVIEW_QUESTIONS)
    assert catalog["interview"][0]["id"] == "intro" and catalog["interview"][0]["framework"]["name"] == "Present-Past-Future"
    assert len(catalog["banks"]["jam_topics"]) >= 20 and len(catalog["banks"]["motions"]) >= 10
    assert all(p["style_label"] for p in catalog["passages"])


def test_free_mode_takes_a_typed_topic():
    context = modes.build_context({"mode": "free", "custom_prompt": "  My hometown  "})
    assert context["prompt"] == "My hometown" and context["framework"]["name"] == "Speech structure"
    assert context["target_seconds"] is None and context["wpm_range"] == [115, 165]


def test_unknown_mode_falls_back_to_free():
    assert modes.build_context({"mode": "karaoke"})["mode"] == "free"


def test_interview_question_sets_category_framework():
    context = modes.build_context({"mode": "interview", "prompt_id": "behavioral-1"})
    assert context["prompt"].startswith("Tell me about a time you faced a conflict")
    assert context["framework"]["name"] == "STAR" and context["category_label"] == "Behavioral"
    assert context["limit_seconds"] == 180


def test_interview_custom_question_uses_prep():
    context = modes.build_context({"mode": "interview", "custom_prompt": "Why this company?"})
    assert context["prompt"] == "Why this company?" and context["framework"]["name"] == "PREP"


def test_jam_topic_from_bank_and_fixed_minute():
    context = modes.build_context({"mode": "jam", "prompt_id": "jam_topics-1"})
    assert context["prompt"] == "Umbrellas" and context["target_seconds"] == 60 and context["limit_seconds"] == 60


def test_read_passage_sets_script_and_style_pace():
    context = modes.build_context({"mode": "read", "prompt_id": "news-night-buses"})
    assert context["script"].startswith("Good evening") and context["wpm_range"] == [145, 175]
    assert context["framework"] is None


def test_read_custom_script_wins():
    context = modes.build_context({"mode": "read", "prompt_id": "news-night-buses", "custom_script": "My own words."})
    assert context["script"] == "My own words." and context["style"] == "custom"


@pytest.mark.parametrize("requested, target, limit", [("180", 180, 270), ("999", 120, 180), (None, 120, 180)])
def test_presentation_target_choice(requested, target, limit):
    context = modes.build_context({"mode": "presentation", "custom_prompt": "AI", "target_seconds": requested, "notes": "x" * 5000})
    assert (context["target_seconds"], context["limit_seconds"]) == (target, limit)
    assert len(context["notes"]) == modes.MAX_NOTES


def test_debate_side_defaults_to_for():
    assert modes.build_context({"mode": "debate", "prompt_id": "motions-1"})["side"] == "for"
    assert modes.build_context({"mode": "debate", "prompt_id": "motions-1", "side": "against"})["side"] == "against"
    assert modes.build_context({"mode": "debate", "side": "sideways"})["side"] == "for"
