"""Evaluates the AI coach and the role prompt writers against the configured LLM (backend/.env).

    python -m evals.coach_eval

For each transcript in fixtures/coach_cases.json it records the model's raw answer and the cleaned
one the app shows, then measures: valid answers and retries, speed, on/off-topic agreement with the
human label, invented numbers caught by the guardrail, placeholders on thin answers, quotes that
really come from the transcript, and how chatbot-like the wording is before and after clean-up.
Writes results/coach_latest.json and results/COACH.md. It makes about 20 API calls.
"""
import datetime as dt
import json
import os
import re
import sys
import time

from dotenv import load_dotenv

from . import metrics as m
from .dataset import EVALS_DIR

BACKEND_DIR = os.path.dirname(EVALS_DIR)
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from analysis import coach, interview, language, llm, modes  # noqa: E402
from analysis.fillers import count_fillers  # noqa: E402
from analysis.reading import NUMBER_WORDS  # noqa: E402

CASES = os.path.join(EVALS_DIR, "fixtures", "coach_cases.json")
RESULTS_DIR = os.path.join(EVALS_DIR, "results")
# Free tiers limit tokens per minute, so calls are spaced out and retried after a rate limit.
PAUSE_BETWEEN_CALLS = 6
RATE_LIMIT_WAITS = (20, 40, 60)
# The wording the coach prompt tells the model to avoid (see analysis/coach.py SYSTEM_PROMPT).
STOCK_PHRASES = ("overall", "great job", "it is important to", "additionally", "furthermore", "in conclusion")
BUZZWORDS = ("enhance", "leverage", "showcase", "demonstrate", "effectively", "delve", "robust", "comprehensive",
             "crucial", "utilize", "valuable")
QUOTE_PATTERN = re.compile(r"[\"“]([^\"”]{3,})[\"”]")


def with_retries(call):
    for wait in (*RATE_LIMIT_WAITS, None):
        try:
            return call()
        except llm.LLMError as error:
            if error.status_code != 429 or wait is None:
                raise
            print(f"  rate limited, waiting {wait}s")
            time.sleep(wait)


def delivery_stub(transcript):
    """Plausible delivery measurements for the prompt (the coach only mentions them when they matter)."""
    words = transcript.split()
    return {
        "score": 7.0,
        "delivery": "Steady",
        "metrics": {
            "speaking_span": round(len(words) / 2.4, 1),
            "wpm": 144,
            "filler_count": count_fillers(transcript),
            "hesitation_pause_count": 1,
            "hedge_count": len(language.find_hedges(words)),
            "pitch_variation": 2.6,
            "dominance": 0.5,
        },
    }


def feedback_texts(result):
    """The prose the user reads (not the rewritten answer)."""
    texts = [result["summary"], result["topic_feedback"], *result["strengths"]]
    for item in result["improvements"]:
        texts += [item["issue"], item["suggestion"]]
    return [text for text in texts if text]


def about_the_speaker(result):
    """The parts that describe what was said, where a quote should be the speaker's own words
    (tips quote suggested phrasing instead)."""
    return [result["summary"], result["topic_feedback"], *result["strengths"], *(item["issue"] for item in result["improvements"])]


def invented_numbers(texts, transcript):
    """Numbers (digits or words from two up) in the texts that the speaker never said."""
    spoken = coach._spoken_numbers(transcript)
    found = []
    for text in texts:
        found += [n for n in coach.NUMBER_PATTERN.findall(text) if n not in spoken]
        found += [w for w in coach.SPELLED_NUMBER_PATTERN.findall(text)
                  if w.lower() not in spoken and NUMBER_WORDS.get(w.lower()) not in spoken]
    return found


