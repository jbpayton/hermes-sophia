"""Awake recall: rank candidates from raw windows and facts, gate with the decider, inject evidence or nothing."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .decider import DeciderError
from .spans import query_time_scope
from .store import sha
from . import text as T

logger = logging.getLogger(__name__)

_TYPE_HINTS = [(re.compile(r"\b(when|what time|what date|which day|how long ago)\b", re.I), "time"),
               (re.compile(r"\b(how much|cost|price|paid|spend|spent|budget)\b", re.I), "money"),
               (re.compile(r"\b(how long|duration)\b", re.I), "duration"),
               (re.compile(r"\b(how many|how far|how big|how heavy|how tall)\b", re.I), "quantity"),
               (re.compile(r"\b(link|url|website|email|phone|number for)\b", re.I), "contact"),
               (re.compile(r"\b(command|path|file|version|ticket|script)\b", re.I), "artifact")]

GATE_INSTRUCTIONS = ("At least one memory item is directly relevant to the message: it answers it, or states a fact "
                     "the reply should take into account.")


def _date(ts: Optional[float]) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"


class Recall:
    def __init__(self, engine):
        self.e = engine

    # ------------------------------------------------------------- candidates
    def candidates(self, query: str, k: int = 20, history: bool = False, use_scope: bool = True,
                   session_id: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        e, cfg, store = self.e, self.e.cfg, self.e.store
        info: Dict[str, Any] = {}
        qv = None
        try:
            qv = e.embed([query], "query")[0]
            e.clear_degraded("embed")
        except Exception as ex:
            e.set_degraded("embed", str(ex))
            info["degraded"] = "embed"
        scope = query_time_scope(query) if use_scope else None
        allowed = None
        if scope:
            t0, t1, clock = scope
            info["scope"] = [_date(t0), _date(t1 - 1), clock]
            ids = set()
            if clock == "any":
                ids.update(r["id"] for r in store.q("SELECT id FROM windows WHERE said>=? AND said<?", (t0, t1)))
            ids.update(r["window_id"] for r in store.q(
                "SELECT window_id FROM spans WHERE type='time' AND t_start<? AND t_end>?", (t1, t0)))
            allowed = ids
        hint = next((t for rx, t in _TYPE_HINTS if rx.search(query)), None)
        info["type_hint"] = hint
        last_sleep = store.get_meta("last_sleep_ts", 0) or 0

        scores: Dict[str, float] = {}
        fts_ids = {i for i, _ in store.fts(query, "window", k)}
        if qv is not None:
            widx = store.index("window", cfg["embed_model"])
            for wid, s in widx.search(qv, k * 3, allowed):
                scores[wid] = s
            missing = [i for i in fts_ids if i not in scores and (allowed is None or i in allowed)]
            scores.update(widx.score_ids(qv, missing))
        else:
            for rank, (wid, _) in enumerate(store.fts(query, "window", k)):
                if allowed is None or wid in allowed:
                    scores[wid] = 0.75 - rank * 0.01             # FTS-only degraded mode: rank order
        rows = store.windows_by_ids(list(scores))
        typed = set()
        if hint and rows:
            ids = list(rows)
            typed = {r["window_id"] for r in store.q(
                f"SELECT DISTINCT window_id FROM spans WHERE type=? AND window_id IN ({','.join('?' * len(ids))})",
                [hint, *ids])}
        items: Dict[str, Dict[str, Any]] = {}
        for wid, s in scores.items():
            r = rows.get(wid)
            if r is None or "echo" in (r["flags"] or "") or "dropped" in (r["flags"] or ""):
                continue
            if session_id and r["session_id"] == session_id and "compacted" not in (r["flags"] or ""):
                continue                                   # already in the live context window
            bonus = (cfg["fts_bonus"] if wid in fts_ids else 0) + (cfg["type_bonus"] if wid in typed else 0) + \
                    (cfg["recency_bonus"] if r["said"] > last_sleep else 0) - \
                    (cfg["assistant_penalty"] if "assistant" in (r["flags"] or "") else 0) - \
                    (cfg["question_penalty"] if (r["text"] or "").rstrip().endswith("?") and len(r["text"]) < 240 else 0)
            if s < cfg["junk_floor"] and wid not in fts_ids:
                continue
            items[wid] = {"kind": "window", "id": wid, "score": s + bonus, "sim": s, "text": r["text"],
                          "said": r["said"], "speaker": r["speaker"], "flags": r["flags"] or "", "ref": r["ref"]}

        # facts (consolidated at night)
        if qv is not None:
            fidx = store.index("fact", cfg["embed_model"])
            fhits = fidx.search(qv, k)
            frows = store.facts_by_ids([i for i, _ in fhits])
            for fid, s in fhits:
                f = frows.get(fid)
                if f is None or s < cfg["junk_floor"]:
                    continue
                if not history and f["status"] not in ("active", "unconfirmed"):
                    continue
                if scope and f["h_start"] and not (f["h_start"] < scope[1] and (f["h_end"] or f["h_start"]) > scope[0]):
                    continue
                srcs = [r["window_id"] for r in store.q("SELECT window_id FROM fact_sources WHERE fact_id=?", (fid,))]
                ev = store.windows_by_ids(srcs[:1])
                evw = next(iter(ev.values()), None)
                best = max([s] + [items[w]["score"] for w in srcs if w in items])
                for w in srcs:
                    items.pop(w, None)                        # the fact carries its own source as evidence
                items["f:" + fid] = {"kind": "fact", "id": fid, "score": best + 0.005, "sim": s,
                                     "evidence_id": evw["id"] if evw else None,
                                     "fact": [f["subject"], f["relation"], f["object"]], "modality": f["modality"],
                                     "happens": f["happens"], "status": f["status"],
                                     "text": evw["text"] if evw else "", "said": evw["said"] if evw else f["created_at"],
                                     "speaker": evw["speaker"] if evw else "", "flags": "", "ref": evw["ref"] if evw else ""}
        # raw windows that stated a fact since superseded: label what changed, keep the verbatim evidence
        by_window: Dict[str, List[Dict[str, Any]]] = {}
        for it in items.values():
            wid = it["id"] if it["kind"] == "window" else it.get("evidence_id")
            if wid:
                by_window.setdefault(wid, []).append(it)
        wids = list(by_window)
        if wids:
            for r in store.q(f"""SELECT fs.window_id, f.subject, f.relation, f.object, f.valid_to, n.object AS new_object
                                 FROM fact_sources fs JOIN facts f ON f.id=fs.fact_id LEFT JOIN facts n ON n.id=f.superseded_by
                                 WHERE f.status='superseded' AND fs.window_id IN ({','.join('?' * len(wids))})""", wids):
                for it in by_window.get(r["window_id"], []):
                    note = f"{r['subject']} {r['relation']} {r['object']} → {r['new_object'] or '?'} ({_date(r['valid_to'])})"
                    if note not in it.setdefault("changed", []):
                        it["changed"].append(note)
        ranked = sorted(items.values(), key=lambda it: it["score"], reverse=True)[:k]
        credit = store.credit([it["id"] for it in ranked])
        for it in ranked:
            c = credit.get(it["id"], {})
            it["credit"] = {kk: round(v, 2) for kk, v in c.items()}
        ranked.sort(key=lambda it: (round(it["score"], 3), it["credit"].get("real", 0), it["credit"].get("replay", 0)),
                    reverse=True)
        return ranked, info

    # ---------------------------------------------------------------- prefetch
    def prefetch(self, query: str, session_id: str) -> Tuple[str, Dict[str, Any]]:
        e, cfg = self.e, self.e.cfg
        t0 = time.perf_counter()
        items, info = self.candidates(query, cfg["recall_k"], session_id=session_id)
        top = items[:cfg["gate_top"]]
        gate, decision_id, passed = "none", "", False
        if top:
            if top[0]["sim"] >= cfg["skip_gate"]:
                passed, gate = True, f"skip:{top[0]['sim']:.2f}"
            else:
                try:
                    state = {"message": query, "memories": [self.short(it) for it in top]}
                    ans = e.decider.noul(state, GATE_INSTRUCTIONS)
                    decision_id = ans.decision_id
                    passed = ans.noul >= cfg["gate_threshold"]
                    gate = f"decider:{ans.noul:.2f}"
                    e.clear_degraded("decider")
                except (DeciderError, Exception) as ex:
                    e.set_degraded("decider", str(ex))
                    gate = "degraded"
        chosen = self.select(top) if passed else []
        text = self.format(chosen, cfg["inject_chars"]) if chosen else ""
        info.update({"gate": gate, "passed": passed, "n": len(chosen),
                     "ms": round((time.perf_counter() - t0) * 1000)})
        inj_id = sha(session_id, query, time.time())
        e.store.x("""INSERT INTO injections(id,session_id,query,items,gate,decision_id,said) VALUES(?,?,?,?,?,?,?)""",
                  (inj_id, session_id, query[:2000],
                   json.dumps([{"kind": it["kind"], "id": it["id"], "sim": round(it["sim"], 4),
                               "assistant": "assistant" in it.get("flags", "")} for it in chosen]),
                   json.dumps({"gate": gate, "passed": passed, "top_sim": round(top[0]["sim"], 4) if top else None,
                               "candidates": [it["id"] for it in top]}),
                   decision_id, time.time()))
        info["injection_id"] = inj_id
        e.note_injection(session_id, inj_id, chosen)
        return text, info

    def select(self, top: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cfg = self.e.cfg
        if not top:
            return []
        floor = top[0]["sim"] - cfg["inject_relative_floor"]
        out, n_asst = [], 0
        for it in top:
            if it["sim"] < floor:
                continue
            if "assistant" in it.get("flags", ""):
                if n_asst >= cfg["max_assistant_items"]:
                    continue
                n_asst += 1
            out.append(it)
        return out

    # ------------------------------------------------------------------ format
    @staticmethod
    def short(it: Dict[str, Any]) -> str:
        if it["kind"] == "fact":
            s, r, o = it["fact"]
            return f"({_date(it['said'])}) {s} | {r} | {o} — \"{it['text'][:200]}\""
        return f"({_date(it['said'])}, {it['speaker']}) {it['text'][:260]}"

    @staticmethod
    def format(items: List[Dict[str, Any]], budget: int) -> str:
        lines = ["Sophia memory — verbatim evidence from earlier conversations and reading "
                 "(dates are when it was said; treat assistant-authored lines as weaker evidence):"]
        used = len(lines[0])
        for it in items:
            c = it.get("credit") or {}
            nums = []
            if c.get("real"):
                nums.append(f"real {c['real']:+g}")
            if c.get("replay"):
                nums.append(f"used {c['replay']:+g}")
            num = (" · " + ", ".join(nums)) if nums else ""
            if it["kind"] == "fact":
                s, r, o = it["fact"]
                mod = it.get("modality") or "asserted"
                when = f" · happens {it['happens']}" if it.get("happens") else ""
                status = f" · {it['status']}" if it.get("status") not in ("active", None) else ""
                changed = f" · evidence later changed: {'; '.join(it['changed'])}" if it.get("changed") else ""
                line = f"- [{_date(it['said'])} · fact · {mod}{when}{status}{num}] {s} | {r} | {o} — \"{it['text']}\"{changed}"
            else:
                who = it["speaker"] + (" (assistant said)" if "assistant" in it["flags"] else "") + \
                      (" (untrusted source text)" if "external" in it["flags"] else "")
                changed = f" · later changed: {'; '.join(it['changed'])}" if it.get("changed") else ""
                line = f"- [{_date(it['said'])} · {who}{num}{changed}] {it['text']}"
            if used + len(line) + 1 > budget:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines) if len(lines) > 1 else ""
