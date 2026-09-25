import json


def _call(cid, name, **args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _session():
    token = "ghp_" + "a" * 36
    return [
        {"role": "user", "content": "Rotate the nginx logs on web-1 please.", "timestamp": 1000},
        {"role": "assistant", "content": "", "tool_calls": [_call("c1", "terminal", command="rm /var/log/nginx/*.log")],
         "timestamp": 1001},
        {"role": "tool", "tool_call_id": "c1", "name": "terminal",
         "content": json.dumps({"output": "rm: cannot remove: Permission denied", "exit_code": 1, "error": None}),
         "timestamp": 1002},
        {"role": "assistant", "content": "", "tool_calls": [
            _call("c2", "terminal", command=f"GITHUB_TOKEN={token} sudo logrotate -f /etc/logrotate.d/nginx"),
            _call("c3", "sophia_recall", query="nginx logs"),
            _call("c4", "vault_read", key="web-1")], "timestamp": 1003},
        {"role": "tool", "tool_call_id": "c2", "name": "terminal",
         "content": json.dumps({"output": "", "exit_code": 0, "error": None}), "timestamp": 1004},
        {"role": "tool", "tool_call_id": "c3", "name": "sophia_recall", "content": "{}", "timestamp": 1005},
        {"role": "tool", "tool_call_id": "c4", "name": "vault_read", "content": "secret", "timestamp": 1006},
        {"role": "assistant", "content": "Done — logrotate forced the rotation.", "timestamp": 1007},
        {"role": "user", "content": "That worked, thanks.", "timestamp": 1100},
    ], token


def test_action_log_records_steps_in_order(engine):
    msgs, token = _session()
    stats = engine.capture.process_messages("ops", msgs)
    rows = engine.store.q("SELECT * FROM actions WHERE session_id='ops' ORDER BY said, seq")
    assert stats["actions"] == 2 and [r["tool"] for r in rows] == ["terminal", "terminal"]
    first, second = rows
    assert json.loads(first["args"])["command"] == "rm /var/log/nginx/*.log"
    assert first["error"] == 1 and first["exit_code"] == 1 and "Permission denied" in first["result_head"]
    assert second["error"] == 0 and second["exit_code"] == 0
    assert token not in second["args"] and "logrotate -f /etc/logrotate.d/nginx" in second["args"]
    assert first["request_text"] == "Rotate the nginx logs on web-1 please."
    assert first["request_ref"] == second["request_ref"] != ""


def test_action_log_is_idempotent(engine):
    msgs, _ = _session()
    engine.capture.process_messages("ops", msgs)
    engine.capture.process_messages("ops", msgs)
    assert engine.store.one("SELECT COUNT(*) AS n FROM actions")["n"] == 2


import re
import time

from hermes_sophia.sleep import SleepRunner
from hermes_sophia.sleep.tasks import OUTCOMES, TaskPass


def _models(fake, outcome="succeeded", card=None):
    """A fake night: picks the option whose text means `outcome`, says follow-ups are new tasks, writes `card`."""
    def readout(prompt):
        opts = dict(re.findall(r"^([A-Z])\) (.*)$", prompt, re.M))
        want = OUTCOMES[outcome] if "How did the task turn out" in prompt else "false"
        letter = next(l for l, d in opts.items() if want.lower() in d.lower())
        return [(letter, -0.05)] + [(l, -4.0) for l in opts if l != letter]
    fake.readout = readout
    fake.chat_fn = lambda p: (card or "GOAL: Rotate the nginx logs on web-1\nWHERE: web-1\nWORKED: a2, a9\n"
                              "DEAD ENDS: a1: permission denied\nLEARNED FROM: -\nLESSON: logrotate -f needs sudo") \
        if p.startswith("You are writing a task card") else ""


def _night(engine):
    return SleepRunner(engine, model="fake", max_wait_s=0, steps=["tasks", "index"], now=time.time() + 60).run()


def test_night_writes_a_card_from_the_log(engine, fake):
    msgs, token = _session()
    engine.capture.process_messages("ops", msgs)
    _models(fake)
    out = _night(engine)
    assert out["status"] == "complete" and out["stats"]["tasks"]["tasks"] == 1
    t = engine.store.one("SELECT * FROM tasks")
    card = __import__("json").loads(t["card"])
    assert t["outcome"] == "succeeded" and card["goal"] == "Rotate the nginx logs on web-1"
    assert [s["step"] for s in card["worked"]] == [s for s in [card["worked"][0]["step"]]]      # a9 does not exist
    assert "logrotate -f /etc/logrotate.d/nginx" in card["worked"][0]["step"] and token not in t["card"]
    assert card["dead_ends"][0]["step"] == "rm /var/log/nginx/*.log" and card["dead_ends"][0]["why"] == "permission denied"
    assert "That worked" in card["reaction"]
    assert engine.store.one("SELECT COUNT(*) AS n FROM actions WHERE task_id=?", (t["id"],))["n"] == 2


def test_card_comes_back_when_the_task_does(engine, fake):
    msgs, _ = _session()
    engine.capture.process_messages("ops", msgs)
    _models(fake)
    _night(engine)
    engine.cfg["skip_gate"] = 0.0
    text, info = engine.recall.prefetch("Rotate the nginx logs on web-1 again", "later")
    assert "earlier task · succeeded" in text and "Worked: `" in text and "Dead ends: `rm /var/log/nginx/*.log`" in text
    view = engine.tools.dispatch("sophia_browse", {"view": "tasks"})
    assert "Rotate the nginx logs" in view
    tid = engine.store.one("SELECT id FROM tasks")["id"]
    full = __import__("json").loads(engine.tools.dispatch("sophia_browse", {"view": "tasks", "key": tid}))
    assert len(full["actions"]) == 2 and full["actions"][0]["exit_code"] == 1


def test_failed_attempt_is_a_warning(engine, fake):
    msgs, _ = _session()
    engine.capture.process_messages("ops", msgs[:3] + [{"role": "assistant", "content": "I couldn't do it.",
                                                         "timestamp": 1003}])
    _models(fake, outcome="failed", card="GOAL: Rotate the nginx logs on web-1\nWHERE: web-1\nWORKED: -\n"
                                          "DEAD ENDS: a1: permission denied\nLEARNED FROM: -\nLESSON: -")
    _night(engine)
    engine.cfg["skip_gate"] = 0.0
    text, _ = engine.recall.prefetch("Rotate the nginx logs on web-1", "later")
    assert "earlier task · failed" in text and "did not work: don't repeat blindly" in text


def test_reusing_a_card_earns_credit(engine, fake):
    msgs, _ = _session()
    engine.capture.process_messages("ops", msgs)
    _models(fake)
    _night(engine)
    card_id = engine.store.one("SELECT id FROM tasks")["id"]
    engine.cfg["skip_gate"] = 0.0
    engine.prefetch("Rotate the nginx logs on web-1 again", "ops2")      # the card is injected in the new session
    t0 = time.time()                                                    # after the injection above
    again = [dict(m, timestamp=t0 + i) for i, m in enumerate(msgs) if m["role"] != "tool" or m["tool_call_id"] == "c2"]
    again = [m for m in again if not (m["role"] == "assistant" and m.get("tool_calls") and m["tool_calls"][0]["id"] == "c1")]
    engine.capture.process_messages("ops2", again)
    _night(engine)
    ev = engine.store.q("SELECT kind, delta FROM credit_events WHERE item_id=?", (card_id,))
    assert any(e["kind"] == "reused_succeeded" and e["delta"] > 0 for e in ev)


def test_card_parser_drops_placeholders():
    p = TaskPass.parse_card("GOAL: Check disk\nWHERE: terminal\nWORKED: a1\nDEAD ENDS: -\nLEARNED FROM: ->\nLESSON: ->", 1)
    assert p["where"] == "" and p["lesson"] == "" and p["worked"] == [0] and p["learned"] == []


def test_actions_are_searchable_the_same_day(engine):
    msgs, token = _session()
    engine.capture.process_messages("ops", msgs)
    rows = engine.store.q("SELECT text, flags FROM windows WHERE speaker='action' ORDER BY said")
    assert len(rows) == 2 and "rm /var/log/nginx/*.log -> failed (exit 1)" in rows[0]["text"]
    assert "error" in rows[0]["flags"] and token not in rows[1]["text"]
    engine.cfg.update(skip_gate=0.0, junk_floor=0.0, inject_relative_floor=1.0)    # plumbing, not ranking
    text, _ = engine.recall.prefetch("What didn't work when we rotated the nginx logs?", "later")
    assert "rm /var/log/nginx/*.log" in text
