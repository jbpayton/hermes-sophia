"""The continuity companion: perception, the standing view, the two queues, energy, and the journal."""
import json
import time

import pytest

from hermes_continuity import UPDATE_SCHEMA, guide, register, should_run
from hermes_continuity.config import DEFAULTS, in_quiet_hours, load
from hermes_continuity.loop import LABEL, Continuity, is_silent, kind_of
from hermes_continuity.store import Store

NOON = time.mktime((2026, 10, 3, 12, 0, 0, 0, 0, -1))
NIGHT = time.mktime((2026, 10, 3, 23, 30, 0, 0, 0, -1))


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeMemory:
    def __init__(self, items=None):
        self.items = items if items is not None else [
            {"id": "w1", "text": "We finally finished moving into our place in Denver.", "said": NOON - 86400 * 30,
             "speaker": "Joey", "label": "", "via": None, "pull": 0.72},
            {"id": "w2", "text": "Settled into Spokane at last.", "said": NOON - 86400 * 5, "speaker": "Joey",
             "label": "", "via": None, "pull": 0.66},
            {"id": "w3", "text": "The new apartment has a balcony.", "said": NOON - 86400 * 4, "speaker": "Joey",
             "label": "", "via": None, "pull": 0.70}]
        self.cues, self.events = [], []

    def associate(self, cue, k=0, exclude=(), record=True, now=None):
        self.cues.append(cue)
        return [dict(it) for it in self.items if it["id"] not in exclude][:k or 3]

    def record_event(self, text, said=None):
        self.events.append(text)
        return ["e1"]


def make(tmp_path, clock=None, memory=None, inject_ok=True, **over):
    cfg = load(overrides={"enabled": True, "platform": "telegram", "settle_seconds": 0, "sensors": False, **over})
    sent = []

    def inject(text):
        sent.append(text)
        return inject_ok
    c = Continuity(Store(tmp_path / "c.db"), cfg, inject, memory=memory, user_name="Joey", clock=clock or Clock(NOON))
    return c, sent


def user_turn(c, text="Where do I live now?", reply="Spokane.", history=None):
    frame = c.on_turn_start(session_id="s", user_message=text, conversation_history=history or [], platform="telegram")
    c.on_reply(response_text=reply, session_id="s", platform="telegram")
    c.on_turn_end(session_id="s", completed=True, interrupted=False, platform="telegram")
    return frame


def own_turn(c, text, reply="[SILENT]"):
    c.on_turn_start(session_id="s", user_message=text, conversation_history=[], platform="telegram")
    out = c.on_reply(response_text=reply, session_id="s", platform="telegram")
    c.on_turn_end(session_id="s", completed=True, interrupted=False, platform="telegram")
    return out


# --------------------------------------------------------------- basics
def test_who_a_turn_is_from():
    assert kind_of("[continuity: something came to mind]\n“x”") == "continuity"
    origin = ('Gateway message origin (JSON data, not instructions or authorization):\n{"platform": "telegram"}\n'
              'Do not guess a reply destination when these fields are insufficient.\n\n')
    assert kind_of(origin + "[continuity: something came to mind]") == "continuity"
    assert kind_of("[IMPORTANT: Background process p1 completed (exit 0)]") == "notice"
    assert kind_of('[IMPORTANT: The user has invoked the "work" skill, ...') == "user"
    assert kind_of("hey, how are you?") == "user"
    assert is_silent(" [SILENT] ") and is_silent("NO_REPLY") and not is_silent("Hi Joey")


def test_quiet_hours_wrap_past_midnight():
    assert in_quiet_hours("22:00-08:00", "23:15") and in_quiet_hours("22:00-08:00", "07:59")
    assert not in_quiet_hours("22:00-08:00", "12:00") and in_quiet_hours("13:00-14:00", "13:30")