def style(texts):
    text = " ".join(texts)
    lower = text.lower()
    words = re.findall(r"[a-z']+", lower)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    per_100 = lambda count: 100 * count / len(words) if words else 0.0  # noqa: E731
    return {
        "words": len(words),
        "chatbot_phrases_per_100_words": per_100(sum(lower.count(p) for p in STOCK_PHRASES + BUZZWORDS)),
        "em_dashes": text.count("—"),
        "semicolons": text.count(";"),
        "third_person": len(re.findall(r"\bthe (speaker|user|candidate)\b", lower)),
        "you_per_100_words": per_100(sum(word in ("you", "your", "you're", "you've", "you'd", "you'll") for word in words)),
        "words_per_sentence": len(words) / len(sentences) if sentences else 0.0,
    }


def quotes(texts, transcript):
    """Quoted phrases in the feedback, and how many really appear in the transcript."""
    found = [q.strip(" .,!?").lower() for text in texts for q in QUOTE_PATTERN.findall(text)]
    spoken = re.sub(r"\s+", " ", transcript.lower())
    grounded = sum(1 for q in found if q and q in spoken)
    return len(found), grounded


def run_case(case, config):
    form = case["form"]
    context = modes.build_context(form)
    mode = modes.get_mode(context["mode"])
    if not context.get("framework"):
        context["framework"] = modes.FRAMEWORKS.get(mode["framework"], modes.FRAMEWORKS["SPEECH"])
    dimensions = modes.coach_dimensions(mode)
    transcript = case["transcript"]
    messages = coach.build_messages(transcript, context, delivery_stub(transcript), mode["coach"], dimensions)
    raw, meta = with_retries(lambda: llm.chat_json(config, messages, coach.build_schema(dimensions), "speech_coaching", temperature=0.4))
    cleaned = coach.normalize(raw, context["framework"], transcript, dimensions)

    raw_parts = raw["framework_check"]["present"] + raw["framework_check"]["missing"]
    known = {coach._part_key(part) for part in context["framework"]["parts"]}
    quoted, grounded = quotes(about_the_speaker(raw), transcript)
    raw_tips = [item["suggestion"] for item in raw["improvements"]]
    clean_tips = [item["suggestion"] for item in cleaned["improvements"]]
    return {
        "id": case["id"],
        "mode": context["mode"],
        "prompt": context.get("prompt"),
        "latency_ms": meta["latency_ms"],
        "attempts": meta.get("attempts", 1),
        "tokens": (meta.get("usage") or {}).get("total_tokens"),
        "on_topic_expected": case["on_topic"],
        "on_topic_found": cleaned["on_topic"],
        "thin": case["thin"],
        "improved_answer_type": cleaned["improved_answer_type"],
        "new_content_share": round(coach.new_content_share(raw["improved_answer"], transcript), 2),
        "placeholders": cleaned["improved_answer"].count("["),
        "invented_numbers_raw": invented_numbers([raw["improved_answer"]], transcript),
        "invented_numbers_after": invented_numbers([cleaned["improved_answer"]], transcript),
        "tip_numbers_raw": invented_numbers(raw_tips, transcript),
        "tip_numbers_after": invented_numbers(clean_tips, transcript),
        "unknown_framework_parts": [p for p in raw_parts if coach._part_key(p) not in known],
        "quotes": quoted,
        "grounded_quotes": grounded,
        "style_raw": style(feedback_texts(raw)),
        "style_clean": style(feedback_texts(cleaned)),
        "raw": raw,
        "clean": {key: cleaned[key] for key in ("summary", "strengths", "improvements", "topic_feedback", "improved_answer")},
    }


def run_role_prompts(roles, config):
    rows = []
    for role in roles:
        for kind, generate, limit, spec in (
            ("questions", interview.generate_questions, 25, {"behavioral": 3, "role": 3, "motivation": 2}),
            ("jam", interview.generate_jam_topics, 8, {"role": 6, "general": 4}),
        ):
            time.sleep(PAUSE_BETWEEN_CALLS)
            started = time.perf_counter()
            items = with_retries(lambda: generate(role, config))
            types = {key: sum(item["type"] == key for item in items) for key in spec}
            rows.append({
                "role": role,
                "kind": kind,
                "count": len(items),
                "types": types,
                "types_as_asked": types == spec,
                "too_long": sum(len(item["text"].split()) > limit for item in items),
                "mentions_role": sum(role.lower().split()[0] in item["text"].lower() for item in items),
                "seconds": round(time.perf_counter() - started, 1),
                "examples": [item["text"] for item in items[:3]],
            })
            print(f"  {kind} for {role}: {len(items)} items, types {types}")
    return rows


