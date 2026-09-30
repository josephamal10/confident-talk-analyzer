"""Loads the evaluation clips (synthetic and own recordings) with everything needed to score them."""
import json
import os
from dataclasses import dataclass, field

from . import markup

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(EVALS_DIR, "dataset")
SYNTHETIC_MANIFEST = os.path.join(DATASET_DIR, "synthetic.json")
AUDIO_DIR = os.path.join(DATASET_DIR, "audio")
TRUTH_DIR = os.path.join(DATASET_DIR, "truth")
OWN_DIR = os.path.join(DATASET_DIR, "own")
OWN_MANIFEST = os.path.join(OWN_DIR, "manifest.json")
OWN_AUDIO_DIR = os.path.join(OWN_DIR, "audio")
AUDIO_EXTENSIONS = (".flac", ".wav", ".m4a", ".mp3", ".ogg", ".webm", ".mp4", ".aac")


@dataclass
class Clip:
    id: str
    category: str
    source: str  # "synthetic" or "own"
    markup: str  # what is said
    script: markup.Script
    mode: str = "free"
    topic: str = ""
    on_topic: bool | None = None
    passage: str | None = None  # the text shown for read-aloud
    document: list | None = None  # paragraphs of a reference document
    expect: dict = field(default_factory=dict)
    voice: str | None = None
    rate: int = 0
    audio_path: str | None = None
    truth: dict | None = None  # word timings from the synthetic voice


def _load_json(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def load_manifest():
    return _load_json(SYNTHETIC_MANIFEST)


def _clip_from_entry(entry, manifest, source):
    passage = manifest["passages"].get(entry["passage"]) if entry.get("passage") else None
    spoken = entry.get("script") or passage
    return Clip(
        id=entry["id"],
        category=entry["category"],
        source=source,
        markup=spoken,
        script=markup.parse(spoken),
        mode=entry.get("mode", "read" if entry["category"] in ("reading", "document") else "free"),
        topic=entry.get("topic", ""),
        on_topic=entry.get("on_topic"),
        passage=passage if entry["category"] == "reading" else None,
        document=manifest["documents"].get(entry["document"]) if entry.get("document") else None,
        expect=entry.get("expect", {}),
        voice=entry.get("voice"),
        rate=entry.get("rate", 0),
    )


def _find_audio(directory, clip_id):
    for extension in AUDIO_EXTENSIONS:
        path = os.path.join(directory, clip_id + extension)
        if os.path.isfile(path):
            return path
    return None


def synthetic_clips(manifest=None):
    manifest = manifest or load_manifest()
    clips = []
    for entry in manifest["clips"]:
        clip = _clip_from_entry(entry, manifest, "synthetic")
        clip.audio_path = _find_audio(AUDIO_DIR, clip.id)
        truth_path = os.path.join(TRUTH_DIR, f"{clip.id}.json")
        if os.path.isfile(truth_path):
            clip.truth = _load_json(truth_path)
        clips.append(clip)
    return clips


def own_clips(manifest=None):
    """Your own recordings of some of the synthetic scripts (evals/dataset/own). Pause lengths are
    unknown in a real recording, so their pauses count as "[pause]"."""
    if not os.path.isfile(OWN_MANIFEST):
        return []
    manifest = manifest or load_manifest()
    by_id = {entry["id"]: entry for entry in manifest["clips"]}
    clips = []
    for entry in _load_json(OWN_MANIFEST)["recordings"]:
        base = dict(by_id[entry["same_as"]])
        base.update({key: value for key, value in entry.items() if key not in ("same_as", "instructions")})
        clip = _clip_from_entry(base, manifest, "own")
        clip.voice, clip.rate = "own", 0
        clip.audio_path = _find_audio(OWN_AUDIO_DIR, clip.id)
        clip.expect = {**clip.expect, "same_as": entry["same_as"]}
        clips.append(clip)
    return clips
