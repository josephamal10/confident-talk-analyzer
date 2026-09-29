from datetime import date

import progress


def session(day, score, mode="free", **sub_scores):
    return {"timestamp": f"2026-09-{day:02d}T10:00:00Z", "score": score, "mode": mode, "sub_scores": sub_scores or None}


def test_empty_history_suggests_free_practice():
    summary = progress.summarize([], today=date(2026, 9, 29))
    assert summary["sessions"] == 0 and summary["streak"] == 0 and summary["best"] is None
    assert summary["suggestion"]["mode"] == "free"


def test_streak_counts_consecutive_days_ending_today_or_yesterday():
    entries = [session(24, 6), session(26, 7), session(27, 7), session(28, 8)]
    assert progress.practice_streak(entries, today=date(2026, 9, 29)) == 3
    assert progress.practice_streak(entries, today=date(2026, 9, 28)) == 3
    assert progress.practice_streak(entries, today=date(2026, 9, 30)) == 0


def test_skill_trends_compare_recent_and_previous_windows():
    entries = [session(day, 6, pace=float(value)) for day, value in zip(range(1, 11), [4, 4, 4, 4, 4, 8, 8, 8, 8, 8])]
    trend = next(t for t in progress.skill_trends(entries) if t["skill"] == "pace")
    assert (trend["recent"], trend["previous"], trend["change"], trend["samples"]) == (8.0, 4.0, 4.0, 10)


def test_focus_prefers_the_recurring_weakest_skill_and_suggests_its_mode():
    entries = [session(day, 6, fluency=4.0, pace=9.0, timing=6.5) for day in range(1, 7)]
    summary = progress.summarize(entries, today=date(2026, 9, 7))
    assert [f["skill"] for f in summary["focus"]] == ["fluency", "timing"]
    assert summary["focus"][0]["reason"] == "Your weakest area in 6 of your last 6 sessions."
    assert summary["suggestion"]["mode"] == "jam"


def test_mode_filter_and_counts():
    entries = [session(1, 5, "jam", fluency=5.0), session(2, 9, "read", accuracy=9.5), session(3, 7, "jam", fluency=6.0)]
    summary = progress.summarize(entries, mode_filter="jam", today=date(2026, 9, 3))
    assert summary["sessions"] == 2 and summary["total_sessions"] == 3
    assert summary["latest_score"] == 7 and summary["best"]["score"] == 7
    counts = {m["id"]: m["count"] for m in summary["modes"]}
    assert counts["jam"] == 2 and counts["read"] == 1 and counts["pitch"] == 0
    assert [t["skill"] for t in summary["skills"]] == ["fluency"]


def test_legacy_sessions_without_mode_or_sub_scores():
    entries = [{"timestamp": "2026-02-12T07:24:46Z", "score": 8.5, "mode": None, "sub_scores": None}]
    summary = progress.summarize(entries, today=date(2026, 9, 29))
    assert summary["modes"][0]["count"] == 1 and summary["skills"] == [] and summary["focus"] == []


def test_strong_user_is_pointed_at_an_untried_mode():
    entries = [session(day, 9, "free", pace=9.0, fluency=9.0) for day in range(1, 4)]
    assert progress.summarize(entries, today=date(2026, 9, 3))["suggestion"]["mode"] == "interview"
