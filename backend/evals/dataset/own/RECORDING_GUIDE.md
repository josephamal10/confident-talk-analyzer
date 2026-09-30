# Recording guide: your own evaluation clips

Real voices are messier than the synthetic ones, so these clips show how the analysis holds up on a
real person. Each one uses the same script as a synthetic clip, so the report can compare them directly.

**How to record**

1. Open the Windows **Sound Recorder** app (or any recorder) in a quiet room.
2. Record each script below as its own file. Say it naturally, including every *um* and *uh* written in it.
   Where it says **(pause)**, stop for about the time given, as if you were thinking.
3. Save the files into `backend/evals/dataset/own/audio/` (create the folder if it is missing), named exactly as
   shown, for example `own-01.m4a`.
   Any common format works: .m4a, .mp3, .wav, .webm, .ogg.
4. From `backend`, run `python -m evals.run --own`.

These audio files stay on your computer: `dataset/own/audio/` is in `.gitignore`.

## own-01

*Say it like a relaxed answer, with the um, uh, like and hmm where they are written.*

> So, um the reason I chose this field is, uh mostly curiosity. I was, like, always taking things apart as a child. Hmm, my parents were not always happy about that.

## own-02

*A hesitant answer: say every um and uh, and 'you know' as a filler.*

> Um I think the uh biggest challenge was um time. We had, you know, three deadlines in one week, and uh I had to um plan everything carefully.

## own-03

*Say 'like' and 'you know' as fillers only where they sit between commas.*

> It was, like, the best trip ever. I like mountains more than beaches. You know the feeling when the air is cold and clean? It was, you know, perfect.

## own-04

*A fluent, confident delivery with no fillers at all.*

> Good communication is a skill that anyone can learn. It starts with listening carefully, then saying one clear idea at a time.

## own-05

*Stop mid-sentence where it says (pause), as if you lost your train of thought.*

> I believe the most important thing (pause 1.0 s) is to stay consistent. Small steps every day add up (pause 1.5 s) over a whole year.

## own-06

*Take a calm breath between sentences where it says (pause).*

> We started early. (pause 1.0 s) The roads were empty. (pause 1.2 s) By nine we had reached the coast.

## own-07

*Pause where marked; the two-second one should feel like a real hesitation.*

> My favourite subject (pause 0.8 s) was history, because the teacher (pause 1.2 s) told great stories. (pause 0.8 s) I still remember (pause 2.0 s) most of them.

## own-08

*Sound unsure: lean on 'I think', 'maybe', 'I guess' and 'kind of'.*

> I think this plan could work, but maybe we should test it first. I guess the budget is kind of tight.

## own-09

*Read the passage exactly as written, like a news reader.*

> The city library will open a new reading room next month. The room will have quiet desks, fast internet and a small cafe. Students can book a desk online for up to four hours a day. The library hopes the space will help people who have nowhere quiet to study at home.

## own-10

*Read the passage as written here. It leaves out three words of the original, which the check should catch.*

> The city library will open a reading room next month. The room will have quiet desks, internet and a small cafe. Students can book a desk for up to four hours a day. The library hopes the space will help people who have nowhere quiet to study at home.
