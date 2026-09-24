"""Deterministic typed spans and a rule-based time resolver.

Value types (prescribed): time, duration, quantity, money, contact, artifact. Entity types (person,
organization, place) are resolved at night; by day only name hints exist. Relative time expressions
are pinned against the moment the words were said, so "next Tuesday" never drifts.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
WEEKDAYS = {d: i for i, d in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
NUMWORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a couple of": 2, "a few": 3,
            "couple of": 2, "few": 3, "several": 3}
ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_WD = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_NUM = r"(\d+|a couple of|a few|couple of|several|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_UNIT = r"(second|minute|hour|day|week|month|year)s?"
_TOD = re.compile(r"\s*(?:,\s*)?(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?(?![\d:])", re.I)


def _tz():
    return dt.datetime.now().astimezone().tzinfo


def _ts(d: dt.date, hour: int = 0, minute: int = 0) -> float:
    return dt.datetime(d.year, d.month, d.day, hour, minute, tzinfo=_tz()).timestamp()


def _day(d: dt.date) -> Tuple[float, float, str]:
    return _ts(d), _ts(d + dt.timedelta(days=1)), d.isoformat()


def _month(y: int, m: int) -> Tuple[float, float, str]:
    start = dt.date(y, m, 1)
    end = dt.date(y + (m == 12), m % 12 + 1, 1)
    return _ts(start), _ts(end), f"{y:04d}-{m:02d}"


def _year(y: int) -> Tuple[float, float, str]:
    return _ts(dt.date(y, 1, 1)), _ts(dt.date(y + 1, 1, 1)), f"{y:04d}"


def _num(s: str) -> int:
    s = s.lower().strip()
    return int(s) if s.isdigit() else NUMWORDS.get(s, 1)


def _add_months(d: dt.date, n: int) -> dt.date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return dt.date(y, m, min(d.day, 28))


class _Spans:
    def __init__(self, text: str):
        self.text = text
        self.out: List[Dict] = []
        self.covered: List[Tuple[int, int]] = []

    def free(self, a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in self.covered)

    def add(self, a: int, b: int, typ: str, value: str, t0: Optional[float] = None, t1: Optional[float] = None,
            conf: float = 1.0) -> bool:
        if a >= b or not self.free(a, b):
            return False
        self.covered.append((a, b))
        self.out.append({"start": a, "end": b, "type": typ, "value": value, "t_start": t0, "t_end": t1,
                         "source": "deterministic", "confidence": conf})
        return True


def _attach_time_of_day(sp: _Spans, end: int, day: dt.date, start: int, value: str) -> Tuple[int, float, float, str]:
    m = _TOD.match(sp.text, end)
    if m and (m.group(2) or m.group(3)):
        h = int(m.group(1)) % 24
        mi = int(m.group(2) or 0)
        ap = (m.group(3) or "").lower().replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if 0 <= h < 24 and 0 <= mi < 60:
            t0 = _ts(day, h, mi)
            return m.end(), t0, t0 + 3600, f"{day.isoformat()}T{h:02d}:{mi:02d}"
    t0, t1, v = _day(day)
    return end, t0, t1, value or v


def resolve_times(text: str, ref: dt.datetime, mode: str = "statement", sp: Optional[_Spans] = None) -> List[Dict]:
    """Time spans with absolute [t_start, t_end). ``mode='query'`` reads bare weekdays and months as past."""
    sp = sp or _Spans(text)
    low = text.lower()
    today = ref.date()

    def add_day(m, day, value=""):
        end, t0, t1, v = _attach_time_of_day(sp, m.end(), day, m.start(), value)
        sp.add(m.start(), end, "time", v, t0, t1)

    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        try:
            add_day(m, dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in re.finditer(rf"\b{_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", low):
        try:
            add_day(m, dt.date(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2))))
        except (ValueError, KeyError):
            pass
    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}\.?,?\s+(\d{{4}})\b", low):
        try:
            add_day(m, dt.date(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1))))
        except (ValueError, KeyError):
            pass
    for m in re.finditer(rf"\b(first|second|third|fourth|last|1st|2nd|3rd|4th)\s+week\s+of\s+{_MON}\b", low):
        mo = MONTHS[m.group(2)[:3]]
        if mode == "query":
            y = today.year if mo <= today.month else today.year - 1
        else:
            y = today.year if mo >= today.month else today.year + 1
        first = dt.date(y, mo, 1)
        if m.group(1) == "last":
            nxt = _add_months(first, 1).replace(day=1)
            s, e = nxt - dt.timedelta(days=7), nxt
        else:
            s = first + dt.timedelta(days=7 * (ORDINAL[m.group(1)] - 1))
            e = s + dt.timedelta(days=7)
        sp.add(m.start(), m.end(), "time", f"{s.isoformat()}/{e.isoformat()}", _ts(s), _ts(e))
    for m in re.finditer(rf"\b{_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{{4}})", low):
        try:
            mo, d = MONTHS[m.group(1)[:3]], int(m.group(2))
            y = today.year
            cand = dt.date(y, mo, d)
            if mode == "query" and cand > today:
                cand = dt.date(y - 1, mo, d)
            add_day(m, cand)
        except (ValueError, KeyError):
            pass
    for m in re.finditer(rf"\b{_MON}\s+(\d{{4}})\b", low):
        t0, t1, v = _month(int(m.group(2)), MONTHS[m.group(1)[:3]])
        sp.add(m.start(), m.end(), "time", v, t0, t1)
    for m in re.finditer(r"\b(?:in|since|by|during|of|from|until)\s+((?:19|20)\d{2})\b", low):
        t0, t1, v = _year(int(m.group(1)))
        sp.add(m.start(1), m.end(1), "time", v, t0, t1)
    for m in re.finditer(r"\b(the day after tomorrow|the day before yesterday|today|tonight|this (?:morning|afternoon|evening)|yesterday|tomorrow)\b", low):
        w = m.group(1)
        off = {"the day after tomorrow": 2, "the day before yesterday": -2, "yesterday": -1, "tomorrow": 1}.get(w, 0)
        add_day(m, today + dt.timedelta(days=off))
    for m in re.finditer(rf"\b(?:(last|next|this|coming|on|past)\s+)?{_WD}\b", low):
        q, wd = m.group(1), WEEKDAYS[m.group(2)]
        delta = (wd - today.weekday()) % 7
        if q in ("last", "past") or (q in (None, "on") and mode == "query"):
            back = (today.weekday() - wd) % 7 or 7
            day = today - dt.timedelta(days=back)
        elif q == "next":
            day = today + dt.timedelta(days=delta or 7)
        else:                                    # this / coming / bare in a statement: the upcoming one
            day = today + dt.timedelta(days=delta)
        add_day(m, day)
    for m in re.finditer(r"\b(last|next|this|past)\s+(week|month|year|weekend)\b", low):
        q, unit = m.group(1), m.group(2)
        if unit in ("week", "weekend"):
            monday = today - dt.timedelta(days=today.weekday())
            base = monday + dt.timedelta(days={"last": -7, "past": -7, "next": 7}.get(q, 0))
            s, e = (base + dt.timedelta(days=5), base + dt.timedelta(days=7)) if unit == "weekend" else (base, base + dt.timedelta(days=7))
            sp.add(m.start(), m.end(), "time", f"{s.isoformat()}/{e.isoformat()}", _ts(s), _ts(e))
        elif unit == "month":
            first = today.replace(day=1)
            base = _add_months(first, {"last": -1, "past": -1, "next": 1}.get(q, 0))
            t0, t1, v = _month(base.year, base.month)
            sp.add(m.start(), m.end(), "time", v, t0, t1)
        else:
            y = today.year + {"last": -1, "past": -1, "next": 1}.get(q, 0)
            t0, t1, v = _year(y)
            sp.add(m.start(), m.end(), "time", v, t0, t1)
    for m in re.finditer(rf"\b{_NUM}\s+{_UNIT}\s+ago\b", low):
        n, unit = _num(m.group(1)), m.group(2)
        if unit in ("month", "year"):
            d = _add_months(today, -n * (12 if unit == "year" else 1))
        else:
            d = today - dt.timedelta(days=n * {"week": 7, "day": 1}.get(unit, 0))
        add_day(m, d)
    for m in re.finditer(rf"\bin\s+{_NUM}\s+{_UNIT}\b", low):
        n, unit = _num(m.group(1)), m.group(2)
        if unit in ("month", "year"):
            d = _add_months(today, n * (12 if unit == "year" else 1))
        else:
            d = today + dt.timedelta(days=n * {"week": 7, "day": 1}.get(unit, 0))
        add_day(m, d)
    for m in re.finditer(rf"\b(?:in|during|this|last|next|since|by|early|late|mid|until)\s+{_MON}\b(?!\s+\d)", low):
        mo = MONTHS[m.group(1)[:3]]
        word = low[m.start():m.start(1)].strip()
        if word == "last" or (mode == "query" and word != "next"):
            y = today.year if mo <= today.month else today.year - 1
        elif word == "next":
            y = today.year if mo > today.month else today.year + 1
        else:
            y = today.year if mo >= today.month else today.year + 1
        t0, t1, v = _month(y, mo)
        sp.add(m.start(1), m.end(1), "time", v, t0, t1)
    return sp.out


_DUR_UNIT = {"second": "S", "minute": "M", "hour": "H", "day": "D", "week": "W", "month": "M", "year": "Y"}
_Q_UNITS = r"(km|kilometers?|miles?|kg|kilograms?|lbs?|pounds|grams?|meters?|metres?|cm|mm|ft|feet|foot|inches|gb|mb|tb|kb|ghz|mhz|°[cf]|degrees?|%|percent|tokens?|steps?|calories|kcal|liters?|ml|mph|kph|km/h)"


def extract_spans(text: str, said: float) -> List[Dict]:
    """All deterministic spans for one window. Order encodes priority: contacts and artifacts first."""
    sp = _Spans(text)
    for m in re.finditer(r"https?://[^\s)>\]\"'`]+", text):
        sp.add(m.start(), m.end(), "contact", m.group(0).rstrip(".,;:"))
    for m in re.finditer(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", text):
        sp.add(m.start(), m.end(), "contact", m.group(0))
    for m in re.finditer(r"`([^`\n]{1,200})`", text):
        sp.add(m.start(), m.end(), "artifact", m.group(1))
    for m in re.finditer(r"(?<![\w/:])(?:~|\.{1,2})?/[\w.\-]+(?:/[\w.\-]*)+", text):
        sp.add(m.start(), m.end(), "artifact", m.group(0))
    for m in re.finditer(r"\bv?\d+\.\d+\.\d+(?:[-+][\w.]+)?\b|\bv\d+\.\d+\b", text):
        sp.add(m.start(), m.end(), "artifact", m.group(0))
    for m in re.finditer(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b|(?<!\w)#\d{2,7}\b", text):
        sp.add(m.start(), m.end(), "artifact", m.group(0))
    for m in re.finditer(r"(?<!\d)(\+?\d{1,3}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)", text):
        sp.add(m.start(), m.end(), "contact", re.sub(r"[^\d+]", "", m.group(0)))
    resolve_times(text, dt.datetime.fromtimestamp(said, tz=_tz()), "statement", sp)
    for m in re.finditer(r"([$€£¥])\s?(\d[\d,]*(?:\.\d+)?)\s?(k|m|bn|million|billion)?\b", text, re.I):
        cur = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}[m.group(1)]
        amt = float(m.group(2).replace(",", "")) * {"k": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}.get((m.group(3) or "").lower(), 1)
        sp.add(m.start(), m.end(), "money", f"{amt:g} {cur}")
    for m in re.finditer(r"\b(\d[\d,]*(?:\.\d+)?)\s?(usd|eur|gbp|jpy|dollars?|euros?|bucks)\b", text, re.I):
        cur = {"dollar": "USD", "dollars": "USD", "bucks": "USD", "euro": "EUR", "euros": "EUR"}.get(m.group(2).lower(), m.group(2).upper())
        sp.add(m.start(), m.end(), "money", f"{float(m.group(1).replace(',', '')):g} {cur}")
    for m in re.finditer(rf"\b{_NUM}\s+{_UNIT}\b(?!\s+ago)", text, re.I):
        pre = text[max(0, m.start() - 3):m.start()].lower()
        if pre.endswith("in "):
            continue
        n, unit = _num(m.group(1)), m.group(2).lower()
        code = f"P{n}{_DUR_UNIT[unit]}" if unit in ("day", "week", "month", "year") else f"PT{n}{_DUR_UNIT[unit]}"
        sp.add(m.start(), m.end(), "duration", code)
    for m in re.finditer(rf"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s?{_Q_UNITS}(?![\w])", text, re.I):
        sp.add(m.start(), m.end(), "quantity", f"{m.group(1).replace(',', '')} {m.group(2).lower()}")
    return sorted(sp.out, key=lambda s: s["start"])


def query_time_scope(query: str, now: Optional[float] = None) -> Optional[Tuple[float, float, str]]:
    """(t_start, t_end, clock) for time expressions in a question; clock is 'happens' for future scopes,
    'any' (said or happens) for past ones. None when the question has no time expression."""
    import time as _t
    now = now or _t.time()
    ref = dt.datetime.fromtimestamp(now, tz=_tz())
    spans = resolve_times(query, ref, mode="query")
    low = query.lower()
    if not spans and re.search(r"\b(recently|lately|earlier today|this week so far)\b", low):
        return now - 7 * 86400, now, "any"
    spans = [s for s in spans if s.get("t_start") is not None]
    if not spans:
        return None
    t0 = min(s["t_start"] for s in spans)
    t1 = max(s["t_end"] for s in spans)
    return t0, t1, ("happens" if t0 > now else "any")
