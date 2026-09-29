"""Build a demo store for the dashboard tab's screenshots from a synthetic Almanac life (never from real memory).

    python scripts/dashboard_demo_store.py bench/work/almanac02_dev10/memories/life-01-night-end.db /tmp/demo/plugin-data/sophia/sophia.db

Copies the store, then moves its two clocks (the life's own timeline and the benchmark's run time) onto one recent
timeline in whole days: the conversation ends yesterday at its own time of day and the night ran at 03:30 today.
Dates written inside the synthetic lines ("July 14") move by the same days, so quotes and plans agree. Point a
throwaway HERMES_HOME at the result (memory.sophia.user_name = the life's user, plugins.enabled = [sophia]) and run
`hermes dashboard --isolated --port 9149 --no-open` against it.
"""
import datetime as dt, json, re, sqlite3, sys, time
src, dst = sys.argv[1], sys.argv[2]
a = sqlite3.connect(src); b = sqlite3.connect(dst); a.backup(b); a.close()
b.execute("PRAGMA journal_mode=DELETE"); b.row_factory = sqlite3.Row
q = lambda s, p=(): b.execute(s, p).fetchall()
now = time.time()
last_line = q("SELECT MAX(said) FROM windows")[0][0]
lt = dt.datetime.fromtimestamp(last_line)
yesterday = dt.datetime.now().date() - dt.timedelta(days=1)
DAYS = (yesterday - lt.date()).days
D = DAYS * 86400.0                                                 # life clock shift, whole days
t = dt.datetime.now()
night0 = dt.datetime(t.year, t.month, t.day, 3, 30).timestamp()   # tonight's run, this morning
ls = json.loads(q("SELECT value FROM meta WHERE key='last_sleep'")[0][0])
old_night = ls["night_id"]
new_night = time.strftime("%Y%m%d-%H%M%S", time.localtime(night0 + 2))
run0 = q("SELECT MIN(ts) FROM journal")[0][0]; run1 = ls["finished"]
run_map = lambda x: night0 + (x - run0) * (22 * 60) / max(1.0, run1 - run0) if x else x
# the life clock
for table, cols in [("windows", ["said"]), ("facts", ["valid_from", "valid_to", "h_start", "h_end"]), ("spans", ["t_start", "t_end"]),
                    ("tasks", ["first_said", "last_said"]), ("actions", ["said"]), ("events", ["said"]), ("chunks", ["fetched_at"])]:
    for c in cols:
        b.execute(f"UPDATE {table} SET {c}={c}+? WHERE {c} IS NOT NULL", (D,))
# recalls happen when the message they answered was said
for inj in q("SELECT id, session_id, query FROM injections"):
    w = q("""SELECT MIN(said) FROM windows WHERE session_id=? AND speaker='Silas' AND (? LIKE substr(text,1,40)||'%')""",
          (inj["session_id"], inj["query"]))[0][0]
    if w is None:
        w = q("SELECT MAX(said) FROM windows WHERE session_id=?", (inj["session_id"],))[0][0] or (now - 3600)
    b.execute("UPDATE injections SET said=? WHERE id=?", (w + 1.5, inj["id"]))
b.execute("UPDATE decisions SET ts=(SELECT said FROM injections i WHERE i.decision_id=decisions.id) WHERE id IN (SELECT decision_id FROM injections)")
# the run clock -> this morning's night
for table, col in [("journal", "ts"), ("facts", "created_at"), ("tasks", "created_at"), ("credit_events", "ts")]:
    for r in q(f"SELECT rowid, {col} FROM {table}"):
        b.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (run_map(r[1]), r[0]))
b.execute("UPDATE decisions SET ts=? WHERE id NOT IN (SELECT decision_id FROM injections WHERE decision_id IS NOT NULL)", (night0 + 600,))
for table, col in [("journal", "night_id"), ("facts", "night_id"), ("windows", "night_id"), ("links", "night_id"), ("tasks", "night_id"),
                   ("credit_events", "night_id"), ("threads", "night_id"), ("views", "built_night"), ("relations", "promoted_night")]:
    b.execute(f"UPDATE {table} SET {col}=? WHERE {col}=?", (new_night, old_night))
# dates written inside plan facts move with the life
def shift(m):
    s = m.group(0)
    try:
        if len(s) >= 10:
            d0 = dt.date.fromisoformat(s[:10]); return (d0 + dt.timedelta(days=DAYS)).isoformat() + s[10:]
        d0 = dt.date.fromisoformat(s + "-15"); return (d0 + dt.timedelta(days=DAYS)).strftime("%Y-%m")
    except ValueError:
        return s
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
def ordinal(n):
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
def move_written(text, year=2024):
    def sub(m):
        try:
            d0 = dt.date(year, MONTHS.index(m.group(1)) + 1, int(m.group(2))) + dt.timedelta(days=DAYS)
        except ValueError:
            return m.group(0)
        return f"{MONTHS[d0.month - 1]} {d0.day}" + (ordinal(d0.day) if m.group(3) else "")
    return re.sub(r"\b(" + "|".join(MONTHS) + r") (\d{1,2})(st|nd|rd|th)?\b", sub, text or "") if text else text
for table, key, cols in [("windows", "id", ["text", "index_text"]), ("facts", "id", ["subject", "object"]), ("entities", "id", ["name", "aliases"]),
                         ("injections", "id", ["query"]), ("chunks", "ref", ["text"])]:
    for r in q(f"SELECT {key}, {', '.join(cols)} FROM {table}"):
        new = [move_written(r[c]) for c in cols]
        if new != [r[c] for c in cols]:
            b.execute(f"UPDATE {table} SET {', '.join(c + '=?' for c in cols)} WHERE {key}=?", (*new, r[key]))
for r in q("SELECT id, happens FROM facts WHERE happens IS NOT NULL"):
    b.execute("UPDATE facts SET happens=? WHERE id=?", (re.sub(r"\d{4}-\d{2}(?:-\d{2}(?:T\d{2}:\d{2})?)?", shift, r["happens"]), r["id"]))
ls.update(night_id=new_night, finished=night0 + 22 * 60 + 14)
b.execute("UPDATE meta SET value=? WHERE key='last_sleep'", (json.dumps(ls),))
b.execute("UPDATE meta SET value=? WHERE key='last_sleep_ts'", (json.dumps(night0),))
b.execute("DELETE FROM meta WHERE key IN ('sleep_progress','degraded')")
b.commit()
print("shift", round(D / 86400, 1), "days; night", new_night, "; lines after the night:",
      q("SELECT COUNT(*) FROM windows WHERE said > ?", (night0,))[0][0], "; last line", time.strftime("%H:%M", time.localtime(q("SELECT MAX(said) FROM windows")[0][0])),
      "; unmatched recalls:", q("SELECT COUNT(*) FROM injections WHERE said > ?", (now,))[0][0])
b.close()
