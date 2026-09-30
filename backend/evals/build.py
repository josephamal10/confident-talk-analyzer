"""Builds the synthetic evaluation clips and the guide for recording your own.

    python -m evals.build            render every synthetic clip (Windows only: uses the built-in voices)
    python -m evals.build fill-03    render only the named clips
    python -m evals.build --guide    rewrite dataset/own/RECORDING_GUIDE.md

For each clip it writes dataset/audio/<id>.flac and dataset/truth/<id>.json: when every word starts
(reported by the voice itself), the true speaking span and pace, and where each scripted pause is.
"""
import json
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

from . import markup
from .dataset import AUDIO_DIR, OWN_DIR, OWN_MANIFEST, TRUTH_DIR, EVALS_DIR, load_manifest, synthetic_clips
from .metrics import norm

FRAME_SECONDS = 0.02
# Frames quieter than this share of the loudest frame are silence (the synthetic voice is clean).
SILENCE_SHARE = 0.03


def _read_wav(path):
    with wave.open(path, "rb") as file:
        rate = file.getframerate()
        samples = np.frombuffer(file.readframes(file.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return samples, rate


def _voiced_frames(samples, rate):
    size = int(FRAME_SECONDS * rate)
    frames = samples[: len(samples) // size * size].reshape(-1, size)
    rms = np.sqrt((frames**2).mean(axis=1))
    return rms > SILENCE_SHARE * rms.max()


def _map_events(tokens, events):
    """Start time for each script token, from the voice's word events (aligned by text)."""
    import difflib

    token_words = [norm(token) for token in tokens]
    event_words = [norm(text) for _time, text in events]
    starts = [None] * len(tokens)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=token_words, b=event_words, autojunk=False).get_opcodes():
        if tag in ("equal", "replace"):
            for offset in range(min(i2 - i1, j2 - j1)):
                starts[i1 + offset] = events[j1 + offset][0]
    return starts


def _silence_around(voiced, window_start, window_end):
    """The longest run of silent frames that overlaps [window_start, window_end], as (start, end) seconds."""
    runs, run_start = [], None
    for index, is_voiced in enumerate([*voiced, True]):
        if not is_voiced and run_start is None:
            run_start = index
        elif is_voiced and run_start is not None:
            runs.append((run_start, index))
            run_start = None
    first, last = window_start / FRAME_SECONDS, window_end / FRAME_SECONDS
    overlapping = [run for run in runs if run[0] < last and run[1] > first]
    if not overlapping:
        return None
    start, end = max(overlapping, key=lambda run: run[1] - run[0])
    return round(start * FRAME_SECONDS, 2), round(end * FRAME_SECONDS, 2)


def truth_for(clip, wav_path, events):
    samples, rate = _read_wav(wav_path)
    voiced = _voiced_frames(samples, rate)
    voiced_indexes = np.flatnonzero(voiced)
    speech_start = round(voiced_indexes[0] * FRAME_SECONDS, 2)
    speech_end = round((voiced_indexes[-1] + 1) * FRAME_SECONDS, 2)
    tokens = clip.script.tokens
    starts = _map_events(tokens, events)

    pauses = []
    for pause in clip.script.pauses:
        next_start = next((start for start in starts[pause.after + 1 :] if start is not None), speech_end)
        silence = _silence_around(voiced, next_start - pause.seconds - 0.3, next_start + 0.05)
        pauses.append(
            {
                "after": pause.after,
                "seconds": pause.seconds,
                "kind": pause.kind,
                "start": silence[0] if silence else round(next_start - pause.seconds, 2),
                "end": silence[1] if silence else round(next_start, 2),
            }
        )
    span = speech_end - speech_start
    return {
        "voice": clip.voice,
        "rate": clip.rate,
        "duration": round(len(samples) / rate, 2),
        "speech_start": speech_start,
        "speech_end": speech_end,
        "speech_span": round(span, 2),
        "word_count": len(tokens),
        "wpm": round(len(tokens) / (span / 60), 1),
        "word_starts": [round(start, 3) if start is not None else None for start in starts],
        "pauses": pauses,
    }


def render(clips):
    import soundfile

    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(TRUTH_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cta-evals-") as work:
        jobs = [
            {
                "id": clip.id,
                "ssml": markup.to_ssml(clip.markup),
                "voice": clip.voice,
                "rate": clip.rate,
                "wav": os.path.join(work, f"{clip.id}.wav"),
                "events": os.path.join(work, f"{clip.id}.tsv"),
            }
            for clip in clips
        ]
        jobs_path = os.path.join(work, "jobs.json")
        with open(jobs_path, "w", encoding="utf-8") as file:
            json.dump(jobs, file)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(EVALS_DIR, "render.ps1"), jobs_path],
            check=True,
        )
        for clip, job in zip(clips, jobs):
            with open(job["events"], encoding="utf-8") as file:
                events = [(float(ms) / 1000, text) for ms, text in (line.split("\t", 1) for line in file.read().splitlines() if line)]
            truth = truth_for(clip, job["wav"], events)
            samples, rate = _read_wav(job["wav"])
            soundfile.write(os.path.join(AUDIO_DIR, f"{clip.id}.flac"), samples, rate, subtype="PCM_16")
            with open(os.path.join(TRUTH_DIR, f"{clip.id}.json"), "w", encoding="utf-8", newline="\n") as file:
                json.dump(truth, file, indent=1)
            print(f"{clip.id}: {truth['speech_span']}s, {truth['wpm']} wpm, {len(truth['pauses'])} pauses")


def write_guide():
    """The recording guide for your own clips, generated from dataset/own/manifest.json."""
    with open(OWN_MANIFEST, encoding="utf-8") as file:
        recordings = json.load(file)["recordings"]
    by_id = {entry["id"]: entry for entry in load_manifest()["clips"]}
    passages = load_manifest()["passages"]
    lines = [
        "# Recording guide: your own evaluation clips",
        "",
        "Real voices are messier than the synthetic ones, so these clips show how the analysis holds up on a",
        "real person. Each one uses the same script as a synthetic clip, so the report can compare them directly.",
        "",
        "**How to record**",
        "",
        "1. Open the Windows **Sound Recorder** app (or any recorder) in a quiet room.",
        "2. Record each script below as its own file. Say it naturally, including every *um* and *uh* written in it.",
        "   Where it says **(pause)**, stop for about the time given, as if you were thinking.",
        "3. Save the files into `backend/evals/dataset/own/audio/` (create the folder if it is missing), named exactly as",
        "   shown, for example `own-01.m4a`.",
        "   Any common format works: .m4a, .mp3, .wav, .webm, .ogg.",
        "4. From `backend`, run `python -m evals.run --own`.",
        "",
        "These audio files stay on your computer: `dataset/own/audio/` is in `.gitignore`.",
        "",
    ]
    for entry in recordings:
        clip = by_id[entry["same_as"]]
        spoken = clip.get("script") or passages[clip["passage"]]
        lines += [f"## {entry['id']}", "", f"*{entry['instructions']}*", "", "> " + markup.to_reading_text(spoken, show_seconds=True), ""]
    path = os.path.join(OWN_DIR, "RECORDING_GUIDE.md")
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines))
    print(f"wrote {path}")


def main(argv):
    if "--guide" in argv:
        write_guide()
        return
    wanted = set(argv)
    clips = [clip for clip in synthetic_clips() if not wanted or clip.id in wanted]
    if not clips:
        sys.exit("No matching clips.")
    render(clips)


if __name__ == "__main__":
    main(sys.argv[1:])
