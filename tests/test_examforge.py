import random
import re
import unittest

from examforge import core, create_app
from examforge.core import BlueprintError, Question, choose, item_analysis, kr20, make_versions, mark, point_biserial, read_questions, score_summary, sem


def bank():
    out = []
    for i in range(40):
        topic = ["Hardware", "Internet"][i % 2]
        level = ["easy", "medium", "hard"][i % 3]
        out.append(Question(i + 1, f"Q{i}", [f"a{i}", f"b{i}", f"c{i}", f"d{i}"], i % 4, topic, level))
    return out


class TestPapers(unittest.TestCase):
    def test_blueprint_is_met_and_repeatable(self):
        bp = {("Hardware", "easy"): 3, ("Internet", "hard"): 2}
        a = choose(bank(), bp, 1)
        self.assertEqual(len(a), 5)
        self.assertEqual(sum(q.topic == "Hardware" for q in a), 3)
        self.assertEqual([q.id for q in a], [q.id for q in choose(bank(), bp, 1)])
        self.assertNotEqual([q.id for q in a], [q.id for q in choose(bank(), bp, 2)])

    def test_blueprint_too_big_says_why(self):
        with self.assertRaises(BlueprintError) as c:
            choose(bank(), {("Hardware", "easy"): 99})
        self.assertIn("needs 99", str(c.exception))

    def test_versions_hold_the_same_questions_in_new_orders(self):
        a, b = make_versions(bank()[:12], 2, 3)
        self.assertEqual(sorted(i.question.id for i in a.items), sorted(i.question.id for i in b.items))
        self.assertNotEqual([i.question.id for i in a.items], [i.question.id for i in b.items])

    def test_key_follows_the_shuffle(self):
        for p in make_versions(bank(), 4, 5):
            for it, letter in zip(p.items, p.key()):
                self.assertEqual(it.shown_options()[core.LETTERS.index(letter)], it.question.options[it.question.answer])

    def test_all_of_the_above_stays_last(self):
        q = Question(1, "x", ["a", "b", "c", "All of the above"], 3)
        for s in range(20):
            self.assertEqual(make_versions([q], 1, s)[0].items[0].shown_options()[-1], "All of the above")

    def test_marking_a_perfect_sheet_on_every_version(self):
        for p in make_versions(bank()[:10], 3, 1):
            self.assertEqual(mark(p, p.key())[0], 10)

    def test_marks_and_blanks(self):
        q = Question(1, "x", ["a", "b"], 0, marks=2.5)
        p = make_versions([q], 1, 0, shuffle_options=False)[0]
        self.assertEqual(mark(p, ["A"])[0], 2.5)
        self.assertEqual(mark(p, ["b"]), (0, [1]))
        self.assertEqual(mark(p, [""]), (0, [None]))

    def test_bad_sheets(self):
        p = make_versions(bank()[:2], 1)[0]
        with self.assertRaises(ValueError):
            mark(p, ["A"])
        with self.assertRaises(ValueError):
            mark(p, ["A", "Z"])


class TestAnalysis(unittest.TestCase):
    def simulate(self, seed=0, people=400, items=30, bad_item=None):
        """Item response model: a stronger learner is more likely to be right."""
        rng = random.Random(seed)
        hard = [rng.uniform(-1.5, 1.5) for _ in range(items)]
        out = []
        for _ in range(people):
            skill = rng.gauss(0, 1)
            row = []
            for j in range(items):
                p = 1 / (1 + 2.718 ** (-1.5 * (skill - hard[j])))
                right = rng.random() < p
                if j == bad_item:
                    right = not right
                row.append(int(right))
            out.append(row)
        return out

    def test_kr20_known_example(self):
        m = [[1, 1, 1], [1, 1, 0], [1, 0, 0], [0, 0, 0]]
        p = [0.75, 0.5, 0.25]
        pq = sum(x * (1 - x) for x in p)
        totals = [3, 2, 1, 0]
        var = sum((t - 1.5) ** 2 for t in totals) / 4
        self.assertAlmostEqual(kr20(m), 3 / 2 * (1 - pq / var))

    def test_reliability_grows_with_test_length(self):
        m = self.simulate()
        short = kr20([r[:5] for r in m])
        self.assertGreater(kr20(m), short + 0.2)

    def test_kr20_edges(self):
        self.assertEqual(kr20([]), 0)
        self.assertEqual(kr20([[1, 1], [1, 1]]), 0)

    def test_point_biserial_matches_a_plain_correlation(self):
        a, b = [1, 0, 1, 1, 0], [10, 3, 8, 9, 5]
        ma, mb = sum(a) / 5, sum(b) / 5
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
        self.assertAlmostEqual(point_biserial(a, b), num / den)
        self.assertEqual(point_biserial([1, 1], [3, 4]), 0)

    def test_a_wrong_key_is_flagged(self):
        rows = item_analysis(self.simulate(bad_item=7))
        self.assertTrue(any("check the key" in f for f in rows[7]["flags"]))
        self.assertLess(rows[7]["discrimination"], 0)
        healthy = [r for i, r in enumerate(rows) if i != 7]
        self.assertGreater(sum(r["point_biserial"] > 0.2 for r in healthy), 20)

    def test_difficulty_flags(self):
        m = [[1, 0, 1] for _ in range(19)] + [[0, 1, 0]]
        rows = item_analysis(m)
        self.assertIn("very easy", rows[0]["flags"])
        self.assertIn("very hard", rows[1]["flags"])

    def test_unused_distractor(self):
        m = [[1], [0], [1], [0]]
        rows = item_analysis(m, [[0], [1], [0], [1]], [4], [0])
        self.assertEqual(rows[0]["option_counts"], [2, 2, 0, 0])
        self.assertIn("unused options: C, D", rows[0]["flags"])

    def test_summary(self):
        s = score_summary([2, 4, 6, 8], 10, 0.5)
        self.assertEqual((s["mean"], s["median"], s["low"], s["high"], s["pass_rate"]), (5, 5, 2, 8, 0.5))
        self.assertEqual(score_summary([], 10)["count"], 0)

    def test_sem(self):
        self.assertAlmostEqual(sem(10, 0.91), 3)
        self.assertEqual(sem(10, 1.2), 0)


