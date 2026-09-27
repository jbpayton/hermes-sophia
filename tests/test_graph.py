import pytest
import re
import time

from conftest import facts_of

from hermes_sophia.sleep import SleepRunner


def _night(engine, fake, facts_for):
    def chat(prompt):
        if prompt.startswith("You are indexing"):
            n = len(re.findall(r"^w\d+ \(", prompt, re.M))
            return "\n".join(f"w{i} | ctx {i} | -" for i in range(1, n + 1))
        if prompt.startswith("Extract facts"):
            lines = prompt.split("Lines:\n")[-1]
            out = []
            for m in re.finditer(r"^w(\d+) \((\w+), [^)]*\) (?:CONTEXT: .*?)?TEXT: (.*)$", lines, re.M):
                out += [f"{f} | w{m.group(1)} | asserted | -" for key, f in facts_for if key in m.group(3)]
            return "\n".join(out)
        return "Where does Lily live?"
    fake.chat_fn = chat
    fake.readout = lambda p: [("A", -0.05), ("B", -3.0)]          # judges say no: nothing superseded or dropped
    assert SleepRunner(engine, model="fake-9b", max_wait_s=0).run()["status"] == "complete"


def _chain(engine, fake):
    t = time.time() - 7200
    engine.capture_turn("a", "", "", [{"role": "user", "content": "My friend Sam has a sister named Lily.", "timestamp": t}])
    engine.capture_turn("b", "", "", [{"role": "user", "content": "Lily just moved to Denver for work.", "timestamp": t + 60}])
    engine.capture_turn("c", "", "", [{"role": "user", "content": "Joey here: I'm bringing the Sony camera.", "timestamp": t + 90}])
    _night(engine, fake, [("sister named Lily", "Sam | has sister | Lily"),
                          ("moved to Denver", "Lily | lives in | Denver"),
                          ("Sony camera", "Joey | is bringing | Sony camera")])
    engine.cfg["junk_floor"] = 0.3


def test_one_hop_reaches_a_fact_similarity_cannot(engine, fake):
    _chain(engine, fake)
    q = "Where does Sam's sister live?"
    engine.cfg["graph_hops"] = 0
    flat, _ = engine.recall.candidates(q, k=20)
    assert not any(f["fact"][2] == "Denver" for it in flat for f in facts_of(it))
    engine.cfg["graph_hops"] = 1
    items, info = engine.recall.candidates(q, k=20)
    hit = next(it for it in items if any(f["fact"][2] == "Denver" for f in facts_of(it)))
    assert "Lily" in hit["via"] and info["graph"]["raised_or_added"] >= 1
    assert "linked via Lily" in engine.recall.format([hit], 4000)


def test_graph_raises_a_weak_candidate(engine, fake):
    _chain(engine, fake)
    engine.cfg["junk_floor"] = 0.0                                     # Denver is a (weak) candidate already
    engine.cfg["graph_hops"] = 0
    flat, _ = engine.recall.candidates("Where does Sam's sister live?", k=20)
    before = next(it for it in flat if any(f["fact"][2] == "Denver" for f in facts_of(it)))["score"]
    engine.cfg["graph_hops"] = 1
    items, _ = engine.recall.candidates("Where does Sam's sister live?", k=20)
    hit = next(it for it in items if any(f["fact"][2] == "Denver" for f in facts_of(it)))
    assert hit["score"] > before and "Lily" in hit["via"]


def test_user_is_never_a_graph_hub(engine, fake):
    _chain(engine, fake)
    _, info = engine.recall.candidates("What is Joey bringing when visiting Lily?", k=20)
    assert "Joey" not in info["graph"]["entities"]


def test_conversation_link_brings_the_correction(engine, fake):
    # (a bare "yes" needs no link: its daytime header already carries the question it answers)
    t = time.time() - 3600
    engine.capture_turn("s1", "", "", [{"role": "user", "content": "The dentist is on Main Street.", "timestamp": t}])
    engine.capture_turn("s2", "", "", [{"role": "user", "content": "Actually it moved to Oak Avenue.", "timestamp": t + 60}])
    rows = {r["text"]: r["id"] for r in engine.store.q("SELECT id, text FROM windows")}
    engine.store.x("INSERT INTO links(src,dst,kind,night_id) VALUES(?,?,?,?)",
                   (rows["Actually it moved to Oak Avenue."], rows["The dentist is on Main Street."], "corrects", "n"))
    engine.cfg["junk_floor"] = 0.3
    engine.cfg["graph_hops"] = 0
    flat, _ = engine.recall.candidates("Where is the dentist?", k=20)
    assert rows["Actually it moved to Oak Avenue."] not in {it["id"] for it in flat}
    engine.cfg["graph_hops"] = 1
    items, _ = engine.recall.candidates("Where is the dentist?", k=20)
    fix = next(it for it in items if it["id"] == rows["Actually it moved to Oak Avenue."])
    assert fix["via"] == "corrects a match"          # the added window corrects what matched


def test_inject_order_time_lists_by_date_under_day_headings():
    from hermes_sophia.recall import Recall
    day = 86400.0
    items = [{"kind": "window", "id": str(i), "said": 1_700_000_000 + d * day, "speaker": "Joey", "flags": "",
              "text": t} for i, (d, t) in enumerate([(3, "Third: we adopted a cat."), (1, "First: bought a bike."),
                                                      (2, "Second: tuned the bike.")])]
    rank = Recall.format(items, 9000)
    assert rank.index("Third") < rank.index("First")                  # best first, as given
    by_time = Recall.format(items, 9000, "time")
    assert by_time.index("First") < by_time.index("Second") < by_time.index("Third")
    assert by_time.count("\n2023-") == 3 and "listed by date" in by_time
    assert Recall.format(items[:1], len(rank.splitlines()[0]) + 5, "time") == ""   # nothing fits: nothing at all



def test_advice_requests_put_the_users_own_words_first(engine):
    """Asked for suggestions, the assistant's earlier lines rank advice_penalty lower, and the user's own past
    questions (which describe them) lose their usual penalty; asking what the agent said is not advice mode."""
    t0 = engine.now()
    engine.now_override = t0 - 5 * 86400
    engine.capture_turn("s1", "I prefer winding down by 9:30 pm; what can I do in the evening?",
                        "Some evening activities you could do: evening walks, evening classes, evening concerts.")
    engine.now_override = t0
    q = "Can you suggest some evening activities I can do?"

    def scores():
        items, info = engine.recall.candidates(q, 20)
        by = {("agent" if "assistant" in (it.get("flags") or "") else "user"): it["score"]
              for it in items if it["kind"] == "window"}
        return by, info
    on, info = scores()
    assert info["asks_advice"] and set(on) == {"agent", "user"}
    engine.cfg.update(advice_penalty=0.0, advice_keeps_questions=False)
    off, _ = scores()
    assert abs((off["agent"] - on["agent"]) - 0.06) < 1e-6              # the agent's line: 0.06 lower
    assert on["user"] - off["user"] == pytest.approx(engine.cfg["question_penalty"])   # the user's question: no penalty
    _, info2 = engine.recall.candidates("What evening activities did you suggest to me?", 20)
    assert not info2["asks_advice"] and info2["asks_agent"]

