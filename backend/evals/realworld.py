"""Real-world check: transcription accuracy on Indian-accented English, for the app's speech model and
bigger alternatives, and how fast each runs on the free hosting the app is deployed on.

    python -m evals.realworld                              default models, 20 minutes of Svarah + own recordings
    python -m evals.realworld --models small.en --minutes 5
    python -m evals.realworld --fresh                      redo models already in results/realworld.json

Svarah (AI4Bharat, CC BY 4.0) has 9.6 hours of English from 117 speakers in 19 Indian states. It is
gated: accept its terms at https://huggingface.co/datasets/ai4bharat/Svarah and run `hf auth login`
once. The audio stays in the Hugging Face cache, outside the repo; only the numbers are written to
results/REALWORLD.md and results/realworld.json.

Svarah clips average 5 seconds, but Whisper always works on 30-second windows, so short clips would make
every model look several times slower than on a real practice take. Each test recording is therefore one
speaker's clips joined into about 40 seconds. Accuracy is measured with every CPU core (the thread count
doesn't change the words); speed is measured separately on a few recordings with the hosting's 2 cores.
"""
import argparse
import datetime as dt
import io
import json
import logging
import os
import random
import time
from collections import defaultdict

import numpy as np

from analysis import transcription
from analysis.audio import SAMPLE_RATE

from . import metrics as m
from .dataset import EVALS_DIR, own_clips

RESULTS_DIR = os.path.join(EVALS_DIR, "results")
SVARAH = "ai4bharat/Svarah"
DEFAULT_MODELS = ("small.en", "distil-large-v3.5", "large-v3-turbo")
# Free Hugging Face Spaces hardware has 2 CPU cores.
HOSTING_THREADS = 2
TEXT_COLUMNS = ("text", "transcript", "transcription", "sentence", "normalized_text")
# Approximate download sizes, for the report.
MODEL_SIZES = {"small.en": "0.5 GB", "distil-large-v3.5": "1.5 GB", "large-v3-turbo": "1.6 GB", "medium.en": "1.5 GB", "distil-small.en": "0.3 GB"}
GROUP_COLUMNS = ("primary_language", "native_language", "language", "state", "native_place_state")
# Svarah has no speaker id, so a speaker is told apart by their recorded details.
SPEAKER_COLUMNS = ("gender", "age-group", "primary_language", "native_place_state", "native_place_district",
                   "highest_qualification", "job_category", "occupation_domain")
GAP_SECONDS = 0.5  # silence between joined clips


def load_svarah(minutes, item_seconds, seed=7):
    """Test recordings of about `item_seconds`, one speaker each, until there are `minutes` of audio."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    folder = snapshot_download(SVARAH, repo_type="dataset", allow_patterns=["*.parquet"])
    files = sorted(os.path.join(root, name) for root, _dirs, names in os.walk(folder) for name in names if name.endswith(".parquet"))
    columns = pq.read_schema(files[0]).names
    text_column = next(c for c in TEXT_COLUMNS if c in columns)
    audio_column = next(c for c in columns if c.startswith("audio"))
    group_column = next((c for c in GROUP_COLUMNS if c in columns), None)
    speaker_columns = [c for c in columns if "speaker" in c][:1] or [c for c in SPEAKER_COLUMNS if c in columns]
    wanted = list(dict.fromkeys(c for c in (text_column, audio_column, "duration", group_column, *speaker_columns) if c in columns))
    rows = pa.concat_tables([pq.read_table(path, columns=wanted) for path in files]).to_pylist()

    random.Random(seed).shuffle(rows)
    by_speaker = defaultdict(list)
    for row in rows:
        if (row[text_column] or "").strip():
            by_speaker["|".join(str(row.get(c)) for c in speaker_columns)].append(row)

    items, total = [], 0.0
    for speaker, clips in by_speaker.items():
        if total >= minutes * 60:
            break
        parts, seconds = [], 0.0
        for clip in clips:
            if seconds >= item_seconds:
                break
            parts.append(clip)
            seconds += clip.get("duration") or 0
        total += seconds
        items.append({
            "id": f"svarah-{len(items):03d}",
            "reference": " ".join(clip[text_column] for clip in parts),
            "group": str(parts[0].get(group_column) or "unknown") if group_column else "unknown",
            "speaker": speaker,
            "audio": [clip[audio_column] for clip in parts],
        })
    return items, {"files": len(files), "columns": columns, "rows": len(rows), "speakers": len(by_speaker)}


def decode(audio_field):
    """Audio from a parquet cell ({"bytes", "path"}) or a file path, as 16 kHz mono float32."""
    from faster_whisper import decode_audio

    if isinstance(audio_field, dict):
        source = io.BytesIO(audio_field["bytes"]) if audio_field.get("bytes") else audio_field["path"]
    else:
        source = audio_field
    return decode_audio(source, sampling_rate=SAMPLE_RATE)


def join(parts):
    gap = np.zeros(int(GAP_SECONDS * SAMPLE_RATE), dtype=np.float32)
    pieces = []
    for samples in parts:
        pieces += [samples, gap]
    return np.concatenate(pieces[:-1])


def content_words(tokens):
    """Normalised words without hesitation sounds, since dataset transcripts don't write them."""
    return [word for word in m.words(tokens) if not m.is_hesitation(word)]