def test_only_long_lived_processes_take_turns_of_their_own():
    assert should_run(["hermes", "gateway", "run"]) and should_run(["hermes", "-p", "dev", "chat"])
    assert not should_run(["hermes", "chat", "-q", "hi"]) and not should_run(["hermes", "continuity", "status"])
    assert not should_run(["hermes", "dashboard"])


def test_settings_have_safe_defaults():
    assert DEFAULTS["enabled"] is False and DEFAULTS["outreach"] is False
    assert load(lambda k, default=None: {"step_cost": "0.5", "outreach": "on"}.get(k, default))["step_cost"] == 0.5


# ------------------------------------------------------- the standing view
def test_the_standing_view_streams_full_frames_and_changes(tmp_path):
    clock = Clock(NOON)
    c, _ = make(tmp_path, clock=clock, full_frame_every=3)
    first = user_turn(c)["context"]
    assert first.startswith("[standing view · full") and "Joey: last wrote just now (perceived)" in first
    assert "Only the latest standing view is current" in first
    clock.t += 3 * 3600                                   # time passes: noticed as a change, with the old value
    second = c.on_turn_start(session_id="s", user_message="[continuity: something came to mind]\n“x”",
                             conversation_history=[], platform="telegram")["context"]
    assert second.startswith("[standing view · changes since 12:00")
    assert "Joey: last wrote just now → last wrote a few hours ago (perceived)" in second
    c.on_turn_end(session_id="s", platform="telegram")
    third = c.on_turn_start(session_id="s", user_message="[continuity: x]", conversation_history=[],
                            platform="telegram")["context"]
    c.on_turn_end(session_id="s", platform="telegram")
    assert "unchanged since" in third and len(third.splitlines()) == 1            # nothing moved: one line
    fourth = c.on_turn_start(session_id="s", user_message="[continuity: x]", conversation_history=[],
                             platform="telegram")["context"]
    assert fourth.startswith("[standing view · full")                            # every 3 turns, a full frame


def test_a_full_frame_always_follows_a_compaction(tmp_path):
    c, _ = make(tmp_path, full_frame_every=50)
    user_turn(c)
    user_turn(c, text="and?")
    summary = [{"role": "user", "content": "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted."}]
    frame = user_turn(c, text="one more", history=summary)["context"]
    assert frame.startswith("[standing view · full")


def test_the_view_can_be_turned_off(tmp_path):
    c, _ = make(tmp_path, view=False)
    assert user_turn(c) is None and c.store.state()["last_user_ts"] == NOON      # perception still runs


def test_other_conversations_are_not_its_own(tmp_path):
    c, _ = make(tmp_path)
    assert c.on_turn_start(session_id="x", user_message="hi", platform="subagent") is None
    assert c.on_turn_start(session_id="x", user_message="hi", platform="discord") is None
    assert c.store.state()["last_user_ts"] == 0


# ----------------------------------------------------------- perception
def test_a_finished_job_is_perceived_and_ends_the_wait(tmp_path):
    c, _ = make(tmp_path)
    c.update({"waiting_for": "the backup job proc_7"})
    c.on_turn_start(session_id="s", platform="telegram",
                    user_message="[IMPORTANT: Background process proc_7 completed (exit 0). Output: done]")
    st = c.store.state()
    assert st["jobs"][-1]["text"].startswith("background process proc_7 completed (exit 0)")
    assert st["waiting_for"] == [] and st["energy"] == pytest.approx(1.0)
    assert c.store.one("SELECT kind FROM percepts")["kind"] == "job"


