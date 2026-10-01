# Evaluation report

Generated 2026-10-01 16:24 on Windows AMD64, Python 3.10.10 · commit `fc709ed + local changes` · 53 synthetic clips, 0 own recordings · speech model faster-whisper `small.en`.

How the set is built and what each number means: [../README.md](../README.md).

## Summary

| Part | Metric | Result |
|---|---|---|
| Transcription | Word error rate, synthetic voices | 0.8% |
| Transcription | Word error rate, own recordings | – |
| Fillers | F1 (synthetic) | 100.0% |
| Fillers | F1 (own recordings) | – |
| Hedges | F1 (synthetic) | 100.0% |
| Pauses | Hesitation-pause F1 | 94.7% |
| Pauses | Share of scripted pauses found | 100.0% |
| Pace | Mean words-per-minute error | 0.9% |
| Pace | Rank correlation with true pace | 1.00 |
| Topic check | On/off-topic accuracy | 100% |
| JAM referee | Deviation F1 | 80% |
| Read-aloud | Verdict accuracy | 100% |
| Read-aloud | Skipped/misread/added counts exactly right | 100% |
| Documents | Located section overlap (IoU) | 100% |
| Scores | Fluency score vs filler density (rank corr.) | -0.97 |
| Speed | Analysis time / audio length | 0.77 |

## Fillers and hedges

| | Precision | Recall | F1 | Found / missed / false alarms |
|---|---|---|---|---|
| Fillers, synthetic | 100.0% | 100.0% | 100.0% | 26 / 0 / 0 |
| Hedges, synthetic | 100.0% | 100.0% | 100.0% | 11 / 0 / 0 |

## Pauses

- Hesitation pauses (synthetic, matched in time within 0.3s): precision 90.0%, recall 100.0%, f1 94.7%
- Scripted pauses found at all: 100.0%; of those, labelled the right kind (hesitation or natural): 100.0%; mean length error 0.09 s.

## Pace

| Clip | True WPM | Measured WPM | Pace score |
|---|---|---|---|
| pace-01 | 107.4 | 106 | 8.4 |
| pace-02 | 136.7 | 136 | 10.0 |
| pace-03 | 163.5 | 162 | 10.0 |
| pace-04 | 165.8 | 165 | 10.0 |
| pace-05 | 236.7 | 234 | 0.0 |
| pace-06 | 332.5 | 332 | 0.0 |

Across all 53 synthetic clips the words-per-minute error is 0.9% on average (95th percentile 2.2%).

## Topic check

| Clip | Mode | Expected | Found | Similarity |
|---|---|---|---|---|
| topic-01 | free | on | on | 0.667 |
| topic-02 | free | off | off | 0.013 |
| topic-03 | free | on | on | 0.658 |
| topic-04 | free | off | off | 0.127 |
| topic-05 | interview | on | on | 0.192 |
| topic-06 | interview | off | off | 0.145 |
| topic-07 | jam | on | on | 0.637 |
| topic-08 | jam | off | off | 0.092 |

## JAM referee

| Clip | Deviations | Repetitions |
|---|---|---|
| jam-01 | 0 (1) | 0 (0) |
| jam-02 | 0 (0) | 0 (0) |
| jam-03 | 2 (2) | 0 (0) |
| jam-04 | 0 (0) | 3 (3) |

Expected values in brackets.

## Read-aloud and documents

| Clip | Verdict (expected) | Accuracy | Skipped | Misread | Added | Section IoU |
|---|---|---|---|---|---|---|
| read-01 | same (same) | 100% | 0 (0) | 0 (0) | 0 (0) | – |
| read-02 | same (same) | 100% | 0 (0) | 0 (0) | 0 (0) | – |
| read-03 | close (close) | 94% | 3 (3) | 0 (0) | 0 (0) | – |
| read-04 | close (close) | 96% | 0 (0) | 2 (2) | 0 (0) | – |
| read-05 | close (close) | 100% | 0 (0) | 0 (0) | 2 (2) | – |
| read-06 | skipped (skipped) | 44% | 29 (29) | 0 (0) | 0 (0) | – |
| read-07 | related (related) | 29% | – | – | – | – |
| read-08 | different (different) | 14% | – | – | – | – |
| doc-01 | same (same) | 100% | – | – | – | 1.00 |
| doc-02 | close (close) | 98% | – | – | – | 0.99 |
| doc-03 | same (same) | 100% | – | – | – | 1.00 |
| doc-04 | different (different) | 0% | – | – | – | 1.00 |
| doc-05 | related (related) | 0% | – | – | – | 1.00 |

## Speed

Model warm-up 3.8 s. Per clip: mean 8.0 s, 95th percentile 14.1 s; 0.77× the audio length on average.
Mean time per stage (ms): decode_vad 238, transcription 5612, pitch 41, emotion 1984.

## Where it went wrong

**Pauses** (1)

- clip: fill-03; expected: []; found: ['natural 4.67-5.51s (0.84s)', 'hesitation 9.44-10.31s (0.87s)']

**Jam** (1)

- clip: jam-01; deviation: 0; expected_deviation: 1; repetition: 0; expected_repetition: 0; events: []
