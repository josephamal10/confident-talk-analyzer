"""Runs the evaluation and writes evals/results/REPORT.md and latest.json.

    python -m evals.run                     all synthetic clips
    python -m evals.run --own               plus your own recordings (dataset/own/audio)
    python -m evals.run --save-as baseline  also keep a copy as results/baseline.json
    python -m evals.run --compare baseline  show the change against a saved run

Every clip goes through the same code as the app: analyze_recording() for the signal, then
evaluation.evaluate() for the practice mode's checks.
"""
import argparse
import datetime as dt
import json
import logging
import os
import platform
import subprocess
import sys
import time
from collections import defaultdict

from analysis import analyze_recording, evaluation, language, modes, relevance, transcription, warm_up
from analysis.fillers import find_filler_spans

from . import metrics as m
from .dataset import EVALS_DIR, own_clips, synthetic_clips

RESULTS_DIR = os.path.join(EVALS_DIR, "results")
PAUSE_TOLERANCE = 0.3


# ---------- Running the pipeline ----------


def context_for(clip):
    form = {"mode": clip.mode}
    document = None
    if clip.document:
        document = {"id": 0, "filename": "document", "word_count": sum(len(p.split()) for p in clip.document)}
    elif clip.passage:
        form["custom_script"] = clip.passage
    elif clip.topic:
        form["custom_prompt"] = clip.topic
    return modes.build_context(form, document=document)


def run_clip(clip):
    started = time.perf_counter()
    try:
        base = analyze_recording(clip.audio_path)
    except Exception as error:  # an unusable clip is a result too
        return {"error": str(getattr(error, "message", error)), "seconds": time.perf_counter() - started}
    context = context_for(clip)
    document = {"text": "\n\n".join(clip.document), "paragraphs": clip.document} if clip.document else None
    result = evaluation.evaluate(base, modes.get_mode(context["mode"]), context, document=document)
    return {"base": base, "result": result, "context": context, "seconds": time.perf_counter() - started}


# ---------- Components ----------


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def eval_transcription(clips, outputs):
    rows, totals = [], defaultdict(lambda: [0, 0, 0])
    for clip in clips:
        out = outputs[clip.id]
        if "base" not in out:
            continue
        hypothesis = [word["text"] for word in out["base"]["words"]]
        for variant, keep in (("all", lambda t: True), ("content", lambda t: not m.is_hesitation(t))):
            ref = m.words([t for t in clip.script.tokens if keep(t)])
            hyp = m.words([t for t in hypothesis if keep(t)])
            errors = sum(m.edit_counts(ref, hyp))
            key = (clip.source, variant)
            totals[key][0] += errors
            totals[key][1] += len(ref)
            if variant == "all":
                rows.append({"clip": clip.id, "wer": round(errors / len(ref), 3), "said": " ".join(hypothesis)})
    result = {f"{source}_{variant}_wer": _rate(e, n) for (source, variant), (e, n, _x) in totals.items()}
    failures = [row for row in rows if row["wer"] > 0.1]
    return {"metrics": result, "rows": rows, "failures": failures}


def _counts_by(clips, outputs, spans_of_reference, spans_of_hypothesis):
    totals = defaultdict(lambda: [0, 0, 0])
    failures = []
    for clip in clips:
        out = outputs[clip.id]
        if "base" not in out:
            continue
        hypothesis = [word["text"] for word in out["base"]["words"]]
        mapping = m.align(clip.script.tokens, hypothesis)
        reference_spans = spans_of_reference(clip)
        hypothesis_spans = spans_of_hypothesis(out, hypothesis)
        tp, fp, fn = m.match_spans(reference_spans, hypothesis_spans, mapping)
        for key in (clip.source, "all"):
            totals[key][0] += tp
            totals[key][1] += fp
            totals[key][2] += fn
        if fp or fn:
            failures.append({
                "clip": clip.id,
                "expected": [" ".join(clip.script.tokens[i] for i in span) for span in reference_spans],
                "found": [" ".join(hypothesis[i] for i in span) for span in hypothesis_spans],
            })
    return {key: m.prf(*value) for key, value in totals.items()}, failures