def _load(name, threads):
    from faster_whisper import WhisperModel

    started = time.perf_counter()
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
    return model, time.perf_counter() - started


def evaluate_model(name, items, threads, filler_prompt=True):
    model, _seconds = _load(name, threads)
    errors, words = defaultdict(int), defaultdict(int)
    group_errors, group_words, examples = defaultdict(int), defaultdict(int), []
    started = time.perf_counter()
    for done, item in enumerate(items, 1):
        if done % 10 == 0:
            print(f"  {done}/{len(items)} recordings, {(time.perf_counter() - started) / 60:.1f} min so far", flush=True)
        _text, hyp_words = transcription.transcribe(item["samples"], model=model, filler_prompt=filler_prompt)
        ref = content_words(item["reference"].split())
        hyp = content_words([word["text"] for word in hyp_words])
        count = sum(m.edit_counts(ref, hyp))
        source = item["source"]
        errors[source] += count
        words[source] += len(ref)
        if source == "svarah":
            group_errors[item["group"]] += count
            group_words[item["group"]] += len(ref)
        if len(examples) < 6 and ref and count / len(ref) > 0.15:
            examples.append({"clip": item["id"], "said": item["reference"], "heard": " ".join(word["text"] for word in hyp_words)})
    return {
        "model": name,
        "filler_prompt": filler_prompt,
        "wer": {source: errors[source] / words[source] for source in words if words[source]},
        "words": dict(words),
        "by_group": {
            group: {"wer": group_errors[group] / group_words[group], "words": group_words[group]}
            for group in sorted(group_words, key=lambda g: -group_words[g])
        },
        "examples": examples,
    }


def measure_speed(name, items, threads):
    """Seconds of transcription per minute of speech with `threads` cores, after one warm-up recording."""
    model, load_seconds = _load(name, threads)
    transcription.transcribe(items[0]["samples"][: 5 * SAMPLE_RATE], model=model)
    seconds = audio_seconds = 0.0
    for item in items:
        started = time.perf_counter()
        transcription.transcribe(item["samples"], model=model)
        seconds += time.perf_counter() - started
        audio_seconds += len(item["samples"]) / SAMPLE_RATE
    return {"seconds_per_minute": 60 * seconds / audio_seconds, "load_seconds": round(load_seconds, 1),
            "audio_seconds": round(audio_seconds, 1), "threads": threads}


