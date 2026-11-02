"""The offline web app."""
import json

from . import core
from .fieldkit import App, Fail, Raw, bar_chart, card, form, h, link, redirect, stats, table

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, stem TEXT NOT NULL, options TEXT NOT NULL, answer INTEGER NOT NULL, topic TEXT NOT NULL, difficulty TEXT NOT NULL, marks REAL NOT NULL);
CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, name TEXT NOT NULL, papers TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY, exam INTEGER NOT NULL REFERENCES exams(id), learner TEXT NOT NULL, version INTEGER NOT NULL, responses TEXT NOT NULL, score REAL NOT NULL, UNIQUE (exam, learner));
"""


def to_question(r):
    return core.Question(r["id"], r["stem"], json.loads(r["options"]), r["answer"], r["topic"], r["difficulty"], r["marks"])


def create_app(db="examforge.db"):
    a = App("ExamForge", db, SCHEMA, [("Home", "/"), ("Question bank", "/bank"), ("Add questions", "/import"), ("New exam", "/exam/new")])

    def bank():
        return [to_question(r) for r in a.rows("SELECT * FROM questions ORDER BY id")]

    def load(exam_id):
        e = a.row("SELECT * FROM exams WHERE id = ?", exam_id)
        if e is None:
            raise Fail("No such exam", 404)
        by_id = {q.id: q for q in bank()}
        papers = []
        for p in json.loads(e["papers"]):
            items = []
            for qid, order in p["items"]:
                if qid not in by_id:
                    raise Fail("A question in this exam has been deleted", 409)
                items.append(core.PaperItem(by_id[qid], order))
            papers.append(core.Paper(p["name"], items))
        return e, papers

    def add_question(q):
        a.run("INSERT INTO questions (stem, options, answer, topic, difficulty, marks) VALUES (?, ?, ?, ?, ?, ?)", q.stem, json.dumps(q.options, ensure_ascii=False), q.answer, q.topic, q.difficulty, q.marks)

    @a.route("/")
    def home(req):
        exams = a.rows("SELECT e.id, e.name, COUNT(r.id) n, AVG(r.score) avg FROM exams e LEFT JOIN results r ON r.exam = e.id GROUP BY e.id ORDER BY e.id DESC")
        topics = a.rows("SELECT topic, COUNT(*) n FROM questions GROUP BY topic ORDER BY n DESC")
        return a.page("Overview", stats([("Questions", a.one("SELECT COUNT(*) FROM questions")), ("Exams", len(exams)), ("Results", a.one("SELECT COUNT(*) FROM results"))]) + card("Exams", table(exams, [("Exam", lambda r: link(f"/exam/{r['id']}", r["name"])), ("Results", "n"), ("Mean score", lambda r: "" if r["avg"] is None else round(r["avg"], 2))], "No exams yet. Add questions, then build one.")) + card("Questions by topic", bar_chart([(t["topic"], t["n"]) for t in topics])))

    @a.route("/bank")
    def question_bank(req):
        return a.page("Question bank", card("Questions", table(a.rows("SELECT * FROM questions ORDER BY topic, id"), [("Topic", "topic"), ("Level", "difficulty"), ("Marks", "marks"), ("Question", "stem")], "The bank is empty.")))

    @a.route("/import", ("GET", "POST"))
    def add(req):
        if req.method == "POST":
            found, problems = core.read_questions(req.text("csv", limit=2_000_000))
            for q in found:
                add_question(q)
            a.log("import questions", len(found))
            note = f"Added {len(found)} questions." + (" Skipped: " + "; ".join(problems) if problems else "")
            return a.page("Add questions", card("Result", f"<p>{h(note)}</p>"))
        return a.page("Add questions", card("Paste a CSV", "<p>Columns: <code>stem, A, B, C, D, answer, topic, difficulty, marks</code></p>" + form(a, "/import", [("csv", "CSV text", "textarea")], "Add")))

    @a.route("/exam/new", ("GET", "POST"))
    def new_exam(req):
        pools = a.rows("SELECT topic, difficulty, COUNT(*) n FROM questions GROUP BY topic, difficulty ORDER BY topic, difficulty")
        if req.method == "POST":
            blueprint = {}
            for i, p in enumerate(pools):
                n = int(req.number(f"n{i}", 0, 0, 500))
                if n:
                    blueprint[(p["topic"], p["difficulty"])] = n
            if not blueprint:
                raise Fail("Choose at least one question")
            seed = int(req.number("seed", 0))
            try:
                chosen = core.choose(bank(), blueprint, seed)
            except core.BlueprintError as exc:
                raise Fail(str(exc)) from None
            papers = core.make_versions(chosen, int(req.number("versions", 2, 1, 8)), seed)
            data = [{"name": p.name, "items": [[i.question.id, i.order] for i in p.items]} for p in papers]
            cur = a.run("INSERT INTO exams (name, papers) VALUES (?, ?)", req.text("name"), json.dumps(data))
            a.log("create exam", req.text("name"))
            return redirect(f"/exam/{cur.lastrowid}")
        fields = [("name", "Exam name"), ("versions", "Paper versions", "number", 2), ("seed", "Seed (keep it to rebuild the same paper)", "number", 1)]
        fields += [(f"n{i}", f"{p['topic']} / {p['difficulty']} (bank has {p['n']})", "number", 0) for i, p in enumerate(pools)]
        return a.page("New exam", card("Blueprint", form(a, "/exam/new", fields, "Build")))

    @a.route("/exam/<id>")
    def exam(req, id):
        e, papers = load(id)
        results = a.rows("SELECT * FROM results WHERE exam = ? ORDER BY score DESC", id)
        total = papers[0].total()
        s = core.score_summary([r["score"] for r in results], total)
        body = stats([("Questions", len(papers[0].items)), ("Total marks", total), ("Learners", s["count"]), ("Mean", round(s.get("mean", 0), 2)), ("Pass rate", f"{s.get('pass_rate', 0):.0%}")])
        body += card("Papers", " · ".join(f'<a href="/exam/{id}/paper/{i}">{h(p.name)}</a> (<a href="/exam/{id}/key/{i}">key</a>)' for i, p in enumerate(papers)))
        body += card("Enter a learner's answers", form(a, f"/exam/{id}/mark", [("learner", "Learner"), ("version", "Version", "select", [(i, p.name) for i, p in enumerate(papers)]), ("responses", "Answers, one letter each, _ for blank (for example ABCD_B)")], "Mark"))
        body += card("Results", table(results, [("Learner", "learner"), ("Score", "score"), ("Version", lambda r: papers[r["version"]].name)], "No results yet.") + f'<p><a href="/exam/{id}/analysis">Item analysis</a></p>')
        return a.page(e["name"], body)

    @a.route("/exam/<id>/paper/<v>")
    def paper(req, id, v):
        e, papers = load(id)
        p = papers[int(v)]
        out = []
        for n, it in enumerate(p.items, 1):
            opts = "".join(f"<li>{h(o)}</li>" for o in it.shown_options())
            out.append(f'<li><p>{h(it.question.stem)} <span class="muted">[{it.question.marks:g}]</span></p><ol type="A">{opts}</ol></li>')
        return a.page(f"{e['name']}: {p.name}", f'<div class="card"><p>Name: ____________________ &nbsp; Total marks: {p.total():g}</p><ol>{"".join(out)}</ol></div>')

    @a.route("/exam/<id>/key/<v>")
    def key(req, id, v):
        e, papers = load(id)
        p = papers[int(v)]
        return a.page(f"{e['name']}: answer key, {p.name}", card("Key", "<p>" + " ".join(f"<b>{i}</b>:{k}" for i, k in enumerate(p.key(), 1)) + "</p>"))

    @a.route("/exam/<id>/mark", ("POST",))
    def mark(req, id):
        e, papers = load(id)
        version = int(req.number("version", 0, 0, len(papers) - 1))
        raw = req.text("responses", limit=2000).upper().replace(" ", "").replace(",", "")
        try:
            score, chosen = core.mark(papers[version], ["" if c == "_" else c for c in raw])
        except ValueError as exc:
            raise Fail(str(exc)) from None
        a.run("INSERT INTO results (exam, learner, version, responses, score) VALUES (?, ?, ?, ?, ?)", id, req.text("learner"), version, json.dumps(chosen), score)
        a.log("mark", f"{id} {req.text('learner')}")
        return redirect(f"/exam/{id}")

    @a.route("/exam/<id>/analysis")
    def analysis(req, id):
        e, papers = load(id)
        rows = a.rows("SELECT * FROM results WHERE exam = ?", id)
        questions = sorted((i.question for i in papers[0].items), key=lambda q: q.id)
        pos = {q.id: j for j, q in enumerate(questions)}
        matrix, choices = [], []
        for r in rows:
            picked = json.loads(r["responses"])
            row, cho = [0] * len(questions), [None] * len(questions)
            for it, c in zip(papers[r["version"]].items, picked):
                j = pos[it.question.id]
                cho[j] = c
                row[j] = int(c == it.question.answer)
            matrix.append(row)
            choices.append(cho)
        if len(matrix) < 2:
            return a.page("Item analysis", card("Not enough results", "<p>Mark at least two learners first.</p>"))
        items = core.item_analysis(matrix, choices, [len(q.options) for q in questions], [q.answer for q in questions])
        rel = core.kr20(matrix)
        totals = [sum(r) for r in matrix]
        summary = stats([("KR-20 reliability", round(rel, 3)), ("Measurement error", round(core.sem(core.variance(totals) ** 0.5, rel), 2))])
        return a.page("Item analysis", summary + card("Items", table(items, [("Question", lambda r: questions[r["item"] - 1].stem[:70]), ("Difficulty", lambda r: round(r["difficulty"], 2)), ("Discrimination", lambda r: round(r["discrimination"], 2)), ("Point-biserial", lambda r: round(r["point_biserial"], 2)), ("Picks by option", lambda r: " ".join(f"{core.LETTERS[i]}:{c}" for i, c in enumerate(r.get("option_counts", [])))), ("Flags", lambda r: Raw(f'<span class="warn">{h("; ".join(r["flags"]))}</span>'))])))

    return a
