import json
import re
import time

from conftest import facts_of
from hermes_sophia.sleep import SleepRunner
from hermes_sophia.sleep.runner import parse_context, parse_facts


def test_parsers():
    h, links = parse_context("w1 | Joey plans the Yosemite trip | -\nw2 | Joey agrees to book Curry Village | answers w1\nnoise", 2)
    assert h[2].startswith("Joey agrees") and links == [(2, "answers", 1)]
    f = parse_facts("Joey | is bringing | Fujifilm X-T5 | w1 | planned | second week of May\n"
                    "bad line\nJoey | likes | [implicit] | w9 | asserted | -", 3)
    assert len(f) == 1 and f[0]["modality"] == "planned" and f[0]["when"] == "second week of May"


def _fake_models(fake):
    def chat(prompt):
        if prompt.startswith("You are indexing a conversation"):
            n = len(re.findall(r"^w\d+ \(", prompt, re.M))
            return "\n".join(f"w{i} | context for line {i} about Joey's Yosemite trip | {'answers w1' if i == 2 else '-'}"
                             for i in range(1, n + 1))
        if prompt.startswith("Extract facts"):
            lines = prompt.split("Lines:\n")[-1]
            out = []
            for m in re.finditer(r"^w(\d+) \((\w+), [^)]*\) (?:CONTEXT: .*?)?TEXT: (.*)$", lines, re.M):
                i, text = m.group(1), m.group(3)
                if "Fujifilm" in text:
                    out.append(f"Joey | is bringing camera | Fujifilm X-T5 | w{i} | planned | -")
                if "Sony instead" in text:
                    out.append(f"Joey | is bringing camera | Sony A7 | w{i} | planned | -")
                if "dentist" in text:
                    out.append(f"Joey | has dentist appointment | Dr. Patel | w{i} | planned | yesterday")
            return "\n".join(out)
        if prompt.startswith("Write one short question"):
            return "What camera is Joey bringing?"
        return ""
    fake.chat_fn = chat
    fake.says(True)                                                # teacher says 'true' (replace / used)


def test_night(engine, fake):
    _fake_models(fake)
    t_day = time.time() - 3600
    engine.capture_turn("s1", "", "", [
        {"role": "user", "content": "For Yosemite I'm bringing the Fujifilm X-T5 camera this time.", "timestamp": t_day},
        {"role": "assistant", "content": "Nice choice, it's much lighter than the Sony.", "timestamp": t_day + 5}])
    engine.capture_turn("s2", "", "", [
        {"role": "user", "content": "Change of plans, I'm bringing the Sony instead of the Fujifilm.", "timestamp": t_day + 600},
        {"role": "user", "content": "Also I have a dentist appointment with Dr. Patel yesterday that I forgot.", "timestamp": t_day + 700}])
    engine.prefetch("What camera is Joey bringing to Yosemite?", "s3")
    engine.capture_turn("s3", "What camera is Joey bringing to Yosemite?", "The Sony A7, since plans changed.")

    r = SleepRunner(engine, model="fake-9b", max_wait_s=0)
    out = r.run()
    assert out["status"] == "complete", out
    s = engine.store
    assert s.one("SELECT COUNT(*) AS n FROM windows WHERE header_source='model'")["n"] >= 3
    assert s.one("SELECT COUNT(*) AS n FROM links WHERE kind='answers'")["n"] >= 1
    facts = {f["object"]: f for f in s.q("SELECT * FROM facts")}
    assert facts["Fujifilm X-T5"]["status"] == "superseded"
    assert facts["Sony A7"]["status"] == "active"
    assert facts["Dr. Patel"]["status"] == "unconfirmed"          # planned, date already passed
    assert facts["Dr. Patel"]["importance"] == 1                   # health: exempt from decay
    assert s.one("SELECT COUNT(*) AS n FROM journal WHERE kind='superseded'")["n"] == 1
    assert s.get_meta("last_sleep_ts") >= t_day + 700
    # recall now prefers the current fact
    items, _ = engine.recall.candidates("what camera is Joey bringing", k=5)
    top_fact = next(f for it in items for f in facts_of(it))
    assert top_fact["fact"][2] == "Sony A7"
    # history mode shows the superseded one
    hist, _ = engine.recall.candidates("what camera is Joey bringing", k=10, history=True)
    assert any(f["fact"][2] == "Fujifilm X-T5" for it in hist for f in facts_of(it))
    # the raw window that said Fujifilm is still evidence, but labelled as changed
    txt = engine.recall.format(engine.recall.candidates("Fujifilm X-T5 camera Yosemite", k=10)[0], 4000)
    assert "later changed: Joey is bringing camera Fujifilm X-T5 → Sony A7" in txt
    # replay judged the injection
    assert s.one("SELECT judged FROM injections WHERE session_id='s3'")["judged"] == 1
    # rerun: nothing new to relate
    n_facts = s.one("SELECT COUNT(*) AS n FROM facts")["n"]
    out2 = SleepRunner(engine, model="fake-9b", max_wait_s=0).run()
    assert out2["status"] == "complete"
    assert s.one("SELECT COUNT(*) AS n FROM facts")["n"] == n_facts
    assert out2["stats"]["relate"]["calls"] == 0


