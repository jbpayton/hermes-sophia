"""The Sophia engine: one per profile. Hermes-independent so it can be tested and driven from the CLI."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import text as T
from .capture import Capture
from .config import load_config
from .decider import Decider
from .lms import LMStudio
from .recall import Recall
from .store import Store
from .tools import Tools

logger = logging.getLogger(__name__)


def default_db_path(hermes_home: str) -> Path:
    return Path(hermes_home) / "plugin-data" / "sophia" / "sophia.db"


class Engine:
    def __init__(self, cfg: Dict[str, Any], db_path: str | Path, client: Optional[LMStudio] = None):
        self.cfg = cfg
        self.store = Store(db_path)
        self.client = client or LMStudio(cfg["lmstudio_url"], cfg["lms_cli"])
        cal = self.store.get_meta("calibration", {}) or {}
        self.decider = Decider(self.client, cfg["decider_model"], permutations=cfg["gate_permutations"],
                               timeout=cfg["decider_timeout"], temperatures=cal.get("temperatures"),
                               log=self._log_decision)
        self.capture = Capture(self)
        self.recall = Recall(self)
        self.tools = Tools(self)
        self.last_injection: Dict[str, str] = {}
        self.last_injection_shingles: Dict[str, set] = {}
        self.last_prefetch: Dict[str, Dict[str, Any]] = {}
        self._degraded: Dict[str, Any] = {}

    @classmethod
    def for_home(cls, hermes_home: str, overrides: Optional[Dict[str, Any]] = None) -> "Engine":
        return cls(load_config(hermes_home, overrides), default_db_path(hermes_home))

    # ---------------------------------------------------------------- models
    def embed(self, texts: Sequence[str], kind: str = "document"):
        return self.client.embed(list(texts), self.cfg["embed_model"], kind, self.cfg["embed_timeout"])

    def _log_decision(self, rec: Dict[str, Any]) -> None:
        self.store.x("""INSERT OR IGNORE INTO decisions(id,ts,model,type,state_sha,instructions,options,probabilities,raw,flip)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (rec["id"], rec["ts"], rec["model"], rec["type"], rec["state_sha"], rec["instructions"],
                      json.dumps(rec["options"]), json.dumps(rec["probabilities"]), json.dumps(rec["raw"]), rec["flip"]))

    # -------------------------------------------------------------- degraded
    def set_degraded(self, name: str, why: str) -> None:
        first = name not in self._degraded
        self._degraded[name] = {"since": self._degraded.get(name, {}).get("since", time.time()), "why": why[:300]}
        if first:
            logger.warning("Sophia degraded: %s (%s)", name, why[:200])
            self.store.set_meta("degraded", self._degraded)

    def clear_degraded(self, name: str) -> None:
        if name in self._degraded:
            self._degraded.pop(name)
            self.store.set_meta("degraded", self._degraded)

    # ----------------------------------------------------------------- awake
    def note_injection(self, session_id: str, inj_id: str, items: List[Dict[str, Any]]) -> None:
        self.last_injection[session_id] = inj_id
        sh = set()
        for it in items:
            sh |= T.shingles(it.get("text", ""))
        self.last_injection_shingles[session_id] = sh

    def prefetch(self, query: str, session_id: str) -> str:
        text, info = self.recall.prefetch(query, session_id)
        self.last_prefetch[session_id] = info
        return text

    def capture_turn(self, session_id: str, user: str, assistant: str,
                     messages: Optional[Sequence[Dict[str, Any]]] = None, agent_context: str = "primary") -> Dict[str, int]:
        msgs = list(messages) if messages else [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
        stats = self.capture.process_messages(session_id, msgs, agent_context=agent_context)
        inj = self.last_injection.pop(session_id, None)
        if inj:
            self.store.x("UPDATE injections SET response_text=? WHERE id=?", ((assistant or "")[:8000], inj))
        self.last_injection_shingles.pop(session_id, None)
        return stats

    def mark_compacted(self, session_id: str, messages: Sequence[Dict[str, Any]]) -> int:
        """Windows of messages that compression is about to drop become retrievable in their own session."""
        from .capture import message_hash
        refs = [f"hermes:{session_id}:{message_hash(session_id, m)[:12]}" for m in messages]
        for i in range(0, len(refs), 400):
            part = refs[i:i + 400]
            self.store.x(f"""UPDATE windows SET flags=trim(flags||' compacted') WHERE ref IN ({','.join('?' * len(part))})
                            AND flags NOT LIKE '%compacted%'""", part)
        return len(refs)

    # ---------------------------------------------------------------- status
    def status(self) -> Dict[str, Any]:
        s = self.store
        return {"db": str(s.path), "counts": s.counts(),
                "short_term_windows": int(s.one("SELECT COUNT(*) AS n FROM windows WHERE said > ?",
                                                (s.get_meta("last_sleep_ts", 0) or 0,))["n"]),
                "missing_vectors": int(s.one("""SELECT COUNT(*) AS n FROM windows w WHERE NOT EXISTS (SELECT 1 FROM vectors v
                                               WHERE v.kind='window' AND v.item_id=w.id AND v.model=?)""",
                                             (self.cfg["embed_model"],))["n"]),
                "last_sleep": s.get_meta("last_sleep", None), "degraded": s.get_meta("degraded", {}) or {},
                "calibration": s.get_meta("calibration", None),
                "models": {k: self.cfg[k] for k in ("embed_model", "decider_model", "sleep_model")}}

    def close(self) -> None:
        self.store.close()
