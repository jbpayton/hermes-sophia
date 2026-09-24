"""Print exactly what Sophia injected on the most recent turn of a profile (debug helper).

Usage: python scripts/last_injection.py [path/to/sophia.db]   (default: $HERMES_HOME/plugin-data/sophia/sophia.db)
"""
import json, os, sqlite3, sys
home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(home, "plugin-data", "sophia", "sophia.db")
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
r = c.execute("SELECT * FROM injections ORDER BY said DESC LIMIT 1").fetchone()
print("query:", r["query"][:120]); print("gate:", json.loads(r["gate"])["gate"])
for it in json.loads(r["items"]):
    if it["kind"] == "fact":
        f = c.execute("SELECT subject, relation, object, status FROM facts WHERE id=?", (it["id"],)).fetchone()
        print(f"  {it['sim']:.3f} fact   [{f['status']}] {f['subject']} | {f['relation']} | {f['object']}")
    elif it["kind"] == "task":
        t = c.execute("SELECT outcome, card FROM tasks WHERE id=?", (it["id"],)).fetchone()
        print(f"  {it['sim']:.3f} task   [{t['outcome']}] {json.loads(t['card'])['text'][:160]}")
        continue
    else:
        w = c.execute("SELECT speaker, session_id, text FROM windows WHERE id=?", (it["id"],)).fetchone()
        print(f"  {it['sim']:.3f} window {w['speaker']}: {w['text'][:110]}")