def eval_fillers(clips, outputs):
    by_source, failures = _counts_by(
        clips, outputs, lambda clip: clip.script.fillers, lambda out, hypothesis: find_filler_spans(hypothesis)
    )
    count_errors = []
    for clip in clips:
        out = outputs[clip.id]
        if "base" in out:
            count_errors.append(abs(out["base"]["metrics"]["filler_count"] - len(clip.script.fillers)))
    return {"metrics": {"by_source": by_source, "count_mae": m.summary(count_errors)["mean"]}, "failures": failures}


def eval_hedges(clips, outputs):
    by_source, failures = _counts_by(
        clips,
        outputs,
        lambda clip: clip.script.hedges,
        lambda out, hypothesis: [hedge["indexes"] for hedge in out["result"]["language"]["hedges"]],
    )
    return {"metrics": {"by_source": by_source}, "failures": failures}


def eval_pauses(clips, outputs):
    hesitation = defaultdict(lambda: [0, 0, 0])
    any_pause = defaultdict(lambda: [0, 0])  # found, total
    kind_right = defaultdict(lambda: [0, 0])
    duration_errors, count_errors, failures = [], [], []
    for clip in clips:
        out = outputs[clip.id]
        if "base" not in out:
            continue
        predicted = out["base"]["pauses"]
        predicted_hesitations = [p for p in predicted if p["kind"] == "hesitation"]
        expected_hesitations = [p for p in clip.script.pauses if p.kind == "hesitation"]
        if clip.source == "own" or not clip.truth:
            # Real recordings: pause lengths aren't known, so compare how many were found.
            count_errors.append(abs(len(predicted_hesitations) - len(expected_hesitations)))
            if len(predicted_hesitations) != len(expected_hesitations):
                failures.append({"clip": clip.id, "expected_hesitations": len(expected_hesitations), "found": len(predicted_hesitations)})
            continue
        truth = clip.truth["pauses"]
        true_hesitations = [(p["start"], p["end"]) for p in truth if p["kind"] == "hesitation"]
        pairs, fp, fn = m.match_intervals(true_hesitations, [(p["start"], p["end"]) for p in predicted_hesitations], PAUSE_TOLERANCE)
        hesitation["synthetic"][0] += len(pairs)
        hesitation["synthetic"][1] += fp
        hesitation["synthetic"][2] += fn
        all_pairs, _fp, _fn = m.match_intervals([(p["start"], p["end"]) for p in truth], [(p["start"], p["end"]) for p in predicted], PAUSE_TOLERANCE)
        any_pause["synthetic"][0] += len(all_pairs)
        any_pause["synthetic"][1] += len(truth)
        for t_index, p_index in all_pairs:
            kind_right["synthetic"][0] += truth[t_index]["kind"] == predicted[p_index]["kind"]
            kind_right["synthetic"][1] += 1
            duration_errors.append(abs(predicted[p_index]["duration"] - (truth[t_index]["end"] - truth[t_index]["start"])))
        if fp or fn:
            failures.append({
                "clip": clip.id,
                "expected": [f"{p['kind']} {p['start']}-{p['end']}s" for p in truth],
                "found": [f"{p['kind']} {p['start']}-{p['end']}s ({p['duration']}s)" for p in predicted],
            })
    return {
        "metrics": {
            "hesitation": {key: m.prf(*value) for key, value in hesitation.items()},
            "pause_recall": {key: _rate(*value) for key, value in any_pause.items()},
            "kind_accuracy": {key: _rate(*value) for key, value in kind_right.items()},
            "duration_error_s": m.summary(duration_errors)["mean"],
            "own_count_mae": m.summary(count_errors)["mean"],
        },
        "failures": failures,
    }


def eval_pace(clips, outputs):
    errors, rows = [], []
    for clip in clips:
        out = outputs[clip.id]
        if "base" not in out or not clip.truth:
            continue
        measured, true = out["base"]["metrics"]["wpm"], clip.truth["wpm"]
        errors.append(abs(measured - true) / true)
        rows.append({"clip": clip.id, "true_wpm": true, "measured_wpm": measured, "pace_score": out["result"]["sub_scores"].get("pace")})
    pace_rows = [row for row in rows if row["clip"].startswith("pace-")]
    return {
        "metrics": {
            "wpm_error": m.summary(errors),
            "rank_correlation": m.spearman([r["true_wpm"] for r in pace_rows], [r["measured_wpm"] for r in pace_rows]),
        },
        "rows": pace_rows,
        "failures": [row for row, error in zip(rows, errors) if error > 0.1],
    }


