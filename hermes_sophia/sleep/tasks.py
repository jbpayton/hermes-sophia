"""Task memory, at night: split the action log into tasks, judge how each turned out, and write a card.

A card is assembled by code from the logged actions. The night model only points at them by number ("a3, a5
worked; a1 was a dead end because …"), so a card can never contain a step the agent didn't take.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ..store import sha
from .. import text as T

OUTCOMES = {"succeeded": "The task was done and it worked.",
            "failed": "The task was attempted and did not work.",
            "partly": "Part of the task worked; part did not or was left undone.",
            "abandoned": "The task was dropped or given up before it was finished.",
            "unclear": "The evidence doesn't show whether it worked."}

CONTINUES = ("The new request continues the same task as the earlier one (a retry, a fix, a correction or the next "
             "step toward the same goal) rather than starting a different task.")

CARD_PROMPT = """You are writing a task card for an agent's memory: what was done, what worked, and what didn't.
The request and the agent's numbered actions (a1, a2, ...) are below, each with its result.
Refer to actions only by their numbers. Never write commands yourself.

Output exactly these lines and nothing else:
GOAL: <the task in one short line>
WHERE: <the host, repository, directory or service it was done on, or ->
WORKED: <the actions that made up the working path, in order, e.g. a3, a5 - or - if nothing worked>
DEAD ENDS: <failed or discarded actions, each with a few words on why, e.g. a1: permission denied; a2: wrong path - or ->
LEARNED FROM: <actions that read documentation or a web page, and the actions they informed, e.g. a4 -> a5 - or ->
LESSON: <one line worth remembering next time, or ->

Request: {request}
Outcome: {outcome}
Actions:
{actions}
Agent's reply: {reply}
User's reaction: {reaction}"""

_ID = re.compile(r"\ba(\d+)\b")
_ARROW = re.compile(r"(a\d+(?:\s*,\s*a\d+)*)\s*->\s*(a\d+(?:\s*,\s*a\d+)*)")
_READ_TOOLS = ("web_extract", "web_search", "browser", "read_file", "fetch")


def step_text(tool: str, args: Dict[str, Any], limit: int = 240) -> str:
    """How a logged action reads in a card: the command itself when there is one."""
    for k in ("command", "code", "script"):
        if isinstance(args.get(k), str):
            return args[k][:limit]
    if args:
        inner = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)[:80]}" for k, v in list(args.items())[:4])
        return f"{tool}({inner})"[:limit]
    return f"{tool}()"


def _status(a) -> str:
    if a["error"]:
        return f"error (exit {a['exit_code']})" if a["exit_code"] not in (None, 0) else "error"
    return "ok" if a["exit_code"] in (None, 0) else f"exit {a['exit_code']}"


