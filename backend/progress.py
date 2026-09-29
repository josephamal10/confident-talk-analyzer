"""Progress analytics over a user's saved sessions: per-mode counts, per-skill trends, focus areas,
a practice suggestion and a daily streak."""
from collections import Counter
from datetime import datetime, timedelta

from analysis import modes
from analysis.scoring import LABELS

RECENT_WINDOW = 5
FOCUS_BELOW = 7.5
WEAKEST_LOOKBACK = 8

# Which mode trains each skill best, and why.
SKILL_PRACTICE = {
    "fluency": ("jam", "JAM makes you keep talking without fillers."),
    "pauses": ("jam", "JAM trains you to keep going instead of stopping to think."),
    "variety": ("jam", "JAM penalises repetition, so it builds a wider vocabulary."),
    "pace": ("read", "Reading aloud at a target pace builds a steady rhythm."),
    "phrasing": ("read", "Reading aloud teaches you to pause at full stops."),
    "accuracy": ("read", "Regular read-aloud practice improves accuracy."),
    "expressiveness": ("read", "Reading a story passage lets you practise varying your tone."),
    "vocal_confidence": ("debate", "Arguing a side trains an assertive, committed voice."),
    "language": ("debate", "Debate pushes you to state claims without hedging."),
    "timing": ("pitch", "Pitches teach you to land exactly on time."),
}


def _mean(values):
    return round(sum(values) / len(values), 1) if values else None


def _session_date(entry):
    try:
        return datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).date()
    except (KeyError, TypeError, ValueError):
        return None


def practice_streak(entries, today=None):
    """Consecutive days with at least one session, ending today or yesterday."""
    days = {day for day in map(_session_date, entries) if day}
    if not days:
        return 0
    today = today or datetime.utcnow().date()
    current = today if today in days else today - timedelta(days=1)
    streak = 0
    while current in days:
        streak += 1
        current -= timedelta(days=1)
    return streak


def skill_trends(entries):
    """Average of the last RECENT_WINDOW scores per skill, compared with the window before it."""
    trends = []
    for skill, label in LABELS.items():
        values = [
            entry["sub_scores"][skill]
            for entry in entries
            if entry.get("sub_scores") and entry["sub_scores"].get(skill) is not None
        ]
        if not values:
            continue
        recent = _mean(values[-RECENT_WINDOW:])
        previous = _mean(values[-2 * RECENT_WINDOW : -RECENT_WINDOW]) if len(values) > RECENT_WINDOW else None
        trends.append(
            {
                "skill": skill,
                "label": label,
                "recent": recent,
                "previous": previous,
                "change": round(recent - previous, 1) if previous is not None else None,
                "samples": len(values),
            }
        )
    return trends


def focus_areas(entries, trends):
    """Skills averaging below FOCUS_BELOW, most often the weakest area first."""
    weakest_counts = Counter()
    scored = [entry for entry in entries if entry.get("sub_scores")][-WEAKEST_LOOKBACK:]
    for entry in scored:
        values = {skill: value for skill, value in entry["sub_scores"].items() if value is not None}
        if values:
            weakest_counts[min(values, key=values.get)] += 1

    candidates = [trend for trend in trends if trend["recent"] < FOCUS_BELOW and trend["samples"] >= 2]
    candidates.sort(key=lambda trend: (-weakest_counts[trend["skill"]], trend["recent"]))
    focus = []
    for trend in candidates[:2]:
        count = weakest_counts[trend["skill"]]
        reason = (
            f"Your weakest area in {count} of your last {len(scored)} sessions."
            if count >= 2
            else f"Averaging {trend['recent']}/10 recently."
        )
        focus.append({"skill": trend["skill"], "label": trend["label"], "average": trend["recent"], "reason": reason})
    return focus


def _suggest(mode_id, reason):
    return {"mode": mode_id, "label": modes.get_mode(mode_id)["label"], "reason": reason}


def suggestion(entries, focus):
    """The mode to practise next: the one that trains the top focus area, else one not tried yet."""
    if not entries:
        return _suggest(modes.DEFAULT_MODE, "Start with free practice to get your baseline.")
    if focus:
        return _suggest(*SKILL_PRACTICE[focus[0]["skill"]])
    tried = {entry.get("mode") or modes.DEFAULT_MODE for entry in entries}
    untried = [mode_id for mode_id in modes.MODES if mode_id not in tried]
    if untried:
        return _suggest(untried[0], "Your scores are solid. Try a mode you haven't practised yet.")
    return _suggest("snap", "Your scores are solid everywhere. Snap talk keeps you sharp under pressure.")


def summarize(entries, mode_filter=None, today=None):
    """`entries` are history rows (oldest first) with timestamp, score, mode and sub_scores."""
    for entry in entries:
        entry["mode"] = entry.get("mode") or modes.DEFAULT_MODE
    counts = Counter(entry["mode"] for entry in entries)
    mode_summaries = [
        {
            "id": mode_id,
            "label": mode["label"],
            "count": counts.get(mode_id, 0),
            "best_score": max((e["score"] for e in entries if e["mode"] == mode_id), default=None),
        }
        for mode_id, mode in modes.MODES.items()
    ]

    selected = [entry for entry in entries if not mode_filter or entry["mode"] == mode_filter]
    trends = skill_trends(selected)
    focus = focus_areas(selected, trends)
    best = max(selected, key=lambda entry: entry["score"], default=None)
    return {
        "mode": mode_filter,
        "sessions": len(selected),
        "total_sessions": len(entries),
        "modes": mode_summaries,
        "streak": practice_streak(entries, today),
        "latest_score": selected[-1]["score"] if selected else None,
        "best": {"score": best["score"], "timestamp": best["timestamp"], "mode": best["mode"]} if best else None,
        "skills": trends,
        "focus": focus,
        "suggestion": suggestion(selected, focus),
    }