def eval_topic(clips, outputs):
    rows = []
    for clip in clips:
        out = outputs[clip.id]
        if clip.on_topic is None or "result" not in out or not out["result"]["topic_match"]:
            continue
        match = out["result"]["topic_match"]
        rows.append({"clip": clip.id, "mode": clip.mode, "expected": clip.on_topic, "found": match["related"], "similarity": match["similarity"]})
    correct = sum(row["expected"] == row["found"] for row in rows)
    return {
        "metrics": {"accuracy": _rate(correct, len(rows)), "n": len(rows)},
        "rows": rows,
        "failures": [row for row in rows if row["expected"] != row["found"]],
    }


def eval_jam(clips, outputs):
    rows, totals = [], {"deviation": [0, 0, 0], "repetition": [0, 0, 0]}
    for clip in clips:
        out = outputs[clip.id]
        if clip.category != "jam" or "result" not in out:
            continue
        counts = out["result"]["referee"]["counts"]
        row = {"clip": clip.id}
        for kind, key in (("deviation", "deviations"), ("repetition", "repetitions")):
            expected, found = clip.expect[key], counts[kind]
            totals[kind][0] += min(expected, found)
            totals[kind][1] += max(0, found - expected)
            totals[kind][2] += max(0, expected - found)
            row[kind], row[f"expected_{kind}"] = found, expected
        row["events"] = [f"{e['type']}: {e['detail']}" for e in out["result"]["referee"]["events"] if e["type"] != "hesitation"]
        rows.append(row)
    return {
        "metrics": {kind: m.prf(*value) for kind, value in totals.items()},
        "rows": rows,
        "failures": [row for row in rows if any(row[k] != row[f"expected_{k}"] for k in ("deviation", "repetition"))],
    }


def _section_range(tokens, first_words, last_words):
    first, last = first_words.split(), last_words.split()
    start = next(i for i in range(len(tokens)) if tokens[i : i + len(first)] == first)
    end = next(i + len(last) for i in range(len(tokens) - len(last), -1, -1) if tokens[i : i + len(last)] == last)
    return start, end


def eval_reading(clips, outputs):
    rows = []
    for clip in clips:
        out = outputs[clip.id]
        if clip.category not in ("reading", "document") or "result" not in out:
            continue
        reading = out["result"]["reading"]
        row = {"clip": clip.id, "source": clip.source, "verdict": reading["match"]["verdict"], "expected_verdict": clip.expect.get("verdict"),
               "accuracy": reading["accuracy"], "spoken_match": reading["spoken_match"]}
        for key in ("missed", "misread", "added"):
            if key in clip.expect:
                row[key] = reading["counts"][key]
                row[f"expected_{key}"] = clip.expect[key]
        if clip.category == "document":
            tokens = "\n\n".join(clip.document).split()
            expected = clip.expect.get("section")
            section = reading.get("section")
            if expected is None:
                row["section_iou"] = 1.0 if section is None else 0.0
            else:
                row["section_iou"] = m.iou(_section_range(tokens, *expected), (section["start"], section["end"]) if section else None)
        rows.append(row)

    def mean_abs(key):
        values = [abs(row[key] - row[f"expected_{key}"]) for row in rows if key in row]
        return m.summary(values)["mean"]

    verdict_rows = [row for row in rows if row["expected_verdict"]]
    count_rows = [row for row in rows if "missed" in row]
    exact_counts = sum(all(row[k] == row[f"expected_{k}"] for k in ("missed", "misread", "added")) for row in count_rows)
    ious = [row["section_iou"] for row in rows if "section_iou" in row]
    return {
        "metrics": {
            "verdict_accuracy": _rate(sum(row["verdict"] == row["expected_verdict"] for row in verdict_rows), len(verdict_rows)),
            "counts_exact": _rate(exact_counts, len(count_rows)),
            "missed_mae": mean_abs("missed"),
            "misread_mae": mean_abs("misread"),
            "added_mae": mean_abs("added"),
            "section_iou": m.summary(ious)["mean"],
        },
        "rows": rows,
        "failures": [row for row in rows if row["verdict"] != row["expected_verdict"]
                     or any(row.get(k) != row.get(f"expected_{k}") for k in ("missed", "misread", "added"))
                     or row.get("section_iou", 1.0) < 0.9],
    }


