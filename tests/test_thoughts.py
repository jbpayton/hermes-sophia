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
