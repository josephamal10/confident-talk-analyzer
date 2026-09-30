"""The script markup the evaluation clips are written in, so every label comes from the script itself.

    {um}        a filler (several words allowed: {you know})
    <maybe>     a hedge (several words allowed: <I think>)
    [1.2]       a pause of 1.2 seconds (the synthetic voice renders it exactly)
    [pause]     a pause of unknown length (own recordings: "pause for about two seconds")

Everything else is spoken as written. Example: "So, {um} I think [1.0] we should go."
"""
import re
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from analysis.fillers import CLAUSE_END_PATTERN
from analysis.prosody import LONG_PAUSE_SECONDS

TOKEN_PATTERN = re.compile(r"\{([^}]*)\}|<([^>]*)>|\[([^\]]*)\]|(\S+)")


@dataclass
class Pause:
    after: int  # index of the token the pause follows
    seconds: float | None  # None for "[pause]" in own recordings
    kind: str  # "hesitation" or "natural", by the pipeline's definition


@dataclass
class Script:
    tokens: list = field(default_factory=list)
    fillers: list = field(default_factory=list)  # token index lists, one per filler
    hedges: list = field(default_factory=list)  # token index lists, one per hedge
    pauses: list = field(default_factory=list)

    @property
    def text(self):
        return " ".join(self.tokens)

    def filler_indexes(self):
        return {index for span in self.fillers for index in span}


def _add_words(script, words, group=None):
    start = len(script.tokens)
    script.tokens.extend(words)
    if group is not None:
        group.append(list(range(start, len(script.tokens))))


def parse(markup):
    """Parses script markup into tokens with filler, hedge and pause labels."""
    script = Script()
    pending = []  # pauses waiting for the next token (to know if they sit next to a filler)
    for match in TOKEN_PATTERN.finditer(markup):
        filler, hedge, pause, word = match.groups()
        if pause is not None:
            if not script.tokens:
                raise ValueError(f"A pause can't start a script: {markup!r}")
            seconds = None if pause.strip() == "pause" else float(pause)
            pending.append(Pause(after=len(script.tokens) - 1, seconds=seconds, kind=""))
            continue
        # A filler written with its commas ("{like},") keeps them on the last word.
        trailing = ""
        if filler is not None or hedge is not None:
            rest = markup[match.end() :]
            trailing = re.match(r"[,.;:!?]*", rest).group(0)
        if filler is not None:
            _add_words(script, filler.split(), script.fillers)
        elif hedge is not None:
            _add_words(script, hedge.split(), script.hedges)
        elif word is not None:
            if re.fullmatch(r"[,.;:!?]+", word) and script.tokens:
                continue  # punctuation already attached to a filler or hedge above
            _add_words(script, [word])
        if trailing:
            script.tokens[-1] += trailing
        for pause_item in pending:
            script.pauses.append(pause_item)
        pending = []
    script.pauses.extend(pending)

    fillers = script.filler_indexes()
    for pause_item in script.pauses:
        previous = script.tokens[pause_item.after]
        mid_phrase = not CLAUSE_END_PATTERN.search(previous)
        next_to_filler = pause_item.after in fillers or (pause_item.after + 1) in fillers
        long_pause = pause_item.seconds is None or pause_item.seconds >= LONG_PAUSE_SECONDS
        pause_item.kind = "hesitation" if (mid_phrase or next_to_filler or long_pause) else "natural"
    return script


def to_ssml(markup, lang="en-US"):
    """SSML for the synthetic voice: the words, with <break> elements for timed pauses."""
    parts = []
    for match in TOKEN_PATTERN.finditer(markup):
        filler, hedge, pause, word = match.groups()
        if pause is not None:
            if pause.strip() == "pause":
                raise ValueError("Synthetic clips need timed pauses, e.g. [1.5].")
            parts.append(f'<break time="{round(float(pause) * 1000)}ms"/>')
        else:
            parts.append(escape(filler or hedge or word))
    body = " ".join(parts)
    body = re.sub(r"\s+([,.;:!?])", r"\1", body)
    return f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">{body}</speak>'


def to_reading_text(markup, show_seconds=False):
    """The script as a person would read it from a card: fillers and hedges as plain words, pauses as
    "(pause)" or, with `show_seconds`, "(pause 1.5 s)"."""

    def replace(match):
        filler, hedge, pause, word = match.groups()
        if pause is not None:
            return f"(pause {pause} s)" if show_seconds and pause.strip() != "pause" else "(pause)"
        return filler or hedge or word

    return re.sub(r"\s+([,.;:!?])", r"\1", TOKEN_PATTERN.sub(replace, markup))