def eval_scores(clips, outputs):
    """Do the scores move the right way? Fluency against filler density, across the fluency clips."""
    xs, ys = [], []
    for clip in clips:
        out = outputs[clip.id]
        if clip.category != "fluency" or clip.source != "synthetic" or "result" not in out:
            continue
        xs.append(100 * len(clip.script.fillers) / len(clip.script.tokens))
        ys.append(out["result"]["sub_scores"]["fluency"])
    return {"metrics": {"fluency_vs_filler_density": m.spearman(xs, ys)}}


def eval_latency(clips, outputs, warm_up_seconds):
    totals, factors, stages = [], [], defaultdict(list)
    for clip in clips:
        out = outputs[clip.id]
        if "base" not in out:
            continue
        totals.append(out["seconds"])
        factors.append(out["seconds"] / out["base"]["metrics"]["duration"])
        for stage, ms in out["base"]["timings_ms"].items():
            stages[stage].append(ms)
    return {
        "metrics": {
            "warm_up_s": warm_up_seconds,
            "seconds_per_clip": m.summary(totals),
            "real_time_factor": m.summary(factors),
            "stage_ms_mean": {stage: round(m.summary(values)["mean"]) for stage, values in stages.items()},
        }
    }


def label_lint(clips):
    """Hedge words the rules would flag in a script but that aren't labelled, so labels stay complete."""
    notes = []
    for clip in clips:
        labelled = {tuple(span) for span in clip.script.hedges}
        for hedge in language.find_hedges(clip.script.tokens, clip.script.filler_indexes()):
            if tuple(hedge["indexes"]) not in labelled:
                notes.append(f"{clip.id}: '{hedge['phrase']}' is not labelled as a hedge")
    return notes


# ---------- Report ----------


def pct(value, digits=1):
    return "–" if value is None else f"{100 * value:.{digits}f}%"


def num(value, digits=2):
    return "–" if value is None else f"{value:.{digits}f}"


def headline(results):
    c = results["components"]
    rows = [
        ("Transcription", "Word error rate, synthetic voices", pct(c["transcription"]["metrics"].get("synthetic_all_wer"))),
        ("Transcription", "Word error rate, own recordings", pct(c["transcription"]["metrics"].get("own_all_wer"))),
        ("Fillers", "F1 (synthetic)", pct(c["fillers"]["metrics"]["by_source"].get("synthetic", {}).get("f1"))),
        ("Fillers", "F1 (own recordings)", pct(c["fillers"]["metrics"]["by_source"].get("own", {}).get("f1"))),
        ("Hedges", "F1 (synthetic)", pct(c["hedges"]["metrics"]["by_source"].get("synthetic", {}).get("f1"))),
        ("Pauses", "Hesitation-pause F1", pct(c["pauses"]["metrics"]["hesitation"].get("synthetic", {}).get("f1"))),
        ("Pauses", "Share of scripted pauses found", pct(c["pauses"]["metrics"]["pause_recall"].get("synthetic"))),
        ("Pace", "Mean words-per-minute error", pct(c["pace"]["metrics"]["wpm_error"]["mean"])),
        ("Pace", "Rank correlation with true pace", num(c["pace"]["metrics"]["rank_correlation"])),
        ("Topic check", "On/off-topic accuracy", pct(c["topic"]["metrics"]["accuracy"], 0)),
        ("JAM referee", "Deviation F1", pct(c["jam"]["metrics"]["deviation"]["f1"], 0)),
        ("Read-aloud", "Verdict accuracy", pct(c["reading"]["metrics"]["verdict_accuracy"], 0)),
        ("Read-aloud", "Skipped/misread/added counts exactly right", pct(c["reading"]["metrics"]["counts_exact"], 0)),
        ("Documents", "Located section overlap (IoU)", pct(c["reading"]["metrics"]["section_iou"], 0)),
        ("Scores", "Fluency score vs filler density (rank corr.)", num(c["scores"]["metrics"]["fluency_vs_filler_density"])),
        ("Speed", "Analysis time / audio length", num(c["latency"]["metrics"]["real_time_factor"]["mean"])),
    ]
    return rows