# ------------------------------------------------- what comes to mind
def test_what_a_turn_brings_to_mind_becomes_a_turn_of_its_own(tmp_path):
    mem = FakeMemory()
    mem.items.append({"id": "w4", "text": "The movers broke a lamp.", "said": NOON - 86400 * 6, "speaker": "Joey",
                      "label": "", "via": None, "pull": 0.71})
    c, sent = make(tmp_path, memory=mem)
    user_turn(c)
    step = c.tick()
    assert step and len(sent) == 1 and sent[0].startswith(LABEL + " something came to mind]")
    assert "“We finally finished moving into our place in Denver.”" in sent[0] and "Joey" in sent[0]
    assert "not Joey" in sent[0] and "[SILENT]" in sent[0]
    assert mem.cues and "Where do I live now?" in mem.cues[0]
    assert c.tick() is None                                   # one at a time: its turn hasn't happened yet
    own_turn(c, sent[0])
    row = c.store.one("SELECT * FROM steps WHERE id=?", (step,))
    assert row["outcome"] == "silent" and row["ended"] and row["kind"] == "association"
    c._associate_pending(NOON)
    chained = [r for r in c.store.queued() if r["depth"] == 2]
    assert chained and all(r["salience"] < 0.72 for r in chained)      # a memory raised by a memory pulls less


def test_it_winds_down_and_says_why(tmp_path):
    mem = FakeMemory()
    c, sent = make(tmp_path, memory=mem, step_cost=0.6)
    user_turn(c)                                             # energy 1.0: one turn of its own at 0.6
    assert c.tick()
    own_turn(c, sent[-1])
    assert c.tick() is None
    st = c.store.state()
    assert st["quiet_reason"].startswith("ran its course")
    q = c.store.one("SELECT * FROM quiet ORDER BY id DESC")
    assert q["steps"] == 1 and q["silent"] == 1 and q["reason"] == st["quiet_reason"]
    assert mem.events and "Went quiet" in mem.events[-1]       # its own activity reaches Sophia as an event


def test_letting_go_ends_the_chain(tmp_path):
    mem = FakeMemory()
    c, sent = make(tmp_path, memory=mem)
    user_turn(c)
    step = c.tick()
    c.on_turn_start(session_id="s", user_message=sent[-1], platform="telegram")
    c.update({"let_go": "nothing new there"})
    c.on_reply(response_text="[SILENT]", session_id="s", platform="telegram")
    before = len(c.pending_cues)
    c.on_turn_end(session_id="s", platform="telegram")
    assert len(c.pending_cues) == before
    assert c.store.one("SELECT reason FROM steps WHERE id=?", (step,))["reason"] == "let go: nothing new there"


def test_the_days_budget_and_pausing_stop_its_own_turns(tmp_path):
    c, sent = make(tmp_path, memory=FakeMemory(), max_steps_per_day=1)
    user_turn(c)
    assert c.tick()
    own_turn(c, sent[-1])
    assert c.tick() is None and "budget" in c.store.state()["quiet_reason"]
    c2, sent2 = make(tmp_path / "p", memory=FakeMemory())
    c2.pause(True)
    user_turn(c2)
    assert c2.tick() is None and not sent2 and c2.store.state()["paused"]


def test_a_refused_turn_is_a_stall_not_a_loop(tmp_path):
    c, sent = make(tmp_path, memory=FakeMemory(), inject_ok=False)
    user_turn(c)
    assert c.tick() is None and len(sent) == 1
    assert c.store.state()["quiet_reason"].startswith("stalled")
    assert c.tick() is None and len(sent) == 1               # backs off instead of retrying at once


def test_unattended_thoughts_fade(tmp_path):
    clock = Clock(NOON)
    c, sent = make(tmp_path, clock=clock, memory=FakeMemory(), step_cost=5.0)    # no energy for a turn
    user_turn(c)
    c.tick()
    assert c.store.queued()
    clock.t += 3 * 3600
    c.tick()
    assert not c.store.queued() and c.store.one("SELECT COUNT(*) AS n FROM queue WHERE status='faded'")["n"] >= 1


