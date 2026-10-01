"""Read-only views of a Sophia store for the Mindscape dashboard: what is going on now, what the last night did,
what needs a look, the entity graph and pages, and what recall injected and why.

Everything here reads through its own short-lived read-only connection, so watching never holds a lock the
gateway or a night needs. Curation (undo, plan outcomes, corrections) goes through ``Store`` methods, which
journal every change with a way back.
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .text import norm_entity

_TTL: Dict[str, Tuple[float, Any]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _TTL.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _TTL[key] = (time.time(), val)
    return val


@contextmanager
def reader(path: str | Path) -> Iterator[sqlite3.Connection]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    c = sqlite3.connect(f"file:{urllib.parse.quote(str(p))}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=10000")
        yield c
    finally:
        c.close()


def _meta(c: sqlite3.Connection, key: str, default: Any = None) -> Any:
    r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def _j(s: Optional[str], default: Any = None) -> Any:
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ gate readings
def parse_gate(gate: str) -> Dict[str, Any]:
    """'choice:g0.03,n0.03,m0.94' -> {'kind': 'choice', 'general': .03, 'none_fit': .03, 'memory': .94}."""
    kind, _, rest = (gate or "none").partition(":")
    out: Dict[str, Any] = {"kind": kind}
    if kind == "choice":
        for part in rest.split(","):
            if part[:1] in "gnm" and part[1:]:
                out[{"g": "general", "n": "none_fit", "m": "memory"}[part[0]]] = float(part[1:])
    elif rest:
        try:
            out["value"] = float(rest)
        except ValueError:
            pass
    return out


def verdict(info: Dict[str, Any], cut: float) -> str:
    """What recall did with a message: injected | possible | general | nothing_found | degraded | closed."""
    g = parse_gate(info.get("gate", ""))
    if info.get("passed"):
        return "possible" if info.get("uncertain") else "injected"
    if g["kind"] == "none":
        return "nothing_found"
    if g["kind"] == "degraded":
        return "degraded"
    if g["kind"] == "choice" and g.get("general", 0) >= cut:
        return "general"
    return "closed"


# ------------------------------------------------------------------ live state
def _proc_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{int(pid)}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except (OSError, ValueError, TypeError):
        return ""


def next_sleep(now: Optional[float] = None) -> Dict[str, Any]:
    """The next scheduled night from the user's crontab (the line that runs ``sophia sleep``)."""
    def read():
        try:
            p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
            return p.stdout if p.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    tab = _cached("crontab", 60, read)
    line = next((ln for ln in tab.splitlines() if "sophia" in ln and "sleep" in ln and not ln.lstrip().startswith("#")), "")
    if not line:
        return {"scheduled": False}
    f = line.split()
    out: Dict[str, Any] = {"scheduled": True, "schedule": " ".join(f[:5])}
    if len(f) >= 5 and f[0].isdigit() and f[1].isdigit() and f[2:5] == ["*", "*", "*"]:
        lt = time.localtime(now or time.time())
        t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(f[1]), int(f[0]), 0, 0, 0, -1))
        if t <= (now or time.time()):
            t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, int(f[1]), int(f[0]), 0, 0, 0, -1))
        out["at"] = t
    return out


def _get_json(url: str, timeout: float = 2.0) -> Tuple[Any, float]:
    t0 = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as r:     # local model servers only (from Sophia's config)
        body = json.loads(r.read().decode() or "null")
    return body, round((time.perf_counter() - t0) * 1000)


