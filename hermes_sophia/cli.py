"""``hermes sophia …`` subcommands (discovered by Hermes when ``memory.provider: sophia``)."""
from __future__ import annotations

import json
import sys
import time


def _engine(args=None):
    from hermes_constants import get_hermes_home
    from .engine import Engine
    return Engine.for_home(str(get_hermes_home()))


def _print(obj):
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def cmd(args):
    sub = getattr(args, "sophia_cmd", None)
    if sub is None:
        print("usage: hermes sophia <status|sleep|journal|recall|undo|reconsolidate|ingest-history>")
        return
    e = _engine()
    try:
        if sub == "status":
            _print(e.status())
        elif sub == "sleep":
            from .sleep import SleepRunner
            steps = args.steps.split(",") if args.steps else None
            r = SleepRunner(e, model=args.model, max_wait_s=args.max_wait, steps=steps, limit=args.limit or 0)
            print(f"Sophia sleep — night {r.night}, model {r.model}")
            out = r.run()
            print(f"status: {out['status']}")
        elif sub == "journal":
            night = args.night or (e.store.get_meta("last_sleep", {}) or {}).get("night_id")
            print(f"night {night}")
            rows = e.store.q("SELECT id, step, kind, detail, undo FROM journal WHERE night_id=? ORDER BY id", (night,))
            for r in rows:
                tag = f"#{r['id']}" + (" (undoable)" if r["undo"] else "")
                print(f"  {tag:16s} {r['step']:12s} {r['kind']:22s} {r['detail'][:200]}")
        elif sub == "recall":
            q = " ".join(args.query)
            if args.gate:
                text, info = e.recall.prefetch(q, "cli")
                _print(info)
                print(text or "(nothing injected)")
            else:
                items, info = e.recall.candidates(q, k=args.k)
                _print(info)
                for it in items:
                    head = " | ".join(it["fact"]) if it["kind"] == "fact" else it["speaker"]
                    print(f"  {it['sim']:.3f} {it['kind']:6s} {head}: {it['text'][:140]}")
        elif sub == "undo":
            row = e.store.one("SELECT * FROM journal WHERE id=?", (args.journal_id,))
            if not row or not row["undo"]:
                print(f"journal entry {args.journal_id} has nothing to undo")
            else:
                u = json.loads(row["undo"])
                if "fact" in u:
                    e.store.x("UPDATE facts SET status=?, valid_to=NULL, superseded_by=NULL WHERE id=?",
                              (u.get("status", "active"), u["fact"]))
                    e.store.x("DELETE FROM credit_events WHERE item_id=? AND kind='contradicted' AND night_id=?",
                              (u["fact"], row["night_id"]))
                e.store.journal("manual", "undo", "undone", {"journal_id": args.journal_id, "detail": row["detail"]})
                print(f"undone: {row['kind']} {row['detail'][:160]}")
        elif sub == "reconsolidate":
            n = e.store.one("SELECT COUNT(*) AS n FROM facts")["n"]
            for sql in ("DELETE FROM facts", "DELETE FROM fact_sources", "DELETE FROM entities", "DELETE FROM relations",
                        "DELETE FROM views", "DELETE FROM vectors WHERE kind='fact'", "DELETE FROM fts WHERE kind='fact'",
                        "DELETE FROM jobs WHERE night_id='*' AND step IN ('relate','rehearse')",
                        "DELETE FROM credit_events WHERE item_kind='fact'"):
                e.store.x(sql)
            if args.headers:
                e.store.x("UPDATE windows SET header_source='heuristic' WHERE header_source='model'")
            e.store.set_meta("last_sleep_ts", 0)
            print(f"cleared {n} facts; the next sleep rebuilds them from the raw record")
        elif sub == "ingest-history":
            from hermes_state import SessionDB
            db = SessionDB(read_only=True)
            since = time.time() - args.days * 86400
            sessions = db.list_sessions_rich(limit=args.max_sessions, order_by_last_active=True)
            n = 0
            for srow in sessions:
                if (srow.get("last_active") or srow.get("started_at") or 0) < since:
                    continue
                msgs = db.get_messages(srow["id"])
                st = e.capture.process_messages(srow["id"], msgs, agent_context="primary")
                n += 1
                print(f"  {srow['id']}  {srow.get('title') or ''!s:40.40}  {st}")
            print(f"ingested {n} sessions")
    finally:
        e.close()


def register_cli(subparser) -> None:
    subs = subparser.add_subparsers(dest="sophia_cmd")
    subs.add_parser("status", help="Store sizes, last sleep, degraded modes, calibration")
    p = subs.add_parser("sleep", help="Run the nightly sequence now")
    p.add_argument("--model", help="Model for night work (default: memory.sophia.sleep_model)")
    p.add_argument("--steps", help="Comma-separated subset of steps")
    p.add_argument("--max-wait", type=int, default=None, help="Seconds to wait for a busy model before yielding")
    p.add_argument("--limit", type=int, default=0, help="Cap model calls per step (testing)")
    p = subs.add_parser("journal", help="What a night learned, superseded, merged, promoted, missed")
    p.add_argument("--night")
    p = subs.add_parser("recall", help="Debug recall for a query")
    p.add_argument("query", nargs="+")
    p.add_argument("--gate", action="store_true", help="Run the full prefetch path including the decider gate")
    p.add_argument("-k", type=int, default=10)
    p = subs.add_parser("undo", help="Revert a supersession, merge or plan change recorded in the journal")
    p.add_argument("journal_id", type=int)
    p = subs.add_parser("reconsolidate", help="Drop derived facts; the next sleep rebuilds them from the raw record")
    p.add_argument("--headers", action="store_true", help="Also redo model context headers")
    p = subs.add_parser("ingest-history", help="Capture past Hermes sessions from the session store")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--max-sessions", type=int, default=200)
    subparser.set_defaults(func=cmd)
