# ExamForge

An offline exam tool for teachers. Keep a question bank, build shuffled paper versions from a blueprint, mark answers, and find out which questions are working. It runs on your own computer with no internet, and your data stays in one file.

```
python -m examforge
```

Then open http://127.0.0.1:8021. Python 3.10 or newer is the only requirement.

## How it works

1. **Add questions** by pasting a CSV with the columns `stem, A, B, C, D, answer, topic, difficulty, marks`. Bangla works. Problems are reported by line.
2. **Build an exam** from a blueprint, such as 5 easy Hardware and 3 hard Internet questions. Keep the seed to rebuild the same paper.
3. **Print** the versions and their keys. Questions and options are shuffled in each version, and "All of the above" stays last.
4. **Enter answers** as letters, and marking follows the right version.
5. **Read the item analysis.**

## What the item analysis tells you

| Number | Meaning |
|---|---|
| Difficulty | The share of learners who got it right |
| Discrimination | Top 27% minus bottom 27% |
| Point-biserial | Does doing well on this item go with doing well overall? |
| KR-20 | How consistent the whole test is, with 0.7 or above a common aim for classroom tests |
| Measurement error | How far a score may sit from a learner's true level |

Flags point to what to fix: very easy or very hard items, unused options, and items that stronger learners get wrong, which often means a wrong key.

## How it is tested

Marking and keys are checked on every shuffled version. Item statistics are checked on hand examples and on simulated classes in which stronger learners are more likely to be right, including one deliberately reversed item that must be flagged. The app is tested from import through to analysis, along with forged forms and script injection.

## Limits

It is for multiple-choice questions only, with no essay marking. It runs for one teacher on one computer and has no user logins, so keep the file safe. Item statistics need a reasonable class size: below about 30 learners, treat them as rough hints.

MIT licence.