def _excerpt(a, n: int = 220) -> str:
    body = (a["result_head"] or "").strip()
    if a["result_tail"]:
        body = body[:n // 2] + " … " + a["result_tail"].strip()[-n // 2:]
    return re.sub(r"\s+", " ", body)[:n]


class TaskPass:
    def __init__(self, runner):
        self.r, self.s, self.e, self.cfg = runner, runner.s, runner.e, runner.cfg

    # ------------------------------------------------------------- segment
    def groups(self) -> List[List[Any]]:
        rows = self.s.q("""SELECT * FROM actions WHERE task_id IS NULL AND said<=?
                           ORDER BY session_id, said, seq""", (self.r.snapshot,))
        out: List[List[Any]] = []
        for a in rows:
            if out and out[-1][0]["session_id"] == a["session_id"] and out[-1][0]["request_ref"] == a["request_ref"]:
                out[-1].append(a)
            else:
                out.append([a])
        return out

    def merge(self, groups: List[List[Any]]) -> Tuple[List[List[Any]], int]:
        merged, calls = [], 0
        for g in groups:
            prev = merged[-1] if merged else None
            if prev and prev[0]["session_id"] == g[0]["session_id"] and g[0]["request_text"]:
                state = {"earlier_request": prev[0]["request_text"],
                         "earlier_steps": [f"{a['tool']}: {step_text(a['tool'], json.loads(a['args'] or '{}'), 100)} "
                                           f"-> {_status(a)}" for a in prev[-4:]],
                         "new_request": g[0]["request_text"]}
                calls += 1
                if self.r.judge(state, CONTINUES) >= 0.5:
                    prev.extend(g)
                    continue
            merged.append(g)
        return merged, calls

    # ----------------------------------------------------------- evidence
    def _said_by(self, session_id: str, speaker: str, after: float, before: Optional[float] = None) -> str:
        rows = self.s.q("""SELECT ref, text FROM windows WHERE session_id=? AND speaker=? AND said>=?
                           AND (? IS NULL OR said<?) ORDER BY said, id LIMIT 6""",
                        (session_id, speaker, after, before, before))
        if not rows:
            return ""
        first = rows[0]["ref"]
        return " ".join(r["text"] for r in rows if r["ref"] == first)[:800]

    def evidence(self, task: List[Any]) -> Dict[str, Any]:
        last = task[-1]["said"]
        reply = self._said_by(task[0]["session_id"], self.cfg["agent_name"], last)
        rrow = self.s.one("""SELECT said FROM windows WHERE session_id=? AND speaker=? AND said>=? ORDER BY said LIMIT 1""",
                          (task[0]["session_id"], self.cfg["agent_name"], last))
        reaction = self._said_by(task[0]["session_id"], self.cfg["user_name"], (rrow["said"] if rrow else last) + 1e-6)
        lines = [f"a{i + 1} {a['tool']}: {step_text(a['tool'], json.loads(a['args'] or '{}'))} -> {_status(a)}: "
                 f"{_excerpt(a)}" for i, a in enumerate(task)]
        return {"request": task[0]["request_text"] or "(no request text)", "actions": lines,
                "reply": reply or "-", "reaction": reaction or "-"}

    # --------------------------------------------------------------- card
    @staticmethod
    def parse_card(text: str, n: int) -> Dict[str, Any]:
        fields = {}
        for line in (text or "").splitlines():
            m = re.match(r"\s*(GOAL|WHERE|WORKED|DEAD ENDS|LEARNED FROM|LESSON)\s*:\s*(.*)$", line, re.I)
            if m:
                fields[m.group(1).upper()] = m.group(2).strip()

        def ids(s: str) -> List[int]:
            return [i for i in (int(x) - 1 for x in _ID.findall(s or "")) if 0 <= i < n]

        dead = []
        for part in re.split(r";", fields.get("DEAD ENDS", "")):
            got = ids(part)
            if got:
                why = re.sub(r"^\s*(a\d+\s*,?\s*)+[:\-–]?\s*", "", part.strip())
                dead.extend((i, why) for i in got)
        learned = [(i, ids(m.group(2))) for m in _ARROW.finditer(fields.get("LEARNED FROM", "")) for i in ids(m.group(1))]
        def clean(v: Optional[str]) -> str:
            v = (v or "").strip().strip("`")
            return "" if v.lower() in ("", "-", "->", "—", "none", "n/a", "terminal", "shell", "unknown") else v
        return {"goal": clean(fields.get("GOAL")), "where": clean(fields.get("WHERE")),
                "worked": ids(fields.get("WORKED", "")), "dead": dead, "learned": learned,
                "lesson": clean(fields.get("LESSON"))}

    def build_card(self, task: List[Any], parsed: Dict[str, Any], outcome: str, ev: Dict[str, Any]) -> Dict[str, Any]:
        def step(i: int) -> Dict[str, Any]:
            a = task[i]
            args = json.loads(a["args"] or "{}")
            return {"action": a["id"], "tool": a["tool"], "step": step_text(a["tool"], args), "status": _status(a)}

        worked = parsed["worked"]
        if not worked and outcome in ("succeeded", "partly"):
            worked = [i for i, a in enumerate(task) if not a["error"]]         # the night said nothing: keep what ran
        dead_ids = {i for i, _ in parsed["dead"]}
        if outcome == "failed":
            dead_ids |= {i for i, a in enumerate(task) if a["error"]}
        sources = []
        for i, a in enumerate(task):
            if any(t in (a["tool"] or "") for t in _READ_TOOLS):
                args = json.loads(a["args"] or "{}")
                url = args.get("url") or (args.get("urls") or [None])[0] or args.get("path") or args.get("query")
                informed = next((d for s_, d in parsed["learned"] if s_ == i), [])
                if url:
                    sources.append({"source": str(url)[:300], "action": a["id"], "informed": [task[j]["id"] for j in informed]})
        return {"goal": parsed["goal"] or (ev["request"][:160]), "where": parsed["where"], "outcome": outcome,
                "worked": [step(i) for i in worked],
                "dead_ends": [dict(step(i), why=next((w for j, w in parsed["dead"] if j == i), "")) for i in sorted(dead_ids)
                              if i not in worked],
                "sources": sources, "lesson": parsed["lesson"], "reaction": ev["reaction"][:300]}

    @staticmethod
    def card_text(card: Dict[str, Any], date: str) -> str:
        where = f" ({card['where']})" if card["where"] else ""
        parts = [f"{card['goal']}{where} — {card['outcome']} on {date}."]
        if card["worked"]:
            parts.append("Worked: " + " → ".join(f"`{s['step']}`" for s in card["worked"]) + ".")
        if card["dead_ends"]:
            parts.append("Dead ends: " + "; ".join(f"`{d['step']}`" + (f" ({d['why']})" if d["why"] else f" ({d['status']})")
                                                  for d in card["dead_ends"]) + ".")
        if card["sources"]:
            parts.append("Learned from: " + ", ".join(s["source"] for s in card["sources"]) + ".")
        if card["lesson"]:
            parts.append(f"Lesson: {card['lesson']}")
        return " ".join(parts)

    # ---------------------------------------------------------------- run
    def run(self) -> Dict[str, Any]:
        groups = self.groups()
        tasks, calls = self.merge(groups)
        made = {"tasks": 0, "succeeded": 0, "failed": 0, "reused": 0, "calls": calls}
        texts, ids = [], []
        for task in tasks:
            if self.r.limit and made["tasks"] >= self.r.limit:
                break
            ev = self.evidence(task)
            self.r.wait_idle()
            ans = self.r.teacher.choice(ev, "How did the task turn out?", OUTCOMES, permutations=2)
            outcome = ans.choice
            parsed = self.parse_card(self.r.llm(CARD_PROMPT.format(
                request=ev["request"], outcome=outcome, actions="\n".join(ev["actions"]), reply=ev["reply"],
                reaction=ev["reaction"]), max_tokens=400), len(task))
            card = self.build_card(task, parsed, outcome, ev)
            first, last = task[0]["said"], task[-1]["said"]
            tid = sha("task", task[0]["session_id"], task[0]["id"])
            date = time.strftime("%Y-%m-%d", time.localtime(last))
            text = self.card_text(card, date)
            card["text"] = text
            self.s.x("""INSERT OR REPLACE INTO tasks(id,session_id,request_ref,goal,outcome,confidence,card,first_said,
                        last_said,n_actions,night_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (tid, task[0]["session_id"], task[0]["request_ref"], card["goal"], outcome,
                      round(ans.confidence, 3), json.dumps(card, ensure_ascii=False), first, last, len(task),
                      self.r.night, time.time()))
            self.s.xmany("UPDATE actions SET task_id=? WHERE id=?", [(tid, a["id"]) for a in task])
            links = [(tid, "request", task[0]["request_ref"])] + [(tid, "source", s["source"]) for s in card["sources"]]
            for name in T.names_in(" ".join([card["goal"], card["where"]])):
                links.append((tid, "entity", T.norm_entity(name)))
            self.s.xmany("INSERT OR IGNORE INTO task_links(task_id,kind,target) VALUES(?,?,?)", links)
            self.s.journal(self.r.night, "tasks", f"task_{outcome}", {"task": tid, "goal": card["goal"],
                                                                     "steps": len(card["worked"])})
            made["reused"] += self.credit_reuse(tid, task, card, outcome)
            texts.append(text)
            ids.append(tid)
            made["tasks"] += 1
            made[outcome] = made.get(outcome, 0) + 1
        if ids:
            vecs = self.e.embed(texts, "document")
            self.s.set_vectors("task", ids, vecs, self.cfg["embed_model"])
            for tid, text in zip(ids, texts):
                self.s.fts_put(tid, "task", text)
            self.link_attempts(ids, vecs)
        return made

    # ------------------------------------------------------------- graph
    def link_attempts(self, ids: List[str], vecs) -> None:
        """Earlier cards for the same goal become the attempt history of a new one."""
        idx = self.s.index("task", self.cfg["embed_model"])
        for tid, v in zip(ids, vecs):
            me = self.s.one("SELECT first_said FROM tasks WHERE id=?", (tid,))
            for other, sim in idx.search(v, 6):
                if other == tid or sim < 0.8:
                    continue
                o = self.s.one("SELECT first_said FROM tasks WHERE id=?", (other,))
                if o and o["first_said"] < me["first_said"]:
                    self.s.x("INSERT OR IGNORE INTO task_links(task_id,kind,target) VALUES(?,?,?)", (tid, "earlier", other))

    # ------------------------------------------------------------ credit
    def credit_reuse(self, tid: str, task: List[Any], card: Dict[str, Any], outcome: str) -> int:
        """A card injected before this task whose steps were followed again earns real credit (or loses it)."""
        inj = self.s.q("SELECT items FROM injections WHERE session_id=? AND said<=?",
                       (task[0]["session_id"], task[0]["said"]))
        shown = {it["id"] for r in inj for it in json.loads(r["items"] or "[]") if it.get("kind") == "task"}
        if not shown or outcome not in ("succeeded", "failed"):
            return 0
        done = [T.shingles(step_text(a["tool"], json.loads(a["args"] or "{}"))) for a in task]
        n = 0
        for old in shown:
            row = self.s.one("SELECT card FROM tasks WHERE id=?", (old,))
            if not row:
                continue
            steps = [T.shingles(s["step"]) for s in json.loads(row["card"]).get("worked", [])]
            if any(st and d and len(st & d) / len(st) >= 0.6 for st in steps for d in done):
                delta = 1.0 if outcome == "succeeded" else -2.0
                self.s.add_credit(old, "task", "real", "reused_" + outcome, delta, self.r.night)
                self.s.journal(self.r.night, "tasks", "card_reused", {"card": old, "by": tid, "outcome": outcome})
                n += 1
        return n
