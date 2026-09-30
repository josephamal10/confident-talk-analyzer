# AI coach evaluation

Generated 2026-09-30 13:47 · model `openai/gpt-oss-120b` via groq · 14 transcripts ([fixtures/coach_cases.json](../fixtures/coach_cases.json)).

| Check | Result |
|---|---|
| Valid structured answer on the first try | 100% |
| Response time (median / 95th percentile) | 2.0 s / 3.3 s |
| Agrees with the human on/off-topic label | 100% |
| Rewrites where the model invented a number | 33% (0 left after the guardrail) |
| Answers whose tips invented a number | 50% (0 left after the guardrail) |
| One-line answers given the fill-in template instead of a made-up story | 100% |
| Full on-topic answers kept as a real rewrite | 100% |
| New content in the model's rewrite: full answers (mean, max) | 37%, 82% |
| New content in the model's rewrite: one-line answers (mean) | 94% |
| Framework parts named outside the framework | 1 |
| Quotes of the speaker that really appear in the transcript | 50% of 2 |

**How it reads** (feedback text only, mean per answer; lower is better except *you*)

| | Raw model output | Shown in the app |
|---|---|---|
| Chatbot phrases per 100 words | 0.04 | 0.04 |
| Em dashes | 0.00 | 0.00 |
| Semicolons | 0.14 | 0.00 |
| "the speaker" / "the user" | 0.00 | 0.00 |
| "you" per 100 words | 5.79 | 5.77 |
| Words per sentence | 16.89 | 16.81 |

## Role prompt writers

| Role | Kind | Items | Types as asked | Too long | Examples |
|---|---|---|---|---|---|
| Data analyst | questions | 8 | yes | 0 | Tell me about a time you cleaned a messy dataset and what steps you took.; Describe a project where you identified a trend that impacted business decisions.; Give an example of when you had to meet a tight deadline for delivering a report. |
| Data analyst | jam | 10 | yes | 0 | Data in everyday life; Visualising trends with dashboards; Cleaning messy datasets |
| Nurse | questions | 8 | yes | 0 | Tell me about a time you handled a medical emergency under pressure.; Describe a situation where you had to advocate for a patient’s needs.; Give an example of how you resolved a conflict with a colleague on a shift. |
| Nurse | jam | 10 | yes | 0 | Patient care routines; Medication administration safety; Electronic health records usage |
| Civil engineer | questions | 8 | yes | 0 | Tell me about a time you solved a challenging structural design problem.; Describe a situation where you had to manage conflicting stakeholder priorities on a project.; Give an example of how you handled a project that fell behind schedule. |
| Civil engineer | jam | 10 | yes | 0 | Designing sustainable urban infrastructure; Using BIM for construction planning; Challenges of soil stabilization |

## Per transcript

| Case | Mode | On-topic (label) | Shown answer | New content | Invented numbers (raw rewrite / tips) | Speaker quotes grounded |
|---|---|---|---|---|---|---|
| coach-01 | interview | True (True) | rewrite | 40% | – / – | 0/0 |
| coach-02 | interview | True (True) | template | 100% | 30%, two / 30%, two | 0/0 |
| coach-03 | interview | False (False) | template | 93% | – / – | 0/1 |
| coach-04 | interview | True (True) | rewrite | 32% | – / – | 0/0 |
| coach-05 | interview | True (True) | rewrite | 82% | 15%, 20% / 15%, two | 0/0 |
| coach-06 | jam | True (True) | rewrite | 32% | – / – | 0/0 |
| coach-07 | jam | False (False) | template | 100% | – / 15, 60 | 0/0 |
| coach-08 | pitch | True (True) | rewrite | 14% | 30%, 15%, three / 30%, 15%, three | 0/0 |
| coach-09 | debate | True (True) | rewrite | 35% | – / 2023, 60% | 0/0 |
| coach-10 | presentation | True (True) | rewrite | 48% | three / – | 0/0 |
| coach-11 | snap | True (True) | rewrite | 13% | – / – | 0/0 |
| coach-12 | free | True (True) | rewrite | 38% | – / – | 0/0 |
| coach-13 | interview | True (True) | template | 97% | 30% / 15%, two | 0/0 |
| coach-14 | pitch | True (True) | template | 86% | 15 / 15 | 1/1 |

## Example (coach-05)

**Raw summary:** You gave a quick, practical outline, but it skips the big‑picture framing and the why‑it‑matters part. Adding a clear opening sentence and a short take‑away will make your answer much stronger.

**Shown in the app:** You gave a quick, practical outline, but it skips the big‑picture framing and the why‑it‑matters part. Adding a clear opening sentence and a short take‑away will make your answer much stronger.
