"""Question bank for interview practice and topic suggestions for free speaking practice."""
import json
import os

_BANK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json")

with open(_BANK_PATH, encoding="utf-8") as _file:
    _BANK = json.load(_file)

FRAMEWORKS = _BANK["frameworks"]
FREE_TOPIC_FRAMEWORK = FRAMEWORKS["SPEECH"]


def _question_id(category_id, index):
    return f"{category_id}-{index + 1}"


QUESTIONS = {
    _question_id(category["id"], index): {
        "id": _question_id(category["id"], index),
        "text": text,
        "category": category["id"],
        "category_label": category["label"],
        "framework": FRAMEWORKS[category["framework"]],
    }
    for category in _BANK["categories"]
    for index, text in enumerate(category["questions"])
}


def get_question(question_id):
    return QUESTIONS.get(question_id)


def public_bank():
    """The bank as the frontend needs it: categories with their questions, plus topic ideas."""
    return {
        "categories": [
            {
                "id": category["id"],
                "label": category["label"],
                "framework": FRAMEWORKS[category["framework"]],
                "questions": [
                    {"id": _question_id(category["id"], index), "text": text}
                    for index, text in enumerate(category["questions"])
                ],
            }
            for category in _BANK["categories"]
        ],
        "topics": _BANK["topics"],
    }
