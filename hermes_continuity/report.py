"""What the continuing process is doing, in one place: for ``hermes continuity report`` and the Sophia tab.

Read-only. Built so that whoever watches it (Joey, or the agent it would run on) can tell at a glance whether a
quiet stretch was the right kind of quiet, what's waiting and why it pulls as hard as it does, what it held back,
and how much of each turn's context the standing view takes.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import view as V

HEALTHY = ("ran its course", "today's budget", "resting", "nothing pulling")          # quiet for the right reasons; anything "stalled" is to chase
AROUND_S = 2 * 3600


def _reader(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _d(ts: Optional[float]) -> Optional[str]:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else None


def build(path: Path, cfg: Dict[str, Any], user: str = "the user", now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    path = Path(path)
    if not path.exists():
        return {"exists": False, "path": str(path)}
    c = _reader(path)
    try:
        meta = {r["key"]: json.loads(r["value"]) for r in c.execute("SELECT key, value FROM meta")}
        st = meta.get("state", {})
        paused = bool(meta.get("paused"))
        midnight = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        steps_today = c.execute("SELECT outcome, ms, tokens FROM steps WHERE ts>=?", (midnight,)).fetchall()
        outcomes = Counter((r["outcome"] or "running") for r in steps_today)
        quiet_reason = st.get("quiet_reason") or ""
        quiet = {"reason": quiet_reason or None, "since": _d(st.get("quiet_since")) if quiet_reason else None,
                 "kind": None if not quiet_reason else "healthy" if quiet_reason.startswith(HEALTHY) else "chase"}

        queued = c.execute("SELECT * FROM queue WHERE status='queued' ORDER BY salience DESC, id").fetchall()
        ttl = cfg["item_ttl_minutes"] * 60
        queue = []
        for r in queued[:12]:
            data = json.loads(r["data"] or "{}")
            queue.append({"id": r["id"], "text": r["text"], "pull": round(r["salience"], 3),
                          "clears_threshold": r["salience"] >= cfg["min_pull"], "depth": r["depth"],
                          "age_min": round((now - r["created"]) / 60), "fades_in_min": max(0, round((r["created"] + ttl - now) / 60)),
                          "superseded": bool(data.get("changed")), "changed": data.get("changed") or [],
                          "speaker": data.get("speaker"), "said": _d(data.get("said")), "via": data.get("via"),
                          "why": data.get("why")})

        last_user = st.get("last_user_ts") or 0
        held = [{"id": r["id"], "created": _d(r["created"]), "reason": r["reason"], "text": r["text"]}
                for r in c.execute("SELECT * FROM outbox WHERE status='held' ORDER BY id")]
        sent_today = c.execute("SELECT COUNT(*) AS n FROM outbox WHERE status='sent' AND settled>=?", (midnight,)).fetchone()["n"]

        journal: List[Dict[str, Any]] = []
        has_outcomes = "outcomes" in {r[1] for r in c.execute("PRAGMA table_info(steps)")}
        oc_col = "outcomes" if has_outcomes else "NULL"
        disp_col = "display" if "display" in {r[1] for r in c.execute("PRAGMA table_info(steps)")} else "NULL"
        for r in c.execute(f"""SELECT 'turn' AS what, ts, kind, outcome, reason, ms, text, NULL AS steps, NULL AS silent,
                                     NULL AS held, context_chars, reply_chars, {oc_col} AS outcomes,
                                     {disp_col} AS display FROM steps
                              UNION ALL SELECT 'quiet', ts, NULL, NULL, reason, ms, NULL, steps, silent, held, tokens, NULL,
                              NULL, NULL FROM quiet ORDER BY ts DESC LIMIT 16"""):
            if r["what"] == "turn":
                lines = (r["text"] or "").splitlines()
                journal.append({"what": "turn", "at": _d(r["ts"]), "kind": r["kind"], "outcome": r["outcome"] or "running",
                                "reason": r["reason"], "seconds": round((r["ms"] or 0) / 1000, 1),
                                "item": lines[1][:160] if len(lines) > 1 else "", "context_chars": r["context_chars"],
                                "reply_chars": r["reply_chars"], "led_to": json.loads(r["outcomes"] or "[]"),
                                "display": r["display"]})
            else:
                journal.append({"what": "quiet", "at": _d(r["ts"]), "reason": r["reason"], "turns": r["steps"],
                                "silent": r["silent"] or 0, "held": r["held"] or 0,
                                "model_seconds": round((r["ms"] or 0) / 1000, 1), "tokens": r["context_chars"] or 0,
                                "kind": "healthy" if (r["reason"] or "").startswith(HEALTHY) else "chase"})

        sent_rows = c.execute("SELECT * FROM outreach ORDER BY id").fetchall() if c.execute(
            "SELECT 1 FROM sqlite_master WHERE name='outreach'").fetchone() else []
        by_kind: Dict[str, Dict[str, Any]] = {}
        for o in sent_rows:
            k = by_kind.setdefault(o["kind"] or "?", {"sent": 0, "reply": 0, "not now": 0, "silence": 0, "waiting": 0,
                                                       "reply_gaps_min": []})
            k["sent"] += 1
            k[o["response"] or "waiting"] += 1
            if o["response"] == "reply" and o["gap_s"] is not None:
                k["reply_gaps_min"].append(round(o["gap_s"] / 60))
        outreach = {"sent": len(sent_rows), "needed": 50, "calibrated": len(sent_rows) >= 50, "by_kind": by_kind,
                    "recent": [{"sent": _d(o["sent"]), "kind": o["kind"], "response": o["response"] or "waiting",
                                "gap_min": round(o["gap_s"] / 60) if o["gap_s"] is not None else None,
                                "text": (o["text"] or "")[:160]} for o in sent_rows[-6:]]}
        has_goals = c.execute("SELECT 1 FROM sqlite_master WHERE name='goals'").fetchone()
        goals = [{"id": g["id"], "text": g["text"], "origin": g["origin"], "status": g["status"],
                  "next_step": g["next_step"], "grew_from": g["grew_from_text"], "last_progress": _d(g["last_progress"]),
                  "pushback": g["pushback"], "declined": g["decline_reason"]}
                 for g in c.execute("SELECT * FROM goals ORDER BY (status='active') DESC, (origin='user') DESC, id DESC "
                                    "LIMIT 12")] if has_goals else []
        goal_events = [{"at": _d(e["ts"]), "goal": e["goal_id"], "kind": e["kind"], "by": e["by"], "note": e["note"]}
                       for e in c.execute("SELECT * FROM goal_events ORDER BY id DESC LIMIT 8")] if has_goals else []
        frames = c.execute("SELECT * FROM frames ORDER BY id DESC LIMIT 20").fetchall()
        # the frame's share of the real prompt: its characters at about 4 per token, against the prompt tokens the
        # model reported for that turn's first call (system prompt and tools included)
        fills = [(r["chars"] / 4) / r["prompt_tokens"] for r in frames if r["prompt_tokens"]]
        frame_rows = [{"at": _d(r["ts"]), "kind": r["kind"], "chars": r["chars"], "turn": r["turn_kind"],
                       "prompt_tokens": r["prompt_tokens"],
                       "fill": round((r["chars"] / 4) / r["prompt_tokens"], 4) if r["prompt_tokens"] else None}
                      for r in frames[:12]]
        kinds = Counter(r["kind"] for r in frames)
        last_full = c.execute("SELECT text, ts FROM frames WHERE kind='full' ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "exists": True, "path": str(path), "now": _d(now), "paused": paused,
            "energy": round(float(st.get("energy") or 0), 2), "step_cost": cfg["step_cost"], "min_pull": cfg["min_pull"],
            "pacing": cfg.get("pacing", "continuous"), "rest": st.get("rest"),
            "quiet": quiet,
            # the number the budget gate uses (the state's counter), and every turn row since midnight
            "today": {"turns": st.get("steps_today", 0) if st.get("day") == dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d")
                      else 0, "rows": len(steps_today), "budget": cfg["max_steps_per_day"], "outcomes": dict(outcomes),
                      "model_seconds": round(sum((r["ms"] or 0) for r in steps_today) / 1000, 1),
                      "tokens": sum((r["tokens"] or 0) for r in steps_today),
                      "outreach_sent": sent_today, "outreach_limit": cfg["max_outreach_per_day"],
                      "outreach": "on" if cfg["outreach"] else "off", "quiet_hours": cfg["quiet_hours"]},
            "user": {"name": user, "last_wrote": _d(last_user) if last_user else None,
                     "ago": V.ago(now - last_user) if last_user else None,
                     "around": bool(last_user) and now - last_user < AROUND_S},
            "working_state": {"focus": st.get("focus") or None,
                              "threads": [t["text"] for t in st.get("threads", [])],
                              "waiting_for": [w["text"] for w in st.get("waiting_for", [])],
                              "came_to_mind": [{"text": m["text"], "at": _d(m["ts"])} for m in st.get("came_to_mind", [])[-5:]]},
            "queue": {"waiting": len(queued), "top": queue},
            "outbox": {"held": held},
            "outreach": outreach,
            "goals": {"list": goals, "events": goal_events},
            "journal": journal,
            "frames": {"recent": frame_rows, "kinds": dict(kinds), "full_every": cfg["full_frame_every"],
                       "mean_fill": round(sum(fills) / len(fills), 4) if fills else None,
                       "max_fill": round(max(fills), 4) if fills else None,
                       "latest": frames[0]["text"] if frames else None,
                       "latest_full": last_full["text"] if last_full else None},
            "settings": {k: cfg[k] for k in ("enabled", "view", "platform", "outreach", "quiet_hours", "pacing",
                                             "max_steps_per_day",
                                             "energy_per_event", "step_cost", "energy_max", "min_pull", "chain_decay",
                                             "item_ttl_minutes", "settle_seconds", "full_frame_every")},
        }
    finally:
        c.close()


def text(rep: Dict[str, Any]) -> str:
    """The same report, for a terminal (or an agent reading it)."""
    if not rep.get("exists"):
        return f"No continuity store at {rep.get('path')}: the companion hasn't run on this profile."
    t, q, u = rep["today"], rep["quiet"], rep["user"]
    out = [f"Continuity report · {rep['now']}" + (" · PAUSED" if rep["paused"] else "")]
    pace = ("pacing continuous" if rep.get("pacing", "energy") != "energy"
            else f"energy {rep['energy']} (a turn costs {rep['step_cost']})")
    out.append(pace + (f" · quiet: {q['reason']} [{q['kind']}] since {q['since']}" if q["reason"] else " · active"))
    oc = ", ".join(f"{n} {k}" for k, n in sorted(t["outcomes"].items(), key=lambda kv: -kv[1])) or "none"
    rows = f", {t['rows']} turn rows in the journal" if t.get("rows", t["turns"]) != t["turns"] else ""
    counted = (f"{t['turns']}/{t['budget']} turns of its own counted against the budget" if t["budget"]
               else f"{t['turns']} turns of its own")
    out.append(f"today: {counted}{rows} ({oc}); "
               f"{t['model_seconds']}s of model time, "
               f"{t['tokens']} tokens; "
               f"outreach {t['outreach']}, {t['outreach_sent']}/{t['outreach_limit']} sent, quiet hours {t['quiet_hours']}")
    out.append(f"{u['name']}: " + (f"last wrote {u['ago']} ({u['last_wrote']}), {'around' if u['around'] else 'not around'}"
                                   if u["last_wrote"] else "hasn't written yet"))
    ws = rep["working_state"]
    out.append(f"focus: {ws['focus'] or '-'} · threads: {'; '.join(ws['threads']) or '-'} · waiting for: "
               f"{'; '.join(ws['waiting_for']) or '-'}")
    out.append(f"\nqueue: {rep['queue']['waiting']} waiting (a turn needs pull >= {rep['min_pull']})")
    for it in rep["queue"]["top"]:
        w = it.get("why") or {}
        bits = [f"pull {it['pull']}" + ("" if it["clears_threshold"] else " (below)"), f"depth {it['depth']}",
                f"{it['age_min']} min old, fades in {it['fades_in_min']}"]
        if it["superseded"]:
            bits.append("SUPERSEDED: " + "; ".join(it["changed"]))
        if w:
            bits.append(f"similarity {w.get('similarity')}, recently raised {w.get('recently_raised')}, "
                        f"chain x{w.get('chain_factor')}")
        out.append(f"  - “{it['text'][:100]}”  [{' · '.join(bits)}]")
    o = rep.get("outreach") or {}
    out.append(f"\nreaching out: {o.get('sent', 0)} sent" + ("" if o.get("calibrated") else
                                                             f" (not enough to act on until {o.get('needed', 50)})"))
    for kind, k in (o.get("by_kind") or {}).items():
        gaps = ", ".join(f"+{g}m" for g in k["reply_gaps_min"][-5:])
        out.append(f"  {kind}: {k['sent']} sent, {k['reply']} replied{(' (' + gaps + ')') if gaps else ''}, "
                   f"{k['not now']} not now, {k['silence']} silence" + (f", {k['waiting']} waiting" if k["waiting"] else ""))
    gl = (rep.get("goals") or {}).get("list") or []
    out.append(f"\ngoals: {sum(1 for g in gl if g['status'] == 'active')} active")
    for g in gl[:6]:
        out.append(f"  #{g['id']} [{g['status']}] ({'set by ' + u['name'] if g['origin'] == 'user' else 'its own'}) "
                   f"{g['text']} · next: {g['next_step'] or '-'} · last progress: {g['last_progress'] or 'none'}"
                   + (f" · ⚑ {g['pushback']}" if g["pushback"] else "") + (f" · declined: {g['declined']}" if g["declined"] else ""))
    out.append(f"\nheld for {u['name']}: {len(rep['outbox']['held'])}")
    for m in rep["outbox"]["held"][:5]:
        out.append(f"  #{m['id']} {m['created']} ({m['reason']}): {m['text'][:160]}")
    out.append("\njournal (newest last):")
    for j in reversed(rep["journal"]):
        if j["what"] == "turn":
            out.append(f"  {j['at']}  turn  {j['kind']:<11} {j['outcome']:<12} {j['seconds']:>5}s  {j['item'][:80]}"
                       + (f"  [{j['reason']}]" if j["reason"] else "")
                       + (f"  → {', '.join(j['led_to'])}" if j.get("led_to") else "")
                       + ("  [shown: fully quiet]" if j.get("display") == "fully quiet" else ""))
        else:
            out.append(f"  {j['at']}  quiet [{j['kind']}] {j['reason']} ({j['turns']} turns: {j['silent']} silent, "
                       f"{j['held']} held; {j['model_seconds']}s, {j['tokens']} tokens)")
    f = rep["frames"]
    fill = f"mean {f['mean_fill']:.1%}, max {f['max_fill']:.1%}" if f["mean_fill"] is not None else "not measured yet"
    out.append(f"\nframes: {f['kinds']} (full every {f['full_every']}); share of each turn's prompt: {fill}")
    return "\n".join(out)
