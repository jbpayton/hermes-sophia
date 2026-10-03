"""The standing view: the agent's situation, delivered with every turn as a stream of frames.

A full frame now and then (and always after a compaction); in between, only what changed since the agent last
looked, with the old value; one line when nothing changed. Frames stay where they fell, so the context keeps its
order: the newest frame is always the latest thing seen. Every line says where it came from.
"""
from __future__ import annotations

import datetime as dt
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


def scene(st: Dict[str, Any], now: float, user: str, held: List[str], queued: int) -> Dict[str, Tuple[Any, str]]:
    """field -> (value, source). Values are short strings or lists of short strings."""
    out: Dict[str, Tuple[Any, str]] = {}
    out[user] = (f"last wrote {ago(now - st['last_user_ts'])}" if st.get("last_user_ts") else "hasn't written yet",
                 PERCEIVED)
    jobs = [f"{j['text']} ({ago(now - j['ts'])})" for j in st.get("jobs", [])[-3:]]
    if jobs:
        out["finished jobs"] = (jobs, PERCEIVED)
    out["focus"] = (st.get("focus") or "nothing in particular", OWN)
    out["open threads"] = ([t["text"] for t in st.get("threads", [])[-5:]] or ["none"], OWN)
    out["waiting for"] = ([w["text"] for w in st.get("waiting_for", [])[-5:]] or ["nothing"], OWN)
    minds = [f"“{c['text'][:120]}”{c.get('label', '')} ({ago(now - c['ts'])})"
             for c in st.get("came_to_mind", [])[-3:]]
    out["came to mind lately"] = (minds or ["nothing"], REMEMBERED)
    out[f"held for {user}"] = ([f"“{h[:100]}”" for h in held[:3]] or ["nothing"], OWN)
    e = float(st.get("energy") or 0.0)
    level = "rested" if e < 0.34 else "low" if e < 1.0 else "moderate" if e < 2.0 else "high"
    out["energy"] = (f"{level} ({e:.1f}), {queued} thing{'s' if queued != 1 else ''} waiting to come to mind", PERCEIVED)
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


def diff(old: Dict[str, Any], new: Dict[str, Tuple[Any, str]]) -> List[str]:
    """Changes since the last frame shown, with the old value: "x: a → b", "+ item", "− item"."""
    out = []
    for k, (v, src) in new.items():
        before = old.get(k, [None])[0] if isinstance(old.get(k), (list, tuple)) else None
        if before == v:
            continue
        if isinstance(v, list) and isinstance(before, list):
            added = [x for x in v if x not in before and x not in _EMPTY]
            gone = [x for x in before if x not in v and x not in _EMPTY]
            bits = [f"+ {x}" for x in added] + [f"− {x}" for x in gone]
            if bits:
                out.append(f"{k}: {'; '.join(bits)} ({src})")
        elif before is None:
            out.append(f"{k}: {_fmt(v)} ({src})")
        else:
            out.append(f"{k}: {_fmt(before)} → {_fmt(v)} ({src})")
    for k in old:
        if k not in new:
            out.append(f"{k}: no longer shown")
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