def test_yields_when_guarded_model_busy(engine, fake):
    _fake_models(fake)
    engine.capture_turn("s1", "I'm bringing the Fujifilm X-T5.", "Noted.")
    fake.status = {"qwen/qwen3.8-27b": "generating"}
    r = SleepRunner(engine, max_wait_s=0)                            # default sleep model = the guarded 27B
    out = r.run()
    assert out["status"].startswith("yielded")
    assert (engine.store.get_meta("last_sleep_ts", 0) or 0) == 0     # watermark not advanced


def test_same_message_negation_does_not_self_supersede(engine, fake):
    def chat(prompt):
        if prompt.startswith("You are indexing"):
            n = len(re.findall(r"^w\d+ \(", prompt, re.M))
            return "\n".join(f"w{i} | ctx {i} | -" for i in range(1, n + 1))
        if prompt.startswith("Extract facts"):
            lines = prompt.split("Lines:\n")[-1]
            out = []
            for m in re.finditer(r"^w(\d+) \((\w+), [^)]*\) (?:CONTEXT: .*?)?TEXT: (.*)$", lines, re.M):
                i, text = m.group(1), m.group(3)
                if "bringing my Fujifilm" in text:
                    out.append(f"Joey | is bringing | Fujifilm X-T5 | w{i} | planned | -")
                if "instead of the Fujifilm" in text:
                    out.append(f"Joey | is bringing | Sony A7 IV | w{i} | planned | -")
                    out.append(f"Joey | is not bringing | Fujifilm X-T5 | w{i} | planned | -")
            return "\n".join(out)
        return "What camera is Joey bringing?"
    fake.chat_fn = chat
    fake.says(True)
    t = time.time() - 3600
    engine.capture_turn("a", "", "", [{"role": "user", "content": "I'm bringing my Fujifilm X-T5.", "timestamp": t}])
    engine.capture_turn("b", "", "", [{"role": "user", "content": "I'm bringing the Sony A7 IV instead of the Fujifilm.", "timestamp": t + 60}])
    engine.capture_turn("c", "", "", [{"role": "assistant", "content": "Curry Village was founded in 1927.", "timestamp": t + 90}])
    assert SleepRunner(engine, model="fake-9b", max_wait_s=0).run()["status"] == "complete"
    st = {(f["relation"], f["object"]): f["status"] for f in engine.store.q("SELECT relation, object, status FROM facts")}
    assert st[("is bringing", "Sony A7 IV")] == "active"
    assert st[("is bringing", "Fujifilm X-T5")] == "superseded"
    assert st[("is not bringing", "Fujifilm X-T5")] == "active"
    assert not any("1927" in o for (_, o) in st)          # no facts extracted from assistant lines


