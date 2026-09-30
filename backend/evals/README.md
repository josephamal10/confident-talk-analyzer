# Evaluation suite

The app turns a recording into a transcript, filler and hedge counts, pauses, pace, a topic check,
JAM referee calls and read-aloud accuracy, then an LLM writes coaching on top. This folder measures
how right each of those parts is, on labelled recordings, with one command.

Latest results: **[results/REPORT.md](results/REPORT.md)** (speech pipeline) and
**[results/COACH.md](results/COACH.md)** (AI coach).

## Run it

From `backend/`, with the virtual environment active:

```bat
python -m evals.run
```

| Command | What it does |
|---|---|
| `python -m evals.run` | Analyses every synthetic clip and writes `results/REPORT.md` and `results/latest.json` (about 5-10 minutes on a laptop CPU) |
| `python -m evals.run --own` | Adds your own recordings from `dataset/own/audio/` (see below) |
| `python -m evals.run --only pauses,pause-03` | Only some categories or clips |
| `python -m evals.run --save-as baseline` / `--compare baseline` | Keep a run, then show a later run against it |
| `python -m evals.coach_eval` | Evaluates the AI coach and the role prompt writers against the LLM in `backend/.env` (about 20 API calls) |
| `python -m evals.build` | Re-renders the synthetic clips (Windows only; the rendered clips are committed) |

The unit tests for the suite itself are in `tests/test_evals.py`.

## The dataset

**53 synthetic clips** in [dataset/synthetic.json](dataset/synthetic.json), spoken by the two built-in
Windows voices (Microsoft David and Zira) at different speeds:

| Category | Clips | What is labelled |
|---|---|---|
| fluency | 10 | fillers (*um, uh, hmm, ah*, and *like* / *you know* used as fillers next to normal uses of the same words) |
| pauses | 8 | timed pauses, mid-sentence and at sentence ends, next to fillers, and a fluent control |
| pace | 6 | the same passage at six speeds (107 to 332 words a minute) |
| hedges | 4 | *I think, maybe, kind of*... and phrases that only look like hedges (*what kind of car*) |
| topic | 8 | on- and off-topic answers in free practice, interview and JAM |
| jam | 4 | off-topic sentences and over-used words a JAM referee should call |
| reading | 8 | a passage read exactly, with skipped, misread and added words, stopped halfway, paraphrased, or replaced by something else |
| document | 5 | parts of a news document read out, a paraphrase, and an unrelated reading |

**Labels come from the script, not from the system being tested.** Each script is written in a small
markup ([markup.py](markup.py)): `{um}` is a filler, `<maybe>` a hedge and `[1.2]` a 1.2-second pause.
The voice reports when every word starts, which gives the true speaking time and pace, and the true
position of every pause. Expected verdicts, counts and on/off-topic calls are set by hand in the
manifest; a unit test checks that the reading labels add up (passage − skipped + added = what is said).

**Your own recordings.** Synthetic voices are clean and very regular, so real speech is harder.
[dataset/own/RECORDING_GUIDE.md](dataset/own/RECORDING_GUIDE.md) has ten scripts (reusing synthetic
clips, so the two can be compared directly) to record in any recorder app. The audio stays on your
computer (`dataset/own/audio/` is in `.gitignore`); only the numbers go in the report.

## What each number means

| Part | Metric |
|---|---|
| Transcription | Word error rate against the script, after lower-casing, dropping punctuation and writing numbers as digits |
| Fillers, hedges | Precision, recall and F1 over occurrences. The transcript is aligned to the script word by word, and a labelled filler counts as found when the app flagged a word aligned with it |
| Pauses | Hesitation pauses found at the right time (within 0.3 s of the scripted silence), the share of all scripted pauses found, whether each was called a hesitation or a natural pause, and the length error |
| Pace | Words-per-minute error against the true pace, and the rank correlation over the six speeds |
| Topic check | Share of on/off-topic calls that match the label |
| JAM referee | Precision, recall and F1 of off-topic (deviation) and repetition calls |
| Read-aloud | Verdict accuracy (*exactly as written, with a few slips, skipped a lot, only partly, same subject in other words, different*), and whether the skipped, misread and added counts are exactly right |
| Documents | Overlap (intersection over union) between the part of the document the app says was read and the part really read |
| Scores | Rank correlation between the fluency score and filler density: it should be strongly negative |
| Speed | Analysis time divided by the recording's length, on the machine that ran the report |

## What the evaluation changed

The first run was saved as a baseline ([results/baseline.json](results/baseline.json), the code as it was at
commit `64c1580`), then each fault it found was fixed and measured again.

| Found | Fix | Before | After |
|---|---|---|---|
| Half the pauses were missed: Whisper stretches a word's start back over the silence before it, so the gap between word timestamps disappears | Pauses now come from the voice-activity detector's silences, each placed before the first word that ends after it ([analysis/prosody.py](../analysis/prosody.py)) | Hesitation-pause F1 33%, pauses found 53% | 95%, 100% |
| "Read exactly as written" was given to readings with two added words, or a skipped word | "Exactly" now allows at most about one slip per 100 words, both ways ([analysis/reading.py](../analysis/reading.py)) | Verdict accuracy 85% | 100% |
| The coach turned a one-line answer into a whole invented story (a job, a project, dates) | A rewrite whose content words are 85% or more new is replaced by the fill-in template ([analysis/coach.py](../analysis/coach.py)) | 1 of 1 one-line answers got a made-up story | 3 of 3 get the template; 9 of 9 full answers keep their rewrite |
| Tips invented statistics ("improving customer satisfaction by 10%"), and spelled-out numbers slipped past the guardrail | The number guardrail covers tips and spelled-out numbers; the prompt asks for [placeholders] in example phrasing | 6 of 12 answers showed invented numbers in tips; 2 of 10 rewrites kept invented spelled-out numbers | 0 and 0 (the model still invents them in half the tips; the guardrail removes them) |

The coach numbers are from [results/coach_baseline.json](results/coach_baseline.json) and
[results/coach_latest.json](results/coach_latest.json). The 85% cut-off separates the cases here by a narrow
margin (the most-changed real rewrite had 82% new content, the least-changed one-line answer 86%), so it needs
more labelled answers before it can be trusted further.

One label problem was fixed on the way: the Windows voices spell *er* as the letters "E. R.", so a clip that
was meant to test *er* tested nothing; it now uses *ah*.

## Limits

- The synthetic voices are clean, American-accented and very regular; the error rates on real speech
  will be higher. The own-recordings set is the check on that, and it is small.
- The Windows voices can't say *er* or *erm* (they spell them out), so those fillers are only covered
  by real recordings.
- Fifty-odd clips is enough to find real faults, not to fine-tune thresholds. The thresholds changed
  here were changed for a stated reason, and the others were left alone on purpose: the JAM referee
  stays cautious (it missed one of three off-topic sentences but made no wrong calls) because a wrong
  call is worse than a missed one.
- A pause the synthetic voice adds on its own at a full stop is not in the labels. When a filler
  follows it ("...as a child. Hmm, my parents") the app calls it a hesitation, which is its rule, and
  the report lists it as a false alarm.
- The coach is judged on 14 transcripts, and some checks rest on very few examples (the model quoted
  the speaker only twice in all its feedback).
- The labels were written by the same person who wrote the checks, so they share that person's idea
  of what, say, a hedge is.
