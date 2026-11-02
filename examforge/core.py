"""Exam logic with no database or web code: papers, marking and item analysis."""
import csv
import io
import math
import random
from dataclasses import dataclass, field

LETTERS = "ABCDEFGH"


@dataclass
class Question:
    id: int
    stem: str
    options: list
    answer: int              # index into options
    topic: str = "General"
    difficulty: str = "medium"
    marks: float = 1.0


@dataclass
class PaperItem:
    question: Question
    order: list              # order[i] is the original option shown at position i

    def shown_answer(self):
        return self.order.index(self.question.answer)

    def shown_options(self):
        return [self.question.options[i] for i in self.order]


@dataclass
class Paper:
    name: str
    items: list = field(default_factory=list)

    def total(self):
        return sum(i.question.marks for i in self.items)

    def key(self):
        return [LETTERS[i.shown_answer()] for i in self.items]


class BlueprintError(Exception):
    pass


def choose(bank, blueprint, seed=0):
    """Pick questions to match a blueprint: {(topic, difficulty): how many}. Each question is used once."""
    rng = random.Random(seed)
    pools = {}
    for q in bank:
        pools.setdefault((q.topic, q.difficulty), []).append(q)
    chosen = []
    problems = []
    for (topic, difficulty), n in blueprint.items():
        pool = sorted(pools.get((topic, difficulty), []), key=lambda q: q.id)
        if len(pool) < n:
            problems.append(f"{topic} / {difficulty}: needs {n}, the bank has {len(pool)}")
        else:
            chosen.extend(rng.sample(pool, n))
    if problems:
        raise BlueprintError("; ".join(problems))
    return sorted(chosen, key=lambda q: q.id)


def make_versions(questions, count=2, seed=0, shuffle_options=True):
    """Build several paper versions of the same questions, in different orders, to discourage copying.
    Options named like 'All of the above' keep their last place, since moving them breaks the sense."""
    rng = random.Random(seed)
    papers = []
    for v in range(count):
        items = []
        for q in rng.sample(questions, len(questions)):
            order = list(range(len(q.options)))
            if shuffle_options:
                fixed = [i for i in order if q.options[i].strip().lower() in ("all of the above", "none of the above", "both a and b")]
                moving = [i for i in order if i not in fixed]
                rng.shuffle(moving)
                order = moving + fixed
            items.append(PaperItem(q, order))
        papers.append(Paper(f"Version {LETTERS[v]}", items))
    return papers


def mark(paper, responses):
    """responses: one letter per item, blank for no answer. Returns (score, original option chosen per item)."""
    if len(responses) != len(paper.items):
        raise ValueError(f"expected {len(paper.items)} answers, got {len(responses)}")
    score = 0.0
    chosen = []
    for item, r in zip(paper.items, responses):
        r = (r or "").strip().upper()
        if not r:
            chosen.append(None)
            continue
        if r not in LETTERS[:len(item.order)]:
            raise ValueError(f"{r!r} is not an option")
        original = item.order[LETTERS.index(r)]
        chosen.append(original)
        if original == item.question.answer:
            score += item.question.marks
    return score, chosen


def mean(v):
    return sum(v) / len(v) if v else 0.0


def variance(v):
    if len(v) < 2:
        return 0.0
    m = mean(v)
    return sum((x - m) ** 2 for x in v) / len(v)


def point_biserial(item, rest):
    """Correlation between getting an item right and the rest of the score (item removed)."""
    n = len(item)
    if n < 2:
        return 0.0
    mi, mr = mean(item), mean(rest)
    si = math.sqrt(sum((x - mi) ** 2 for x in item))
    sr = math.sqrt(sum((x - mr) ** 2 for x in rest))
    if si == 0 or sr == 0:
        return 0.0
    return sum((a - mi) * (b - mr) for a, b in zip(item, rest)) / (si * sr)