def model_health(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each role's model: reachable, loaded, busy, and how long the server took to answer."""
    from .config import ROLES, endpoint

    def probe():
        out = []
        for role in ROLES:
            url, api = endpoint(cfg, role)
            model = cfg[f"{role}_model"]
            row: Dict[str, Any] = {"role": role, "model": model, "server": url, "api": api, "up": False}
            try:
                body, ms = _get_json(url.rstrip("/") + ("/v1/models" if api != "lmstudio" else "/api/v0/models"))
                row.update(up=True, ms=ms)
                for m in (body or {}).get("data", []) if isinstance(body, dict) else []:
                    if m.get("id") == model:
                        st = m.get("status")
                        row["state"] = (st or {}).get("value") if isinstance(st, dict) else (st or m.get("state"))
                if api != "lmstudio":
                    try:
                        slots, _ = _get_json(url.rstrip("/") + "/slots?model=" + urllib.parse.quote(model, safe=""))
                        if isinstance(slots, list):
                            row["busy"] = any(bool(s.get("is_processing")) for s in slots if isinstance(s, dict))
                    except Exception:
                        pass
            except Exception as e:
                row["error"] = str(e)[:160]
            out.append(row)
        return out
    return _cached("models:" + json.dumps([cfg.get(f"{r}_model") for r in ("embed", "decider", "sleep")]), 10, probe)


def sleep_state(c: sqlite3.Connection, now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    prog = _meta(c, "sleep_progress", None) or {}
    last = _meta(c, "last_sleep", None) or {}
    running = False
    if prog.get("status") == "running":
        cmd = _proc_cmdline(prog.get("pid", 0))
        running = "sophia" in cmd and "sleep" in cmd
        if not running:
            prog = dict(prog, status="interrupted")
    out: Dict[str, Any] = {"running": running, "progress": prog or None, "next": next_sleep(now)}
    if last:
        stats = last.get("stats") or {}
        out["last"] = {"night_id": last.get("night_id"), "status": last.get("status"), "model": last.get("model"),
                       "finished": last.get("finished"),
                       "seconds": round(sum((s or {}).get("seconds", 0) for s in stats.values() if isinstance(s, dict)))}
    return out


def now_state(path: str | Path, cfg: Dict[str, Any], feed: int = 5) -> Dict[str, Any]:
    """The live strip: the night, what waits for it, models, the last capture and the latest recalls."""
    with reader(path) as c:
        wm = _meta(c, "last_sleep_ts", 0) or 0
        waiting = c.execute("SELECT COUNT(*) AS n FROM windows WHERE said > ?", (wm,)).fetchone()["n"]
        missing = c.execute("""SELECT COUNT(*) AS n FROM windows w WHERE NOT EXISTS (SELECT 1 FROM vectors v
                               WHERE v.kind='window' AND v.item_id=w.id AND v.model=?)""",
                            (cfg["embed_model"],)).fetchone()["n"]
        cap = c.execute("SELECT session_id, speaker, said, flags FROM windows ORDER BY said DESC LIMIT 1").fetchone()
        rec = c.execute("SELECT id, query, gate, items, said FROM injections ORDER BY said DESC LIMIT ?", (feed,)).fetchall()
        out = {"now": time.time(), "sleep": sleep_state(c), "waiting": {"lines": waiting, "missing_vectors": missing},
               "degraded": _meta(c, "degraded", {}) or {},
               "capture": dict(cap) if cap else None,
               "recall": [_recall_row(r, cfg) for r in rec]}
    out["models"] = model_health(cfg)
    return out


def _recall_row(r: sqlite3.Row, cfg: Dict[str, Any]) -> Dict[str, Any]:
    info = _j(r["gate"], {}) or {}
    items = _j(r["items"], []) or []
    return {"id": r["id"], "query": (r["query"] or "")[:240], "said": r["said"], "gate": parse_gate(info.get("gate", "")),
            "verdict": verdict(info, cfg.get("gate_general", 0.8)), "n": len(items), "ms": info.get("ms"),
            "top_sim": info.get("top_sim")}


# ------------------------------------------------------------------ overview
def _speaker_group(speaker: str, flags: str, cfg: Dict[str, Any]) -> str:
    s, f = speaker or "", flags or ""
    if "assistant" in f:
        return cfg.get("agent_name") or "Assistant"
    if "thought" in f:
        return "Own thoughts"
    if "event" in f:
        return "System notices"
    if "caption" in f:
        return "Image descriptions"
    if s == cfg.get("user_name"):
        return s
    if s.startswith("memory:") or s == "note":
        return "Memory notes"
    if s.startswith("source:") or "external" in f:
        return "Web"
    if s in ("tool", "action") or "action" in f:
        return "Tool steps"
    return "Others"


def overview(path: str | Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    with reader(path) as c:
        last = _meta(c, "last_sleep", None) or {}
        st = last.get("stats") or {}
        rel, integ, tasks = st.get("relate") or {}, st.get("integrate") or {}, st.get("tasks") or {}
        steps = [{"step": k, "seconds": v.get("seconds", 0), "failed": "error" in v}
                 for k, v in st.items() if isinstance(v, dict) and "seconds" in v]
        speakers = Counter()
        for r in c.execute("SELECT speaker, flags, COUNT(*) AS n FROM windows GROUP BY speaker, flags"):
            speakers[_speaker_group(r["speaker"], r["flags"], cfg)] += r["n"]
        facts = Counter({r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) AS n FROM facts GROUP BY status")})
        sizes = {"lines": c.execute("SELECT COUNT(*) AS n FROM windows").fetchone()["n"],
                 "facts": facts.get("active", 0) + facts.get("unconfirmed", 0),
                 "entities": c.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"],
                 "tasks": c.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"],
                 "sessions": c.execute("SELECT COUNT(DISTINCT session_id) AS n FROM windows").fetchone()["n"],
                 "fact_status": dict(facts), "speakers": speakers.most_common()}
        since = time.time() - 7 * 86400
        rows = c.execute("SELECT gate, items FROM injections WHERE said > ?", (since,)).fetchall()
        verdicts = Counter(verdict(_j(r["gate"], {}) or {}, cfg.get("gate_general", 0.8)) for r in rows)
        ms = [(_j(r["gate"], {}) or {}).get("ms") for r in rows]
        ms = [m for m in ms if isinstance(m, (int, float))]
        lines = [len(_j(r["items"], []) or []) for r in rows]
        recall = {"days": 7, "messages": len(rows), "verdicts": dict(verdicts),
                  "median_ms": round(statistics.median(ms)) if ms else None,
                  "median_lines": statistics.median([n for n in lines if n]) if any(lines) else 0}
        night = {"night_id": last.get("night_id"), "status": last.get("status"), "model": last.get("model"),
                 "finished": last.get("finished"), "steps": steps,
                 "new_facts": rel.get("new_facts", 0), "superseded": integ.get("superseded", 0),
                 "plans_unconfirmed": integ.get("plans_unconfirmed", 0), "tasks": tasks.get("tasks", 0),
                 "judge_errors": st.get("judge_errors", 0)} if last else None
    return {"night": night, "sizes": sizes, "recall": recall}


# ------------------------------------------------------------------ journal and review queue
def _reviewed(c: sqlite3.Connection) -> Tuple[set, set]:
    undone = {(_j(r["detail"], {}) or {}).get("journal_id") for r in c.execute("SELECT detail FROM journal WHERE kind='undone'")}
    reviewed = set()
    for r in c.execute("SELECT id, detail FROM journal WHERE kind='reviewed'"):
        if r["id"] not in undone:
            reviewed.add((_j(r["detail"], {}) or {}).get("item"))
    return undone, reviewed


def journal(path: str | Path, night: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    with reader(path) as c:
        nights = [r["night_id"] for r in c.execute(
            "SELECT night_id, MAX(id) AS m FROM journal GROUP BY night_id ORDER BY m DESC LIMIT 30")]
        undone, _ = _reviewed(c)
        args: List[Any] = []
        sql = "SELECT id, night_id, step, kind, detail, undo, ts FROM journal WHERE kind != 'summary'"
        if night:
            sql += " AND night_id=?"
            args.append(night)
        rows = c.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    return {"nights": nights, "entries": [{"id": r["id"], "night_id": r["night_id"], "step": r["step"], "kind": r["kind"],
                                           "detail": _j(r["detail"], r["detail"]), "undoable": bool(r["undo"]),
                                           "undone": r["id"] in undone, "ts": r["ts"]} for r in rows]}


def _fact_brief(c: sqlite3.Connection, fid: str) -> Optional[Dict[str, Any]]:
    f = c.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
    if not f:
        return None
    src = c.execute("""SELECT w.id, w.speaker, w.said, w.text, w.flags, w.session_id FROM fact_sources fs
                       JOIN windows w ON w.id=fs.window_id WHERE fs.fact_id=? ORDER BY w.said LIMIT 3""", (fid,)).fetchall()
    return {"id": f["id"], "fact": [f["subject"], f["relation"], f["object"]], "status": f["status"],
            "modality": f["modality"], "happens": f["happens"], "h_start": f["h_start"], "night_id": f["night_id"],
            "sources": [_window_brief(w) for w in src]}


def _window_brief(w: sqlite3.Row, cap: int = 900) -> Dict[str, Any]:
    t = w["text"] or ""
    return {"id": w["id"], "speaker": w["speaker"], "said": w["said"], "flags": (w["flags"] or "").split(),
            "session_id": w["session_id"], "text": t[:cap], "cut": len(t) > cap}


def queue(path: str | Path, cfg: Dict[str, Any], plans: int = 12) -> Dict[str, Any]:
    """What needs a person: changes the night made on thin evidence, plans whose date passed without word,
    facts recall could not find again, degraded models and failed steps."""
    out: List[Dict[str, Any]] = []
    with reader(path) as c:
        undone, reviewed = _reviewed(c)
        last = _meta(c, "last_sleep", None) or {}
        for r in c.execute("""SELECT id, night_id, detail FROM journal WHERE kind='superseded' AND undo IS NOT NULL
                              ORDER BY id DESC LIMIT 20"""):
            if r["id"] in undone or f"j:{r['id']}" in reviewed:
                continue
            d = _j(r["detail"], {}) or {}
            out.append({"key": f"j:{r['id']}", "type": "superseded", "journal_id": r["id"], "night_id": r["night_id"],
                        "old": d.get("old"), "new": d.get("new"), "p": d.get("p")})
        n_plans = 0
        for f in c.execute("""SELECT id FROM facts WHERE status='unconfirmed' ORDER BY COALESCE(h_start, created_at) DESC"""):
            if f"f:{f['id']}" in reviewed:
                continue
            n_plans += 1
            if n_plans <= plans:
                b = _fact_brief(c, f["id"])
                if b:
                    out.append({"key": f"f:{f['id']}", "type": "plan", **b})
        if last.get("night_id"):
            for r in c.execute("SELECT id, detail FROM journal WHERE night_id=? AND kind='prompt_injection'", (last["night_id"],)):
                if f"j:{r['id']}" not in reviewed:
                    d = _j(r["detail"], {}) or {}
                    out.append({"key": f"j:{r['id']}", "type": "prompt_injection", "journal_id": r["id"],
                                "url": d.get("url"), "p": d.get("p")})
            for r in c.execute("SELECT id, detail FROM journal WHERE night_id=? AND kind='recall_miss'", (last["night_id"],)):
                if f"j:{r['id']}" not in reviewed:
                    d = _j(r["detail"], {}) or {}
                    out.append({"key": f"j:{r['id']}", "type": "recall_miss", "journal_id": r["id"],
                                "question": d.get("question"), "fact": d.get("fact")})
            for step, v in (last.get("stats") or {}).items():
                if isinstance(v, dict) and v.get("error"):
                    out.append({"key": f"step:{last['night_id']}:{step}", "type": "step_failed", "step": step,
                                "error": v["error"]})
        for name, d in (_meta(c, "degraded", {}) or {}).items():
            out.append({"key": f"degraded:{name}", "type": "degraded", "name": name, **(d or {})})
    return {"items": out, "plans_total": n_plans}


# ------------------------------------------------------------------ graph and pages
def _roles(c: sqlite3.Connection, cfg: Dict[str, Any]) -> Dict[str, str]:
    roles = {norm_entity(cfg.get("user_name") or ""): "user", norm_entity(cfg.get("agent_name") or ""): "agent"}
    for r in c.execute("SELECT DISTINCT speaker FROM windows WHERE speaker NOT LIKE '%:%' AND speaker NOT IN ('tool','action','note')"):
        roles.setdefault(norm_entity(r["speaker"]), "speaker")
    roles.pop("", None)
    return roles


def communities(weights: Dict[Tuple[str, str], float], resolution: float = 1.0, min_size: int = 3) -> Dict[str, int]:
    """Louvain modularity clustering on an undirected weighted graph ({(a, b): weight}), deterministic. Returns
    {node: cluster}, clusters numbered by size (0 = largest); nodes in clusters smaller than ``min_size`` get -1."""
    adj: Dict[str, Dict[str, float]] = defaultdict(dict)
    for (a, b), w in weights.items():
        if a == b or w <= 0:
            continue
        adj[a][b] = adj[a].get(b, 0.0) + w
        adj[b][a] = adj[b].get(a, 0.0) + w
    if not adj:
        return {}
    member: Dict[str, List[str]] = {n: [n] for n in adj}          # super-node -> original nodes
    deg = {n: sum(nb.values()) for n, nb in adj.items()}
    m2 = sum(deg.values())
    while True:
        comm = {n: n for n in adj}
        tot = dict(deg)
        moved_any, improved = False, True
        order = sorted(adj, key=lambda n: (-deg[n], n))
        while improved:
            improved = False
            for n in order:
                c0, k = comm[n], deg[n]
                tot[c0] -= k
                links: Dict[str, float] = defaultdict(float)
                for nb, w in adj[n].items():
                    if nb != n:
                        links[comm[nb]] += w
                best, gain = c0, links.get(c0, 0.0) - resolution * tot[c0] * k / m2
                for c, w in sorted(links.items()):
                    g = w - resolution * tot[c] * k / m2
                    if g > gain + 1e-12:
                        best, gain = c, g
                comm[n] = best
                tot[best] += k
                if best != c0:
                    improved = moved_any = True
        if not moved_any:
            break
        # fold each community into one node and go again
        new_adj: Dict[str, Dict[str, float]] = defaultdict(dict)
        new_member: Dict[str, List[str]] = defaultdict(list)
        new_deg: Dict[str, float] = defaultdict(float)
        for n, c in comm.items():
            new_member[c].extend(member[n])
            new_deg[c] += deg[n]
            for nb, w in adj[n].items():
                cb = comm[nb]
                if cb != c:
                    new_adj[c][cb] = new_adj[c].get(cb, 0.0) + w
        for c in new_member:
            new_adj.setdefault(c, {})
        if len(new_member) == len(adj):
            break
        adj, member, deg = new_adj, dict(new_member), dict(new_deg)
    groups = sorted(member.values(), key=lambda g: (-len(g), min(g)))
    out: Dict[str, int] = {}
    rank = 0
    for g in groups:
        cid = rank if len(g) >= min_size else -1
        rank += len(g) >= min_size
        for n in g:
            out[n] = cid
    return out


def graph(path: str | Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Every entity and every fact between them. The client shows the hubs (entities that are subjects) first and
    expands a hub into its facts on demand."""
    with reader(path) as c:
        roles = _roles(c, cfg)
        ents = {norm_entity(r["name"]): r for r in c.execute("SELECT id, name, fact_count, page FROM entities")}
        nodes: Dict[str, Dict[str, Any]] = {}

        def node(key: str, label: str) -> str:
            if key not in nodes:
                e = ents.get(key)
                nodes[key] = {"id": key, "label": e["name"] if e else label, "role": roles.get(key, "thing"),
                              "facts": 0, "subject": False, "entity": bool(e), "page": bool(e and e["page"])}
            return key
        edges = []
        for f in c.execute("""SELECT id, subject, subject_norm, relation, object, status, modality, happens, h_start
                              FROM facts WHERE status != 'retracted'"""):
            s = node(f["subject_norm"] or norm_entity(f["subject"]), f["subject"])
            o = node(norm_entity(f["object"]), f["object"])
            if s == o:
                continue
            nodes[s]["subject"] = True
            nodes[s]["facts"] += 1
            nodes[o]["facts"] += 1
            edges.append({"id": f["id"], "s": s, "o": o, "relation": f["relation"], "status": f["status"],
                          "modality": f["modality"], "happens": f["happens"]})
        # lines that mention two hubs together tie them even without a fact between them
        hubs = {k for k, n in nodes.items() if n["subject"]}
        per_window, per_line = defaultdict(set), defaultdict(set)
        for r in c.execute("""SELECT fs.window_id, f.subject_norm, f.object FROM fact_sources fs JOIN facts f ON f.id=fs.fact_id
                              WHERE f.status != 'retracted'"""):
            for k in (r["subject_norm"], norm_entity(r["object"])):
                if k in nodes:
                    per_line[r["window_id"]].add(k)
                if k in hubs:
                    per_window[r["window_id"]].add(k)
        together = Counter()
        for ks in per_window.values():
            ks = sorted(ks)
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    together[(ks[i], ks[j])] += 1
    # clusters are what gets talked about together. A fact ties its subject and object, but less when one of them is
    # a hub with facts about everything (the user, typically: 1/sqrt(degree/4)); entities named in the same line tie
    # each other too, so a busy person's facts split into topics instead of forming one star.
    deg = Counter()
    for e in edges:
        deg[e["s"]] += 1
        deg[e["o"]] += 1
    w: Dict[Tuple[str, str], float] = defaultdict(float)
    for e in edges:
        w[tuple(sorted((e["s"], e["o"])))] += min(1.0, 1.0 / math.sqrt(max(1, deg[e["s"]], deg[e["o"]]) / 4.0))
    mention = float(cfg.get("dashboard_graph_mention_weight", 0.5))
    for ks in per_line.values():
        ks = sorted(ks)
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                w[(ks[i], ks[j])] += mention
    cl = communities(w, resolution=float(cfg.get("dashboard_graph_resolution", 1.0)))
    for n in nodes.values():
        n["cluster"] = cl.get(n["id"], -1)
    clusters = []
    for cid in sorted({c for c in cl.values() if c >= 0}):
        members = sorted((n for n in nodes.values() if n["cluster"] == cid), key=lambda n: (-n["subject"], -n["facts"], n["label"]))
        clusters.append({"id": cid, "size": len(members), "label": " · ".join(m["label"] for m in members[:3]),
                         "top": [m["id"] for m in members[:8]]})
    return {"nodes": list(nodes.values()), "edges": edges, "clusters": clusters,
            "together": [{"a": a, "b": b, "n": n} for (a, b), n in together.most_common(400)],
            "settings": {"hops": int(cfg.get("dashboard_graph_hops", 2)), "view": cfg.get("dashboard_graph_view", "neighborhood")}}


def entities(path: str | Path, cfg: Dict[str, Any], q: str = "") -> Dict[str, Any]:
    with reader(path) as c:
        roles = _roles(c, cfg)
        subj = Counter(r["subject_norm"] for r in c.execute("SELECT subject_norm FROM facts WHERE status != 'retracted'"))
        rows = c.execute("SELECT name, fact_count, page FROM entities ORDER BY fact_count DESC").fetchall()
    ql = q.strip().lower()
    out = []
    for r in rows:
        k = norm_entity(r["name"])
        if ql and ql not in r["name"].lower():
            continue
        out.append({"id": k, "name": r["name"], "facts": r["fact_count"], "page": bool(r["page"]),
                    "role": roles.get(k, "thing"), "hub": subj.get(k, 0) > 0})
    return {"entities": out}


def entity(path: str | Path, cfg: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """An entity's page: what is believed now, what changed, every mention, and what it links to."""
    key = norm_entity(key)
    with reader(path) as c:
        roles = _roles(c, cfg)
        e = next((r for r in c.execute("SELECT * FROM entities") if norm_entity(r["name"]) == key), None)
        if not e:
            return None
        name = e["name"]
        like = f"%{name}%"
        rows = c.execute("""SELECT id FROM facts WHERE (subject_norm=? OR object LIKE ?) ORDER BY
                            COALESCE(h_start, created_at)""", (key, like)).fetchall()
        facts = [b for b in (_fact_brief(c, r["id"]) for r in rows) if b]
        facts = [f for f in facts if norm_entity(f["fact"][0]) == key or norm_entity(f["fact"][2]) == key
                 or name.lower() in f["fact"][2].lower()]
        # lines that name it, and the lines its facts came from (a person rarely names themself: "I", not "Joey")
        rows = {w["id"]: w for w in c.execute(
            """SELECT id, speaker, said, text, flags, session_id FROM windows WHERE text LIKE ? ORDER BY said DESC LIMIT 40""",
            (like,))}
        src = [x["id"] for f in facts for x in f["sources"] if x["id"] not in rows]
        if src:
            rows.update({w["id"]: w for w in c.execute(
                f"SELECT id, speaker, said, text, flags, session_id FROM windows WHERE id IN ({','.join('?' * len(src))})", src)})
        mentions = [_window_brief(w, 600) for w in sorted(rows.values(), key=lambda w: -(w["said"] or 0))[:60]]
        view = c.execute("SELECT body, built_night FROM views WHERE key=?", (f"entity:{key}",)).fetchone()
        known = {norm_entity(r["name"]) for r in c.execute("SELECT name FROM entities")}
    linked: Dict[str, Dict[str, Any]] = {}
    for f in facts:
        s, o = norm_entity(f["fact"][0]), norm_entity(f["fact"][2])
        other = o if s == key else s
        if other != key:
            ln = linked.setdefault(other, {"name": f["fact"][2] if s == key else f["fact"][0], "relations": []})
            if f["fact"][1] not in ln["relations"]:
                ln["relations"].append(f["fact"][1])
    groups = {"now": [], "planned": [], "before": [], "check": []}
    for f in facts:
        if f["status"] == "unconfirmed":
            groups["check"].append(f)
        elif f["status"] in ("superseded", "cancelled", "retracted"):
            groups["before"].append(f)
        elif f["modality"] == "planned":
            groups["planned"].append(f)
        else:
            groups["now"].append(f)
    return {"id": key, "name": name, "role": roles.get(key, "thing"), "aliases": _j(e["aliases"], []) if (e["aliases"] or "").startswith("[") else [],
            "fact_count": len(facts), "groups": groups, "mentions": mentions,
            "linked": [{"id": k, "name": v["name"], "relation": v["relations"][0], "relations": v["relations"], "entity": k in known}
                       for k, v in sorted(linked.items(), key=lambda kv: -len(kv[1]["relations"]))[:24]],
            "page_built": view["built_night"] if view else None}


# ------------------------------------------------------------------ recall
def recall_list(path: str | Path, cfg: Dict[str, Any], limit: int = 60, before: Optional[float] = None) -> Dict[str, Any]:
    with reader(path) as c:
        rows = c.execute("SELECT id, query, gate, items, said FROM injections WHERE said < ? ORDER BY said DESC LIMIT ?",
                         (before or time.time() + 1, limit)).fetchall()
    return {"items": [_recall_row(r, cfg) for r in rows]}


def recall_detail(path: str | Path, cfg: Dict[str, Any], inj_id: str) -> Optional[Dict[str, Any]]:
    with reader(path) as c:
        r = c.execute("SELECT * FROM injections WHERE id=?", (inj_id,)).fetchone()
        if not r:
            return None
        info = _j(r["gate"], {}) or {}
        d = c.execute("SELECT options, probabilities, model, flip FROM decisions WHERE id=?", (r["decision_id"] or "",)).fetchone()
        reading = None
        if d:
            opts, probs = _j(d["options"], []) or [], _j(d["probabilities"], []) or []
            reading = {"model": d["model"], "flip": d["flip"], "options": [{"option": o, "p": p} for o, p in zip(opts, probs)]}
        items = []
        for it in _j(r["items"], []) or []:
            row: Dict[str, Any] = {"kind": it.get("kind"), "id": it.get("id"), "sim": it.get("sim"),
                                   "assistant": it.get("assistant"), "vouched": it.get("vouched")}
            if it.get("kind") == "fact":
                b = _fact_brief(c, it["id"])
                if b:
                    row.update(fact=b["fact"], status=b["status"], modality=b["modality"], sources=b["sources"])
            else:
                w = c.execute("SELECT id, speaker, said, text, flags, session_id FROM windows WHERE id=?", (it.get("id"),)).fetchone()
                if w:
                    row["window"] = _window_brief(w, 1200)
            items.append(row)
        cands = info.get("candidates") or []
        cand_rows = {w["id"]: w for w in c.execute(
            f"SELECT id, speaker, said, text, flags, session_id FROM windows WHERE id IN ({','.join('?' * len(cands))})",
            cands)} if cands else {}
    return {"id": r["id"], "session_id": r["session_id"], "query": r["query"], "said": r["said"],
            "gate": parse_gate(info.get("gate", "")), "gate_raw": info.get("gate"), "passed": info.get("passed"),
            "uncertain": info.get("uncertain"), "referential": info.get("referential"), "ms": info.get("ms"),
            "top_sim": info.get("top_sim"), "verdict": verdict(info, cfg.get("gate_general", 0.8)),
            "cutoff": cfg.get("gate_general", 0.8), "strong_match": cfg.get("skip_gate"),
            "reading": reading, "items": items,
            "candidates": [_window_brief(cand_rows[i], 300) if i in cand_rows else {"id": i} for i in cands],
            "response": (r["response_text"] or "")[:1200] if "response_text" in r.keys() else ""}


def window_ref(path: str | Path, window_id: str) -> List[str]:
    """Every window of the message a window belongs to (a correction applies to the whole message)."""
    with reader(path) as c:
        w = c.execute("SELECT ref FROM windows WHERE id=?", (window_id,)).fetchone()
        if not w:
            return []
        return [r["id"] for r in c.execute("SELECT id FROM windows WHERE ref=?", (w["ref"],))]
