"""Goals: what the agent keeps working toward, with where each came from and a reason for every change.

Shaped with Sophia:
- a goal the agent sets itself must point at what it grew from (a memory line, a thought, an event or an outcome);
  without that anchor it's still a thought, not a goal;
- goals never add energy. A goal can become a turn of its own only with energy something real put in the pool, and
  only when nothing perceived, noticed or remembered is waiting. Its pull fades the longer it goes without progress,
  so a stalled goal quietly loses its claim instead of nagging. The user's goals rank above its own;
- no silent veto. The agent can push back on a goal (a concern with a reason: visible, non-blocking, overridable),
  and can decline one the user set in exactly two cases: it's outside its tools or permissions, or it judges it
  harmful. Both are visible and journaled; the user can override either.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, origin TEXT, grew_from TEXT,
  grew_from_text TEXT, status TEXT DEFAULT 'active', next_step TEXT, created REAL, updated REAL, last_progress REAL,
  last_turn REAL, pushback TEXT, decline_reason TEXT);
CREATE TABLE IF NOT EXISTS goal_events(id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INT, ts REAL, kind TEXT, note TEXT,
  by TEXT);
"""
DECLINE_CASES = ("outside my tools or permissions", "harmful")
HALF_LIFE_S = 3 * 86400            # a goal's pull halves for every three days without progress
COOLDOWN_S = 6 * 3600              # a goal isn't taken up again within this long of its last turn

SCHEMA_TOOL = {
    "name": "continuity_goal",
    "description": ("Your goals: what you keep working toward between messages, shown in your standing view. "
                    "action=add needs text, and for a goal of your own, grew_from: the id or words of the memory line, "
                    "thought, event or outcome it grew from (if you can't point at one, keep it as a thought instead). "
                    "Use origin=user when the user asked for it. progress records a step (note, optionally next_step); "
                    "revise, done, drop, pause and resume need a reason. pushback flags a concern about a goal with a "
                    "reason: it stays active, and the user sees it and can override it. decline is for a goal the user "
                    "set, and only when it's outside your tools or permissions, or you judge it harmful. Dropping a "
                    "goal is fine."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["add", "progress", "revise", "done", "drop", "pause", "resume", "pushback",
                                              "decline", "list"]},
        "id": {"type": "integer", "description": "The goal's id (all actions but add and list)."},
        "text": {"type": "string", "description": "add: the goal. revise: its new wording."},
        "next_step": {"type": "string", "description": "add or progress: the next concrete step."},
        "origin": {"type": "string", "enum": ["self", "user"], "description": "add: who set it (default self)."},
        "grew_from": {"type": "string", "description": "add, for your own goal: id or words of what it grew from."},
        "note": {"type": "string", "description": "progress: what was done."},
        "reason": {"type": "string", "description": "revise, done, drop, pause, resume, pushback, decline: why."},
        "case": {"type": "string", "enum": list(DECLINE_CASES), "description": "decline: which of the two cases."}},
        "required": ["action"]},
}


