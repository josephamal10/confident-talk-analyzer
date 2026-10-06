import json

import pytest

import app as app_module
from analysis import coach, interview, llm, modes
from test_api import FAKE_BASE, analyze, upload


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  Data   analyst ", "Data analyst"),
        ("AI / ML engineer (fresher)", "AI / ML engineer (fresher)"),
        ("<script>alert(1)</script> Nurse", "scriptalert(1)/script Nurse"),
        ("", ""),
        (None, ""),
        ("x" * 200, "x" * interview.MAX_ROLE_LENGTH),
    ],
)
def test_clean_role(raw, expected):
    assert interview.clean_role(raw) == expected


def test_fallback_questions_mention_the_role_and_cover_all_types():
    questions = interview.fallback_questions("Data analyst")
    assert len(questions) == 8 and questions[0]["id"] == "role-1"
    assert {q["type"] for q in questions} == {"behavioral", "role", "motivation"}
    assert any("Data analyst" in q["text"] for q in questions)


def test_normalize_questions_dedupes_and_fixes_types():
    raw = {"questions": [
        {"text": "Tell me about a time you   led a team.", "type": "Behavioral"},
        {"text": "tell me about a time you led a team.", "type": "behavioral"},
        {"text": "How would you clean a messy dataset?", "type": "technical"},
        {"text": "Why?", "type": "motivation"},
    ]}
    questions = interview.normalize_questions(raw)
    assert [(q["text"], q["type"], q["type_label"]) for q in questions] == [
        ("Tell me about a time you led a team.", "behavioral", "Behavioral"),
        ("How would you clean a messy dataset?", "role", "Role-specific"),
    ]


def test_generate_questions_uses_strict_schema_and_delimits_the_role(monkeypatch):
    captured = {}

    def fake_chat_json(config, messages, schema, name, **options):
        captured.update(messages=messages, schema=schema, name=name)
        return {"questions": [{"text": "Walk me through a dashboard you built.", "type": "role"}]}, {}

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    questions = interview.generate_questions("Data analyst", config=object())
    assert questions[0]["type"] == "role" and captured["name"] == "interview_questions"
    assert captured["messages"][1]["content"] == "<role>Data analyst</role>"
    assert captured["schema"] is interview.QUESTIONS_SCHEMA


def test_generated_question_type_picks_the_framework():
    context = modes.build_context({"mode": "interview", "custom_prompt": "Tell me about a time you led a team.",
                                   "question_type": "behavioral", "role": "Product manager"})
    assert context["framework"]["name"] == "STAR" and context["category_label"] == "Behavioral"
    assert context["role"] == "Product manager"
    technical = modes.build_context({"mode": "interview", "custom_prompt": "How do you prioritise?", "question_type": "role"})
    assert technical["framework"]["name"] == "Explain simply"


def test_role_reaches_the_coach_prompt():
    context = modes.build_context({"mode": "interview", "prompt_id": "personal-2", "role": "Data analyst"})
    analysis = {"score": 7.0, "delivery": "Steady", "metrics": FAKE_BASE["metrics"]}
    user = coach.build_messages("I am good with numbers.", context, analysis)[1]["content"]
    assert "preparing for a job interview as: Data analyst" in user


def test_catalog_lists_common_roles():
    assert "Data analyst" in modes.public_catalog()["roles"]


def test_role_questions_endpoint_falls_back_without_llm(client, make_user):
    make_user()
    assert client.post("/interview/questions", json={"role": "  "}).status_code == 400
    body = client.post("/interview/questions", json={"role": "Nurse"}).get_json()
    assert body["source"] == "built-in" and body["role"] == "Nurse" and len(body["questions"]) == 8


def test_role_questions_are_generated_once_then_cached(client, make_user, monkeypatch):
    make_user()
    calls = []

    def fake_generate(role, config):
        calls.append(role)
        return interview.normalize_questions({"questions": [{"text": f"What does a great {role} do daily?", "type": "role"}]})

    monkeypatch.setattr(app_module.llm, "get_config", lambda: object())
    monkeypatch.setattr(app_module.interview, "generate_questions", fake_generate)
    first = client.post("/interview/questions", json={"role": "Civil engineer"}).get_json()
    second = client.post("/interview/questions", json={"role": "civil ENGINEER"}).get_json()
    assert first["source"] == "ai" and first["cached"] is False and second["cached"] is True
    assert calls == ["Civil engineer"] and second["questions"] == first["questions"]


