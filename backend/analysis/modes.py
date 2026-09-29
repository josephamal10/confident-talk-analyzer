"""Practice modes. Each speaking situation (JAM, interview, read aloud...) is defined in modes.json and
draws its content from prompts.json, so adding a situation is a config change rather than new code."""
import json
import os

from . import interview

_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    with open(os.path.join(_DIR, name), encoding="utf-8") as file:
        return json.load(file)


_CONFIG = _load("modes.json")
_PROMPTS = _load("prompts.json")

FRAMEWORKS = _CONFIG["frameworks"]
COACH_DIMENSIONS = {key: [tuple(pair) for pair in pairs] for key, pairs in _CONFIG["coach_dimensions"].items()}
MODES = {mode["id"]: mode for mode in _CONFIG["modes"]}
DEFAULT_MODE = "free"
PASSAGE_STYLES = _PROMPTS["passage_styles"]
TOPIC_BANKS = ("topics", "jam_topics", "snap_topics", "pitch_prompts", "motions")
MAX_CUSTOM_PROMPT = 300
MAX_CUSTOM_SCRIPT = 3000
MAX_NOTES = 1500


def _question_id(category_id, index):
    return f"{category_id}-{index + 1}"


INTERVIEW_QUESTIONS = {
    _question_id(category["id"], index): {
        "id": _question_id(category["id"], index),
        "text": text,
        "category": category["id"],
        "category_label": category["label"],
        "framework": FRAMEWORKS[category["framework"]],
    }
    for category in _PROMPTS["interview"]
    for index, text in enumerate(category["questions"])
}
BANK_ITEMS = {
    bank: {f"{bank}-{index + 1}": text for index, text in enumerate(_PROMPTS[bank])} for bank in TOPIC_BANKS
}
PASSAGES = {passage["id"]: passage for passage in _PROMPTS["passages"]}


def get_mode(mode_id):
    return MODES.get(mode_id) or MODES[DEFAULT_MODE]


def coach_dimensions(mode):
    return COACH_DIMENSIONS[mode["coach"]["dimensions"]] if mode.get("coach") else None


def resolve_timer(mode, requested_target=None):
    """Returns (target_seconds, limit_seconds) for a mode; either can be None."""
    timer = mode["timer"]
    target = timer.get("target_seconds")
    choices = timer.get("target_choices")
    if choices:
        try:
            requested = int(requested_target or 0)
        except (TypeError, ValueError):
            requested = 0
        target = requested if requested in choices else target
    limit = timer.get("limit_seconds")
    if limit is None and target and timer.get("limit_factor"):
        limit = round(target * timer["limit_factor"])
    return target, limit


def build_context(form, document=None):
    """What the speaker is practising, resolved from the submitted form against the content banks.

    `document` is the uploaded reference document chosen for read-aloud ({"id", "filename", "word_count"}).
    """
    mode = get_mode(form.get("mode", DEFAULT_MODE))
    prompt_config = mode["prompt"]
    framework_key = mode.get("framework")
    context = {
        "mode": mode["id"],
        "mode_label": mode["label"],
        "prompt_label": prompt_config["label"],
        "prompt": "",
        "prompt_id": None,
        "framework": FRAMEWORKS.get(framework_key) if framework_key not in (None, "category") else None,
    }
    custom_prompt = (form.get("custom_prompt") or "").strip()[:MAX_CUSTOM_PROMPT]
    prompt_id = form.get("prompt_id") or ""
    # The job role the user is practising for (interview questions, interview JAM rounds).
    role = interview.clean_role(form.get("role")) if prompt_config.get("roles") else ""
    if role:
        context["role"] = role

    if prompt_config["kind"] == "question":
        question = INTERVIEW_QUESTIONS.get(prompt_id)
        question_type = form.get("question_type")
        if custom_prompt:
            # A typed question, or one generated for the user's role (which sends its type along).
            context.update(prompt=custom_prompt, framework=FRAMEWORKS[interview.framework_key(question_type)])
            if question_type in interview.TYPE_LABELS:
                context["category_label"] = interview.TYPE_LABELS[question_type]
        elif question:
            context.update(
                prompt=question["text"],
                prompt_id=question["id"],
                category_label=question["category_label"],
                framework=question["framework"],
            )
        else:
            context["framework"] = FRAMEWORKS["PREP"]
    elif prompt_config["kind"] == "passage":
        custom_script = (form.get("custom_script") or "").strip()[:MAX_CUSTOM_SCRIPT]
        passage = PASSAGES.get(prompt_id)
        # Your own text or document can be read in any style (news, story...), which sets the target pace.
        style = form.get("reading_style") if form.get("reading_style") in PASSAGE_STYLES else "custom"
        if document:
            context.update(prompt=document["filename"], document=document, style=style)
        elif custom_script:
            context.update(prompt="Your own text", script=custom_script, style=style)
        elif passage:
            context.update(prompt=passage["title"], prompt_id=passage["id"], script=passage["text"], style=passage["style"])
    else:
        bank_text = BANK_ITEMS.get(prompt_config["bank"], {}).get(prompt_id)
        context["prompt"] = custom_prompt or bank_text or ""
        context["prompt_id"] = None if custom_prompt else (prompt_id if bank_text else None)

    if prompt_config.get("notes"):
        context["notes"] = (form.get("notes") or "").strip()[:MAX_NOTES]
    if prompt_config.get("sides"):
        context["side"] = form.get("side") if form.get("side") in ("for", "against") else "for"

    context["target_seconds"], context["limit_seconds"] = resolve_timer(mode, form.get("target_seconds"))
    if mode["wpm_range"] == "passage":
        context["wpm_range"] = PASSAGE_STYLES[context.get("style", "custom")]["wpm_range"]
    else:
        context["wpm_range"] = mode["wpm_range"]
    return context


def public_catalog():
    """Everything the frontend needs to render the mode picker and each mode's setup panel."""
    return {
        "modes": [
            {
                "id": mode["id"],
                "label": mode["label"],
                "tagline": mode["tagline"],
                "prompt": mode["prompt"],
                "timer": mode["timer"],
                "framework": FRAMEWORKS.get(mode["framework"]) if mode["framework"] not in (None, "category") else None,
                "skills": sorted(mode["weights"], key=lambda skill: -mode["weights"][skill]),
                "coached": mode.get("coach") is not None,
            }
            for mode in _CONFIG["modes"]
        ],
        "interview": [
            {
                "id": category["id"],
                "label": category["label"],
                "framework": FRAMEWORKS[category["framework"]],
                "questions": [
                    {"id": _question_id(category["id"], index), "text": text}
                    for index, text in enumerate(category["questions"])
                ],
            }
            for category in _PROMPTS["interview"]
        ],
        "roles": interview.COMMON_ROLES,
        "banks": {
            bank: [{"id": item_id, "text": text} for item_id, text in BANK_ITEMS[bank].items()] for bank in TOPIC_BANKS
        },
        "passages": [
            {**passage, "style_label": PASSAGE_STYLES[passage["style"]]["label"]} for passage in _PROMPTS["passages"]
        ],
        "passage_styles": [
            {"id": style_id, "label": style["label"], "wpm_range": style["wpm_range"]} for style_id, style in PASSAGE_STYLES.items()
        ],
    }