def write_report(results, compare=None):
    lines = [
        "# Evaluation report",
        "",
        f"Generated {results['generated']} on {results['machine']} · commit `{results['commit']}` · "
        f"{results['clips']['synthetic']} synthetic clips, {results['clips']['own']} own recordings · "
        f"speech model faster-whisper `{results['whisper']}`.",
        "",
        "How the set is built and what each number means: [../README.md](../README.md).",
        "",
        "## Summary",
        "",
    ]
    before = {(a, b): v for a, b, v in headline(compare)} if compare else {}
    lines.append("| Part | Metric | Result |" + (" Before |" if compare else ""))
    lines.append("|---|---|---|" + ("---|" if compare else ""))
    for part, metric, value in headline(results):
        # Speed depends on whatever else the machine was doing, so it isn't compared across runs.
        earlier = "not compared" if part == "Speed" else before.get((part, metric), "–")
        lines.append(f"| {part} | {metric} | {value} |" + (f" {earlier} |" if compare else ""))
    if compare:
        lines += ["", f"*Before* is the saved run `{compare['name']}` ({compare['generated']}, commit `{compare['commit']}`)."]

    c = results["components"]
    lines += ["", "## Fillers and hedges", "", "| | Precision | Recall | F1 | Found / missed / false alarms |", "|---|---|---|---|---|"]
    for part in ("fillers", "hedges"):
        for source, value in c[part]["metrics"]["by_source"].items():
            if source == "all":
                continue
            lines.append(f"| {part.capitalize()}, {source} | {pct(value['precision'])} | {pct(value['recall'])} | {pct(value['f1'])} | {value['tp']} / {value['fn']} / {value['fp']} |")

    p = c["pauses"]["metrics"]
    lines += [
        "",
        "## Pauses",
        "",
        f"- Hesitation pauses (synthetic, matched in time within {PAUSE_TOLERANCE}s): "
        + ", ".join(f"{k} {pct(v)}" for k, v in p["hesitation"].get("synthetic", m.prf(0, 0, 0)).items() if k in ("precision", "recall", "f1")),
        f"- Scripted pauses found at all: {pct(p['pause_recall'].get('synthetic'))}; of those, labelled the right kind "
        f"(hesitation or natural): {pct(p['kind_accuracy'].get('synthetic'))}; mean length error {num(p['duration_error_s'])} s.",
    ]
    if p["own_count_mae"] is not None:
        lines.append(f"- Own recordings: hesitation-pause count off by {num(p['own_count_mae'])} on average.")

    lines += ["", "## Pace", "", "| Clip | True WPM | Measured WPM | Pace score |", "|---|---|---|---|"]
    for row in c["pace"]["rows"]:
        lines.append(f"| {row['clip']} | {row['true_wpm']} | {row['measured_wpm']} | {row['pace_score']} |")
    w = c["pace"]["metrics"]["wpm_error"]
    lines += ["", f"Across all {w['n']} synthetic clips the words-per-minute error is {pct(w['mean'])} on average (95th percentile {pct(w['p95'])})."]

    lines += ["", "## Topic check", "", "| Clip | Mode | Expected | Found | Similarity |", "|---|---|---|---|---|"]
    for row in c["topic"]["rows"]:
        lines.append(f"| {row['clip']} | {row['mode']} | {'on' if row['expected'] else 'off'} | {'on' if row['found'] else 'off'} | {row['similarity']} |")

    lines += ["", "## JAM referee", "", "| Clip | Deviations | Repetitions |", "|---|---|---|"]
    for row in c["jam"]["rows"]:
        lines.append(f"| {row['clip']} | {row['deviation']} ({row['expected_deviation']}) | {row['repetition']} ({row['expected_repetition']}) |")
    lines += ["", "Expected values in brackets."]

    lines += ["", "## Read-aloud and documents", "", "| Clip | Verdict (expected) | Accuracy | Skipped | Misread | Added | Section IoU |", "|---|---|---|---|---|---|---|"]
    for row in c["reading"]["rows"]:
        counts = [f"{row[k]} ({row[f'expected_{k}']})" if k in row else "–" for k in ("missed", "misread", "added")]
        lines.append(f"| {row['clip']} | {row['verdict']} ({row['expected_verdict']}) | {pct(row['accuracy'], 0)} | {' | '.join(counts)} | {num(row.get('section_iou'))} |")

    lat = c["latency"]["metrics"]
    lines += [
        "",
        "## Speed",
        "",
        f"Model warm-up {lat['warm_up_s']:.1f} s. Per clip: mean {num(lat['seconds_per_clip']['mean'], 1)} s, "
        f"95th percentile {num(lat['seconds_per_clip']['p95'], 1)} s; {num(lat['real_time_factor']['mean'])}× the audio length on average.",
        "Mean time per stage (ms): " + ", ".join(f"{k} {v}" for k, v in lat["stage_ms_mean"].items()) + ".",
        "",
        "## Where it went wrong",
        "",
    ]
    for part in ("transcription", "fillers", "hedges", "pauses", "pace", "topic", "jam", "reading"):
        failures = c[part].get("failures") or []
        if not failures:
            continue
        lines.append(f"**{part.capitalize()}** ({len(failures)})")
        lines.append("")
        for failure in failures[:12]:
            lines.append("- " + "; ".join(f"{k}: {v}" for k, v in failure.items()))
        lines.append("")
    if results["label_lint"]:
        lines += ["**Label check**", ""] + [f"- {note}" for note in results["label_lint"]] + [""]
    if results["errors"]:
        lines += ["**Clips that could not be analysed**", ""] + [f"- {k}: {v}" for k, v in results["errors"].items()] + [""]

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "REPORT.md"), "w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines).rstrip() + "\n")