def test_llm_failure_falls_back_and_is_not_cached(client, make_user, monkeypatch):
    make_user()

    def failing(role, config):
        raise llm.LLMError("rate limited", retryable=True, status_code=429)

    monkeypatch.setattr(app_module.llm, "get_config", lambda: object())
    monkeypatch.setattr(app_module.interview, "generate_questions", failing)
    body = client.post("/interview/questions", json={"role": "Teacher"}).get_json()
    assert body["source"] == "built-in"
    with app_module.app.app_context():
        assert app_module.get_db().execute("SELECT COUNT(*) FROM role_questions WHERE role_key = 'teacher'").fetchone()[0] == 0


def test_role_questions_require_login(client):
    assert client.post("/interview/questions", json={"role": "Nurse"}).status_code == 401


def test_interview_answer_saves_the_role(client, make_user, monkeypatch):
    make_user()
    body = analyze(client, monkeypatch, mode="interview", custom_prompt="Why do you want to be a nurse?",
                   question_type="motivation", role="Nurse")
    assert body["context"]["role"] == "Nurse" and body["context"]["framework"]["name"] == "PREP"


def stream_events(response):
    return [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()]


def test_streamed_analysis_reports_stages_then_the_result(client, make_user, monkeypatch):
    make_user()

    def staged(path, report=None):
        for stage in ("decode", "transcribe", "prosody", "tone"):
            report(stage)
        return FAKE_BASE

    monkeypatch.setattr(app_module, "analyze_recording", staged)
    response = client.post("/analyze?stream=1", data=upload(mode="free"))
    assert response.mimetype == "application/x-ndjson"
    events = stream_events(response)
    assert [e["stage"] for e in events if "stage" in e] == ["decode", "transcribe", "prosody", "tone", "score"]
    assert events[-1]["result"]["mode"] == "free" and events[-1]["result"]["id"] > 0


def test_streamed_analysis_reports_errors(client, make_user, monkeypatch):
    make_user()

    def silent(path, report=None):
        report("decode")
        raise app_module.AnalysisError("No speech was detected.", 422)

    monkeypatch.setattr(app_module, "analyze_recording", silent)
    events = stream_events(client.post("/analyze?stream=1", data=upload()))
    assert events == [{"stage": "decode"}, {"error": "No speech was detected.", "status": 422}]


def poll_job(client, job_id):
    events, after = [], 0
    for _ in range(50):
        update = client.get(f"/analyze/jobs/{job_id}?after={after}").get_json()
        events += update["events"]
        after = update["next"]
        if update["done"]:
            return events
    raise AssertionError("the job never finished")


def test_analysis_job_is_polled_for_stages_then_the_result(client, make_user, monkeypatch):
    make_user()

    def staged(path, report=None):
        for stage in ("decode", "transcribe", "prosody", "tone"):
            report(stage)
        return FAKE_BASE

    monkeypatch.setattr(app_module, "analyze_recording", staged)
    response = client.post("/analyze?job=1", data=upload(mode="free"))
    assert response.status_code == 202
    events = poll_job(client, response.get_json()["job"])
    assert [e["stage"] for e in events if "stage" in e] == ["decode", "transcribe", "prosody", "tone", "score"]
    assert events[-1]["result"]["mode"] == "free" and events[-1]["result"]["id"] > 0


def test_analysis_job_reports_errors_and_is_private(client, make_user, monkeypatch):
    make_user()

    def silent(path, report=None):
        report("decode")
        raise app_module.AnalysisError("No speech was detected.", 422)

    monkeypatch.setattr(app_module, "analyze_recording", silent)
    job_id = client.post("/analyze?job=1", data=upload()).get_json()["job"]
    assert poll_job(client, job_id) == [{"stage": "decode"}, {"error": "No speech was detected.", "status": 422}]

    other = app_module.app.test_client()
    make_user(other)
    assert other.get(f"/analyze/jobs/{job_id}").status_code == 404
    assert client.get("/analyze/jobs/not-a-job").status_code == 404