def write_report(results):
    pct = lambda v: "–" if v is None else f"{100 * v:.1f}%"  # noqa: E731
    svarah = results["svarah"]
    lines = [
        "# Real-world speech: Indian-accented English",
        "",
        f"Generated {results['generated']} · {svarah['minutes']:.0f} minutes of [Svarah](https://huggingface.co/datasets/{SVARAH}) "
        f"(AI4Bharat, CC BY 4.0) from {svarah['speakers_sampled']} speakers, joined into {svarah['recordings']} recordings of "
        f"about {svarah['item_seconds']} seconds, plus {results['own_clips']} own recordings.",
        "",
        "Word error rate counts words only; hesitation sounds (*um, uh*) are left out because dataset transcripts "
        "don't write them. *Time per minute* is how long speech-to-text takes for one minute of speech on "
        f"{results['speed_threads']} CPU cores (free hosting has 2) on this machine, measured on "
        f"{results['speed_minutes']:.1f} minutes of audio. It covers transcription only, not the rest of the analysis.",
        "",
        "| Model | Svarah WER | Own recordings WER | Time per minute | Download |",
        "|---|---|---|---|---|",
    ]
    for row in results["models"]:
        label = row["model"] + ("" if row["filler_prompt"] else " (no filler prompt)")
        speed = "{:.0f} s".format(row["speed"]["seconds_per_minute"]) if row.get("speed") else "–"
        lines.append(f"| {label} | {pct(row['wer'].get('svarah'))} | {pct(row['wer'].get('own'))} | "
                     f"{speed} | {results['sizes'].get(row['model'], '–')} |")
    best = min(results["models"], key=lambda row: row["wer"].get("svarah", 1))
    lines += ["", f"## By the speaker's first language ({best['model']})", "", "| Group | WER | Words |", "|---|---|---|"]
    for group, value in list(best["by_group"].items())[:12]:
        lines.append(f"| {group} | {pct(value['wer'])} | {value['words']} |")
    lines += ["", "## Examples of mistakes", ""]
    for row in results["models"]:
        if not row["filler_prompt"]:
            continue
        lines.append(f"**{row['model']}**")
        lines.append("")
        for example in row["examples"][:3]:
            lines.append(f"- said: *{example['said']}*  \n  heard: *{example['heard']}*")
        lines.append("")
    with open(os.path.join(RESULTS_DIR, "REALWORLD.md"), "w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines).rstrip() + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--minutes", type=float, default=20, help="minutes of Svarah audio")
    parser.add_argument("--item-seconds", type=int, default=40, help="length of each joined test recording")
    parser.add_argument("--speed-recordings", type=int, default=4, help="recordings timed on the hosting's cores")
    parser.add_argument("--threads", type=int, default=HOSTING_THREADS, help="cores for the speed check")
    parser.add_argument("--no-prompt-check", action="store_true", help="skip measuring small.en without the filler prompt")
    parser.add_argument("--fresh", action="store_true", help="redo models already in results/realworld.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    svarah, info = load_svarah(args.minutes, args.item_seconds)
    items = [{**item, "source": "svarah", "samples": join([decode(part) for part in item.pop("audio")])} for item in svarah]
    minutes = sum(len(item["samples"]) for item in items) / SAMPLE_RATE / 60
    print(f"Svarah: {info['rows']} clips from {info['speakers']} speakers; testing {len(items)} recordings, {minutes:.1f} min", flush=True)
    for clip in own_clips():
        if clip.audio_path:
            items.append({"id": clip.id, "source": "own", "group": "own", "reference": clip.script.text,
                          "samples": decode(clip.audio_path)})
    own_count = sum(item["source"] == "own" for item in items)
    speed_items = items[: args.speed_recordings]

    setup = {"minutes": args.minutes, "item_seconds": args.item_seconds, "own_clips": own_count,
             "speed_threads": args.threads, "speed_recordings": len(speed_items)}
    results = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "setup": setup,
        "speed_threads": args.threads,
        "speed_minutes": sum(len(item["samples"]) for item in speed_items) / SAMPLE_RATE / 60,
        "svarah": {"recordings": len(svarah), "minutes": minutes, "item_seconds": args.item_seconds,
                   "speakers_sampled": len({item["speaker"] for item in svarah}), "info": info},
        "own_clips": own_count,
        "sizes": MODEL_SIZES,
        "models": [],
    }
    # A run is long, so finished models are kept: rerunning the same setup only does the missing ones.
    path = os.path.join(RESULTS_DIR, "realworld.json")
    if not args.fresh and os.path.exists(path):
        with open(path, encoding="utf-8") as file:
            old = json.load(file)
        if old.get("setup") == setup:
            results["models"] = old["models"]
    runs = [(name, True) for name in args.models.split(",")]
    if "small.en" in args.models.split(",") and not args.no_prompt_check:
        runs.append(("small.en", False))
    accuracy_threads = os.cpu_count() or HOSTING_THREADS
    for name, filler_prompt in runs:
        label = name + ("" if filler_prompt else " (no filler prompt)")
        if any(row["model"] == name and row["filler_prompt"] == filler_prompt for row in results["models"]):
            print(f"Model {label}: already done", flush=True)
            continue
        print(f"Model {label}: accuracy on {accuracy_threads} threads...", flush=True)
        row = evaluate_model(name, items, accuracy_threads, filler_prompt=filler_prompt)
        print(f"  WER {row['wer']}", flush=True)
        if filler_prompt:
            print(f"Model {label}: speed on {args.threads} threads...", flush=True)
            row["speed"] = measure_speed(name, speed_items, args.threads)
            print(f"  {row['speed']['seconds_per_minute']:.0f} s per minute of speech", flush=True)
        results["models"].append(row)
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as file:
            json.dump(results, file, indent=1, default=str)
        write_report(results)
    print(f"Report: {os.path.join(RESULTS_DIR, 'REALWORLD.md')}", flush=True)


if __name__ == "__main__":
    main()