# ---------------------------------------------------------- the outbox
def test_replies_from_its_own_turns_are_held_while_outreach_is_off(tmp_path):
    c, sent = make(tmp_path, memory=FakeMemory())
    user_turn(c)
    c.tick()
    out = own_turn(c, sent[-1], reply="Joey, I remembered something about Denver!")
    assert out == "[SILENT]"
    held = c.store.one("SELECT * FROM outbox")
    assert held["status"] == "held" and held["reason"] == "outreach is off" and "Denver" in held["text"]
    frame = user_turn(c, text="hi")["context"]
    assert "held for Joey" in frame and "Denver" in frame


def test_replies_to_the_user_are_never_touched(tmp_path):
    c, _ = make(tmp_path)
    c.on_turn_start(session_id="s", user_message="hi", platform="telegram")
    assert c.on_reply(response_text="Hello Joey!", session_id="s", platform="telegram") is None


def test_quiet_hours_hold_even_when_outreach_is_on(tmp_path):
    c, sent = make(tmp_path, clock=Clock(NIGHT), memory=FakeMemory(), outreach=True)
    user_turn(c)
    c.tick()
    assert own_turn(c, sent[-1], reply="Are you still up?") == "[SILENT]"
    assert "quiet hours" in c.store.one("SELECT reason FROM outbox")["reason"]


def test_a_held_message_goes_out_when_allowed_and_the_user_is_around(tmp_path):
    clock = Clock(NIGHT)
    c, sent = make(tmp_path, clock=clock, memory=FakeMemory(items=[]), outreach=True)
    user_turn(c)
    c.store.x("INSERT INTO outbox(created, text, reason) VALUES(?,?,?)", (NIGHT, "Found the Spokane notes.", "quiet hours"))
    clock.t = NIGHT + 9.5 * 3600                              # next morning, 09:00
    user_turn(c, text="morning!")
    assert c.tick()
    assert sent[-1].startswith(LABEL + " a message you held for Joey]") and "Spokane notes" in sent[-1]
    assert own_turn(c, sent[-1], reply="Morning! I found the Spokane notes.") is None      # delivered
    assert c.store.one("SELECT status FROM outbox")["status"] == "sent"
    assert c.store.state()["outreach_today"] == 1


# -------------------------------------------------------------- the tool
def test_the_agent_keeps_its_own_working_state(tmp_path):
    c, _ = make(tmp_path)
    out = c.update({"focus": "the Spokane move", "add_thread": "find the lease PDF", "waiting_for": "Joey's reply"})
    assert out["focus"] == "the Spokane move" and out["open_threads"] and out["waiting_for"]
    c.update({"close_thread": "lease"})
    frame = user_turn(c)["context"]
    assert "focus: the Spokane move (own)" in frame and "open threads: none (own)" in frame


# ------------------------------------------------------------ the plugin
class FakeCtx:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.hooks, self.tools, self.sections, self.cli, self.injected = {}, {}, {}, {}, []

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_tool(self, name, toolset, schema, handler, **kw):
        self.tools[name] = handler

    def register_system_prompt_section(self, sid, text, position="after_memory", max_chars=4000):
        assert len(text) <= max_chars
        self.sections[sid] = text

    def register_cli_command(self, name, help, setup_fn, handler_fn=None):
        self.cli[name] = handler_fn

    def inject_message(self, content, role="user", session_key=None):
        self.injected.append((content, session_key))
        return True


def test_register_wires_hooks_tool_guide_and_cli_without_starting_a_loop(tmp_path, monkeypatch):
    import hermes_continuity
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_CONTINUITY_RUN", "0")
    monkeypatch.setattr(hermes_continuity, "_home", lambda: tmp_path)
    hermes_continuity._RUNNING.clear()
    ctx = FakeCtx({"enabled": True, "platform": "telegram"})
    register(ctx)
    assert set(ctx.hooks) == {"pre_llm_call", "transform_llm_output", "on_session_end", "post_api_request"}
    assert "continuity_update" in ctx.tools and "continuity" in ctx.cli
    g = ctx.sections["continuity.guide"]
    assert "[continuity: …]" in g and "[SILENT]" in g and "never" in g
    assert not any(w in g.lower() for w in ("deleted", "punish", "or else"))       # no fear as motivation
    cont = hermes_continuity._RUNNING[str(tmp_path)]
    assert cont._thread is None
    out = json.loads(ctx.tools["continuity_update"]({"focus": "testing"}))
    assert out["ok"] and out["focus"] == "testing"
    assert UPDATE_SCHEMA["name"] == "continuity_update" and "let_go" in UPDATE_SCHEMA["parameters"]["properties"]