# ---------- Interview JAM rounds ----------


def test_fallback_jam_topics_mention_the_role_and_mix_types():
    topics = interview.fallback_jam_topics("Data analyst")
    assert any("Data analyst" in topic["text"] for topic in topics)
    assert {topic["type"] for topic in topics} == {"role", "general"}
    assert topics[0]["id"] == "jam-role-1" and topics[0]["type_label"] == "About the role"


def test_normalize_jam_topics_dedupes_trims_and_drops_long_ones():
    result = {"topics": [
        {"text": ' "Data in everyday life." ', "type": "ROLE"},
        {"text": "data in everyday life", "type": "role"},
        {"text": "Teamwork", "type": "general"},
        {"text": "A topic that is far too long to be a JAM topic for anyone", "type": "general"},
        {"text": "Dashboards", "type": "weird"},
    ]}
    topics = interview.normalize_jam_topics(result)
    assert [(t["text"], t["type"]) for t in topics] == [("Data in everyday life", "role"), ("Teamwork", "general"), ("Dashboards", "role")]


def test_generate_jam_topics_delimits_the_role(monkeypatch):
    seen = {}

    def fake_chat_json(config, messages, schema, name, **options):
        seen.update(messages=messages, schema=schema, name=name)
        return {"topics": [{"text": "Data in everyday life", "type": "role"}]}, {}

    monkeypatch.setattr(interview.llm, "chat_json", fake_chat_json)
    topics = interview.generate_jam_topics("Data analyst", object())
    assert topics[0]["text"] == "Data in everyday life"
    assert seen["name"] == "jam_topics" and seen["messages"][1]["content"] == "<role>Data analyst</role>"
    assert "untrusted" in seen["messages"][0]["content"] and seen["schema"]["additionalProperties"] is False


def test_jam_topics_endpoint_falls_back_then_caches_ai_topics(client, make_user, monkeypatch):
    make_user()
    body = client.post("/jam/topics", json={"role": "Nurse"}).get_json()
    assert body["source"] == "built-in" and any("Nurse" in topic["text"] for topic in body["topics"])
    assert client.post("/jam/topics", json={"role": "  "}).status_code == 400

    calls = []

    def fake_generate(role, config):
        calls.append(role)
        return interview.normalize_jam_topics({"topics": [{"text": "Patient care at night", "type": "role"}]})

    monkeypatch.setattr(app_module.llm, "get_config", lambda: object())
    monkeypatch.setattr(app_module.interview, "generate_jam_topics", fake_generate)
    first = client.post("/jam/topics", json={"role": "Staff nurse"}).get_json()
    second = client.post("/jam/topics", json={"role": "STAFF NURSE"}).get_json()
    assert first["cached"] is False and second["cached"] is True and calls == ["Staff nurse"]
    assert second["topics"][0]["text"] == "Patient care at night"


def test_jam_topics_require_login(client):
    assert client.post("/jam/topics", json={"role": "Nurse"}).status_code == 401


def test_interview_jam_keeps_the_role_and_judges_like_a_panel(client, make_user, monkeypatch):
    make_user()
    body = analyze(client, monkeypatch, mode="jam", custom_prompt="Data in everyday life", role="Data analyst")
    context = body["context"]
    assert context["role"] == "Data analyst" and context["prompt"] == "Data in everyday life"
    mode = modes.get_mode("jam")
    analysis = {"score": 7.0, "delivery": "Steady", "metrics": FAKE_BASE["metrics"]}
    user = coach.build_messages("Data is everywhere.", context, analysis, mode["coach"])[1]["content"]
    assert "JAM round of a job interview for a Data analyst role" in user
    assert "preparing for a job interview as" not in user


def test_modes_without_roles_ignore_a_role():
    assert "role" not in modes.build_context({"mode": "free", "role": "Nurse"})
