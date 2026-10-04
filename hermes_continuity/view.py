"""The standing view: the agent's situation, delivered with every turn as a stream of frames.

A full frame now and then (and always after a compaction); in between, only what changed since the agent last
looked, with the old value; one line when nothing changed. Frames stay where they fell, so the context keeps its
order: the newest frame is always the latest thing seen. Every line says where it came from.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Tuple

# where an item came from
PERCEIVED, REMEMBERED, OWN = "perceived", "remembered", "own"


def ago(seconds: float) -> str:
    """Coarse on purpose: the view changes when the bucket changes, not every minute."""
    s = max(0.0, seconds)
    if s < 120:
        return "just now"
    if s < 15 * 60:
        return "a few minutes ago"
    if s < 50 * 60:
        return "under an hour ago"
    if s < 90 * 60:
        return "about an hour ago"
    if s < 6 * 3600:
        return "a few hours ago"
    if s < 20 * 3600:
        return "many hours ago"
    if s < 36 * 3600:
        return "about a day ago"
    if s < 6 * 86400:
        return f"{int(round(s / 86400))} days ago"
    return "over a week ago"


def part_of_day(t: dt.datetime) -> str:
    h = t.hour
    return ("night" if h < 5 else "early morning" if h < 8 else "morning" if h < 12 else "afternoon" if h < 17
            else "evening" if h < 22 else "night")


def clock(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def _hours(s: float) -> str:
    h = s / 3600
    return f"{round(h * 60)} min" if h < 1 else f"{round(h)} h" if h < 36 else f"{round(h / 24)} days"


def outreach_line(score: Dict[str, Any]) -> str:
    if not score or not score.get("sent"):
        return f"none sent yet (calibrates after {score.get('needed', 50) if score else 50})"
    gap = f", median reply after {_hours(score['median_reply_gap_s'])}" if score.get("median_reply_gap_s") else ""
    cal = "calibrated" if score["calibrated"] else f"not enough to act on yet ({score['sent']} of {score['needed']})"
    waiting = f", {score['waiting']} waiting" if score.get("waiting") else ""
    return (f"{score['sent']} sent: {score['reply']} replied, {score['not now']} not now, {score['silence']} silence"
            f"{waiting}{gap}; {cal}")


def scene(st: Dict[str, Any], now: float, user: str, held: List[str], queued: int,
          outreach: Dict[str, Any] = None, goals: List[Any] = None, pacing: str = "energy") -> Dict[str, Tuple[Any, str]]:
    """field -> (value, source). Values are short strings or lists of short strings."""
    out: Dict[str, Tuple[Any, str]] = {}
    out[user] = (f"last wrote {ago(now - st['last_user_ts'])}" if st.get("last_user_ts") else "hasn't written yet",
                 PERCEIVED)
    s = st.get("sensors") or {}
    if s.get("usual_gap") or s.get("morning_at"):
        bits = [f"usually starts around {s['morning_at']}" if s.get("morning_at") else "",
                f"about {_hours(s['usual_gap'])} between conversations" if s.get("usual_gap") else ""]
        out[f"{user}'s rhythm"] = ("; ".join(b for b in bits if b), PERCEIVED)
    jobs = [f"{j['text']} ({ago(now - j['ts'])})" for j in st.get("jobs", [])[-3:]]
    if jobs:
        out["finished jobs"] = (jobs, PERCEIVED)
    out["focus"] = (st.get("focus") or "nothing in particular", OWN)
    out["open threads"] = ([t["text"] for t in st.get("threads", [])[-5:]] or ["none"], OWN)
    if goals is not None:
        shown = []
        for g in goals:
            who = user if g["origin"] == "user" else "yours"
            if g["status"] == "declined":
                shown.append(f"#{g['id']} {g['text']} (declined: {g['decline_reason']})")
                continue
            last = f"last progress {ago(now - g['last_progress'])}" if g["last_progress"] else "no progress yet"
            shown.append(f"#{g['id']} {g['text']} ({who}; next: {g['next_step'] or '-'}; {last})"
                         + (f" \u2691 concern: {g['pushback']}" if g["pushback"] else ""))
        out["goals"] = (shown or ["none"], OWN)
    out["waiting for"] = ([w["text"] + (f" (by {clock(w['by'])})" if w.get("by") else "")
                           for w in st.get("waiting_for", [])[-5:]] or ["nothing"], OWN)
    minds = [f"“{c['text'][:120]}”{c.get('label', '')} ({ago(now - c['ts'])})"
             for c in st.get("came_to_mind", [])[-3:]]
    out["came to mind lately"] = (minds or ["nothing"], REMEMBERED)
    out[f"held for {user}"] = ([f"“{h[:100]}”" for h in held[:3]] or ["nothing"], OWN)
    if outreach is not None:
        out["your reaching out"] = (outreach_line(outreach), PERCEIVED)
    waiting = f"{queued} thing{'s' if queued != 1 else ''} waiting to come to mind"
    if pacing == "energy":
        e = float(st.get("energy") or 0.0)
        level = "rested" if e < 0.34 else "low" if e < 1.0 else "moderate" if e < 2.0 else "high"
        out["energy"] = (f"{level} ({e:.1f}), {waiting}", PERCEIVED)
    else:
        out["on your mind"] = (waiting, PERCEIVED)
    rest = st.get("rest")
    if rest:
        out["resting"] = ("your choice, until " + (clock(rest["until"]) if rest.get("until") else "something happens")
                          + (f": {rest['why']}" if rest.get("why") else ""), OWN)
    if st.get("paused"):
        out["paused"] = (f"yes, by {user}", PERCEIVED)
    elif st.get("quiet_reason"):
        out["quiet"] = (st["quiet_reason"], PERCEIVED)
    return out


def _fmt(value: Any) -> str:
    return "; ".join(value) if isinstance(value, list) else str(value)


def render_full(sc: Dict[str, Tuple[Any, str]], now: float) -> str:
    t = dt.datetime.fromtimestamp(now)
    lines = [f"[standing view · full · {t.strftime('%a %Y-%m-%d %H:%M')}, {part_of_day(t)}]"]
    for k, (v, src) in sc.items():
        lines.append(f"{k}: {_fmt(v)} ({src})")
    lines.append("Only the latest standing view is current; older ones show what you saw then.")
    return "\n".join(lines)


_EMPTY = {"nothing", "none"}
# An item's age changes as time passes; that alone isn't a change in what's there
_AGE = re.compile(r" \((?:just now|a few minutes ago|under an hour ago|about an hour ago|a few hours ago|many hours ago|"
                  r"about a day ago|\d+ days ago|over a week ago)\)$")


def _same(x: str) -> str:
    return _AGE.sub("", x) if isinstance(x, str) else x


def diff(old: Dict[str, Any], new: Dict[str, Tuple[Any, str]]) -> List[str]:
    """Changes since the last frame shown, with the old value: "x: a → b", "+ item", "− item"."""
    out = []
    for k, (v, src) in new.items():
        before = old.get(k, [None])[0] if isinstance(old.get(k), (list, tuple)) else None
        if before == v:
            continue
        if isinstance(v, list) and isinstance(before, list):
            was = {_same(x) for x in before}
            now_ = {_same(x) for x in v}
            added = [x for x in v if _same(x) not in was and x not in _EMPTY]
            gone = [x for x in before if _same(x) not in now_ and x not in _EMPTY]
            bits = [f"+ {x}" for x in added] + [f"− {x}" for x in gone]
            if bits:
                out.append(f"{k}: {'; '.join(bits)} ({src})")
        elif before is None:
            out.append(f"{k}: {_fmt(v)} ({src})")
        else:
            out.append(f"{k}: {_fmt(before)} → {_fmt(v)} ({src})")
    for k in old:
        if k not in new:
            out.append(f"{k}: ended" if k in ("quiet", "paused") else f"{k}: no longer shown")
    return out


def render_change(old: Dict[str, Any], sc: Dict[str, Tuple[Any, str]], since: float, now: float) -> str:
    t = dt.datetime.fromtimestamp(now)
    changes = diff(old, sc)
    if not changes:
        return f"[standing view · {t.strftime('%a %H:%M')}, {part_of_day(t)} · unchanged since {clock(since)}]"
    head = f"[standing view · changes since {clock(since)} · now {t.strftime('%a %H:%M')}, {part_of_day(t)}]"
    return "\n".join([head, *changes])


def as_stored(sc: Dict[str, Tuple[Any, str]]) -> Dict[str, Any]:
    return {k: [v, src] for k, (v, src) in sc.items()}