def _commit():
    """The commit the analysis code came from, flagged when the code has uncommitted changes."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=EVALS_DIR).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", os.path.join(os.path.dirname(EVALS_DIR), "analysis")],
            capture_output=True, text=True, cwd=EVALS_DIR,
        ).stdout.strip()
    except OSError:
        return "unknown"
    return f"{sha or 'unknown'}{' + local changes' if dirty else ''}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--own", action="store_true", help="include your own recordings from dataset/own/audio")
    parser.add_argument("--only", help="comma-separated clip ids or categories")
    parser.add_argument("--save-as", help="also save the results as results/<name>.json")
    parser.add_argument("--compare", help="compare with results/<name>.json in the report")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    clips = synthetic_clips()
    if args.own:
        recorded = [clip for clip in own_clips() if clip.audio_path]
        print(f"Own recordings found: {len(recorded)} of {len(own_clips())}")
        clips += recorded
    if args.only:
        wanted = set(args.only.split(","))
        clips = [clip for clip in clips if clip.id in wanted or clip.category in wanted]
    missing = [clip.id for clip in clips if not clip.audio_path]
    if missing:
        sys.exit(f"Missing audio for {missing}; run python -m evals.build first.")

    started = time.perf_counter()
    warm_up()
    relevance.warm_up()
    warm_up_seconds = time.perf_counter() - started
    outputs = {}
    for number, clip in enumerate(clips, start=1):
        outputs[clip.id] = run_clip(clip)
        print(f"[{number}/{len(clips)}] {clip.id} ({outputs[clip.id]['seconds']:.1f}s){' ERROR ' + outputs[clip.id]['error'] if 'error' in outputs[clip.id] else ''}")

    results = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "commit": _commit(),
        "whisper": transcription.MODEL_NAME,
        "clips": {"synthetic": sum(c.source == "synthetic" for c in clips), "own": sum(c.source == "own" for c in clips)},
        "errors": {clip.id: outputs[clip.id]["error"] for clip in clips if "error" in outputs[clip.id]},
        "label_lint": label_lint(clips),
        "components": {
            "transcription": eval_transcription(clips, outputs),
            "fillers": eval_fillers(clips, outputs),
            "hedges": eval_hedges(clips, outputs),
            "pauses": eval_pauses(clips, outputs),
            "pace": eval_pace(clips, outputs),
            "topic": eval_topic(clips, outputs),
            "jam": eval_jam(clips, outputs),
            "reading": eval_reading(clips, outputs),
            "scores": eval_scores(clips, outputs),
            "latency": eval_latency(clips, outputs, warm_up_seconds),
        },
    }
    compare = None
    if args.compare:
        with open(os.path.join(RESULTS_DIR, f"{args.compare}.json"), encoding="utf-8") as file:
            compare = {**json.load(file), "name": args.compare}
    os.makedirs(RESULTS_DIR, exist_ok=True)
    for name in ["latest"] + ([args.save_as] if args.save_as else []):
        with open(os.path.join(RESULTS_DIR, f"{name}.json"), "w", encoding="utf-8", newline="\n") as file:
            json.dump(results, file, indent=1, default=str)
    write_report(results, compare)
    print("\n".join(f"{part:12} {metric:48} {value}" for part, metric, value in headline(results)))
    print(f"Report: {os.path.join(RESULTS_DIR, 'REPORT.md')}")


if __name__ == "__main__":
    main()