def aggregate(rows):
    def share(predicate, subset=rows):
        return sum(1 for row in subset if predicate(row)) / len(subset) if subset else None

    rewrites = [row for row in rows if row["improved_answer_type"] == "rewrite"]
    thin = [row for row in rows if row["thin"]]
    on_topic_full = [row for row in rows if row["on_topic_expected"] and not row["thin"]]
    return {
        "cases": len(rows),
        "first_try_valid": share(lambda row: row["attempts"] == 1),
        "latency_ms": m.summary([row["latency_ms"] for row in rows]),
        "tokens_mean": m.summary([row["tokens"] for row in rows if row["tokens"]])["mean"],
        "on_topic_agreement": share(lambda row: row["on_topic_expected"] == row["on_topic_found"]),
        "rewrites_with_invented_numbers_raw": share(lambda row: bool(row["invented_numbers_raw"]), rewrites),
        "invented_numbers_after_guardrail": sum(len(row["invented_numbers_after"]) for row in rows),
        "answers_with_invented_tip_numbers_raw": share(lambda row: bool(row["tip_numbers_raw"])),
        "invented_tip_numbers_after_guardrail": sum(len(row["tip_numbers_after"]) for row in rows),
        "thin_answers_given_template": share(lambda row: row["improved_answer_type"] == "template", thin),
        "full_answers_kept_as_rewrite": share(lambda row: row["improved_answer_type"] == "rewrite", on_topic_full),
        "new_content_share": {
            "full_answers": m.summary([row["new_content_share"] for row in on_topic_full]),
            "thin_answers": m.summary([row["new_content_share"] for row in thin]),
        },
        "unknown_framework_parts": sum(len(row["unknown_framework_parts"]) for row in rows),
        "quotes": sum(row["quotes"] for row in rows),
        "grounded_quote_share": (sum(row["grounded_quotes"] for row in rows) / sum(row["quotes"] for row in rows))
        if sum(row["quotes"] for row in rows) else None,
        "style_raw": {key: m.summary([row["style_raw"][key] for row in rows])["mean"] for key in rows[0]["style_raw"]},
        "style_clean": {key: m.summary([row["style_clean"][key] for row in rows])["mean"] for key in rows[0]["style_clean"]},
    }


