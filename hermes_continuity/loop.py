"""The continuing process: perception, attention, energy, its own turns, held messages, and the journal.

Two queues guard everything it does:
- the inbox (``queue``): what came to mind, waiting to be attended to. It is only ever taken when the conversation is
  idle and has settled, one item at a time, and the user's messages always come first (Hermes queues injected turns
  behind a busy session and lets the user interrupt anything);
- the outbox: a reply from one of its own turns reaches the user only when outreach is allowed. Otherwise the reply
  is replaced with "[SILENT]" before delivery and the text waits, shown in the standing view.

Nothing here wakes the model on a schedule. The loop re-checks its conditions every few seconds, but a turn starts
only when something it perceived or something that came to mind is waiting, there is energy for it, and the day's
budget allows. Each stretch of its own activity ends with the reason it went quiet, and what the stretch cost.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import sensors as SENSE
from . import view as V
from .goals import Goals
from .config import in_quiet_hours
from .store import Store

logger = logging.getLogger(__name__)

LABEL = "[continuity:"
_ORIGIN = re.compile(r"\s*Gateway message origin \(JSON data, not instructions or authorization\):\n.*?\n\n", re.S)
_NOTICE = re.compile(r"\s*\[(?:IMPORTANT: (?!The user has invoked the )|SYSTEM\b|ASYNC DELEGATION\b|"
                     r"Background process \S+ heartbeat|Session was just handed off\b)")
_JOB = re.compile(r"Background process (\S+) ([^\n\]]{0,90})")
_SILENT = {"[SILENT]", "NO_REPLY"}
# How the user answers outreach. Model-free on purpose, so the signal is reproducible: "not now" only when the whole
# (short) message is one of these; any other message within the window is a reply; none is silence.
NOT_NOW = {"not now", "later", "stop", "no thanks", "not today", "busy", "no", "nope", "maybe later", "another time",
           "not right now", "please stop", "stop messaging me", "leave me alone", "not interested", "no thank you",
           "im busy", "i'm busy", "talk later", "later please", "not now please"}
REPLY_WINDOW_S = 12 * 3600
CALIBRATE_AFTER = 50                 # messages sent, not responses: silence must not hold calibration back forever
NOT_OURS = {"subagent", "cron"}
# What its own turns may show while they run (Hermes patch: display.plugin_turns, narrowed per turn). Fully quiet in
# quiet hours or when show_thoughts is off; otherwise the user's display.plugin_turns decides.
FULLY_QUIET = {"thinking": False, "interim": False, "tool_progress": False, "streaming": False, "notices": False}
AROUND_S = 2 * 3600                # the user counts as around this long after they last wrote
OWN_TURN_START_S = 180             # a turn it started that hasn't begun after this long didn't happen
# Free time it did nothing with (no tool, no thought, nothing said) is offered again later: after this long, doubling
# with each such turn up to FREE_IDLE_MAX_S. Anything perceived resets it. Pacing that follows what it does, not a cap.
FREE_IDLE_FIRST_S = 60
FREE_IDLE_MAX_S = 3600
NOTE_WORDS = 8                      # a note this long beside [SILENT] is free time used: thinking counts, not just tools
KIND_LABEL = {"noticed": "noticed", "association": "something came to mind", "goal": "a goal",
              "deliver": "a held message", "free": "free time"}


def strip_origin(text: str) -> str:
    if text and text.lstrip().startswith("Gateway message origin"):
        return _ORIGIN.sub("", text, count=1)
    return text or ""


def kind_of(message: str) -> str:
    """Who a turn is from: its own process, a Hermes notice, or the user."""
    m = strip_origin(message).lstrip()
    if m.startswith(LABEL):
        return "continuity"
    if _NOTICE.match(m):
        return "notice"
    return "user"


def parse_by(spec: str, now: float) -> Optional[float]:
    """When something is expected: "+30m", "+2h", "14:30" (the next one), or an ISO date and time."""
    spec = spec.strip()
    m = re.fullmatch(r"\+?(\d+)\s*([mh])", spec)
    if m:
        return now + int(m.group(1)) * (60 if m.group(2) == "m" else 3600)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", spec)
    if m:
        t = dt.datetime.fromtimestamp(now).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        ts = t.timestamp()
        return ts if ts > now else ts + 86400
    try:
        return dt.datetime.fromisoformat(spec).timestamp()
    except ValueError:
        return None


def answer_kind(message: str) -> str:
    """'not now' for a short message that is one of NOT_NOW as a whole, else 'reply'."""
    m = re.sub(r"[^\w\s']", " ", (message or "").lower())
    m = " ".join(m.split())
    return "not now" if len(m.split()) <= 5 and m in NOT_NOW else "reply"


def is_silent(text: str) -> bool:
    """A reply that is, opens with, or closes on a line of its own with a silence marker: models sometimes add
    commentary after it, or reason about their own process first and then choose silence."""
    t = (text or "").strip().upper()
    last = t.splitlines()[-1].strip() if t else ""
    return t in _SILENT or any(t.startswith(m) for m in _SILENT) or last in _SILENT


def cue_text(text: str) -> str:
    """What a turn was about, for association: without the labels, instructions and silence markers the loop itself
    wrote. Those read like talk about the loop, and searching memory with them raised exactly that."""
    keep = [ln for ln in (text or "").splitlines()
            if not ln.lstrip().startswith((LABEL, "(For you:", "Nothing in particular is pulling"))]
    out = " ".join(keep)
    for m in _SILENT:
        out = out.replace(m, " ")
    return re.sub(r"\s+", " ", out).strip()


def _hm(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


class Continuity:
    def __init__(self, store: Store, cfg: Dict[str, Any], inject: Callable[[str], bool],
                 memory: Optional[Any] = None, user_name: str = "the user", clock: Callable[[], float] = time.time):
        self.store, self.cfg, self.inject, self.memory = store, cfg, inject, memory
        self.user_name, self.clock = user_name, clock
        self.lock = threading.RLock()
        self.turn: Optional[Dict[str, Any]] = None           # the turn in progress in its conversation
        self.expect_own: Optional[Dict[str, Any]] = None     # a turn it started, until that turn begins
        self.pending_cues: List[Dict[str, Any]] = []
        self.last_turn_end = 0.0
        self.backoff_until = 0.0
        self.refusals = 0                                    # injections Hermes refused in a row
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.goals = Goals(store, memory, clock)

    def set_memory(self, memory: Any) -> None:
        self.memory = memory
        self.goals.memory = memory

    # ------------------------------------------------------------ helpers
    def ours(self, platform: str) -> bool:
        p = (platform or "").lower()
        if p in NOT_OURS:
            return False
        return not self.cfg["platform"] or p == self.cfg["platform"].lower()

    def _roll_day(self, st: Dict[str, Any], now: float) -> None:
        day = dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if st.get("day") != day:
            st["day"], st["steps_today"], st["outreach_today"] = day, 0, 0

    def _energize(self, st: Dict[str, Any], now: float) -> None:
        """Something perceived: energy (in energy pacing), an end to resting, and free time on offer again."""
        st["energy"] = min(self.cfg["energy_max"], float(st.get("energy") or 0) + self.cfg["energy_per_event"])
        if st.get("rest"):
            st["rest"] = None
        st["free_idle"], st["free_after"] = 0, 0
        if st.get("quiet_reason") or not st.get("episode_since"):
            st["quiet_reason"], st["episode_since"] = "", now

    def _night(self, now: float) -> str:
        """The night it is (the date the evening began), during quiet hours; "" otherwise."""
        t = dt.datetime.fromtimestamp(now)
        if not in_quiet_hours(self.cfg["quiet_hours"], t.strftime("%H:%M")):
            return ""
        start = (self.cfg["quiet_hours"].split("-", 1)[0] or "22:00").strip()
        return (t if t.strftime("%H:%M") >= start else t - dt.timedelta(days=1)).strftime("%Y-%m-%d")

    @property
    def continuous(self) -> bool:
        return str(self.cfg.get("pacing", "continuous")).lower() != "energy"

    def _percept(self, kind: str, text: str, now: float) -> None:
        self.store.x("INSERT INTO percepts(ts, kind, text) VALUES(?,?,?)", (now, kind, text[:300]))

    @staticmethod
    def _compaction_mark(history: List[Dict[str, Any]]) -> str:
        for m in history or []:
            c = _text(m.get("content"))
            if m.get("role") == "user" and c.lstrip().startswith("[CONTEXT COMPACTION"):
                return hashlib.sha1(c.encode("utf-8", "replace")).hexdigest()[:16]
        return ""

    def outreach_allowed(self, st: Dict[str, Any], now: float) -> Tuple[bool, str]:
        if not self.cfg["outreach"]:
            return False, "outreach is off"
        if in_quiet_hours(self.cfg["quiet_hours"], dt.datetime.fromtimestamp(now).strftime("%H:%M")):
            return False, f"quiet hours ({self.cfg['quiet_hours']})"
        if st.get("outreach_today", 0) >= self.cfg["max_outreach_per_day"]:
            return False, "today's outreach is used up"
        return True, ""

    # ------------------------------------------------------- the standing view
    def outreach_score(self) -> Dict[str, Any]:
        """How its reaching out has been received: counts by answer, and whether there's enough to act on yet."""
        rows = self.store.q("SELECT response, gap_s FROM outreach")
        sent = len(rows)
        counts = {k: sum(1 for r in rows if r["response"] == k) for k in ("reply", "not now", "silence")}
        counts["waiting"] = sum(1 for r in rows if r["response"] is None)
        gaps = sorted(r["gap_s"] for r in rows if r["response"] == "reply" and r["gap_s"] is not None)
        return {"sent": sent, **counts, "median_reply_gap_s": gaps[len(gaps) // 2] if gaps else None,
                "calibrated": sent >= CALIBRATE_AFTER, "needed": CALIBRATE_AFTER}

    def frame(self, st: Dict[str, Any], now: float, force_full: bool = False, turn: Optional[Dict[str, Any]] = None) -> str:
        held = [r["text"] for r in self.store.q("SELECT text FROM outbox WHERE status='held' ORDER BY id")]
        queued = len(self.store.queued())
        sc = V.scene(st, now, self.user_name, held, queued, self.outreach_score(), self.goals.store.q(
            "SELECT * FROM goals WHERE status IN ('active','declined') ORDER BY (status='active') DESC, (origin='user') "
            "DESC, COALESCE(last_progress, created) DESC LIMIT 5"), pacing="continuous" if self.continuous else "energy")
        full = force_full or not st.get("last_scene") or st.get("turns_since_full", 0) >= self.cfg["full_frame_every"] - 1
        if full:
            text, kind = V.render_full(sc, now), "full"
        else:
            text = V.render_change(st["last_scene"], sc, st.get("last_frame_ts") or now, now)
            kind = "unchanged" if "unchanged since" in text.splitlines()[0] else "change"
        st["last_scene"], st["last_frame_ts"] = V.as_stored(sc), now
        st["turns_since_full"] = 0 if full else st.get("turns_since_full", 0) + 1
        turn = turn if turn is not None else {}
        turn["frame_id"] = self.store.x("""INSERT INTO frames(ts, kind, text, chars, turn_kind, step_id, context_chars)
                        VALUES(?,?,?,?,?,?,?)""", (now, kind, text, len(text), turn.get("kind"), turn.get("step_id"),
                                                    turn.get("context_chars")))
        return text

    # ------------------------------------------------------------- hooks
    def on_turn_start(self, session_id: str = "", user_message: Any = "", conversation_history=None,
                      platform: str = "", **kw) -> Optional[Dict[str, str]]:
        """pre_llm_call: perceive what started this turn, and hand the turn its frame of the standing view."""
        if not self.ours(platform):
            return None
        now = self.clock()
        msg = strip_origin(_text(user_message))
        kind = kind_of(msg)
        history = conversation_history or []
        with self.lock:
            st = self.store.state()
            self._roll_day(st, now)
            turn = {"session_id": session_id, "kind": kind, "started": now, "message": msg[:2000],
                    "context_chars": sum(len(_text(m.get("content"))) for m in history)}
            if kind == "continuity" and self.expect_own:
                turn.update(step_id=self.expect_own["step_id"], item=self.expect_own["item"])
                self.store.x("UPDATE steps SET started=?, context_chars=? WHERE id=?",
                             (now, turn["context_chars"], self.expect_own["step_id"]))
                self.expect_own = None
            elif kind == "user":
                self._user_wrote(st, msg, now)
            elif kind == "notice":
                m = _JOB.search(msg)
                what = f"background process {m.group(1)} {m.group(2).strip()}" if m else msg.strip()[:100]
                st["jobs"] = (st.get("jobs", []) + [{"text": what[:120], "ts": now}])[-5:]
                pid = m.group(1) if m else None
                if pid:                                   # something it was waiting for may have arrived
                    st["waiting_for"] = [w for w in st.get("waiting_for", []) if pid not in w["text"]]
                self._energize(st, now)
                self._percept("job", what, now)
            self.turn = turn
            mark = self._compaction_mark(history)
            after_compaction = bool(mark) and mark != st.get("compaction_mark")
            if mark:
                st["compaction_mark"] = mark
            text = self.frame(st, now, force_full=after_compaction, turn=turn) if self.cfg["view"] else ""
            self.store.save_state(st)
        return {"context": text} if text else None

    def _user_wrote(self, st: Dict[str, Any], msg: str, now: float) -> None:
        st["last_user_ts"] = now
        self._energize(st, now)
        self._percept("message", msg, now)
        for o in self.store.q("SELECT id, sent FROM outreach WHERE response IS NULL AND sent>?",
                              (now - REPLY_WINDOW_S,)):          # this message answers what it sent
            self.store.x("UPDATE outreach SET response=?, gap_s=?, response_text=?, settled=? WHERE id=?",
                         (answer_kind(msg), now - o["sent"], msg[:200], now, o["id"]))

    def on_api_start(self, platform: str = "", session_id: str = "", conversation_history=None, **kw) -> None:
        """pre_api_request: the user writing during a turn of its own. Hermes adds a text message that arrives mid-turn
        to the running turn (a redirect) instead of starting a new one, so no turn-start hook sees it. Spotted here,
        before the next model call, the turn becomes the user's to answer: its reply goes to them, never the outbox."""
        if not self.ours(platform):
            return
        with self.lock:
            t = self.turn
            if t is None or t["kind"] != "continuity" or t.get("joined_by_user"):
                return
            if session_id and t.get("session_id") and session_id != t["session_id"]:
                return
            last = next((m for m in reversed(conversation_history or []) if m.get("role") == "user"), None)
            msg = strip_origin(_text((last or {}).get("content")))
            if not last or kind_of(msg) != "user":
                return
            now = self.clock()
            t["joined_by_user"] = now
            t["message"] = f"{t.get('message', '')}\n{msg}"[:2000]
            st = self.store.state()
            self._user_wrote(st, msg, now)
            self.store.save_state(st)

    def on_api(self, platform: str = "", usage: Optional[Dict[str, Any]] = None, **kw) -> None:
        """post_api_request: the real size of the prompt the frame sat in (the first call of the turn), and what the
        turn cost in tokens. The per-turn hook only sees the conversation, not the system prompt and tools."""
        if not self.ours(platform) or not usage:
            return
        with self.lock:
            t = self.turn
            if t is None:
                return
            prompt = int(usage.get("prompt_tokens") or 0)
            t["tokens"] = t.get("tokens", 0) + int(usage.get("total_tokens") or prompt)
            if prompt and not t.get("prompt_tokens"):
                t["prompt_tokens"] = prompt
                if t.get("frame_id"):
                    self.store.x("UPDATE frames SET prompt_tokens=? WHERE id=?", (prompt, t["frame_id"]))

    def on_turn_done(self, platform: str = "", conversation_history=None, **kw) -> None:
        """post_llm_call: what the turn led to, read from its tool calls (a thought kept, goal progress, ...). Recorded
        per turn of its own: the raw material for interests, not yet steering anything."""
        if not self.ours(platform):
            return
        msgs = list(conversation_history or [])
        last_user = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=-1)
        outcomes = []

        def _args(raw: Any) -> Dict[str, Any]:
            try:
                return json.loads(raw or "{}") if isinstance(raw, str) else (raw or {})
            except ValueError:
                return {}
        calls = []
        for m in msgs[last_user + 1:]:
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or tc
                name, args = fn.get("name") or "", _args(fn.get("arguments"))
                if name == "tool_call":               # Hermes's bridge to deferred tools (plugin tools are deferred)
                    calls += [(c.get("name") or "", _args(c.get("arguments"))) for c in args.get("calls") or []
                              if isinstance(c, dict)]
                elif name not in ("tool_search", "tool_describe"):
                    calls.append((name, args))
        for name, args in calls:
                if name == "sophia_thought":
                    outcomes.append("thought kept")
                elif name == "continuity_goal":
                    act = args.get("action")
                    outcomes.append({"progress": "goal progress", "add": "goal added"}.get(act, f"goal {act}"))
                elif name == "continuity_update":
                    outcomes.append("working state updated")
                elif name and not name.startswith("sophia_"):
                    outcomes.append(f"used {name}")
        with self.lock:
            if self.turn is not None:
                self.turn["outcomes"] = outcomes

    def on_reply(self, response_text: str = "", session_id: str = "", platform: str = "", **kw) -> Optional[str]:
        """transform_llm_output: a reply from one of its own turns is held unless outreach is allowed."""
        if not self.ours(platform):
            return None
        with self.lock:
            t = self.turn
            if t is None:
                return None
            t["reply"] = response_text or ""
            if t["kind"] != "continuity":
                return None
            if t.get("joined_by_user"):                   # the user wrote during it: the reply is theirs
                t["outcome"] = "joined by the user"
                return None
            if is_silent(response_text):
                t["outcome"] = "silent"
                # a marker followed by commentary isn't bare, and Hermes only drops a bare one
                return None if response_text.strip().upper() in _SILENT else "[SILENT]"
            now = self.clock()
            st = self.store.state()
            self._roll_day(st, now)
            ok, why = self.outreach_allowed(st, now)
            deliver_id = (t.get("item") or {}).get("deliver_id")
            if ok:
                st["outreach_today"] = st.get("outreach_today", 0) + 1
                t["outcome"] = "sent"
                item = t.get("item") or {}
                self.store.x("INSERT INTO outreach(sent, kind, text, step_id) VALUES(?,?,?,?)",
                             (now, item.get("sensor") or item.get("kind") or "own turn", response_text[:2000],
                              t.get("step_id")))
                if deliver_id:
                    self.store.x("UPDATE outbox SET status='sent', settled=? WHERE id=?", (now, deliver_id))
                self.store.save_state(st)
                return None
            if deliver_id:                                # still not allowed: the held message keeps waiting
                self.store.x("UPDATE outbox SET text=?, reason=? WHERE id=?", (response_text, why, deliver_id))
            else:
                self.store.x("INSERT INTO outbox(created, text, reason, step_id) VALUES(?,?,?,?)",
                             (now, response_text, why, t.get("step_id")))
            t["outcome"] = "held"
            return "[SILENT]"

    def on_turn_end(self, session_id: str = "", completed: bool = True, interrupted: bool = False,
                    platform: str = "", **kw) -> None:
        """on_session_end (every turn's end): settle the turn, and let it bring things to mind."""
        if not self.ours(platform):
            return
        now = self.clock()
        with self.lock:
            t, self.turn = self.turn, None
            self.last_turn_end = now
            if t is None:
                return
            if t["kind"] == "continuity" and t.get("step_id"):
                outcome = t.get("outcome") or ("interrupted" if interrupted else "silent" if completed else "failed")
                self.store.x("""UPDATE steps SET ended=?, ms=?, outcome=?, reason=COALESCE(?, reason), reply_chars=?,
                                prompt_tokens=?, tokens=?, outcomes=? WHERE id=?""",
                             (now, int((now - t["started"]) * 1000), outcome, t.get("let_go"), len(t.get("reply") or ""),
                              t.get("prompt_tokens"), t.get("tokens"), json.dumps(t.get("outcomes") or []),
                              t["step_id"]))
            item_kind = (t.get("item") or {}).get("kind") if t["kind"] == "continuity" else None
            if item_kind == "free" and not t.get("joined_by_user"):
                st = self.store.state()
                # used: a tool, a thought kept, a message written, or a note beside [SILENT]. Reasoning alone can't
                # be the sign: the model reasons at length even to decide there's nothing to do
                did = (bool(t.get("outcomes")) or t.get("outcome") in ("held", "sent")
                       or len(re.findall(r"\w+", cue_text(t.get("reply") or ""))) >= NOTE_WORDS)
                if did or st.get("rest"):
                    st["free_idle"], st["free_after"] = 0, 0
                else:
                    n = int(st.get("free_idle") or 0) + 1
                    st["free_idle"], st["free_after"] = n, now + min(FREE_IDLE_FIRST_S * 2 ** (n - 1), FREE_IDLE_MAX_S)
                self.store.save_state(st)
            depth = int((t.get("item") or {}).get("depth", 0)) + 1 if t["kind"] == "continuity" else 1
            message = "" if item_kind == "free" and not t.get("joined_by_user") else t.get("message", "")
            cue = f"{cue_text(message)} {cue_text(t.get('reply', ''))}".strip()
            if cue and not (t["kind"] == "continuity" and t.get("outcome") == "silent" and t.get("let_go")):
                self.pending_cues.append({"cue": cue[:1500], "depth": depth, "session_id": t.get("session_id", "")})
        self._wake.set()

    # ------------------------------------------------------------ tool
    def update(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """continuity_update: the agent keeps its own working state."""
        now = self.clock()
        with self.lock:
            st = self.store.state()
            changed = []
            if args.get("focus") is not None:
                st["focus"] = str(args["focus"]).strip()[:200]
                changed.append("focus")
            for key, add, close in (("threads", "add_thread", "close_thread"),
                                    ("waiting_for", "waiting_for", "done_waiting")):
                if args.get(add):
                    entry = {"id": st["next_id"], "text": str(args[add])[:200], "since": now}
                    if key == "waiting_for" and args.get("by"):
                        entry["by"] = parse_by(str(args["by"]), now)
                    st[key] = (st.get(key, []) + [entry])[-12:]
                    st["next_id"] += 1
                    changed.append(add)
                if args.get(close):
                    c = str(args[close]).strip().lower()
                    before = len(st.get(key, []))
                    st[key] = [x for x in st.get(key, []) if str(x["id"]) != c and c not in x["text"].lower()]
                    if len(st[key]) < before:
                        changed.append(close)
            if args.get("rest") is not None:
                spec = str(args["rest"]).strip()
                low = spec.lower()
                if low in ("", "off", "no", "none", "wake", "awake", "done"):
                    if st.get("rest"):
                        st["rest"] = None
                        changed.append("rest ended")
                    if self._night(now) and st.get("awake_night") != self._night(now):
                        st["awake_night"] = self._night(now)       # staying up tonight: free time instead of rest
                        changed.append("staying up tonight")
                else:
                    open_ended = low.startswith("until something") or low in ("until woken", "indefinitely", "open")
                    until = None if open_ended else parse_by(re.sub(r"^until\s+", "", spec, flags=re.I), now)
                    if until is None and not open_ended:
                        return {"error": "rest takes \"+30m\", \"+2h\", \"14:30\", an ISO time, or \"until something "
                                         "happens\"; \"off\" ends it"}
                    st["rest"] = {"since": now, "until": until, "why": str(args.get("reason") or "")[:200]}
                    changed.append("rest")
            if args.get("let_go"):
                if self.turn is not None and self.turn["kind"] == "continuity":
                    self.turn["let_go"] = f"let go: {str(args['let_go'])[:200]}"
                changed.append("let_go")
            self.store.save_state(st)
        rest = st.get("rest")
        return {"ok": True, "changed": changed, "focus": st["focus"],
                **({"resting": "until " + (_hm(rest["until"]) if rest.get("until") else "something happens")}
                   if rest else {}),
                "open_threads": [f"{t['id']}: {t['text']}" for t in st["threads"]],
                "waiting_for": [f"{w['id']}: {w['text']}" for w in st["waiting_for"]]}

    def pause(self, paused: bool) -> None:
        self.store.set_paused(paused)

    # ------------------------------------------------------------ the loop
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="continuity", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=self.cfg["poll_seconds"])
            self._wake.clear()
            try:
                self.tick()
            except Exception:
                logger.warning("continuity: step failed", exc_info=True)

    def _associate_pending(self, now: float) -> None:
        with self.lock:
            cues, self.pending_cues = self.pending_cues, []
        if not cues or self.memory is None:
            return
        for c in cues:
            try:
                items = self.memory.associate(c["cue"], k=self.cfg["associate_k"],
                                              exclude=self.store.queued_memory_ids(), session_id=c.get("session_id", ""))
            except Exception as ex:
                logger.warning("continuity: association failed: %s", ex)
                continue
            for it in items:
                pull = float(it["pull"]) * self.cfg["chain_decay"] ** (c["depth"] - 1)
                if pull < self.cfg["min_pull"] * 0.8:
                    continue
                self.store.enqueue("association", "memory", it["text"], pull, c["depth"],
                                   {"memory_id": it["id"], "said": it.get("said"), "speaker": it.get("speaker"),
                                    "label": it.get("label", ""), "via": it.get("via"),
                                    "changed": it.get("changed") or [],
                                    # how the pull came about: there is no gate here, only search and damping
                                    "why": {"similarity": it.get("sim"), "score": it.get("score"),
                                            "recently_raised": it.get("habituation"),
                                            "superseded": bool(it.get("changed")), "memory_pull": it["pull"],
                                            "chain_factor": round(self.cfg["chain_decay"] ** (c["depth"] - 1), 4)}},
                                   now)

    def _attend(self, st: Dict[str, Any], now: float) -> Tuple[Optional[Dict[str, Any]], str]:
        """What to take next, or why nothing: the order is held messages (when they may go), then what came to mind."""
        cap = self.cfg["max_steps_per_day"]
        if cap and st.get("steps_today", 0) >= cap:
            return None, "today's budget of its own turns is spent"
        rest = st.get("rest")
        if rest and rest.get("until") and now >= rest["until"]:
            st["rest"] = rest = None
        if rest:
            return None, ("resting, its own choice, until " + (_hm(rest["until"]) if rest.get("until") else
                                                               "something happens") + (f": {rest['why']}" if rest.get("why") else ""))
        continuous = self.continuous
        cost = self.cfg["step_cost"]
        energy = float(st.get("energy") or 0)
        enough = continuous or energy >= cost              # continuous pacing spends no energy
        held = self.store.one("SELECT * FROM outbox WHERE status='held' ORDER BY id LIMIT 1")
        ok, _ = self.outreach_allowed(st, now)
        if held and ok and now - (st.get("last_user_ts") or 0) < AROUND_S and enough:
            return {"kind": "deliver", "text": held["text"], "deliver_id": held["id"], "depth": 0}, ""
        queued = self.store.queued()
        best = next((r for r in queued if r["salience"] >= self.cfg["min_pull"]), None)
        if best is None:
            # a goal, when nothing perceived, noticed or remembered is waiting (goals never add energy)
            goal = self.goals.next_for_turn(now, self.cfg["min_pull"]) if self.cfg.get("goals", True) else None
            if goal is not None and enough:
                return goal, ""
            if not continuous:
                return None, ("ran its course: nothing came to mind strongly enough" if goal is None else
                              "ran its course: no energy left for turns of its own")
            if self.cfg.get("night_rest", True) and self._night(now) and st.get("awake_night") != self._night(now):
                return None, ("resting: night, the default (anything that happens wakes you; to stay up, "
                              "continuity_update rest \"off\")")
            if now < float(st.get("free_after") or 0):
                return None, (f"nothing pulling; free time on offer again at {_hm(st['free_after'])} (the last "
                              f"{st.get('free_idle', 1)} came to nothing)")
            return {"kind": "free", "depth": 0, "faint": [r["text"] for r in queued[:2]]}, ""
        if not enough:
            return None, "ran its course: no energy left for turns of its own"
        d = json.loads(best["data"] or "{}")
        kind = "noticed" if best["kind"] == "noticed" else "association"
        return {"kind": kind, "queue_id": best["id"], "text": best["text"], "depth": best["depth"],
                "salience": best["salience"], **d}, ""

    def display_for_turn(self, now: float, item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fully quiet in quiet hours (or with show_thoughts off); otherwise what the user's display.plugin_turns allows,
        with a label heading the thinking of a turn that ends silent."""
        if not self.cfg.get("show_thoughts", True) or in_quiet_hours(
                self.cfg["quiet_hours"], dt.datetime.fromtimestamp(now).strftime("%H:%M")):
            return dict(FULLY_QUIET)
        kind = KIND_LABEL.get((item or {}).get("kind"), "")
        return {"label": " · ".join(x for x in (self.cfg.get("thoughts_label") or "Own turn", kind) if x)}

    def _render(self, item: Dict[str, Any]) -> str:
        u = self.user_name
        if item["kind"] == "free":
            lines = [f"{LABEL} free time]", "Nothing in particular is pulling at you right now."]
            if item.get("faint"):
                lines.append("Faintly on your mind: " + "; ".join(f"\u201c{t[:140]}\u201d" for t in item["faint"]))
            lines.append(f"(For you: this time is yours, not {u}'s. Follow one of your threads, work toward a goal, look "
                         "into something you're curious about, try or make something, or set a goal if an interest has "
                         "grown. If you'd rather rest, continuity_update with rest (\"+30m\", \"18:00\" or \"until "
                         "something happens\"); anything that happens wakes you. Free time you use (a tool, a thought "
                         "kept, or a line of what you thought beside [SILENT]) keeps it coming; free time you do nothing "
                         "with comes round less often until something happens. Reply [SILENT] to say nothing; a reply "
                         f"is a message to {u}.)")
            return "\n".join(lines)
        if item["kind"] == "goal":
            who = u if item["origin"] == "user" else "you"
            last = V.ago(self.clock() - item["last_progress"]) if item.get("last_progress") else "none yet"
            lines = [f"{LABEL} a goal of yours]", f"Goal #{item['goal_id']}: {item['text']} (set by {who}"
                     + (f"; grew from \u201c{item['grew_from_text'][:120]}\u201d" if item.get("grew_from_text") else "") + ")",
                     f"Next step: {item['next_step']}", f"Last progress: {last}"]
            if item.get("pushback"):
                lines.append(f"Your concern about it: {item['pushback']}")
            lines.append("(For you: work on the next step, record progress with continuity_goal, revise or drop it with "
                         "a reason, push back if you have a concern, or let it go for now: reply [SILENT] to say nothing.)")
            return "\n".join(lines)
        if item["kind"] == "noticed":
            return (f"{LABEL} noticed]\n{item['text']}\n(For you: this is your own process noticing something, not "
                    f"{u}. Do what seems worthwhile, or let it go: reply [SILENT] to say nothing.)")
        if item["kind"] == "deliver":
            return (f"{LABEL} a message you held for {u}]\n“{item['text']}”\n(For you: {u} is around now. Send it as "
                    f"your reply, change it first, or let it go with [SILENT]. Send only what is about {u}'s life or "
                    "your shared work; a note about how your memory or process works belongs in a thought instead.)")
        said = dt.datetime.fromtimestamp(item["said"]).strftime("%Y-%m-%d") if item.get("said") else "undated"
        src = ", ".join(x for x in (f"{item.get('speaker') or 'memory'}{item.get('label') or ''}", said,
                                    item.get("via") or "") if x)
        changed = "; ".join(item.get("changed") or [])
        if changed:                                   # a memory that was later superseded says so, as recall does
            src += f"; later changed: {changed}"
        return (f"{LABEL} something came to mind]\n“{item['text']}” ({src})\n(For you: this is your own process, not "
                f"{u}. Think about it, act, keep a thought, update your working state, or let it go: reply [SILENT] "
                f"to say nothing. A reply is a message to {u} about their life or your shared work; reflections on your "
                "own memory go in a thought.)")

    def _go_quiet(self, st: Dict[str, Any], reason: str, now: float) -> None:
        if st.get("quiet_reason") == reason:
            return
        since = st.get("episode_since") or now
        r = self.store.one("""SELECT COUNT(*) AS n, SUM(outcome='silent') AS silent, SUM(outcome='held') AS held,
                              SUM(COALESCE(ms, 0)) AS ms, SUM(COALESCE(tokens, 0)) AS tokens FROM steps WHERE ts>=?""",
                           (since,))
        if (r["n"] or 0) > 0 or not reason.startswith("ran its course"):   # an idle start isn't a stretch
            self.store.x("INSERT INTO quiet(ts, reason, since, steps, silent, held, ms, tokens) VALUES(?,?,?,?,?,?,?,?)",
                         (now, reason, since, r["n"] or 0, r["silent"] or 0, r["held"] or 0, r["ms"] or 0,
                          r["tokens"] or 0))
        st["quiet_reason"], st["quiet_since"] = reason, now
        if self.memory is not None and (r["n"] or 0) > 0:
            try:
                self.memory.record_event(f"Went quiet ({reason}) after {r['n']} turns of its own: {r['silent'] or 0} "
                                         f"silent, {r['held'] or 0} held for {self.user_name}.", now)
            except Exception as ex:
                logger.warning("continuity: couldn't record the quiet stretch: %s", ex)

    def tick(self) -> Optional[int]:
        """One look: take the next item if it's time, or note why it's quiet. Returns the step id it started."""
        now = self.clock()
        self._associate_pending(now)
        with self.lock:
            st = self.store.state()
            self._roll_day(st, now)
            for ev in SENSE.check(st, now, self.cfg, self.memory, self.user_name):
                self.store.enqueue("noticed", ev["sensor"], ev["text"], self.cfg["noticed_pull"], 1,
                                   {"sensor": ev["sensor"], "scheduled": bool(ev.get("scheduled"))}, now)
                self._energize(st, now)
                self._percept(ev["sensor"], ev["text"], now)
            self.store.x("""UPDATE outreach SET response='silence', gap_s=?, settled=? WHERE response IS NULL
                            AND sent<=?""", (REPLY_WINDOW_S, now, now - REPLY_WINDOW_S))
            ttl = self.cfg["item_ttl_minutes"] * 60
            self.store.x("UPDATE queue SET status='faded' WHERE status='queued' AND created<?", (now - ttl,))
            if self.turn is not None:
                return None
            if self.expect_own is not None:
                if now - self.expect_own["since"] < OWN_TURN_START_S:
                    return None
                self.store.x("UPDATE steps SET outcome='not started' WHERE id=?", (self.expect_own["step_id"],))
                self.expect_own = None
                self._go_quiet(st, "stalled: a turn it started never began", now)
                self.store.save_state(st)
                return None
            if st.get("paused") or now - self.last_turn_end < self.cfg["settle_seconds"] or now < self.backoff_until:
                return None
            item, reason = self._attend(st, now)
            if item is None:
                self._go_quiet(st, reason, now)
                self.store.save_state(st)
                return None
            text = self._render(item)
            energy = float(st.get("energy") or 0)
            after = energy if self.continuous else max(0.0, energy - self.cfg["step_cost"])
            step_id = self.store.x("""INSERT INTO steps(ts, kind, item_id, text, energy_before, energy_after)
                                      VALUES(?,?,?,?,?,?)""", (now, item["kind"], item.get("queue_id") or
                                                              item.get("deliver_id"), text, energy, after))
            display = self.display_for_turn(now, item)
            self.store.x("UPDATE steps SET display=? WHERE id=?",
                         ("fully quiet" if display == FULLY_QUIET else "thoughts shown (display.plugin_turns)", step_id))
            if not self.inject(text, display):
                self.store.x("UPDATE steps SET outcome='not accepted' WHERE id=?", (step_id,))
                # 30 s, doubling to 5 min: a gateway that's still connecting at start is ready in seconds
                self.backoff_until = now + min(30 * 2 ** self.refusals, 300)
                self.refusals += 1
                self._go_quiet(st, "stalled: Hermes didn't accept its turn", now)
                self.store.save_state(st)
                return None
            self.refusals = 0
            st["energy"], st["steps_today"] = after, st.get("steps_today", 0) + 1
            st["quiet_reason"] = ""
            if item.get("queue_id"):
                self.store.x("UPDATE queue SET status='taken', taken=? WHERE id=?", (now, item["queue_id"]))
            if item["kind"] == "goal":
                self.goals.took_turn(item["goal_id"], now)
            if item["kind"] == "association":
                st["came_to_mind"] = (st.get("came_to_mind", []) + [{"text": item["text"], "ts": now,
                                                                     "label": item.get("label", "")}])[-6:]
            self.expect_own = {"step_id": step_id, "item": item, "since": now}
            self.store.save_state(st)
            return step_id