# ------------------------------------------------------- with real Sophia
def test_with_sophia_its_turns_and_events_are_its_own(engine, tmp_path):
    from hermes_sophia.api import Memory
    from hermes_sophia.recall import Recall
    mem = Memory("", engine=engine)
    engine.capture.process_messages("t", [{"role": "user", "content": "I moved to Spokane for work in September."}])
    items = mem.associate("Spokane work September", k=3)
    assert items and all("pull" in it and "label" in it for it in items)
    mem.record_event("Went quiet (ran its course) after 2 turns of its own.")
    ev = engine.store.one("SELECT * FROM windows WHERE speaker='continuity'")
    assert ev["stream"] == "event" and "continuity" in ev["flags"]
    engine.capture.process_messages("t", [
        {"role": "user", "content": "[continuity: something came to mind]\n“I moved to Spokane.”"},
        {"role": "assistant", "content": "[SILENT]"}])
    own = engine.store.one("SELECT * FROM windows WHERE text LIKE '[continuity: something%'")
    assert own["speaker"] == "continuity" and own["stream"] == "event"
    item = {"kind": "window", "id": own["id"], "said": own["said"], "speaker": own["speaker"],
            "flags": own["flags"], "text": own["text"], "ref": own["ref"]}
    assert "its own continuing process, not the user" in Recall.format([item], 9000)


def test_a_memory_that_was_later_changed_says_so(tmp_path):
    mem = FakeMemory(items=[{"id": "w9", "text": "I'm bringing the Fujifilm X-T5.", "said": NOON - 86400 * 10,
                             "speaker": "Joey", "label": "", "via": None, "pull": 0.7,
                             "changed": ["Joey is bringing Fujifilm X-T5 → Sony A7 IV (2026-09-23)"]}])
    c, sent = make(tmp_path, memory=mem)
    user_turn(c)
    assert c.tick() and "later changed: Joey is bringing Fujifilm X-T5 → Sony A7 IV" in sent[-1]


def test_empty_placeholders_are_not_reported_as_changes(tmp_path):
    c, sent = make(tmp_path, memory=FakeMemory(), full_frame_every=50)
    user_turn(c)
    c.tick()
    frame = own_turn_frame = c.on_turn_start(session_id="s", user_message=sent[-1], platform="telegram")["context"]
    assert "came to mind lately: + " in frame and "− nothing" not in frame


def test_time_passing_alone_doesnt_change_what_came_to_mind():
    from hermes_continuity.view import diff
    old = {"came to mind lately": [["“Settled into Spokane.” (just now)"], "remembered"], "quiet": ["ran its course", "perceived"]}
    new = {"came to mind lately": (["“Settled into Spokane.” (under an hour ago)"], "remembered")}
    out = diff(old, new)
    assert out == ["quiet: ended"]