def kr20(matrix):
    """Reliability of a right-or-wrong test. matrix: one row per learner, of 0s and 1s."""
    if not matrix or len(matrix[0]) < 2:
        return 0.0
    k = len(matrix[0])
    totals = [sum(r) for r in matrix]
    var = variance(totals)
    if var == 0:
        return 0.0
    pq = 0.0
    for j in range(k):
        p = mean([r[j] for r in matrix])
        pq += p * (1 - p)
    return k / (k - 1) * (1 - pq / var)


def item_analysis(matrix, choices=None, option_counts=None, answers=None):
    """Classical test theory for each item. matrix: rows of 0/1. choices: rows of the original option picked.

    difficulty is the share who got it right. discrimination compares the top and bottom 27%.
    """
    if not matrix:
        return []
    k = len(matrix[0])
    totals = [sum(r) for r in matrix]
    order = sorted(range(len(matrix)), key=lambda i: totals[i])
    cut = max(1, round(len(matrix) * 0.27))
    low, high = order[:cut], order[-cut:]
    out = []
    for j in range(k):
        col = [r[j] for r in matrix]
        rest = [t - c for t, c in zip(totals, col)]
        p = mean(col)
        d = mean([matrix[i][j] for i in high]) - mean([matrix[i][j] for i in low])
        row = {"item": j + 1, "difficulty": p, "discrimination": d, "point_biserial": point_biserial(col, rest), "flags": []}
        if p > 0.9:
            row["flags"].append("very easy")
        if p < 0.2:
            row["flags"].append("very hard")
        if row["point_biserial"] < 0.1:
            row["flags"].append("weak discrimination")
        if row["point_biserial"] < 0:
            row["flags"].append("stronger learners do worse: check the key")
        if choices is not None and option_counts is not None:
            counts = [0] * option_counts[j]
            for r in choices:
                if r[j] is not None:
                    counts[r[j]] += 1
            row["option_counts"] = counts
            if answers is not None:
                unused = [LETTERS[i] for i, c in enumerate(counts) if c == 0 and i != answers[j]]
                if unused:
                    row["flags"].append("unused options: " + ", ".join(unused))
        out.append(row)
    return out


def score_summary(scores, total, pass_mark=0.4):
    if not scores:
        return {"count": 0}
    s = sorted(scores)
    n = len(s)
    return {"count": n, "mean": mean(s), "median": (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2), "low": s[0], "high": s[-1], "sd": math.sqrt(variance(s)), "pass_rate": sum(1 for x in s if x >= pass_mark * total) / n}


def sem(sd, reliability):
    """Standard error of measurement: how far a learner's score may sit from their true level."""
    return sd * math.sqrt(max(1 - reliability, 0))


def read_questions(text):
    """CSV columns: stem, A, B, C, D (E and more are optional), answer (a letter), topic, difficulty, marks."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or "stem" not in reader.fieldnames or "answer" not in reader.fieldnames:
        raise ValueError("the file needs at least the columns stem, A, B, answer")
    out, problems = [], []
    for number, row in enumerate(reader, 2):
        options = [row[c].strip() for c in LETTERS if row.get(c) and row[c].strip()]
        letter = (row.get("answer") or "").strip().upper()
        if len(options) < 2:
            problems.append(f"line {number}: needs at least two options")
            continue
        if letter not in LETTERS[:len(options)]:
            problems.append(f"line {number}: answer {letter!r} is not one of the options")
            continue
        if len(set(options)) != len(options):
            problems.append(f"line {number}: two options are the same")
            continue
        difficulty = (row.get("difficulty") or "medium").strip().lower()
        if difficulty not in ("easy", "medium", "hard"):
            problems.append(f"line {number}: difficulty must be easy, medium or hard")
            continue
        try:
            marks = float(row.get("marks") or 1)
        except ValueError:
            problems.append(f"line {number}: marks must be a number")
            continue
        out.append(Question(0, row["stem"].strip(), options, LETTERS.index(letter), (row.get("topic") or "General").strip(), difficulty, marks))
    return out, problems