def write_report(results):
    a = results["coach"]
    pct = lambda v: "–" if v is None else f"{100 * v:.0f}%"  # noqa: E731
    lines = [
        "# AI coach evaluation",
        "",
        f"Generated {results['generated']} · model `{results['model']}` via {results['provider']} · {a['cases']} transcripts "
        "([fixtures/coach_cases.json](../fixtures/coach_cases.json)).",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Valid structured answer on the first try | {pct(a['first_try_valid'])} |",
        f"| Response time (median / 95th percentile) | {a['latency_ms']['median'] / 1000:.1f} s / {a['latency_ms']['p95'] / 1000:.1f} s |",
        f"| Agrees with the human on/off-topic label | {pct(a['on_topic_agreement'])} |",
        f"| Rewrites where the model invented a number | {pct(a['rewrites_with_invented_numbers_raw'])} ({a['invented_numbers_after_guardrail']} left after the guardrail) |",
        f"| Answers whose tips invented a number | {pct(a['answers_with_invented_tip_numbers_raw'])} ({a['invented_tip_numbers_after_guardrail']} left after the guardrail) |",
        f"| One-line answers given the fill-in template instead of a made-up story | {pct(a['thin_answers_given_template'])} |",
        f"| Full on-topic answers kept as a real rewrite | {pct(a['full_answers_kept_as_rewrite'])} |",
        f"| New content in the model's rewrite: full answers (mean, max) | {pct(a['new_content_share']['full_answers']['mean'])}, {pct(a['new_content_share']['full_answers']['max'])} |",
        f"| New content in the model's rewrite: one-line answers (mean) | {pct(a['new_content_share']['thin_answers']['mean'])} |",
        f"| Framework parts named outside the framework | {a['unknown_framework_parts']} |",
        f"| Quotes of the speaker that really appear in the transcript | {pct(a['grounded_quote_share'])} of {a['quotes']} |",
        "",
        "**How it reads** (feedback text only, mean per answer; lower is better except *you*)",
        "",
        "| | Raw model output | Shown in the app |",
        "|---|---|---|",
    ]
    labels = {
        "chatbot_phrases_per_100_words": "Chatbot phrases per 100 words",
        "em_dashes": "Em dashes",
        "semicolons": "Semicolons",
        "third_person": "\"the speaker\" / \"the user\"",
        "you_per_100_words": "\"you\" per 100 words",
        "words_per_sentence": "Words per sentence",
    }
    for key, label in labels.items():
        lines.append(f"| {label} | {a['style_raw'][key]:.2f} | {a['style_clean'][key]:.2f} |")
    lines += ["", "## Role prompt writers", "", "| Role | Kind | Items | Types as asked | Too long | Examples |", "|---|---|---|---|---|---|"]
    for row in results["roles"]:
        lines.append(f"| {row['role']} | {row['kind']} | {row['count']} | {'yes' if row['types_as_asked'] else row['types']} | {row['too_long']} | {'; '.join(row['examples'])} |")
    lines += ["", "## Per transcript", "", "| Case | Mode | On-topic (label) | Shown answer | New content | Invented numbers (raw rewrite / tips) | Speaker quotes grounded |", "|---|---|---|---|---|---|---|"]
    for row in results["rows"]:
        lines.append(
            f"| {row['id']} | {row['mode']} | {row['on_topic_found']} ({row['on_topic_expected']}) | {row['improved_answer_type']} | "
            f"{pct(row['new_content_share'])} | {', '.join(row['invented_numbers_raw']) or '–'} / {', '.join(row['tip_numbers_raw']) or '–'} | "
            f"{row['grounded_quotes']}/{row['quotes']} |"
        )
    example = next((row for row in results["rows"] if row["style_raw"]["em_dashes"] or row["style_raw"]["chatbot_phrases_per_100_words"]), results["rows"][0])
    lines += ["", f"## Example ({example['id']})", "", "**Raw summary:** " + example["raw"]["summary"], "", "**Shown in the app:** " + example["clean"]["summary"]]
    with open(os.path.join(RESULTS_DIR, "COACH.md"), "w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines) + "\n")


def main():
    config = llm.get_config()
    if config is None:
        sys.exit("No LLM is configured. Put your GROQ_API_KEY in backend/.env first.")
    with open(CASES, encoding="utf-8") as file:
        fixtures = json.load(file)
    rows = []
    for number, case in enumerate(fixtures["cases"], start=1):
        if number > 1:
            time.sleep(PAUSE_BETWEEN_CALLS)
        rows.append(run_case(case, config))
        row = rows[-1]
        print(f"[{number}/{len(fixtures['cases'])}] {case['id']}: on_topic {row['on_topic_found']} (label {case['on_topic']}), {row['latency_ms']} ms")
    roles = run_role_prompts(fixtures["roles"], config)
    results = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "provider": config.provider,
        "model": config.model,
        "coach": aggregate(rows),
        "rows": rows,
        "roles": roles,
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "coach_latest.json"), "w", encoding="utf-8", newline="\n") as file:
        json.dump(results, file, indent=1)
    write_report(results)
    print(json.dumps(results["coach"], indent=1, default=str))
    print(f"Report: {os.path.join(RESULTS_DIR, 'COACH.md')}")


if __name__ == "__main__":
    main()