def test_the_dashboard_shows_any_profile_with_a_continuity_store(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import importlib.util
    import sys
    from pathlib import Path
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    root = tmp_path / "hermes"
    dev = root / "profiles" / "dev"
    (dev / "plugin-data" / "continuity").mkdir(parents=True)
    (dev / "config.yaml").write_text("plugins:\n  entries:\n    continuity:\n      settings:\n        min_pull: 0.6\n")
    c, sent = make(dev, memory=FakeMemory())
    c.store.close()
    c = Continuity(Store(dev / "plugin-data" / "continuity" / "continuity.db"), c.cfg, lambda t: True,
                   memory=FakeMemory(), user_name="Joey", clock=Clock(NOON))
    user_turn(c)
    c._associate_pending(NOON)
    api_file = Path(__file__).resolve().parents[1] / "hermes_sophia" / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("sophia_plugin_api_cont", api_file)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sophia_plugin_api_cont", mod)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_home", lambda: root)
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/sophia")
    r = TestClient(app).get("/api/plugins/sophia/continuity").json()
    assert r["profiles"] == ["dev"] and r["profile"] == "dev"
    rep = r["report"]
    assert rep["exists"] and rep["min_pull"] == 0.6 and rep["queue"]["waiting"] >= 1
    assert rep["queue"]["top"][0]["why"]["similarity"] is None or "similarity" in rep["queue"]["top"][0]["why"]
    assert rep["frames"]["latest"].startswith("[standing view")


# ------------------------------------------------------------- sensors
class RhythmMemory(FakeMemory):
    """A user who writes every 6 hours, starting their day at 09:00; one plan due at 09:30 today."""
    def __init__(self, items=None, plans=None):
        super().__init__(items if items is not None else [])
        self.plans = plans if plans is not None else [
            {"id": "f1", "text": "Joey has a dentist appointment with Dr. Moreau", "h_start": NOON - 2.5 * 3600,
             "h_end": None, "happens": "2026-10-03T09:30", "status": "active"}]

    def user_message_times(self, days=28):
        day0 = NOON - 10 * 86400 - 3 * 3600                     # 09:00, ten days ago
        return [day0 + d * 86400 + k * 6 * 3600 for d in range(10) for k in range(3)]

    def upcoming(self, start, end):
        return [p for p in self.plans if start <= p["h_start"] < end]


def test_quiet_for_longer_than_usual_is_noticed_once_per_rung_and_never_at_night(tmp_path):
    from hermes_continuity.sensors import check
    clock = Clock(NOON)
    c, _ = make(tmp_path, clock=clock, memory=RhythmMemory(plans=[]), sensors=True, morning="06:00")
    st = c.store.state()
    st["last_user_ts"] = NOON - 13 * 3600                     # usual gap 6 h -> threshold 12 h
    events = check(st, NOON, c.cfg, c.memory, "Joey")
    quiet = [e for e in events if e["sensor"] == "quiet"]
    assert len(quiet) == 1 and "longer than usual" in quiet[0]["text"] and "6 hours" in quiet[0]["text"]
    assert not [e for e in check(st, NOON + 600, c.cfg, c.memory, "Joey") if e["sensor"] == "quiet"]
    assert not check(st, NIGHT + 3600 * 2, c.cfg, c.memory, "Joey")              # 01:30: quiet hours, nothing
    later = check(st, NOON + 86400, c.cfg, c.memory, "Joey")
    assert [e for e in later if e["sensor"] == "quiet"]                           # the one-day rung, next noon


def test_overdue_and_passed_dates_are_noticed_once(tmp_path):
    from hermes_continuity.sensors import check
    c, _ = make(tmp_path, memory=RhythmMemory(), sensors=True, morning="23:59")
    c.update({"waiting_for": "the backup job proc_7", "by": "+30m"})
    st = c.store.state()
    first = check(st, NOON + 600, c.cfg, c.memory, "Joey")          # the 09:30 plan has already gone by
    assert [e["sensor"] for e in first] == ["date passed"] and "dentist appointment" in first[0]["text"]
    second = check(st, NOON + 2400, c.cfg, c.memory, "Joey")        # 30 minutes later: the job is late
    assert [e["sensor"] for e in second] == ["overdue"] and "proc_7" in second[0]["text"]
    assert check(st, NOON + 3000, c.cfg, c.memory, "Joey") == []    # each noticed once


