"""Time, noticed rather than ticked.

Each sensor checks a condition cheaply, with no model call, and raises one event when the condition becomes true.
While it stays true it is noticed again only as it grows (a day, then three days), never at every check. Nothing
is noticed during quiet hours: the condition still holds when they end, so it's noticed then, when it's useful.

The sensors only perceive. Each event becomes one "noticed" item in the queue and gives the process some energy, as
anything perceived does; whether it turns into a turn of its own is the loop's decision (energy, budget, what else
is waiting).

Morning is the one scheduled event: it fires because the clock reached the user's usual start of day, not because
a condition changed. It's kept, labelled as scheduled in the journal so the comparison can attribute it, and it
carries what's due that day.
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any, Dict, List, Optional

from .config import in_quiet_hours
from .view import ago

CONVERSATION_GAP_S = 30 * 60          # messages closer than this belong to one conversation
LATEST_MORNING = "11:00"              # a usual first message later than this doesn't move "morning" past it
DAY = 86400


def _hm(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def _day(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def quiet_hours_end(spec: str) -> str:
    try:
        return spec.split("-", 1)[1].strip() or "08:00"
    except (AttributeError, IndexError):
        return "08:00"


def usual_gap(times: List[float]) -> Optional[float]:
    """The median time between the starts of the user's conversations (None with fewer than three)."""
    times = sorted(times)
    gaps = [b - a for a, b in zip(times, times[1:]) if b - a >= CONVERSATION_GAP_S]
    return statistics.median(gaps) if len(gaps) >= 3 else None


def usual_morning(times: List[float], floor: str) -> Optional[str]:
    """The median time of the user's first message of the day, never before ``floor`` (quiet hours' end)."""
    firsts: Dict[str, float] = {}
    for t in sorted(times):
        if _hm(t) >= floor:
            firsts.setdefault(_day(t), t)
    if len(firsts) < 3:
        return None
    mins = statistics.median(int(_hm(t)[:2]) * 60 + int(_hm(t)[3:]) for t in firsts.values())
    return f"{int(mins // 60):02d}:{int(mins % 60):02d}"


def _span(seconds: float) -> str:
    h = seconds / 3600
    return f"about {round(h)} hours" if h < 36 else f"about {round(h / 24)} days"


def check(st: Dict[str, Any], now: float, cfg: Dict[str, Any], memory: Optional[Any] = None,
          user: str = "the user") -> List[Dict[str, Any]]:
    """Events for conditions that just became true. Mutates ``st['sensors']`` (what was already noticed)."""
    s = st.setdefault("sensors", {})
    if not cfg.get("sensors", True) or in_quiet_hours(cfg["quiet_hours"], _hm(now)):
        return []
    out: List[Dict[str, Any]] = []

    # what memory says about the user's rhythm, refreshed once a day
    if s.get("rhythm_day") != _day(now):
        times: List[float] = []
        if memory is not None:
            try:
                times = memory.user_message_times(28)
            except Exception:
                times = []
        floor = quiet_hours_end(cfg["quiet_hours"])
        s["rhythm_day"] = _day(now)
        s["usual_gap"] = usual_gap(times)
        usual = usual_morning(times, floor)
        if usual and usual > LATEST_MORNING:          # first contact usually comes later in the day: the morning
            usual = None                              # event still belongs in the morning
        s["morning_at"] = cfg["morning"] if cfg.get("morning", "auto") != "auto" else (usual or floor)

    # 4. morning: the one scheduled event, carrying what's due today. Started for the first time well past morning,
    # today's morning counts as already seen: "Morning" at 17:30 would be noise.
    if "morning_day" not in s and _hm(now) >= s.get("morning_at", "08:00"):
        h, m = (int(x) for x in s.get("morning_at", "08:00").split(":"))
        if now - dt.datetime.fromtimestamp(now).replace(hour=h, minute=m, second=0, microsecond=0).timestamp() > 3 * 3600:
            s["morning_day"] = _day(now)
    if s.get("morning_day") != _day(now) and _hm(now) >= s.get("morning_at", "08:00"):
        s["morning_day"] = _day(now)
        due = []
        if memory is not None:
            try:
                start = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                due = memory.upcoming(start, start + DAY)
            except Exception:
                due = []
        t = dt.datetime.fromtimestamp(now)
        text = f"Morning: {t.strftime('%A, %B')} {t.day}."
        if due:
            text += " Due today: " + "; ".join(f"{d['text']}" + (f" ({_hm(d['h_start'])})" if d.get("h_start")
                                                                     and _hm(d["h_start"]) != "00:00" else "")
                                               for d in due[:5]) + "."
        else:
            text += " Nothing in memory is due today."
        out.append({"sensor": "morning", "text": text, "scheduled": True})

    # 1. the user quiet for longer than usual: noticed at the threshold, then at a day and at three days
    last = st.get("last_user_ts") or 0
    if last:
        usual = s.get("usual_gap") or DAY
        threshold = min(max(2 * usual, 6 * 3600), 3 * DAY)
        rungs = sorted({threshold, *(r for r in (DAY, 3 * DAY) if r > threshold)})
        reached = sum(1 for r in rungs if now - last >= r)
        if s.get("quiet_for") != last:
            s["quiet_for"], s["quiet_level"] = last, 0
        if reached > s.get("quiet_level", 0):
            s["quiet_level"] = reached
            usual_txt = f"usually {_span(s['usual_gap'])} between conversations" if s.get("usual_gap") else \
                "not enough history yet to say what's usual"
            out.append({"sensor": "quiet", "text": f"{user} hasn't written for {_span(now - last)}, longer than "
                                                   f"usual ({usual_txt}). Last wrote {ago(now - last)}."})

    # 2. overdue: something it was waiting for, past the time it expected it by
    for w in st.get("waiting_for", []):
        if w.get("by") and now >= w["by"] and not w.get("overdue_noticed"):
            w["overdue_noticed"] = now
            out.append({"sensor": "overdue", "text": f"Still waiting for {w['text']}; you expected it by "
                                                     f"{_hm(w['by'])}."})

    # 3. a date passed: something planned for a time now gone by, with nothing since saying how it went
    if memory is not None:
        try:
            passed = memory.upcoming(now - DAY, now)
        except Exception:
            passed = []
        seen = s.setdefault("passed", [])
        for d in passed:
            end = d.get("h_end") or d.get("h_start") or 0
            if d["id"] in seen or not end or end > now:
                continue
            seen.append(d["id"])
            when = _hm(d["h_start"]) if d.get("h_start") and _hm(d["h_start"]) != "00:00" else "today"
            out.append({"sensor": "date passed", "text": f"“{d['text']}” was due {when}; nothing since "
                                                         "says whether it happened."})
        del seen[:-100]
    return out
