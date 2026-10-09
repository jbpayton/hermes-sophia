"""What isn't anyone's words to the agent: Hermes's notices, skill text, images, and the agent's own thoughts.
And association: what a cue brings to mind, damped for what came up recently."""
import json

import pytest
import re
import time

from hermes_sophia.recall import Recall
from hermes_sophia.sleep import SleepRunner


def _user_lines(engine, session):
    return engine.store.q("SELECT * FROM windows WHERE session_id=? AND flags NOT LIKE '%assistant%' ORDER BY said, id",
                          (session,))


# ------------------------------------------------------------------ notices
def test_hermes_notices_are_events_not_the_users_words(engine):
    engine.capture.process_messages("n", [
        {"role": "user", "content": "Run the backup in the background."},
        {"role": "assistant", "content": "Started it."},
        {"role": "user", "content": "[IMPORTANT: Background process proc_7 completed (exit 0). Output: backup done, "
                                    "412 files copied]"},
        {"role": "assistant", "content": "The backup finished: 412 files copied."},
        {"role": "user", "content": "[ASYNC DELEGATION COMPLETE — d1] The research task found three sources."},
        {"role": "assistant", "content": "The research came back."}])
    rows = {r["text"][:14]: r for r in _user_lines(engine, "n")}
    assert rows["Run the backup"]["speaker"] == "Joey" and rows["Run the backup"]["stream"] == "conversation"
    for key in ("[IMPORTANT: Ba", "[ASYNC DELEGAT"):
        assert rows[key]["speaker"] == "system" and rows[key]["stream"] == "event" and "event" in rows[key]["flags"]
    item = {"kind": "window", "id": "x", "said": time.time(), "speaker": "system", "flags": "event",
            "text": "Background process proc_7 completed", "ref": "r"}
    assert "(system notice)" in Recall.format([item], 9000)


def test_a_skill_turn_keeps_only_what_the_user_typed(engine):
    skill = ('[IMPORTANT: The user has invoked the "work" skill, indicating they want you to follow its instructions. '
             'The full skill content is loaded below.]\n\n# Work\nAlways run the tests before committing.\n\n'
             'The user has provided the following instruction alongside the skill invocation: fix the title leak')
    engine.capture.process_messages("k", [{"role": "user", "content": skill}, {"role": "assistant", "content": "On it."}])
    lines = _user_lines(engine, "k")
    assert [r["text"] for r in lines] == ["/work fix the title leak"] and lines[0]["speaker"] == "Joey"
    assert not engine.store.q("SELECT 1 FROM windows WHERE text LIKE '%run the tests before committing%'")