class Goals:
    def __init__(self, store, memory=None, clock=time.time):
        self.store, self.memory, self.clock = store, memory, clock
        with store.lock:
            store.conn.executescript(SCHEMA)
            store.conn.commit()

    def _event(self, gid: int, kind: str, note: str = "", by: str = "agent") -> None:
        self.store.x("INSERT INTO goal_events(goal_id, ts, kind, note, by) VALUES(?,?,?,?,?)",
                     (gid, self.clock(), kind, (note or "")[:500], by))

    def _anchor(self, grew_from: str) -> Optional[str]:
        """The words of what a goal grew from: a memory line or fact found by id, or the words given."""
        g = (grew_from or "").strip()
        if not g:
            return None
        if self.memory is not None:
            try:
                st = self.memory.e.store
                r = st.one("SELECT text FROM windows WHERE id=?", (g,)) or \
                    st.one("SELECT subject || ' ' || relation || ' ' || object AS text FROM facts WHERE id=?", (g,))
                if r:
                    return r["text"][:300]
            except Exception:
                pass
        return g[:300]

    def get(self, gid: Any):
        return self.store.one("SELECT * FROM goals WHERE id=?", (gid,))

    def active(self) -> List[Any]:
        return self.store.q("""SELECT * FROM goals WHERE status='active'
                               ORDER BY (origin='user') DESC, COALESCE(last_progress, created) DESC""")

    def pull(self, g: Any, now: float) -> float:
        base = 0.8 if g["origin"] == "user" else 0.6
        since = now - (g["last_progress"] or g["created"] or now)
        return base * 0.5 ** (since / HALF_LIFE_S)

    def next_for_turn(self, now: float, min_pull: float) -> Optional[Dict[str, Any]]:
        """The goal worth a turn now, if any: active, with a next step, out of cooldown, pulling hard enough."""
        best = None
        for g in self.active():
            if not g["next_step"] or (g["last_turn"] and now - g["last_turn"] < COOLDOWN_S):
                continue
            p = self.pull(g, now)
            if p >= min_pull and (best is None or p > best[1]):
                best = (g, p)
        if best is None:
            return None
        g, p = best
        return {"kind": "goal", "goal_id": g["id"], "text": g["text"], "next_step": g["next_step"], "origin": g["origin"],
                "grew_from_text": g["grew_from_text"], "last_progress": g["last_progress"], "pushback": g["pushback"],
                "salience": p, "depth": 0}

    def took_turn(self, gid: int, now: float) -> None:
        self.store.x("UPDATE goals SET last_turn=? WHERE id=?", (now, gid))

    def handle(self, a: Dict[str, Any], by: str = "agent") -> Dict[str, Any]:
        """The continuity_goal tool (and the user's overrides, by='user')."""
        now = self.clock()
        act = (a.get("action") or "").strip()
        if act == "list":
            return {"goals": [self.describe(g) for g in self.store.q("SELECT * FROM goals ORDER BY id DESC LIMIT 20")]}
        if act == "add":
            text = (a.get("text") or "").strip()
            if not text:
                return {"error": "a goal needs text"}
            origin = "user" if a.get("origin") == "user" else "self"
            anchor = self._anchor(a.get("grew_from") or "")
            if origin == "self" and not anchor:
                return {"error": "a goal of your own needs grew_from: what it grew from (a memory line, thought, event "
                                 "or outcome). Without one, keep it as a thought (sophia_thought) for now."}
            gid = self.store.x("""INSERT INTO goals(text, origin, grew_from, grew_from_text, next_step, created, updated)
                                  VALUES(?,?,?,?,?,?,?)""", (text[:300], origin, (a.get("grew_from") or "")[:200], anchor,
                                                              (a.get("next_step") or "")[:300], now, now))
            self._event(gid, "added", f"{origin}: {text}" + (f" (grew from: {anchor})" if anchor else ""), by)
            return {"ok": True, "id": gid}
        g = self.get(a.get("id"))
        if g is None:
            return {"error": f"no goal with id {a.get('id')}"}
        reason = (a.get("reason") or "").strip()
        if act == "progress":
            note = (a.get("note") or "").strip()
            if not note:
                return {"error": "progress needs a note: what was done"}
            self.store.x("UPDATE goals SET last_progress=?, updated=?, next_step=COALESCE(?, next_step) WHERE id=?",
                         (now, now, (a.get("next_step") or None), g["id"]))
            self._event(g["id"], "progress", note, by)
            return {"ok": True}
        if act in ("revise", "done", "drop", "pause", "resume", "pushback", "decline") and not reason:
            return {"error": f"{act} needs a reason"}
        if act == "revise":
            if not (a.get("text") or "").strip():
                return {"error": "revise needs the new text"}
            self.store.x("UPDATE goals SET text=?, updated=? WHERE id=?", (a["text"].strip()[:300], now, g["id"]))
            self._event(g["id"], "revised", f"{g['text']} → {a['text'].strip()} ({reason})", by)
        elif act in ("done", "drop", "pause", "resume"):
            status = {"done": "done", "drop": "dropped", "pause": "paused", "resume": "active"}[act]
            self.store.x("UPDATE goals SET status=?, updated=? WHERE id=?", (status, now, g["id"]))
            self._event(g["id"], status, reason, by)
        elif act == "pushback":
            self.store.x("UPDATE goals SET pushback=?, updated=? WHERE id=?", (reason[:300], now, g["id"]))
            self._event(g["id"], "pushback", reason, by)
        elif act == "decline":
            case = a.get("case")
            if g["origin"] != "user":
                return {"error": "decline is for goals the user set; drop a goal of your own instead"}
            if case not in DECLINE_CASES:
                return {"error": f"decline is only for: {', '.join(DECLINE_CASES)}. For anything else, push back "
                                 "with a reason and keep the goal."}
            self.store.x("UPDATE goals SET status='declined', decline_reason=?, updated=? WHERE id=?",
                         (f"{case}: {reason}"[:300], now, g["id"]))
            self._event(g["id"], "declined", f"{case}: {reason}", by)
        else:
            return {"error": f"unknown action {act!r}"}
        return {"ok": True}

    def override(self, gid: int, note: str = "") -> bool:
        """The user overrides a push-back or a decline: the goal is active again, the concern is kept in the journal."""
        g = self.get(gid)
        if g is None:
            return False
        self.store.x("UPDATE goals SET status='active', pushback=NULL, decline_reason=NULL, updated=? WHERE id=?",
                     (self.clock(), gid))
        self._event(gid, "overridden", note or "overridden by the user", by="user")
        return True

    def describe(self, g: Any) -> Dict[str, Any]:
        return {"id": g["id"], "text": g["text"], "origin": g["origin"], "status": g["status"], "next_step": g["next_step"],
                "grew_from": g["grew_from_text"], "last_progress": g["last_progress"], "pushback": g["pushback"],
                "declined": g["decline_reason"]}
