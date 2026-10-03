"""The continuing process's own state: its queue, working state, the outbox of held messages, and the journal.

One SQLite file per profile (``plugin-data/continuity/continuity.db``), shared by the gateway, the CLI and the
dashboard. Sophia's memory is a separate store; this one holds only what the process itself owns.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, source TEXT, text TEXT,
  salience REAL, depth INT DEFAULT 1, data TEXT, created REAL, status TEXT DEFAULT 'queued', taken REAL,
  outcome TEXT);
CREATE INDEX IF NOT EXISTS queue_status ON queue(status, salience);
CREATE TABLE IF NOT EXISTS steps(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, item_id INT, text TEXT,
  energy_before REAL, energy_after REAL, outcome TEXT, reason TEXT, started REAL, ended REAL, ms INT,
  context_chars INT, reply_chars INT);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, text TEXT,
  status TEXT DEFAULT 'held', reason TEXT, step_id INT, settled REAL);
CREATE TABLE IF NOT EXISTS frames(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, text TEXT, chars INT,
  turn_kind TEXT, step_id INT, context_chars INT);
CREATE TABLE IF NOT EXISTS quiet(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, reason TEXT, since REAL, steps INT,
  silent INT, held INT, ms INT);
CREATE TABLE IF NOT EXISTS percepts(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS outreach(id INTEGER PRIMARY KEY AUTOINCREMENT, sent REAL, kind TEXT, text TEXT, step_id INT,
  response TEXT, gap_s REAL, response_text TEXT, settled REAL);
"""

# The working state: short-term memory. Everything the standing view shows comes from here or the tables above.
STATE: Dict[str, Any] = {
    "focus": "",
    "threads": [],            # [{"id", "text", "since"}]
    "waiting_for": [],        # [{"id", "text", "since"}]
    "energy": 0.0,
    "last_user_ts": 0.0,
    "jobs": [],               # finished background jobs seen lately: [{"text", "ts"}]
    "came_to_mind": [],       # memories it attended to lately: [{"text", "ts", "label"}]
    "last_scene": {},         # the scene shown in the latest frame (what "changed since it last looked" compares to)
    "last_frame_ts": 0.0,
    "turns_since_full": 0,
    "compaction_mark": "",    # identity of the latest compaction summary seen, so the next frame after one is full
    "paused": False,
    "quiet_reason": "",
    "quiet_since": 0.0,
    "episode_since": 0.0,     # start of the current stretch of its own activity
    "day": "",
    "steps_today": 0,
    "outreach_today": 0,
    "next_id": 1,
}


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA busy_timeout=30000")
            self.conn.executescript(SCHEMA)
            for table, cols in (("frames", (("turn_kind", "TEXT"), ("step_id", "INT"), ("context_chars", "INT"),
                                            ("prompt_tokens", "INT"))),
                                ("steps", (("prompt_tokens", "INT"), ("tokens", "INT"), ("outcomes", "TEXT"))),
                                ("quiet", (("tokens", "INT"),))):
                have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                for col, typ in cols:
                    if col not in have:                # files from earlier versions
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            self.conn.commit()

    def q(self, sql: str, args: Sequence[Any] = ()) -> List[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def x(self, sql: str, args: Sequence[Any] = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def xmany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    # ------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        r = self.one("SELECT value FROM meta WHERE key='state'")
        st = json.loads(r["value"]) if r else {}
        return {**json.loads(json.dumps(STATE)), **st, "paused": self.paused()}

    def save_state(self, st: Dict[str, Any]) -> None:
        st = {k: v for k, v in st.items() if k != "paused"}
        self.x("INSERT OR REPLACE INTO meta(key, value) VALUES('state', ?)", (json.dumps(st, default=str),))

    # Pausing has its own record, so a pause from the CLI can't be overwritten by the loop saving its state
    def paused(self) -> bool:
        r = self.one("SELECT value FROM meta WHERE key='paused'")
        return bool(r and json.loads(r["value"]))

    def set_paused(self, paused: bool) -> None:
        self.x("INSERT OR REPLACE INTO meta(key, value) VALUES('paused', ?)", (json.dumps(bool(paused)),))

    # ------------------------------------------------------------- queue
    def enqueue(self, kind: str, source: str, text: str, salience: float, depth: int = 1,
                data: Optional[Dict[str, Any]] = None, now: Optional[float] = None) -> int:
        return self.x("INSERT INTO queue(kind,source,text,salience,depth,data,created) VALUES(?,?,?,?,?,?,?)",
                      (kind, source, text, salience, depth, json.dumps(data or {}, default=str), now or time.time()))

    def queued(self) -> List[sqlite3.Row]:
        return self.q("SELECT * FROM queue WHERE status='queued' ORDER BY salience DESC, id")

    def queued_memory_ids(self) -> List[str]:
        out = []
        for r in self.q("SELECT data FROM queue WHERE status='queued' OR (status='taken' AND taken>?)",
                        (time.time() - 6 * 3600,)):
            mid = json.loads(r["data"] or "{}").get("memory_id")
            if mid:
                out.append(mid)
        return out

    def close(self) -> None:
        with self.lock:
            self.conn.close()