def test_validation_rules():
    ok = SleepRunner._validate
    assert ok({"subject": "Joey", "relation": "wants to know", "object": "the camera"})[1] == "question, not a fact"
    assert ok({"subject": "Joey", "relation": "is bringing", "object": "[implicit]"})[1] == "placeholder"
    assert ok({"subject": "Joey", "relation": "is bringing", "object": "Sony A7 IV"})[0]
    assert ok({"subject": "Joey", "relation": "is bringing a Fujifilm X-T5 to", "object": "Yosemite"})[1] == "entity inside relation"
    assert ok({"subject": "Joey", "relation": "requested extraction of", "object": "founding date"})[1] == "question, not a fact"
    assert ok({"subject": "Dr. Patel", "relation": "moved his office to", "object": "55 Oak Avenue"})[0]


def test_events_do_not_supersede_each_other(engine, fake):
    photos = {"cup": "a cup with a dog face", "sunset": "a sunset painting"}

    def chat(prompt):
        if prompt.startswith("You are indexing"):
            n = len(re.findall(r"^w\d+ \(", prompt, re.M))
            return "\n".join(f"w{i} | ctx {i} | -" for i in range(1, n + 1))
        if prompt.startswith("Extract facts"):
            out = []
            for m in re.finditer(r"^w(\d+) \(.*?TEXT: (.*)$", prompt.split("Lines:\n")[-1], re.M):
                for key, obj in photos.items():
                    if key in m.group(2):
                        out.append(f"Melanie | shares a photo of | {obj} | w{m.group(1)} | asserted | -")
            return "\n".join(out)
        return "Q?"

    def readout(prompt):                    # "the new one replaces it": yes; "is it an ongoing state": no
        opts = dict(re.findall(r"^([A-Z])\) (.*)$", prompt, re.M))
        want = "false:" if "ongoing state" in prompt else "true:"
        pick = next(l for l, d in opts.items() if d.startswith(want))
        return [(pick, -0.05)] + [(l, -3.0) for l in opts if l != pick]

    fake.chat_fn, fake.readout = chat, readout
    t = time.time() - 3600
    engine.capture_turn("p1", "", "", [{"role": "user", "name": "Melanie", "content": "Look at this cup! [shares a photo: cup]",
                                        "timestamp": t}])
    engine.capture_turn("p2", "", "", [{"role": "user", "name": "Melanie", "content": "My sunset painting. [shares a photo: sunset]",
                                        "timestamp": t + 60}])
    assert SleepRunner(engine, model="fake-9b", max_wait_s=0, steps=["relate", "integrate"]).run()["status"] == "complete"
    st = [f["status"] for f in engine.store.q("SELECT status FROM facts")]
    assert len(st) == 2 and set(st) == {"active"}


def test_parallel_night_is_not_blocked_by_its_own_calls(engine, fake):
    """The night model is also the guarded model (the 27B case): its own in-flight calls must not look like chat."""
    import threading
    inflight = {"n": 0}
    lock = threading.Lock()
    _fake_models(fake)
    base_chat = fake.chat

    def chat(*a, **k):
        with lock:
            inflight["n"] += 1
        try:
            time.sleep(0.05)
            return base_chat(*a, **k)
        finally:
            with lock:
                inflight["n"] -= 1
    fake.chat = chat
    fake.model_status = lambda: {"qwen/qwen3.8-27b": "generating" if inflight["n"] else "idle"}
    for i in range(6):
        engine.capture_turn(f"s{i}", "", "", [{"role": "user", "content": f"For Yosemite I'm bringing the Fujifilm X-T5, day {i}.",
                                               "timestamp": time.time() - 3600 + i}])
    engine.cfg["night_parallel"] = 3
    out = SleepRunner(engine, max_wait_s=0, steps=["contextualize", "relate"]).run()   # guard = the night model
    assert out["status"] == "complete", out
