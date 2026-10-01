"""SQLite store: raw windows, typed spans, threads/links, facts, entities, credit, logs, sleep jobs.

One file per profile, shared safely by the CLI, gateway, dashboard and cron processes: WAL where the linked SQLite is
free of the WAL-reset bug, a rollback journal otherwise (see wal_safe). Vectors are
float32 blobs keyed by (id, model); an in-memory matrix per table is refreshed incrementally by rowid,
so appends and night-time rewrites from other processes become visible without full reloads.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS windows(
  id TEXT PRIMARY KEY, ref TEXT, session_id TEXT, speaker TEXT, said REAL,
  text TEXT, index_text TEXT, header_source TEXT, flags TEXT DEFAULT '', stream TEXT,
  night_id TEXT);
CREATE INDEX IF NOT EXISTS windows_said ON windows(said);
CREATE INDEX IF NOT EXISTS windows_session ON windows(session_id, said);
CREATE TABLE IF NOT EXISTS vectors(
  rid INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, item_id TEXT, model TEXT, vec BLOB);
CREATE INDEX IF NOT EXISTS vectors_item ON vectors(kind, model, item_id);
CREATE TABLE IF NOT EXISTS spans(
  window_id TEXT, start INT, end INT, type TEXT, value TEXT, t_start REAL, t_end REAL,
  source TEXT, confidence REAL);
CREATE INDEX IF NOT EXISTS spans_window ON spans(window_id);
CREATE INDEX IF NOT EXISTS spans_time ON spans(type, t_start, t_end);
CREATE TABLE IF NOT EXISTS links(src TEXT, dst TEXT, kind TEXT, night_id TEXT, PRIMARY KEY (src, dst, kind));
CREATE TABLE IF NOT EXISTS threads(id TEXT PRIMARY KEY, session_id TEXT, title TEXT, start_window TEXT,
  end_window TEXT, night_id TEXT);
CREATE TABLE IF NOT EXISTS chunks(ref TEXT PRIMARY KEY, url TEXT, title TEXT, text TEXT, fetched_at REAL,
  content_hash TEXT, sorted INT DEFAULT 0, dropped INT DEFAULT 0, headroom TEXT);
CREATE TABLE IF NOT EXISTS facts(
  id TEXT PRIMARY KEY, subject TEXT, relation TEXT, object TEXT, subject_norm TEXT, relation_norm TEXT,
  modality TEXT, happens TEXT, h_start REAL, h_end REAL, valid_from REAL, valid_to REAL,
  superseded_by TEXT, status TEXT DEFAULT 'active', importance INT DEFAULT 0, night_id TEXT, created_at REAL);
CREATE INDEX IF NOT EXISTS facts_subject ON facts(subject_norm, status);
CREATE TABLE IF NOT EXISTS fact_sources(fact_id TEXT, window_id TEXT, PRIMARY KEY (fact_id, window_id));
CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, name TEXT, type TEXT, aliases TEXT,
  fact_count INT DEFAULT 0, page INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS relations(name TEXT PRIMARY KEY, instances INT, sessions INT, canonical INT DEFAULT 0,
  exclusive INT DEFAULT 0, promoted_night TEXT, pinned INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, summary TEXT, said REAL,
  detail TEXT);
CREATE TABLE IF NOT EXISTS actions(
  id TEXT PRIMARY KEY, session_id TEXT, seq INT, context TEXT, request_ref TEXT, request_text TEXT,
  tool TEXT, args TEXT, result_head TEXT, result_tail TEXT, result_chars INT, error INT, exit_code INT,
  said REAL, task_id TEXT);
CREATE INDEX IF NOT EXISTS actions_session ON actions(session_id, said, seq);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, session_id TEXT, request_ref TEXT, goal TEXT, outcome TEXT, confidence REAL,
  card TEXT, first_said REAL, last_said REAL, n_actions INT, night_id TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS task_links(task_id TEXT, kind TEXT, target TEXT, PRIMARY KEY (task_id, kind, target));
CREATE TABLE IF NOT EXISTS outcomes(id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, ok INT, summary TEXT, said REAL);
CREATE TABLE IF NOT EXISTS citations(session_id TEXT, message_ref TEXT, target TEXT, said REAL);
CREATE TABLE IF NOT EXISTS injections(id TEXT PRIMARY KEY, session_id TEXT, query TEXT, items TEXT, gate TEXT,
  decision_id TEXT, response_ref TEXT, response_text TEXT, said REAL, judged INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS credit_events(item_id TEXT, item_kind TEXT, class TEXT, kind TEXT, delta REAL,
  night_id TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS credit_item ON credit_events(item_id);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, ts REAL, model TEXT, type TEXT, state_sha TEXT,
  instructions TEXT, options TEXT, probabilities TEXT, raw TEXT, flip INT, gold TEXT, gold_class TEXT);
CREATE TABLE IF NOT EXISTS views(key TEXT PRIMARY KEY, kind TEXT, body TEXT, built_night TEXT);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY AUTOINCREMENT, night_id TEXT, step TEXT, kind TEXT,
  detail TEXT, undo TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS jobs(night_id TEXT, step TEXT, item TEXT, status TEXT, attempts INT DEFAULT 0,
  updated_at REAL, PRIMARY KEY (night_id, step, item));
CREATE TABLE IF NOT EXISTS processed(session_id TEXT, msg_hash TEXT, PRIMARY KEY (session_id, msg_hash));
CREATE TABLE IF NOT EXISTS eval_questions(id TEXT PRIMARY KEY, question TEXT, category TEXT, answer_refs TEXT,
  origin TEXT, created_night TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(item_id UNINDEXED, kind UNINDEXED, text);
CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY, file TEXT, mime TEXT, bytes INT, source TEXT, first_said REAL,
  session_id TEXT, ref TEXT, caption TEXT, caption_by TEXT, caption_at REAL);
CREATE TABLE IF NOT EXISTS activations(item_id TEXT, item_kind TEXT, ts REAL, cue TEXT);
CREATE INDEX IF NOT EXISTS activations_item ON activations(item_id, ts);
"""

