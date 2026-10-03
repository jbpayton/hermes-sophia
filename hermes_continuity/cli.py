"""``hermes continuity …``: look at the continuing process, and pause or resume it."""
from __future__ import annotations

import datetime as dt
import json
import time


def _d(ts) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "-"


def setup(sub) -> None:
    subs = sub.add_subparsers(dest="continuity_cmd")
    subs.add_parser("status", help="Energy, what's waiting, today's turns and outreach, why it's quiet")
    p = subs.add_parser("report", help="Everything at once: why it's quiet, today's outcomes, the queue with why each "
                                       "item pulls, held messages, the journal, and how much context frames take")
    p.add_argument("--json", action="store_true")
    subs.add_parser("view", help="The standing view as it would look now (a full frame; changes nothing)")
    subs.add_parser("queue", help="What came to mind and is waiting")
    p = subs.add_parser("journal", help="Its own turns, and each quiet stretch with its reason and cost")
    p.add_argument("-n", type=int, default=20)
    subs.add_parser("outbox", help="Messages it held for you")
    subs.add_parser("pause", help="Stop taking turns of its own (its state is kept)")
    subs.add_parser("resume", help="Let it take turns of its own again")
    sub.set_defaults(func=cmd)


def _plugin_settings():
    """The profile's plugins.entries.continuity.settings, read the way Hermes would (the CLI has no ctx)."""
    try:
        from hermes_cli.config import load_config
        entry = ((load_config() or {}).get("plugins") or {}).get("entries", {}).get("continuity") or {}
        settings = entry.get("settings") or {}
    except Exception:
        settings = {}
    return lambda key, default=None: settings.get(key, default)


def cmd(args) -> None:
    from . import _RUNNING, _home, _user_name
    from .config import load
    from .loop import Continuity
    from .store import Store
    from . import view as V

    store = Store(_home() / "plugin-data" / "continuity" / "continuity.db")
    sub = getattr(args, "continuity_cmd", None)
    st = store.state()
    now = time.time()
    if sub == "report":
        from .report import build, text
        cfg = load(_plugin_settings())
        rep = build(store.path, cfg, user=_user_name(cfg))
        print(json.dumps(rep, indent=2, default=str) if args.json else text(rep))
    elif sub in (None, "status"):
        today = dt.datetime.now().strftime("%Y-%m-%d")
        q = store.queued()
        print(json.dumps({
            "paused": st["paused"], "energy": round(float(st["energy"] or 0), 2),
            "waiting_to_come_to_mind": len(q), "turns_today": st["steps_today"] if st["day"] == today else 0,
            "outreach_today": st["outreach_today"] if st["day"] == today else 0,
            "held_messages": store.one("SELECT COUNT(*) AS n FROM outbox WHERE status='held'")["n"],
            "quiet": st["quiet_reason"] or None, "quiet_since": _d(st["quiet_since"]),
            "last_frame": _d(st["last_frame_ts"]), "focus": st["focus"] or None,
        }, indent=2))
    elif sub == "view":
        cont = Continuity(store, load(), lambda t: False, user_name=_user_name(load()))
        held = [r["text"] for r in store.q("SELECT text FROM outbox WHERE status='held'")]
        print(V.render_full(V.scene(st, now, cont.user_name, held, len(store.queued())), now))
    elif sub == "queue":
        for r in store.queued():
            print(f"  {r['salience']:.2f}  depth {r['depth']}  {_d(r['created'])}  {r['text'][:110]}")
    elif sub == "journal":
        rows = store.q("""SELECT 'turn' AS what, ts, kind, outcome, reason, ms, text, NULL AS steps, NULL AS silent
                          FROM steps UNION ALL
                          SELECT 'quiet', ts, NULL, NULL, reason, ms, held, steps, silent FROM quiet
                          ORDER BY ts DESC LIMIT ?""", (args.n,))
        for r in reversed(rows):
            if r["what"] == "turn":
                first = (r["text"] or "").splitlines()
                print(f"  {_d(r['ts'])}  turn   {r['kind']:11s} {r['outcome'] or 'running':12s} "
                      f"{(r['ms'] or 0) / 1000:5.1f}s  {first[1][:70] if len(first) > 1 else ''}"
                      + (f"  [{r['reason']}]" if r["reason"] else ""))
            else:
                print(f"  {_d(r['ts'])}  quiet  {r['reason']}  ({r['steps']} turns: {r['silent'] or 0} silent, "
                      f"{r['text'] or 0} held; {(r['ms'] or 0) / 1000:.0f}s of model time)")
    elif sub == "outbox":
        for r in store.q("SELECT * FROM outbox ORDER BY id DESC LIMIT 20"):
            print(f"  #{r['id']} {_d(r['created'])} {r['status']:5s} ({r['reason']})  {r['text'][:200]}")
    elif sub in ("pause", "resume"):
        store.set_paused(sub == "pause")
        print("paused: it won't take turns of its own (perception and the view continue)" if sub == "pause"
              else "resumed")
    store.close()