class TestImport(unittest.TestCase):
    def test_good(self):
        q, p = read_questions("stem,A,B,C,answer,topic,difficulty,marks\nWhat is RAM?,Memory,Disk,Screen,A,Hardware,easy,2\n")
        self.assertEqual(p, [])
        self.assertEqual((q[0].options, q[0].answer, q[0].marks), (["Memory", "Disk", "Screen"], 0, 2))

    def test_bangla_and_byte_order_mark(self):
        q, _ = read_questions("﻿stem,A,B,answer\nকম্পিউটার কী?,যন্ত্র,ফল,A\n")
        self.assertEqual(q[0].stem, "কম্পিউটার কী?")

    def test_each_problem_names_its_line(self):
        text = "stem,A,B,C,answer,difficulty,marks\nok,a,b,,A,easy,1\nno,a,,,A,easy,1\nbad,a,b,,Z,easy,1\nsame,a,a,,A,easy,1\nlevel,a,b,,A,brutal,1\nm,a,b,,A,easy,x\n"
        q, p = read_questions(text)
        self.assertEqual(len(q), 1)
        self.assertEqual([x.split(":")[0] for x in p], ["line 3", "line 4", "line 5", "line 6", "line 7"])

    def test_missing_columns(self):
        with self.assertRaises(ValueError):
            read_questions("a,b\n1,2\n")


CSV_TEXT = "stem,A,B,C,D,answer,topic,difficulty,marks\n" + "".join(f"Question {i},w{i},x{i},y{i},z{i},{'ABCD'[i % 4]},ICT,easy,1\n" for i in range(12))


class TestApp(unittest.TestCase):
    def setUp(self):
        self.a = create_app(":memory:")

    def body(self, r):
        return r.body.decode()

    def build(self):
        self.a.post("/import", csv=CSV_TEXT)
        r = self.a.post("/exam/new", name="Term 1", versions=2, seed=3, n0=5)
        self.assertEqual(r.status, 303)
        return r.headers["Location"]

    def test_flow_from_import_to_analysis(self):
        url = self.build()
        self.assertIn("Term 1", self.body(self.a.get(url)))
        key = re.findall(r"<b>\d+</b>:([A-D])", self.body(self.a.get(url + "/key/0")))
        self.assertEqual(len(key), 5)
        self.assertEqual(self.a.post(url + "/mark", learner="Rahima", version=0, responses="".join(key)).status, 303)
        wrong = "".join("A" if k != "A" else "B" for k in key)
        self.a.post(url + "/mark", learner="Karim", version=0, responses=wrong)
        page = self.body(self.a.get(url))
        self.assertIn("Rahima", page)
        self.assertIn("5.0", page)
        self.assertIn("KR-20", self.body(self.a.get(url + "/analysis")))

    def test_paper_shows_questions_without_answers(self):
        url = self.build()
        page = self.body(self.a.get(url + "/paper/0"))
        self.assertEqual(len(re.findall(r"Question \d+", page)), 5)
        self.assertNotIn("Key", page)

    def test_same_learner_twice_is_refused(self):
        url = self.build()
        self.a.post(url + "/mark", learner="R", version=0, responses="AAAAA")
        self.assertEqual(self.a.post(url + "/mark", learner="R", version=0, responses="AAAAA").status, 409)

    def test_wrong_number_of_answers(self):
        url = self.build()
        self.assertEqual(self.a.post(url + "/mark", learner="R", version=0, responses="AA").status, 400)

    def test_blueprint_too_large(self):
        self.a.post("/import", csv=CSV_TEXT)
        self.assertEqual(self.a.post("/exam/new", name="x", n0=99).status, 400)

    def test_empty_blueprint(self):
        self.a.post("/import", csv=CSV_TEXT)
        self.assertEqual(self.a.post("/exam/new", name="x", n0=0).status, 400)

    def test_text_is_escaped(self):
        self.a.post("/import", csv='stem,A,B,answer\n<script>alert(1)</script>,a,b,A\n')
        self.assertNotIn("<script>alert", self.body(self.a.get("/bank")))

    def test_forged_post_is_refused(self):
        self.assertEqual(self.a.handle("POST", "/import", {"csv": CSV_TEXT}).status, 403)
        self.assertEqual(self.a.one("SELECT COUNT(*) FROM questions"), 0)

    def test_missing_exam(self):
        self.assertEqual(self.a.get("/exam/99").status, 404)


if __name__ == "__main__":
    unittest.main()