_FTS_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-\.]*")
_FTS_STOP = frozenset("""a an the of to in on for and or is are was were be been it its this that what which who whom
whose when where why how do does did i you he she we they me my your our their with at by from as about into
than then there here have has had not no yes can could would should will shall may might""".split())


def sha(*parts: Any, n: int = 16) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()[:n]


class VectorIndex:
    """In-memory matrix for one (kind, model), refreshed incrementally from the vectors table."""

    def __init__(self, kind: str, model: str):
        self.kind, self.model = kind, model
        self.ids: List[str] = []
        self.pos: Dict[str, int] = {}
        self.mat: Optional[np.ndarray] = None
        self.last_rid = 0

    def refresh(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT rid, item_id, vec FROM vectors WHERE kind=? AND model=? AND rid>? ORDER BY rid",
                            (self.kind, self.model, self.last_rid)).fetchall()
        if not rows:
            return
        new_ids, new_vecs = [], []
        for rid, item_id, blob in rows:
            v = np.frombuffer(blob, dtype=np.float32)
            if item_id in self.pos and self.mat is not None and self.mat.shape[1] == v.shape[0]:
                self.mat[self.pos[item_id]] = v            # night-time rewrite of an existing item
            else:
                new_ids.append(item_id)
                new_vecs.append(v)
            self.last_rid = max(self.last_rid, rid)
        if new_vecs:
            block = np.vstack(new_vecs).astype(np.float32)
            if self.mat is None or self.mat.shape[0] == 0:
                self.mat = block
            elif self.mat.shape[1] != block.shape[1]:
                self.mat, self.ids, self.pos = block, [], {}   # model dimension changed: restart
            else:
                self.mat = np.vstack([self.mat, block])
            for i in new_ids:
                self.pos[i] = len(self.ids)
                self.ids.append(i)

    def search(self, q: np.ndarray, k: int, allowed: Optional[Iterable[str]] = None) -> List[Tuple[str, float]]:
        if self.mat is None or not len(self.ids):
            return []
        if allowed is not None:
            idx = np.array([self.pos[i] for i in allowed if i in self.pos], dtype=np.int64)
            if idx.size == 0:
                return []
            scores = self.mat[idx] @ q
            order = np.argsort(-scores)[:k]
            return [(self.ids[int(idx[j])], float(scores[j])) for j in order]
        scores = self.mat @ q
        k = min(k, scores.shape[0])
        top = np.argpartition(-scores, k - 1)[:k] if k < scores.shape[0] else np.arange(scores.shape[0])
        top = top[np.argsort(-scores[top])]
        return [(self.ids[int(j)], float(scores[j])) for j in top]

    def score_ids(self, q: np.ndarray, ids: Iterable[str]) -> Dict[str, float]:
        if self.mat is None:
            return {}
        return {i: float(self.mat[self.pos[i]] @ q) for i in ids if i in self.pos}