# ------------------------------------------------------------------- images
def test_an_image_is_kept_after_hermes_deletes_its_copy(engine, tmp_path):
    cached = tmp_path / "cache" / "img_9f2.png"
    cached.parent.mkdir()
    cached.write_bytes(b"\x89PNG\r\n\x1a\n fake image bytes")
    engine.capture.process_messages("i", [
        {"role": "user", "content": [{"type": "text", "text": f"Look at my workout\n\n[Image attached at: {cached}]"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
        {"role": "assistant", "content": "Nice session!"}])
    img = engine.store.one("SELECT * FROM images")
    line = _user_lines(engine, "i")[0]
    assert line["text"] == f"Look at my workout\n[image {img['id'][:8]}]" and "image" in line["flags"]
    cached.unlink()                                                   # Hermes prunes its cache after a day
    kept = engine.store.path.parent / "images" / img["file"]
    assert kept.read_bytes().endswith(b"fake image bytes") and img["source"] == str(cached)


def test_a_vision_description_is_a_labelled_caption_not_the_users_words(engine, tmp_path):
    cached = tmp_path / "img_tread.jpg"
    cached.write_bytes(b"\xff\xd8 treadmill photo")
    text = ("[The user sent an image~ Here's what I can see:\nA treadmill display showing 40:00 and 312 kcal.]\n"
            f"[If you need a closer look, use vision_analyze with image_url: {cached} ~]\n\nDone for today")
    engine.capture.process_messages("v", [{"role": "user", "content": text}, {"role": "assistant", "content": "Great!"}])
    img = engine.store.one("SELECT * FROM images")
    line = _user_lines(engine, "v")[0]
    assert line["text"] == f"Done for today\n[image {img['id'][:8]}]" and "treadmill" not in line["text"]
    cap = engine.store.one("SELECT * FROM windows WHERE stream='caption'")
    assert cap["speaker"] == "vision" and "312 kcal" in cap["text"] and "caption" in cap["flags"]
    assert "312 kcal" in img["caption"] and img["caption_by"].startswith("vision model")
    item = {"kind": "window", "id": cap["id"], "said": cap["said"], "speaker": "vision", "flags": cap["flags"],
            "text": cap["text"], "ref": cap["ref"]}
    assert "written by a vision model" in Recall.format([item], 9000)


def test_images_can_be_left_out(engine, tmp_path):
    engine.cfg["keep_images"] = False
    cached = tmp_path / "img.png"
    cached.write_bytes(b"png")
    engine.capture.process_messages("o", [{"role": "user", "content": f"See this\n[Image attached at: {cached}]"},
                                          {"role": "assistant", "content": "Seen."}])
    img = engine.store.one("SELECT * FROM images")
    assert img["file"] is None and not (engine.store.path.parent / "images").exists()


# ----------------------------------------------------------------- thoughts
def test_thoughts_are_labelled_and_never_become_facts(engine, fake):
    engine.capture.process_messages("t", [
        {"role": "user", "content": "My camera sensor keeps acting up on hot days.", "timestamp": time.time() - 7200},
        {"role": "assistant", "content": "That sounds frustrating."}])
    line = _user_lines(engine, "t")[0]
    out = json.loads(engine.tools.dispatch("sophia_thought", {
        "thought": "Maybe Joey's camera problem is heat. Joey should try a cooling grip.", "about": line["id"]}))
    th = engine.store.one("SELECT * FROM windows WHERE id=?", (out["ids"][0],))
    assert th["stream"] == "thought" and "thought" in th["flags"] and th["speaker"] == engine.cfg["agent_name"]
    assert engine.store.one("SELECT kind FROM links WHERE src=? AND dst=?", (th["id"], line["id"]))["kind"] == "about"

    def chat(prompt):                                  # the extractor would happily read a fact from every line
        if not prompt.startswith("Extract facts"):
            return "Q?"
        return "\n".join(f"Joey | mentioned | line {m.group(1)} | w{m.group(1)} | asserted | -"
                         for m in re.finditer(r"^w(\d+) \(", prompt.split("Lines:\n")[-1], re.M))
    fake.chat_fn = chat
    assert SleepRunner(engine, model="fake-9b", max_wait_s=0, steps=["relate"]).run()["status"] == "complete"
    sources = {r["window_id"] for r in engine.store.q("SELECT window_id FROM fact_sources")}
    assert line["id"] in sources and th["id"] not in sources

    items, _ = engine.recall.candidates("camera heat cooling grip", k=10)
    mine = next(it for it in items if it["id"] == th["id"])
    assert "own earlier thought, not an observation" in Recall.format([mine], 9000)
    engine.cfg["inject_thoughts"] = False
    items, _ = engine.recall.candidates("camera heat cooling grip", k=10, thoughts=False)
    assert th["id"] not in {it["id"] for it in items}


def test_a_thought_needs_words(engine):
    assert "error" in json.loads(engine.tools.dispatch("sophia_thought", {"thought": "  "}))


# -------------------------------------------------------------- association
def _seed(engine):
    t = time.time() - 86400
    for i, text in enumerate(["I bought a Fujifilm X-T5 camera for the Yosemite trip.",
                              "The camera strap broke on the hike to Half Dome.",
                              "Sam is coming to Yosemite with me in May.",
                              "I need new hiking boots before the trip.",
                              "My sister Lily lives in Denver."]):
        engine.capture.process_messages(f"a{i}", [{"role": "user", "content": text, "timestamp": t + i * 60}])


def test_association_damps_what_came_up_recently_and_it_recovers(engine):
    _seed(engine)
    now = time.time()
    first, _ = engine.recall.associate("camera", k=3, now=now)
    top = first[0]
    assert top["habituation"] == 0 and "camera" in top["text"].lower()
    again, info = engine.recall.associate("camera", k=3, now=now + 600)
    same = next(it for it in again if it["id"] == top["id"])
    assert same["habituation"] > 0.5 and same["activation"] < top["activation"] and info["damped"] >= 1
    later, _ = engine.recall.associate("camera", k=3, now=now + 3 * 86400, record=False)
    back = next(it for it in later if it["id"] == top["id"])
    assert back["habituation"] < 0.01 and abs(back["activation"] - top["activation"]) < 1e-6


def test_a_conversation_doesnt_come_back_one_piece_at_a_time(engine):
    # live, 2026-10-04: Sophia noticed association raising yesterday's design conversation fragment by fragment
    t = time.time() - 86400
    engine.capture.process_messages("design", [
        {"role": "user", "content": "The outreach score counts a reply within twelve hours.", "timestamp": t},
        {"role": "user", "content": "A held message is about Joey's life, not about memory.", "timestamp": t + 60},
        {"role": "user", "content": "Every goal change needs a reason in the journal.", "timestamp": t + 120},
        {"role": "user", "content": "Much later the outreach journal got a new column.", "timestamp": t + 6 * 3600}])
    engine.capture.process_messages("other", [
        {"role": "user", "content": "The garden journal needs a reason for every change too.", "timestamp": t + 90}])
    lines = {r["text"][:12]: r["id"] for r in engine.store.q("SELECT id, text FROM windows")}
    now = time.time()
    engine.store.xmany("INSERT INTO activations(item_id,item_kind,ts,cue) VALUES(?,?,?,?)",
                       [(lines["The outreach"], "window", now - 60, "c")])
    items = [{"kind": "window", "id": i} for i in lines.values()]
    h = engine.recall.conversation_habituation(items, now)
    assert h.get(lines["A held messa"], 0) > 0.9 and h.get(lines["Every goal c"], 0) > 0.9   # same conversation
    assert lines["The outreach"] not in h                      # its own raising is ordinary habituation
    assert lines["Much later t"] not in h and lines["The garden j"] not in h   # later in the session; another one
    out, _ = engine.recall.associate("a reason for every goal change in the journal", k=5, now=now, record=False)
    damped = {it["id"]: it["habituation"] for it in out}
    assert damped.get(lines["Every goal c"], 0) > 0.4 and damped.get(lines["The garden j"], 1) == 0


def test_what_the_live_conversation_just_said_never_comes_to_mind_even_once_compacted(engine):
    # live, 2026-10-05: compaction flagged Joey's 09:53 message as compacted, and it came to mind at 10:00
    now = time.time()
    engine.capture.process_messages("live", [
        {"role": "user", "content": "The Quest 3 is a client of a shared server room.", "timestamp": now - 300},
        {"role": "user", "content": "Last month the Quest 3 arrived in the mail.", "timestamp": now - 30 * 86400}])
    engine.store.x("UPDATE windows SET flags = COALESCE(flags,'') || ' compacted' WHERE session_id='live'")
    out, _ = engine.recall.associate("Quest 3 headset", k=5, session_id="live", now=now, record=False)
    texts = [it["text"] for it in out]
    assert not any("shared server room" in t for t in texts)          # minutes old: still working memory
    assert any("arrived in the mail" in t for t in texts)             # a month old: that can come to mind
    other, _ = engine.recall.associate("Quest 3 headset", k=5, session_id="elsewhere", now=now, record=False)
    assert any("shared server room" in it["text"] for it in other)    # from another conversation it can


def test_a_compaction_summary_is_never_kept_in_either_role(engine):
    # live, 2026-10-08: Hermes put a compaction handoff in the assistant role; it was kept as Sophia's words and came
    # back to mind in pieces
    summary = ("[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below.\n\n"
               "Treat ONLY the latest message as the active task and discard stale items.")
    engine.capture.process_messages("cmp", [
        {"role": "user", "content": "The Quest 3 arrived today."},
        {"role": "assistant", "content": summary},
        {"role": "user", "content": summary},
        {"role": "assistant", "content": "Lovely, the headset is here."}])
    texts = [r["text"] for r in engine.store.q("SELECT text FROM windows WHERE session_id='cmp'")]
    assert any("Quest 3 arrived" in t for t in texts) and any("headset is here" in t for t in texts)
    assert not any("COMPACTION" in t or "Treat ONLY" in t for t in texts)


def test_its_own_replies_pull_less_and_finished_work_stays_out_of_association(engine):
    # live, 2026-10-04 to 10-09: 86% of its own replies that came to mind were let go as echoes; task cards replayed
    t = time.time() - 86400
    engine.capture.process_messages("own", [
        {"role": "user", "content": "The lantern festival is on Saturday by the river.", "timestamp": t},
        {"role": "assistant", "content": "The lantern festival on Saturday by the river sounds lovely.", "timestamp": t + 5}])
    engine.cfg["associate_band"] = 1.0                 # this test is about the weight, not which lines are in band
    engine.cfg["associate_own_weight"] = 1.0
    even, _ = engine.recall.associate("lantern festival by the river", k=4, record=False)
    engine.cfg["associate_own_weight"] = 0.5
    weighed, _ = engine.recall.associate("lantern festival by the river", k=4, record=False)
    own = lambda items: next(it for it in items if "sounds lovely" in it["text"])
    heard = lambda items: next(it for it in items if "is on Saturday" in it["text"])
    assert abs(own(weighed)["activation"] - 0.5 * own(even)["activation"]) < 1e-6
    assert heard(weighed)["activation"] == heard(even)["activation"]
    assert weighed[0]["text"].startswith("The lantern festival is on Saturday")
    card = {"kind": "task", "id": "t1", "score": 0.9, "sim": 0.9, "text": "Plan the lantern festival — succeeded",
            "ref": "t1"}
    orig = engine.recall.candidates
    engine.recall.candidates = lambda *a, **kw: ([card] + orig(*a, **kw)[0], {})
    assert not any(it["kind"] == "task" for it in engine.recall.associate("lantern festival", k=4, record=False)[0])
    engine.cfg["associate_tasks"] = True
    assert any(it["kind"] == "task" for it in engine.recall.associate("lantern festival", k=4, record=False)[0])


def test_a_thought_just_kept_doesnt_come_straight_back(engine):
    # Sophia's review, 2026-10-09: a kept thought came back six minutes after she kept it, recently_raised 0.0
    now = time.time()
    ids = engine.capture.think("The lantern festival might be worth a visit with Sam.", now=now - 360)
    out, _ = engine.recall.associate("lantern festival visit", k=4, now=now, record=False)
    it = next(x for x in out if x["id"] in ids)
    assert it["habituation"] > 0.9                    # kept six minutes ago: damped like anything just raised
    later, _ = engine.recall.associate("lantern festival visit", k=4, now=now + 3 * 86400, record=False)
    assert next(x for x in later if x["id"] in ids)["habituation"] < 0.01      # and it recovers


def test_association_skips_what_the_caller_already_holds(engine):
    _seed(engine)
    first, _ = engine.recall.associate("Yosemite", k=5, record=False)
    held = first[0]["id"]
    rest, _ = engine.recall.associate("Yosemite", k=5, record=False, exclude=[held])
    assert held not in {it["id"] for it in rest}


def test_the_associate_tool(engine):
    _seed(engine)
    out = json.loads(engine.tools.dispatch("sophia_associate", {"cue": "hiking", "limit": 3}))
    assert out["items"] and all("pull" in it for it in out["items"]) and len(out["items"]) <= 3
    assert "error" in json.loads(engine.tools.dispatch("sophia_associate", {"cue": ""}))


# ---------------------------------------------------- notices stored by older versions
def test_old_notices_can_be_relabelled_and_undone(engine):
    engine.store.add_windows([{"id": "w1", "ref": "hermes:s:abc", "session_id": "s", "speaker": "Joey",
                               "said": time.time(), "text": "[IMPORTANT: Background process p1 completed (exit 0)]",
                               "index_text": "x", "flags": "", "stream": "conversation", "spans": []}], None, "m")
    assert engine.store.mark_events(["w1"], "a notice", by="test") == 1
    w = engine.store.one("SELECT speaker, stream, flags FROM windows WHERE id='w1'")
    assert (w["speaker"], w["stream"], w["flags"]) == ("system", "event", "event")
    jid = engine.store.one("SELECT id FROM journal WHERE kind='marked_as_event'")["id"]
    assert engine.store.undo_journal(jid)
    w = engine.store.one("SELECT speaker, stream, flags FROM windows WHERE id='w1'")
    assert (w["speaker"], w["stream"], w["flags"]) == ("Joey", "conversation", "")


def test_damping_reorders_what_is_relevant_and_never_lets_the_unrelated_in(engine):
    _seed(engine)
    now = time.time()
    first, _ = engine.recall.associate("camera", k=8, now=now)
    again, _ = engine.recall.associate("camera", k=8, now=now + 60)
    assert {it["id"] for it in again} <= {it["id"] for it in first}
    assert not any("Lily" in it["text"] for it in again)


def test_association_puts_the_current_version_first_and_skips_bare_replies(engine):
    _seed(engine)
    engine.capture.process_messages("q", [
        {"role": "assistant", "content": "Should I book the Curry Village cabin for you?"},
        {"role": "user", "content": "yes"}])
    items, _ = engine.recall.associate("camera", k=8, record=False)
    top = next(it for it in items if "camera" in it["text"].lower())
    stale = dict(top, changed=["Joey is bringing Fujifilm X-T5 → Sony A7 IV (2026-09-23)"])
    import hermes_sophia.recall as R
    orig = R.Recall.candidates
    R.Recall.candidates = lambda self, *a, **k: ([dict(it) for it in [stale]], {})
    try:
        damped, _ = engine.recall.associate("camera", k=8, record=False)
    finally:
        R.Recall.candidates = orig
    assert damped[0]["activation"] == pytest.approx(top["score"] * 0.5)
    yes, _ = engine.recall.associate("yes", k=8, record=False)
    assert not any(it["text"].strip().lower() == "yes" for it in yes)