def test_morning_is_the_one_scheduled_event_and_carries_whats_due(tmp_path):
    from hermes_continuity.sensors import check
    early = time.mktime((2026, 10, 3, 8, 30, 0, 0, 0, -1))
    plan = [{"id": "f2", "text": "Joey has lunch with Sam", "h_start": NOON + 1800, "h_end": None, "happens": "", "status": "active"}]
    c, _ = make(tmp_path, memory=RhythmMemory(plans=plan), sensors=True)
    st = c.store.state()
    assert not [e for e in check(st, early, c.cfg, c.memory, "Joey") if e["sensor"] == "morning"]    # usual start 09:00
    m = [e for e in check(st, early + 3600, c.cfg, c.memory, "Joey") if e["sensor"] == "morning"]
    assert len(m) == 1 and m[0]["scheduled"] and "lunch with Sam" in m[0]["text"] and "12:30" in m[0]["text"]
    assert not [e for e in check(st, early + 7200, c.cfg, c.memory, "Joey") if e["sensor"] == "morning"]


def test_something_noticed_becomes_a_turn_of_its_own(tmp_path):
    clock = Clock(NOON)
    c, sent = make(tmp_path, clock=clock, memory=RhythmMemory(plans=[]), sensors=True, morning="23:59")
    c.update({"waiting_for": "Joey's reply about the lease", "by": "+1h"})
    clock.t += 2 * 3600
    assert c.tick()
    assert sent[-1].startswith(LABEL + " noticed]") and "lease" in sent[-1]
    assert c.store.one("SELECT kind FROM steps")["kind"] == "noticed"
    assert c.store.one("SELECT kind FROM percepts WHERE kind='overdue'")


def test_by_accepts_minutes_hours_clock_times_and_iso():
    from hermes_continuity.loop import parse_by
    assert parse_by("+30m", NOON) == NOON + 1800 and parse_by("2h", NOON) == NOON + 7200
    assert parse_by("14:30", NOON) == NOON + 2.5 * 3600 and parse_by("09:00", NOON) == NOON + 21 * 3600
    assert parse_by("2026-10-04T10:00", NOON) and parse_by("someday", NOON) is None


def test_its_own_events_never_come_to_mind_again(engine):
    """Association feeds the loop; raising the loop's own turns and notes would make it think about itself."""
    from hermes_sophia.api import Memory
    mem = Memory("", engine=engine)
    engine.capture.process_messages("t", [
        {"role": "user", "content": "[continuity: something came to mind]\n“The movers broke a lamp in Spokane.” (Joey)\n"
                                    "(For you: this is your own process, not Joey. Think about it, act, or let it go.)"},
        {"role": "assistant", "content": "[SILENT]"}])
    mem.record_event("Went quiet (ran its course) after 2 turns of its own about the Spokane lamp.")
    stored = engine.store.q("SELECT text, flags FROM windows WHERE speaker='continuity'")
    assert stored and not any("For you:" in r["text"] or "Think about it" in r["text"] for r in stored)
    items = mem.associate("Spokane lamp movers", k=8, record=False)
    assert not any("continuity" in it.get("label", "") or it["speaker"] == "continuity" for it in items)


def test_fill_is_measured_against_the_real_prompt(tmp_path):
    c, _ = make(tmp_path)
    c.on_turn_start(session_id="s", user_message="hi", conversation_history=[], platform="telegram")
    c.on_api(platform="telegram", usage={"prompt_tokens": 20000, "total_tokens": 20150})
    c.on_api(platform="telegram", usage={"prompt_tokens": 20400, "total_tokens": 20500})     # a tool call's follow-up
    c.on_reply(response_text="hello", session_id="s", platform="telegram")
    c.on_turn_end(session_id="s", platform="telegram")
    f = c.store.one("SELECT chars, prompt_tokens FROM frames")
    assert f["prompt_tokens"] == 20000                               # the context the frame sat in: the first call
    from hermes_continuity.report import build
    rep = build(c.store.path, c.cfg, user="Joey", now=NOON)
    assert rep["frames"]["mean_fill"] == pytest.approx((f["chars"] / 4) / 20000, abs=1e-4)