def wal_safe(version: Tuple[int, ...] = sqlite3.sqlite_version_info) -> bool:
    """SQLite's WAL-reset bug corrupts a WAL database written by several connections at once: versions 3.7.0 to
    3.51.2, fixed in 3.51.3 and backported to 3.50.7 and 3.44.6 (https://sqlite.org/wal.html#walresetbug). The same
    rule Hermes uses for its own databases."""
    v = tuple(version[:3])
    return v < (3, 7, 0) or v >= (3, 51, 3) or (3, 50, 7) <= v < (3, 51, 0) or (3, 44, 6) <= v < (3, 45, 0)


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.last_journal_id: Optional[int] = None        # the entry this instance wrote last (for "undo" links)
        with self.lock:
            self.conn.execute("PRAGMA busy_timeout=30000")
            # WAL only where SQLite is free of the WAL-reset bug; a store already in WAL stays WAL, because switching
            # it while another process (the gateway, a night) holds it would lose that process's commits
            mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
            if mode != "wal" and wal_safe():
                mode = self.conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            self.conn.execute("PRAGMA synchronous=NORMAL" if mode == "wal" else "PRAGMA synchronous=FULL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()
        self._indexes: Dict[Tuple[str, str], VectorIndex] = {}
        if not self.get_meta("secrets_scrubbed_v1"):
            self.scrub_secrets()
            self.set_meta("secrets_scrubbed_v1", True)

    def scrub_secrets(self) -> int:
        """Redact every stored text value again: databases from before redaction covered headers, logs and cut text
        can still hold a pasted key. Returns the number of values changed. Runs once per database."""
        from .text import redact
        changed = 0
        with self.lock:
            c = self.conn
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                      if not r[0].startswith(("fts_", "sqlite_"))]
            for t in tables:
                cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
                for col in cols:
                    for rowid, v in c.execute(f'SELECT rowid, "{col}" FROM "{t}"').fetchall():
                        if isinstance(v, str):
                            clean = redact(v)[0]
                            if clean != v:
                                c.execute(f'UPDATE "{t}" SET "{col}"=? WHERE rowid=?', (clean, rowid))
                                changed += 1
            if changed:
                c.execute("INSERT INTO fts(fts) VALUES('optimize')")    # drop the old terms from the index
                c.commit()
                try:                                                  # and the freed pages that held them
                    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    c.execute("VACUUM")
                except sqlite3.OperationalError:                      # another process has it open: next time
                    pass
            c.commit()
        return changed

    # ------------------------------------------------------------ basics
    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def q(self, sql: str, args: Sequence[Any] = ()) -> List[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def x(self, sql: str, args: Sequence[Any] = ()) -> None:
        with self.lock:
            self.conn.execute(sql, args)
            self.conn.commit()

    def xmany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self.lock:
            self.conn.executemany(sql, list(rows))
            self.conn.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def set_meta(self, key: str, value: Any) -> None:
        self.x("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value)))

    # ---------------------------------------------------------- windows
    def processed(self, session_id: str) -> set:
        return {r["msg_hash"] for r in self.q("SELECT msg_hash FROM processed WHERE session_id=?", (session_id,))}

    def mark_processed(self, session_id: str, hashes: Iterable[str]) -> None:
        self.xmany("INSERT OR IGNORE INTO processed(session_id,msg_hash) VALUES(?,?)",
                   [(session_id, h) for h in hashes])

    def add_windows(self, windows: List[Dict[str, Any]], vecs: Optional[np.ndarray], model: str) -> None:
        with self.lock:
            c = self.conn
            for i, w in enumerate(windows):
                c.execute("""INSERT OR REPLACE INTO windows(id,ref,session_id,speaker,said,text,index_text,
                             header_source,flags,stream) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (w["id"], w["ref"], w.get("session_id", ""), w.get("speaker", ""), w["said"], w["text"],
                           w["index_text"], w.get("header_source", "heuristic"), w.get("flags", ""),
                           w.get("stream", "conversation")))
                c.execute("DELETE FROM fts WHERE item_id=? AND kind='window'", (w["id"],))
                if "echo" not in w.get("flags", ""):
                    c.execute("INSERT INTO fts(item_id,kind,text) VALUES(?,?,?)", (w["id"], "window", w["index_text"]))
                for s in w.get("spans", []):
                    c.execute("""INSERT INTO spans(window_id,start,end,type,value,t_start,t_end,source,confidence)
                                 VALUES(?,?,?,?,?,?,?,?,?)""",
                              (w["id"], s["start"], s["end"], s["type"], s.get("value"), s.get("t_start"),
                               s.get("t_end"), s.get("source", "deterministic"), s.get("confidence", 1.0)))
                if vecs is not None and len(vecs) > i:
                    c.execute("INSERT INTO vectors(kind,item_id,model,vec) VALUES('window',?,?,?)",
                              (w["id"], model, vecs[i].astype(np.float32).tobytes()))
            c.commit()

    def set_vectors(self, kind: str, ids: Sequence[str], vecs: np.ndarray, model: str) -> None:
        with self.lock:
            for i, item_id in enumerate(ids):
                self.conn.execute("DELETE FROM vectors WHERE kind=? AND model=? AND item_id=?", (kind, model, item_id))
                self.conn.execute("INSERT INTO vectors(kind,item_id,model,vec) VALUES(?,?,?,?)",
                                  (kind, item_id, model, vecs[i].astype(np.float32).tobytes()))
            self.conn.commit()

    def index(self, kind: str, model: str) -> VectorIndex:
        key = (kind, model)
        with self.lock:
            idx = self._indexes.get(key)
            if idx is None:
                idx = self._indexes[key] = VectorIndex(kind, model)
            idx.refresh(self.conn)
            return idx

    # --------------------------------------------------------------- fts
    @staticmethod
    def fts_query(text: str) -> Optional[str]:
        toks = [t for t in _FTS_TOKEN.findall(text) if t.lower() not in _FTS_STOP and len(t) > 1]
        if not toks:
            return None
        return " OR ".join('"' + t.replace('"', '') + '"' for t in toks[:24])

    def fts(self, text: str, kind: str, limit: int = 20) -> List[Tuple[str, float]]:
        expr = self.fts_query(text)
        if not expr:
            return []
        try:
            rows = self.q("SELECT item_id, bm25(fts) AS s FROM fts WHERE fts MATCH ? AND kind=? ORDER BY s LIMIT ?",
                          (expr, kind, limit))
        except sqlite3.OperationalError:
            return []
        return [(r["item_id"], -float(r["s"])) for r in rows]

    def fts_put(self, item_id: str, kind: str, text: str) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM fts WHERE item_id=? AND kind=?", (item_id, kind))
            self.conn.execute("INSERT INTO fts(item_id,kind,text) VALUES(?,?,?)", (item_id, kind, text))
            self.conn.commit()

    # ------------------------------------------------------------- misc
    def windows_by_ids(self, ids: Sequence[str]) -> Dict[str, sqlite3.Row]:
        if not ids:
            return {}
        out = {}
        ids = list(ids)
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            for r in self.q(f"SELECT * FROM windows WHERE id IN ({','.join('?' * len(part))})", part):
                out[r["id"]] = r
        return out

    def facts_by_ids(self, ids: Sequence[str]) -> Dict[str, sqlite3.Row]:
        if not ids:
            return {}
        ids = list(ids)
        return {r["id"]: r for r in self.q(f"SELECT * FROM facts WHERE id IN ({','.join('?' * len(ids))})", ids)}

    def credit(self, item_ids: Sequence[str]) -> Dict[str, Dict[str, float]]:
        """{item: {class: total}}; failures were already written as 2x negative deltas."""
        if not item_ids:
            return {}
        ids = list(item_ids)
        out: Dict[str, Dict[str, float]] = {}
        for r in self.q(f"""SELECT item_id, class, SUM(delta) AS s, COUNT(*) AS n FROM credit_events
                            WHERE item_id IN ({','.join('?' * len(ids))}) GROUP BY item_id, class""", ids):
            out.setdefault(r["item_id"], {})[r["class"]] = float(r["s"])
        return out

    def add_credit(self, item_id: str, item_kind: str, cls: str, kind: str, delta: float,
                   night_id: str = "") -> None:
        self.x("INSERT INTO credit_events(item_id,item_kind,class,kind,delta,night_id,ts) VALUES(?,?,?,?,?,?,?)",
               (item_id, item_kind, cls, kind, delta, night_id, time.time()))

    def journal(self, night_id: str, step: str, kind: str, detail: Any, undo: Any = None) -> int:
        with self.lock:
            cur = self.conn.execute("INSERT INTO journal(night_id,step,kind,detail,undo,ts) VALUES(?,?,?,?,?,?)",
                                    (night_id, step, kind, json.dumps(detail, default=str),
                                     json.dumps(undo, default=str) if undo is not None else None, time.time()))
            self.conn.commit()
            self.last_journal_id = cur.lastrowid
        return self.last_journal_id

    # --------------------------------------------------------- corrections
    # Only what was derived can be corrected: who a line is attributed to, and extracted facts. The verbatim text is
    # the record and is never changed. Every correction is journaled with its reason and can be undone.
    def relabel_speaker(self, window_ids: Sequence[str], speaker: str, reason: str, by: str = "manual") -> int:
        rows = self.q(f"SELECT id, speaker FROM windows WHERE id IN ({','.join('?' * len(window_ids))})",
                      list(window_ids)) if window_ids else []
        rows = [r for r in rows if r["speaker"] != speaker]
        if not rows:
            return 0
        olds = {}
        for r in rows:
            olds.setdefault(r["speaker"], []).append(r["id"])
        for old, ids in olds.items():
            self.x(f"UPDATE windows SET speaker=? WHERE id IN ({','.join('?' * len(ids))})", [speaker, *ids])
            self.journal("manual", "correct", "speaker_corrected",
                         {"windows": len(ids), "from": old, "to": speaker, "reason": reason, "by": by,
                          "first": ids[0]},
                         undo={"windows": ids, "speaker": old})
        return len(rows)

    def mark_events(self, window_ids: Sequence[str], reason: str, by: str = "manual", speaker: str = "system") -> int:
        """Lines stored as someone's words that were really Hermes's own notices (a finished background job, a
        delegation result): relabelled as events, which recall labels and the night never reads facts from."""
        rows = [r for r in (self.q(f"SELECT id, speaker, stream, flags FROM windows WHERE id IN "
                                   f"({','.join('?' * len(window_ids))})", list(window_ids)) if window_ids else [])
                if r["stream"] != "event"]
        for r in rows:
            self.x("UPDATE windows SET speaker=?, stream='event', flags=? WHERE id=?",
                   (speaker, " ".join(sorted(set((r["flags"] or "").split()) | {"event"})), r["id"]))
        if rows:
            self.journal("manual", "correct", "marked_as_event",
                         {"windows": len(rows), "reason": reason, "by": by, "first": rows[0]["id"]},
                         undo={"restore": {r["id"]: {"speaker": r["speaker"], "stream": r["stream"],
                                                     "flags": r["flags"] or ""} for r in rows}})
        return len(rows)

    def drop_windows(self, window_ids: Sequence[str], reason: str, by: str = "manual") -> int:
        """Keep lines out of recall (flag 'dropped') without deleting them: the text stays, the journal can undo it."""
        rows = [r for r in (self.q(f"SELECT id, flags FROM windows WHERE id IN ({','.join('?' * len(window_ids))})",
                                   list(window_ids)) if window_ids else []) if "dropped" not in (r["flags"] or "")]
        for r in rows:
            self.x("UPDATE windows SET flags=? WHERE id=?", (((r["flags"] or "") + " dropped").strip(), r["id"]))
        if rows:
            self.journal("manual", "correct", "windows_dropped",
                         {"windows": len(rows), "reason": reason, "by": by, "first": rows[0]["id"]},
                         undo={"flags": {r["id"]: r["flags"] or "" for r in rows}})
        return len(rows)

    def retract_fact(self, fact_id: str, reason: str, by: str = "manual") -> bool:
        f = self.one("SELECT id, subject, relation, object, status FROM facts WHERE id=?", (fact_id,))
        if not f or f["status"] == "retracted":
            return False
        self.x("UPDATE facts SET status='retracted' WHERE id=?", (fact_id,))
        self.journal("manual", "correct", "fact_retracted",
                     {"fact": [f["subject"], f["relation"], f["object"]], "reason": reason, "by": by},
                     undo={"fact": fact_id, "status": f["status"]})
        return True

    def resolve_plan(self, fact_id: str, outcome: str, reason: str = "", by: str = "manual") -> bool:
        """A plan whose date passed: ``happened`` makes it an asserted fact, ``didnt`` sets it 'cancelled' (kept, not
        recalled as current). Journaled with the old status and modality, so it can be undone."""
        if outcome not in ("happened", "didnt"):
            raise ValueError(f"unknown plan outcome {outcome!r}")
        f = self.one("SELECT id, subject, relation, object, status, modality FROM facts WHERE id=?", (fact_id,))
        if not f:
            return False
        status, modality = ("active", "asserted") if outcome == "happened" else ("cancelled", f["modality"])
        if (f["status"], f["modality"]) == (status, modality):
            return False
        self.x("UPDATE facts SET status=?, modality=? WHERE id=?", (status, modality, fact_id))
        self.journal("manual", "correct", "plan_resolved",
                     {"fact": [f["subject"], f["relation"], f["object"]], "outcome": outcome, "reason": reason,
                      "by": by, "id": fact_id},
                     undo={"fact": fact_id, "status": f["status"], "modality": f["modality"]})
        return True

    def mark_reviewed(self, item: str, note: str = "", by: str = "manual") -> None:
        """Someone looked at a flagged item (a journal entry 'j:<id>' or a fact 'f:<id>') and left it as it is."""
        self.journal("manual", "review", "reviewed", {"item": item, "note": note, "by": by}, undo={"reviewed": item})

    def undone_ids(self) -> set:
        return {json.loads(r["detail"]).get("journal_id") for r in self.q("SELECT detail FROM journal WHERE kind='undone'")}

    def undo_journal(self, journal_id: int, by: str = "manual") -> Optional[str]:
        """Revert one journaled change (supersession, plan change, correction, review). Returns what was undone,
        or None when the entry has nothing to undo or was undone already."""
        row = self.one("SELECT * FROM journal WHERE id=?", (int(journal_id),))
        if not row or not row["undo"] or int(journal_id) in self.undone_ids():
            return None
        u = json.loads(row["undo"])
        for wid, flags in (u.get("flags") or {}).items():         # dropped lines: their old flags back
            self.x("UPDATE windows SET flags=? WHERE id=?", (flags, wid))
        for wid, old in (u.get("restore") or {}).items():          # lines relabelled as events: as they were
            self.x("UPDATE windows SET speaker=?, stream=?, flags=? WHERE id=?",
                   (old["speaker"], old["stream"], old["flags"], wid))
        if "windows" in u:                                        # a speaker correction: the old label back
            ids = u["windows"]
            self.x(f"UPDATE windows SET speaker=? WHERE id IN ({','.join('?' * len(ids))})", [u["speaker"], *ids])
        if "fact" in u:
            self.x("UPDATE facts SET status=?, valid_to=NULL, superseded_by=NULL WHERE id=?",
                   (u.get("status", "active"), u["fact"]))
            if u.get("modality"):
                self.x("UPDATE facts SET modality=? WHERE id=?", (u["modality"], u["fact"]))
            self.x("DELETE FROM credit_events WHERE item_id=? AND kind='contradicted' AND night_id=?",
                   (u["fact"], row["night_id"]))
        self.journal("manual", "undo", "undone", {"journal_id": int(journal_id), "detail": row["detail"], "by": by})
        return f"{row['kind']} {row['detail'][:160]}"

    def job_done(self, night_id: str, step: str, item: str) -> bool:
        r = self.one("SELECT status FROM jobs WHERE night_id=? AND step=? AND item=?", (night_id, step, item))
        return bool(r and r["status"] == "done")

    def job_mark(self, night_id: str, step: str, item: str, status: str) -> None:
        self.x("""INSERT INTO jobs(night_id,step,item,status,attempts,updated_at) VALUES(?,?,?,?,1,?)
                  ON CONFLICT(night_id,step,item) DO UPDATE SET status=excluded.status,
                  attempts=jobs.attempts+1, updated_at=excluded.updated_at""",
               (night_id, step, item, status, time.time()))

    def counts(self) -> Dict[str, int]:
        out = {}
        for t in ("windows", "spans", "facts", "entities", "chunks", "events", "actions", "tasks", "injections",
                  "decisions", "credit_events", "links", "journal"):
            out[t] = int(self.one(f"SELECT COUNT(*) AS n FROM {t}")["n"])
        return out
