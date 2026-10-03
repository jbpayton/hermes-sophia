"""Sophia as a library: the small, stable interface other plugins use (the continuity companion first).

Hermes routes memory tools through its memory manager, not the shared tool registry, so another plugin can't call
``sophia_associate`` as a tool. It opens the same store instead, which the gateway, CLI, dashboard and night already
share safely. Everything here is passive: it remembers and answers, and never starts anything.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from . import text as T
from .engine import Engine
from .recall import own_label
from .store import sha


class Memory:
    def __init__(self, hermes_home: str, overrides: Optional[Dict[str, Any]] = None, engine: Optional[Engine] = None):
        self.e = engine or Engine.for_home(hermes_home, overrides)

    @property
    def user_name(self) -> str:
        return self.e.cfg["user_name"]

    @property
    def agent_name(self) -> str:
        return self.e.cfg["agent_name"]

    def associate(self, cue: str, k: int = 0, exclude: Sequence[str] = (), record: bool = True,
                  now: Optional[float] = None) -> List[Dict[str, Any]]:
        """What a cue brings to mind (no gate), damped for what came up recently. Each item: id, kind, text, said,
        speaker, label (how it must be shown), via, pull."""
        items, _ = self.e.recall.associate(cue, k=k, exclude=exclude, record=record, now=now)
        return [{"id": it["id"], "kind": it["kind"], "text": it["text"], "said": it.get("said"),
                 "speaker": it.get("speaker") or "", "label": own_label(it.get("flags", "")),
                 "via": it.get("via"), "changed": list(it.get("changed") or []),
                 "pull": round(float(it["activation"]), 4)} for it in items]

    def think(self, text: str, about: str = "") -> List[str]:
        """Keep one of the agent's thoughts, as a thought (never a source of facts)."""
        return self.e.capture.think(text, about=about)

    def record_event(self, text: str, said: Optional[float] = None) -> List[str]:
        """Something the continuing process perceived or did, kept as its own event: searchable, labelled, never
        anyone's words and never a source of facts."""
        said = said or time.time()
        clean, _ = T.redact(text)
        ref = f"continuity:{sha(clean, said)}"
        hdr = T.header("continuity", said)
        ws = [{"id": sha(ref, i), "ref": ref, "session_id": "", "speaker": "continuity", "said": said, "text": w,
               "index_text": f"{hdr} {w}", "flags": " ".join(sorted({"event", "continuity", *wf.split()})),
               "stream": "event", "spans": []}
              for i, (w, wf) in enumerate(T.make_windows(clean, 3, 480, 800))]
        self.e.capture._persist(ws)
        return [w["id"] for w in ws]

    def user_message_times(self, days: int = 28) -> List[float]:
        """When the user wrote, over the last ``days``: the raw material for their usual hours."""
        since = time.time() - days * 86400
        return [r["said"] for r in self.e.store.q(
            "SELECT DISTINCT ref, MIN(said) AS said FROM windows WHERE speaker=? AND stream='conversation' AND said>? "
            "GROUP BY ref", (self.user_name, since))]

    def close(self) -> None:
        self.e.close()
