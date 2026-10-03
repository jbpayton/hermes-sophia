"""Awake recall: rank candidates from raw windows and facts, gate with the decider, inject evidence or nothing."""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

# The user asks about the agent's own words: then the agent's lines are the evidence, not restatements to demote.
_ASKS_ADVICE = re.compile(r"\b(?:suggest|suggestions?|recommend|recommendations?|advice|tips?|ideas?|what should I|"
                          r"should I|help me (?:choose|pick|find|decide|plan)|any (?:thoughts|pointers))\b", re.I)
_ASKS_AGENT = re.compile(r"\b(?:you|you've|you had)\s+(?:said|told|recommended|suggested|mentioned|gave|wrote|listed|"
                         r"proposed|explained|described|shared|provided|came up with)\b|"    # past: "can you suggest" is a request
                         r"\bdid you\s+(?:say|tell|recommend|suggest|mention|give|list)\b|"
                         r"\byour\s+(?:answer|suggestions?|recommendations?|advice|list|reply|explanation)\b", re.I)

# gate=choice: one readout that is both the gate and the per-line split. "general" closes the gate; otherwise the
# memories' share of the probability says which lines are Relevant and which are only Possible matches
GATE_QUESTION = ("What does this message need from memory? A memory bears on it when it answers the message or states "
                 "a fact the reply should take into account.")


def gate_options(n: int) -> Dict[str, str]:
    return {"general": "Nothing: a good reply would be the same for any user (general facts, explanations, writing, "
                       "calculations, translation or code), so nothing about this user or earlier conversations is "
                       "needed.",
            "none_fit": "It is about the user or earlier conversations, but none of these memories bears on it.",
            **{f"m{i + 1}": f"Memory [{i + 1}] bears on it most directly." for i in range(n)}}


# follow-ups whose meaning lives in the conversation ("and the other one?", "what about next week?")
_REFERENTIAL = re.compile(r"^\s*(?:and|also|what about|how about|so what|then)\b|"
                          r"\b(?:it|this|those|these|them|the other(?: one)?|that one|the same|again)\b", re.I)

GATE_INSTRUCTIONS = ("At least one memory item is directly relevant to the message: it answers it, or states a fact "
                     "the reply should take into account.")


def own_label(flags: str) -> str:
    """How a line that isn't anyone's words to the agent is labelled wherever it is shown."""
    flags = flags or ""
    if "thought" in flags:
        return " (own earlier thought, not an observation)"
    if "continuity" in flags:
        return " (its own continuing process, not the user)"
    if "event" in flags:
        return " (system notice)"
    if "caption" in flags:
        return " (image description written by a vision model)"
    return ""


def _agent_authored(flags: str) -> bool:
    return "assistant" in (flags or "") or "thought" in (flags or "")


def _date(ts: Optional[float]) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"


class Recall:
    def __init__(self, engine):
        self.e = engine

    # ------------------------------------------------------------- candidates
    def candidates(self, query: str, k: int = 20, history: bool = False, use_scope: bool = True,
                   session_id: str = "", now: Optional[float] = None, hops: Optional[int] = None,
                   thoughts: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """``now``: the moment the question is asked (defaults to the clock; benchmarks replay other dates).
        ``hops``: how far the graph walk goes (default graph_hops). ``thoughts``: include the agent's own kept
        thoughts."""
        e, cfg, store = self.e, self.e.cfg, self.e.store
        info: Dict[str, Any] = {}
        qv = None
        try:
            qv = e.embed([query], "query")[0]
            e.clear_degraded("embed")
        except Exception as ex:
            e.set_degraded("embed", str(ex))
            info["degraded"] = "embed"
        scope = query_time_scope(query, now if now is not None else e.now()) if use_scope else None
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
        in_scope: set = set()
        if allowed is not None and cfg["time_scope"] == "boost":
            in_scope, allowed = allowed, None     # a parsed date range ranks things up; it doesn't hide the rest
        asks_agent = bool(_ASKS_AGENT.search(query))
        info["asks_agent"] = asks_agent
        info["asks_advice"] = asks_advice = bool(_ASKS_ADVICE.search(query)) and not asks_agent
        a_pen = cfg["assistant_penalty"] + (cfg["advice_penalty"] if asks_advice else 0.0)
        hint = next((t for rx, t in _TYPE_HINTS if rx.search(query)), None)
        info["type_hint"] = hint
        last_sleep = store.get_meta("last_sleep_ts", 0) or 0

        scores: Dict[str, float] = {}
        fts_hits = store.fts(query, "window", k * (3 if cfg["fts_weight"] else 1))
        fts_ids = {i for i, _ in fts_hits}
        top_bm25 = max((b for _, b in fts_hits), default=0.0)
        fts_grade = {i: b / top_bm25 for i, b in fts_hits} if top_bm25 > 0 else {}
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
            if r is None or any(f in (r["flags"] or "") for f in ("echo", "dropped", "ungrounded")):
                continue
            if not thoughts and "thought" in (r["flags"] or ""):
                continue
            if session_id and r["session_id"] == session_id and "compacted" not in (r["flags"] or ""):
                continue                                   # already in the live context window
            lexical = cfg["fts_weight"] * fts_grade.get(wid, 0.0) if cfg["fts_weight"] else \
                (cfg["fts_bonus"] if wid in fts_ids else 0)
            bonus = lexical + (cfg["type_bonus"] if wid in typed else 0) + \
                    (cfg["time_scope_bonus"] if wid in in_scope else 0) + \
                    (cfg["recency_bonus"] if r["said"] > last_sleep else 0) - \
                    (a_pen if _agent_authored(r["flags"]) and not asks_agent else 0) - \
                    (cfg["question_penalty"] if (r["text"] or "").rstrip().endswith("?") and len(r["text"]) < 240
                     and not (asks_advice and cfg["advice_keeps_questions"]) else 0)
            if s < cfg["junk_floor"] and wid not in fts_ids:
                continue
            bare_q = "assistant" not in (r["flags"] or "") and (r["text"] or "").rstrip().endswith("?") \
                and len(r["text"]) < 240 and len(T.split_sentences(r["text"])) <= 1
            items[wid] = {"kind": "window", "id": wid, "score": s + bonus, "sim": s, "text": r["text"],
                          "bare_question": bare_q,
                          "said": r["said"], "speaker": r["speaker"], "flags": r["flags"] or "", "ref": r["ref"]}

        # facts (consolidated at night)
        if qv is not None:
            fidx = store.index("fact", cfg["embed_model"])
            fhits = fidx.search(qv, k)
            frows = store.facts_by_ids([i for i, _ in fhits])
            for fid, s in fhits:
                f = frows.get(fid)
                boost_scope = cfg["time_scope"] == "boost"
                if f is None or s < cfg["junk_floor"] or not self._fact_ok(f, history, None if boost_scope else scope):
                    continue
                if boost_scope and scope and f["h_start"] and f["h_start"] < scope[1] and (f["h_end"] or f["h_start"]) > scope[0]:
                    s += cfg["time_scope_bonus"]
                if cfg["facts_as"] == "keys":
                    self._attach_fact(items, f, s, s, session_id=session_id)
                else:
                    self._add_fact(items, f, s, s)
        # task cards: what the agent did before, and how it turned out. A card carries its request the way a
        # fact carries its source: when the request itself matched, the card takes its place and its score.
        found: Dict[str, float] = {}
        if qv is not None and (not scope or cfg["time_scope"] == "boost"):
            tidx = store.index("task", cfg["embed_model"])
            found.update({tid: s for tid, s in tidx.search(qv, 5) if s >= cfg["junk_floor"]})
        refs = {it["ref"]: it for it in items.values() if it["kind"] == "window" and it.get("ref")}
        if refs:
            ph = ",".join("?" * len(refs))
            for t in store.q(f"SELECT id, request_ref FROM tasks WHERE request_ref IN ({ph})", list(refs)):
                found[t["id"]] = max(found.get(t["id"], 0.0), refs[t["request_ref"]]["score"] + 0.005)
        for tid, sc in found.items():
            t = store.one("SELECT * FROM tasks WHERE id=?", (tid,))
            if t is None:
                continue
            for wid in [w for w, it in items.items() if it["kind"] == "window" and it.get("ref") == t["request_ref"]]:
                items.pop(wid)
            card = json.loads(t["card"])
            items["t:" + tid] = {"kind": "task", "id": tid, "score": sc, "sim": sc, "text": card.get("text", ""),
                                 "said": t["last_said"], "speaker": "", "flags": "", "ref": t["request_ref"],
                                 "outcome": t["outcome"]}
        # the graph: walk from what matched to what it connects to
        if (cfg["graph_hops"] if hops is None else hops) > 0:
            info["graph"] = self._expand(items, query, qv, history, scope, session_id, hops)
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
        if not thoughts:                                  # the graph walk and links can bring them in too
            items = {i: it for i, it in items.items() if "thought" not in (it.get("flags") or "")}
        ranked = sorted(items.values(), key=lambda it: it["score"], reverse=True)[:k]
        self._attach_times(ranked, now)
        credit = store.credit([it["id"] for it in ranked])
        for it in ranked:
            c = credit.get(it["id"], {})
            it["credit"] = {kk: round(v, 2) for kk, v in c.items()}
        ranked.sort(key=lambda it: (round(it["score"], 3), it["credit"].get("real", 0), it["credit"].get("replay", 0)),
                    reverse=True)
        return ranked, info

    def _attach_times(self, items: List[Dict[str, Any]], now: Optional[float] = None) -> None:
        """Relative time words resolved against when they were said ("last Saturday" -> 2023-05-20), so the
        reader doesn't have to do the date arithmetic. Phrases that already name a year are left alone.
        mark_passed_dates: a phrase that pointed ahead when it was said ("next weekend") and whose date is now over
        says so, so an old plan isn't read as still coming up."""
        today = dt.datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")
        wins = {it["id"]: it for it in items if it["kind"] == "window"}
        if not wins or not self.e.cfg["show_resolved_dates"]:
            return
        ph = ",".join("?" * len(wins))
        for r in self.e.store.q(f"""SELECT window_id, start, end, value FROM spans WHERE type='time'
                                    AND window_id IN ({ph}) ORDER BY window_id, start""", list(wins)):
            it = wins[r["window_id"]]
            phrase = (it["text"] or "")[r["start"]:r["end"]].strip()
            if not phrase or re.search(r"\b(1[89]|20)\d\d\b", phrase) or not r["value"]:
                continue
            value = r["value"]
            if self.e.cfg["mark_passed_dates"] and it.get("said"):
                said = dt.datetime.fromtimestamp(it["said"]).strftime("%Y-%m-%d")
                start, end = value.split("/")[0], value.split("/")[-1]
                if start > said[:len(start)] and end < today[:len(end)]:
                    value += ", now past; this line doesn't say if it happened"
            times = it.setdefault("times", [])
            if len(times) < 3 and (phrase, value) not in times:
                times.append((phrase, value))

    # ------------------------------------------------------------------ graph
    @staticmethod
    def _fact_ok(f, history: bool, scope) -> bool:
        if not history and f["status"] not in ("active", "unconfirmed"):
            return False
        if scope and f["h_start"] and not (f["h_start"] < scope[1] and (f["h_end"] or f["h_start"]) > scope[0]):
            return False
        return True

    def _add_fact(self, items: Dict[str, Dict[str, Any]], f, sim: float, score: float,
                  via: Optional[str] = None) -> None:
        """A fact item carries its source window as evidence (and replaces that window's own entry)."""
        store = self.e.store
        srcs = [r["window_id"] for r in store.q("SELECT window_id FROM fact_sources WHERE fact_id=?", (f["id"],))]
        evw = next(iter(store.windows_by_ids(srcs[:1]).values()), None)
        best = max([score] + [items[w]["score"] for w in srcs if w in items])
        for w in srcs:
            items.pop(w, None)
        items["f:" + f["id"]] = {"kind": "fact", "id": f["id"], "score": best + 0.005, "sim": sim,
                                 "evidence_id": evw["id"] if evw else None,
                                 "fact": [f["subject"], f["relation"], f["object"]], "modality": f["modality"],
                                 "happens": f["happens"], "status": f["status"],
                                 "text": evw["text"] if evw else "", "said": evw["said"] if evw else f["created_at"],
                                 "speaker": evw["speaker"] if evw else "", "flags": "",
                                 "ref": evw["ref"] if evw else "", **({"via": via} if via else {})}

    def _attach_fact(self, items: Dict[str, Dict[str, Any]], f, sim: float, score: float, via: Optional[str] = None,
                     session_id: str = "") -> bool:
        """facts_as=keys: a fact is one more search key for the window it came from. The window -- the verbatim
        evidence -- is what ranks and is injected, labelled with the fact. True if the window was added or raised."""
        store = self.e.store
        srcs = [r["window_id"] for r in store.q("SELECT window_id FROM fact_sources WHERE fact_id=?", (f["id"],))]
        if not srcs:
            return False
        wid = next((w for w in srcs if w in items), srcs[0])
        it = items.get(wid)
        changed = False
        if it is None:
            r = store.windows_by_ids([wid]).get(wid)
            if r is None or any(x in (r["flags"] or "") for x in ("echo", "dropped", "ungrounded")):
                return False
            if session_id and r["session_id"] == session_id and "compacted" not in (r["flags"] or ""):
                return False
            it = items[wid] = {"kind": "window", "id": wid, "score": score, "sim": sim, "text": r["text"],
                               "said": r["said"], "speaker": r["speaker"], "flags": r["flags"] or "", "ref": r["ref"]}
            changed = True
            if via:
                it["via"] = f"linked via {via}"
        elif score > it["score"]:
            it["score"] = score
            changed = True
            if via:
                it["via"] = f"linked via {via}"
        it["sim"] = max(it["sim"], sim)
        facts = it.setdefault("facts", [])
        if not any(x["id"] == f["id"] for x in facts):
            facts.append({"id": f["id"], "fact": [f["subject"], f["relation"], f["object"]],
                          "modality": f["modality"], "happens": f["happens"], "status": f["status"]})
        return changed

    def _expand(self, items: Dict[str, Dict[str, Any]], query: str, qv, history: bool, scope,
                session_id: str, hops: Optional[int] = None) -> Dict[str, Any]:
        """Graph expansion. Bridge entities -- named in the top items but not in the question, which
        similarity already covers -- are seeds. Facts one hop away join the candidates (or are raised) at
        the seed's score times ``graph_decay`` (or their own similarity, if higher), damped for hub entities
        with many facts. Conversation links (answers / corrects) are followed too. The user and the agent
        are never expanded: everything connects to them."""
        e, cfg, store = self.e, self.e.cfg, self.e.store
        decay, fanout, hub = cfg["graph_decay"], cfg["graph_fanout"], cfg["graph_hub_degree"]
        n_hops = cfg["graph_hops"] if hops is None else hops
        skip = {T.norm_entity(cfg["user_name"]), T.norm_entity(cfg["agent_name"]), "i", "me", "user", "assistant"}
        skip |= {T.norm_entity(n) for n in T.names_in(query)}
        seeds = sorted(items.values(), key=lambda it: it["score"], reverse=True)[:cfg["gate_top"]]
        weight: Dict[str, float] = {}
        names: Dict[str, str] = {}

        def seed(name: str, w: float) -> None:
            eid = T.norm_entity(name)
            if eid and eid not in skip and w > weight.get(eid, 0.0):
                weight[eid], names[eid] = w, name

        for it in seeds:
            for x in it.get("facts", []):
                seed(x["fact"][0], it["score"])
                seed(x["fact"][2], it["score"])
            if it["kind"] == "fact":
                seed(it["fact"][0], it["score"])
                seed(it["fact"][2], it["score"])
            else:
                for name in T.names_in(it.get("text") or ""):
                    seed(name, it["score"])
        known = {r["id"]: r for r in store.q(
            f"SELECT id, name, fact_count FROM entities WHERE id IN ({','.join('?' * len(weight))})", list(weight))} \
            if weight else {}
        frontier = sorted(((w, eid) for eid, w in weight.items() if eid in known), reverse=True)[:cfg["graph_entities"]]
        added, walked = 0, []
        fidx = store.index("fact", cfg["embed_model"]) if qv is not None else None
        for hop in range(n_hops):
            nxt: Dict[str, float] = {}
            for w, eid in frontier:
                deg = max(1, known[eid]["fact_count"] if eid in known else 1)
                damp = min(1.0, (hub / deg) ** 0.5)
                facts = [f for f in store.q("""SELECT * FROM facts WHERE (subject_norm=? OR lower(object)=?)
                                               ORDER BY valid_from DESC LIMIT 50""", (eid, eid))
                         if self._fact_ok(f, history, scope)]
                if not facts:
                    continue
                own = fidx.score_ids(qv, [f["id"] for f in facts]) if fidx is not None else {}
                facts.sort(key=lambda f: own.get(f["id"], 0.0), reverse=True)
                via = known[eid]["name"] if eid in known else names.get(eid, eid)
                reached = False
                for f in facts[:fanout]:
                    sim = own.get(f["id"], 0.0)
                    score = max(sim, w * decay * damp)
                    if cfg["facts_as"] == "keys":
                        if self._attach_fact(items, f, sim, score, via=via, session_id=session_id):
                            added += 1
                            reached = True
                        for other in (T.norm_entity(f["subject"]), T.norm_entity(f["object"])):
                            if other != eid and other not in skip:
                                nxt[other] = max(nxt.get(other, 0.0), score)
                        continue
                    have = items.get("f:" + f["id"])
                    if have is not None:                 # already a candidate: the path can only raise it
                        if score > have["score"]:
                            have["score"], have["via"] = score, via
                            added += 1
                            reached = True
                    else:
                        self._add_fact(items, f, sim, score, via=via)
                        added += 1
                        reached = True
                    for other in (T.norm_entity(f["subject"]), T.norm_entity(f["object"])):
                        if other != eid and other not in skip:
                            nxt[other] = max(nxt.get(other, 0.0), score)
                if reached:
                    walked.append(via)
            if hop + 1 < n_hops and nxt:
                more = {r["id"]: r for r in store.q(
                    f"SELECT id, name, fact_count FROM entities WHERE id IN ({','.join('?' * len(nxt))})", list(nxt))}
                known.update(more)
                frontier = sorted(((w, i) for i, w in nxt.items() if i in more), reverse=True)[:cfg["graph_entities"]]
        # adjacency: the turns right before and after a matched one (a question and its answer, a claim and its
        # correction) join at the seed's score times graph_adjacent_decay
        wseeds = {it["id"]: it for it in seeds if it["kind"] == "window"}
        if cfg["graph_adjacent"] > 0:
            n_adj = cfg["graph_adjacent"]
            for wid, it in list(wseeds.items()):
                me = store.one("SELECT session_id, said FROM windows WHERE id=?", (wid,))
                if me is None or not me["session_id"]:
                    continue
                around = store.q("""SELECT * FROM (SELECT * FROM windows WHERE session_id=? AND said<? ORDER BY said DESC, id DESC LIMIT ?)
                                    UNION ALL SELECT * FROM (SELECT * FROM windows WHERE session_id=? AND said>? ORDER BY said, id LIMIT ?)""",
                                 (me["session_id"], me["said"], n_adj, me["session_id"], me["said"], n_adj))
                for w in around:
                    if w["id"] in items or any(x.get("evidence_id") == w["id"] for x in items.values()):
                        continue
                    if any(f in (w["flags"] or "") for f in ("echo", "dropped", "ungrounded")):
                        continue
                    if session_id and w["session_id"] == session_id and "compacted" not in (w["flags"] or ""):
                        continue
                    items[w["id"]] = {"kind": "window", "id": w["id"], "score": it["score"] * cfg["graph_adjacent_decay"],
                                      "sim": it["sim"], "text": w["text"], "said": w["said"], "speaker": w["speaker"],
                                      "flags": w["flags"] or "", "ref": w["ref"], "via": "next to a match"}
                    added += 1
        # conversation links: a matched "yes" brings the question it answered, and the reverse
        if wseeds:
            ids = list(wseeds)
            ph = ",".join("?" * len(ids))
            for r in store.q(f"SELECT src, dst, kind FROM links WHERE src IN ({ph}) OR dst IN ({ph})", ids + ids):
                parent, other = (r["src"], r["dst"]) if r["src"] in wseeds else (r["dst"], r["src"])
                if other in items or any(it.get("evidence_id") == other for it in items.values()):
                    continue
                w = store.windows_by_ids([other]).get(other)
                if w is None or any(f in (w["flags"] or "") for f in ("echo", "dropped", "ungrounded")):
                    continue
                if session_id and w["session_id"] == session_id and "compacted" not in (w["flags"] or ""):
                    continue
                rel = r["kind"] if r["src"] == other else {"answers": "answered by", "corrects": "corrected by",
                                                           "about": "thought about in"}.get(r["kind"], r["kind"])
                items[other] = {"kind": "window", "id": other, "score": wseeds[parent]["score"] * decay,
                                "sim": wseeds[parent]["sim"], "text": w["text"], "said": w["said"],
                                "speaker": w["speaker"], "flags": w["flags"] or "", "ref": w["ref"],
                                "via": f"{rel} a match"}
                added += 1
        return {"entities": walked, "raised_or_added": added}

    # --------------------------------------------------------------- associate
    def associate(self, cue: str, k: int = 0, hops: Optional[int] = None, session_id: str = "",
                  record: bool = True, exclude: Sequence[str] = (),
                  now: Optional[float] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """What a cue brings to mind, with no question to answer and no gate deciding whether to use it.

        The same search as recall (meaning, keywords, the graph), walking further (associate_hops), so a cue can
        reach what is two steps away; every step weakens the pull (graph_decay). Each memory raised is recorded,
        and a memory raised recently is damped: its pull is divided by 1 + the sum of exp(-age / τ) over its
        recent raisings (τ = associate_habituation_hours). The same things don't keep coming back, and they recover
        as time passes. Damping only reorders what the cue is about: everything raised scores within associate_band
        of the best match, so when what's relevant has all come up lately, it comes back weaker rather than being
        replaced by whatever is next. Neighbouring turns ("next to a match") help a question's context, not
        association, and are left out. At most associate_per_source items come from one message or page.

        The continuing process's own events (its turns, its quiet notes) are never raised: association feeds that
        process, and raising its own output would loop it on itself. Recall still finds them, labelled.

        Two kinds of line pull less. One that stated something later superseded keeps its "later changed" note and
        pulls associate_superseded_weight as hard, so the current version ranks first and an old one rarely starts
        a train of thought. A bare reply ("yes", "ok, thanks") under associate_min_words is skipped: it says nothing
        without the line it answered, which can come up on its own."""
        cfg, store = self.e.cfg, self.e.store
        k = k or cfg["associate_k"]
        now = now if now is not None else self.e.now()
        ranked, info = self.candidates(cue, max(20, k * 4), use_scope=False, session_id=session_id, now=now,
                                       hops=cfg["associate_hops"] if hops is None else hops)
        hab = self.habituation([it["id"] for it in ranked], now)
        skip, per_source, out = set(exclude), Counter(), []
        top = max((it["score"] for it in ranked if it.get("via") != "next to a match"), default=0.0)
        for it in ranked:
            if it["id"] in skip or it.get("bare_question") or it.get("via") == "next to a match":
                continue
            if "continuity" in (it.get("flags") or ""):
                continue        # the process's own turns and notes: raising them would loop it on itself
            if it["kind"] == "window" and not it.get("facts") and \
                    len(re.findall(r"\w+", it.get("text") or "")) < cfg["associate_min_words"]:
                continue
            if it["score"] < top - cfg["associate_band"]:
                continue
            src = it.get("ref") or it["id"]
            if per_source[src] >= cfg["associate_per_source"]:
                continue
            per_source[src] += 1
            h = hab.get(it["id"], 0.0)
            weight = cfg["associate_superseded_weight"] if it.get("changed") else 1.0
            out.append({**it, "activation": it["score"] * weight / (1.0 + h), "habituation": h})
        out.sort(key=lambda it: it["activation"], reverse=True)
        out = out[:k]
        if record and out:
            store.xmany("INSERT INTO activations(item_id,item_kind,ts,cue) VALUES(?,?,?,?)",
                        [(it["id"], it["kind"], now, cue[:200]) for it in out])
        info["damped"] = sum(1 for it in out if it["habituation"] > 0.05)
        return out, info

    def habituation(self, ids: Sequence[str], now: float) -> Dict[str, float]:
        """Per item: the sum of exp(-age / τ) over the times it was raised in the last 5 τ."""
        tau = max(1.0, float(self.e.cfg["associate_habituation_hours"]) * 3600)
        out: Dict[str, float] = {}
        ids = list(ids)
        for i in range(0, len(ids), 400):
            part = ids[i:i + 400]
            for r in self.e.store.q(f"SELECT item_id, ts FROM activations WHERE ts>? AND ts<=? AND item_id IN "
                                    f"({','.join('?' * len(part))})", [now - 5 * tau, now, *part]):
                out[r["item_id"]] = out.get(r["item_id"], 0.0) + math.exp(-(now - r["ts"]) / tau)
        return out

    # ---------------------------------------------------------------- prefetch
    def _previous_user_line(self, session_id: str) -> str:
        """The user's last message in this conversation (the current one is captured after the reply)."""
        r = self.e.store.one("SELECT text FROM windows WHERE session_id=? AND flags NOT LIKE '%assistant%' "
                             "AND stream='conversation' ORDER BY said DESC LIMIT 1", (session_id,))
        return (r["text"] if r else "")[-300:]

    def prefetch(self, query: str, session_id: str, now: Optional[float] = None) -> Tuple[str, Dict[str, Any]]:
        e, cfg = self.e, self.e.cfg
        t0 = time.perf_counter()
        referential = len(query) < 100 and bool(_REFERENTIAL.search(query))
        search, prev = query, ""
        if referential:                                   # resolve the follow-up with the previous message
            prev = self._previous_user_line(session_id)
            search = f"{prev} {query}".strip() if prev else query
        items, info = self.candidates(search, cfg["recall_k"], session_id=session_id, now=now,
                                      thoughts=bool(cfg["inject_thoughts"]))
        top = items[:cfg["gate_top"]]
        gate, decision_id, passed = "none", "", False
        info["uncertain"] = False
        relevant: Optional[set] = None                    # gate_split: the lines the gate itself vouched for
        if top:
            if cfg["gate"] == "similarity":                # no model call: the search's own best score decides
                passed, gate = top[0]["sim"] >= cfg["gate_floor"], f"similarity:{top[0]['sim']:.2f}"
            elif cfg["gate"] == "choice":
                # "general" closes the gate (a very strong match always passes); "none fits" outweighing every memory
                # marks the whole block as possible matches; otherwise memories with a real share are Relevant
                try:
                    state = {**({"previous message": prev} if prev else {}), "message": query,
                             "memories": [f"[{i + 1}] {self.short(it)}" for i, it in enumerate(top)]}
                    # read the reverse order too when the first reading is unsure, but only if the average of the
                    # two could land on the other side of the cutoff (below 2c - 1 it can't: the gate opens anyway)
                    band, cut = cfg["gate_recheck"], cfg["gate_general"]
                    lo = max(band, 2 * cut - 1)
                    ans = e.decider.choice(state, GATE_QUESTION, gate_options(len(top)),
                                           permutations=cfg["gate_permutations"],
                                           recheck=(lambda p: lo <= p["general"] <= 1 - band) if band > 0 else None)
                    decision_id, pr = ans.decision_id, ans.probabilities
                    mem = [pr[f"m{i + 1}"] for i in range(len(top))]
                    mass = sum(mem)
                    passed = top[0]["sim"] >= cfg["skip_gate"] or pr["general"] < cfg["gate_general"]
                    info["uncertain"] = passed and pr["none_fit"] >= mass
                    if passed and cfg["gate_split"] and not info["uncertain"]:
                        relevant = {(it["kind"], it["id"]) for it, p in zip(top, mem)
                                    if p / max(mass, 1e-12) >= cfg["split_min"]}
                    gate = f"choice:g{pr['general']:.2f},n{pr['none_fit']:.2f},m{mass:.2f}"
                    e.clear_degraded("decider")
                except (DeciderError, Exception) as ex:
                    e.set_degraded("decider", str(ex))
                    passed = top[0]["sim"] >= cfg["skip_gate"]      # without the decider, only a strong match
                    gate = "degraded"
            elif top[0]["sim"] >= cfg["skip_gate"]:
                passed, gate = True, f"skip:{top[0]['sim']:.2f}"
            else:
                try:
                    state = {"message": query, "memories": [self.short(it) for it in top]}
                    ans = e.decider.noul(state, GATE_INSTRUCTIONS, permutations=cfg["gate_permutations"])
                    decision_id = ans.decision_id
                    passed = ans.noul >= cfg["gate_threshold"]
                    gate = f"decider:{ans.noul:.2f}"
                    e.clear_degraded("decider")
                except (DeciderError, Exception) as ex:
                    e.set_degraded("decider", str(ex))
                    gate = "degraded"
        info["referential"] = referential
        chosen = self.select(items[:max(cfg["inject_top"], 1)], agent_asked=info.get("asks_agent", False)) if passed else []
        text = (self.format(chosen, cfg["inject_chars"], cfg["inject_order"], info["uncertain"], relevant)
                if chosen else "")
        if relevant is not None:
            info["split"] = [sum((it["kind"], it["id"]) in relevant for it in chosen), len(chosen)]
        info.update({"gate": gate, "passed": passed, "n": len(chosen),
                     "ms": round((time.perf_counter() - t0) * 1000)})
        inj_id = sha(session_id, query, time.time())
        e.store.x("""INSERT INTO injections(id,session_id,query,items,gate,decision_id,said) VALUES(?,?,?,?,?,?,?)""",
                  (inj_id, session_id, T.redact(query)[0][:2000],
                   json.dumps([{"kind": it["kind"], "id": it["id"], "sim": round(it["sim"], 4),
                               "assistant": "assistant" in it.get("flags", ""),
                               **({"vouched": (it["kind"], it["id"]) in relevant} if relevant is not None else {})}
                               for it in chosen]),
                   json.dumps({"gate": gate, "passed": passed, "top_sim": round(top[0]["sim"], 4) if top else None,
                               "uncertain": info["uncertain"], "referential": referential, "ms": info["ms"],
                               "candidates": [it["id"] for it in top]}),
                   decision_id, time.time()))
        info["injection_id"] = inj_id
        e.note_injection(session_id, inj_id, chosen)
        return text, info

    def select(self, top: List[Dict[str, Any]], agent_asked: bool = False) -> List[Dict[str, Any]]:
        cfg = self.e.cfg
        if not top:
            return []
        floor = max(it["score"] for it in top) - cfg["inject_relative_floor"]
        out, n_asst = [], 0
        for it in top:
            if it["score"] < floor:                 # score: graph-raised items keep a low raw similarity
                continue
            if it.get("bare_question"):             # an earlier question carries no facts; sophia_recall still finds it
                continue
            if _agent_authored(it.get("flags", "")) and not agent_asked:
                if n_asst >= cfg["max_assistant_items"]:
                    continue
                n_asst += 1
            out.append(it)
        return out

    # ------------------------------------------------------------------ format
    @staticmethod
    def short(it: Dict[str, Any]) -> str:
        if it["kind"] == "task":
            return f"({_date(it['said'])}, earlier task, {it['outcome']}) {it['text'][:300]}"
        if it["kind"] == "fact":
            s, r, o = it["fact"]
            return f"({_date(it['said'])}) {s} | {r} | {o} — \"{it['text'][:200]}\""
        facts = "; ".join(" | ".join(x["fact"]) for x in it.get("facts", [])[:2])
        return (f"({_date(it['said'])}, {it['speaker']}{own_label(it.get('flags', ''))}) {it['text'][:260]}"
                + (f" [fact: {facts}]" if facts else ""))

    @classmethod
    def fit(cls, items: List[Dict[str, Any]], budget: int) -> List[Dict[str, Any]]:
        """The items whose lines actually fit in the injected block (format stops at the budget)."""
        n, prev = 0, ""
        for i in range(1, len(items) + 1):            # lines may contain newlines, so compare whole blocks
            cur = cls.format(items[:i], budget)
            if cur == prev:
                break
            n, prev = i, cur
        return items[:n]

    @staticmethod
    def format(items: List[Dict[str, Any]], budget: int, order: str = "rank", uncertain: bool = False,
               relevant: Optional[set] = None) -> str:
        """The injected block. Items are chosen best-first until the budget is spent; ``order="time"`` then lists
        them by date under a heading per day, which makes counting and ordering across conversations easier.
        ``relevant``: the (kind, id) of lines the gate vouched for; they go under "Relevant" and the rest under
        "Possible matches", so a doubtful line never casts doubt on a confident one."""
        lines = ["Sophia memory — verbatim evidence from earlier conversations and reading "
                 "(dates are when it was said; treat assistant-authored lines as weaker evidence):"]
        if uncertain:                                     # the gate judged that none of these answers the message
            lines[0] = ("Sophia memory — possible matches only: less certain; rely on one only if it clearly answers "
                        "the message (dates are when it was said; treat assistant-authored lines as weaker evidence):")
        used = len(lines[0])
        said: List[float] = []
        vouched: List[bool] = []
        for it in items:
            c = it.get("credit") or {}
            nums = []
            if c.get("real"):
                nums.append(f"real {c['real']:+g}")
            if c.get("replay"):
                nums.append(f"used {c['replay']:+g}")
            num = (" · " + ", ".join(nums)) if nums else ""
            if it["kind"] == "task":
                warn = " · did not work: don't repeat blindly" if it["outcome"] in ("failed", "abandoned") else ""
                line = f"- [{_date(it['said'])} · earlier task · {it['outcome']}{num}{warn}] {it['text']}"
                if used + len(line) + 1 > budget:
                    break
                lines.append(line)
                said.append(it.get("said") or 0.0)
                vouched.append(relevant is None or (it["kind"], it["id"]) in relevant)
                used += len(line) + 1
                continue
            if it["kind"] == "fact":
                s, r, o = it["fact"]
                mod = it.get("modality") or "asserted"
                when = f" · happens {it['happens']}" if it.get("happens") else ""
                status = f" · {it['status']}" if it.get("status") not in ("active", None) else ""
                changed = f" · evidence later changed: {'; '.join(it['changed'])}" if it.get("changed") else ""
                via = f" · linked via {it['via']}" if it.get("via") else ""
                line = f"- [{_date(it['said'])} · fact · {mod}{when}{status}{num}{via}] {s} | {r} | {o} — \"{it['text']}\"{changed}"
            else:
                who = it["speaker"] + (" (assistant said)" if "assistant" in it["flags"] else "") + \
                      (" (untrusted source text)" if "external" in it["flags"] else "") + own_label(it["flags"])
                changed = f" · later changed: {'; '.join(it['changed'])}" if it.get("changed") else ""
                via = f" · {it['via']}" if it.get("via") else ""
                fx = ""
                if it.get("facts"):
                    parts = []
                    for x in it["facts"][:3]:
                        fs, fr, fo = x["fact"]
                        extra = (f", happens {x['happens']}" if x.get("happens") else "") + \
                                (f", {x['status']}" if x.get("status") not in ("active", None) else "")
                        parts.append(f"{fs} {fr} {fo} ({x.get('modality') or 'asserted'}{extra})")
                    fx = " · fact: " + "; ".join(parts)
                tm = ""
                if it.get("times"):
                    tm = " · " + "; ".join(f'"{p}" = {v}' for p, v in it["times"])
                line = f"- [{_date(it['said'])} · {who}{num}{via}{changed}{fx}{tm}] {it['text']}"
            if used + len(line) + 1 > budget:
                break
            lines.append(line)
            said.append(it.get("said") or 0.0)
            vouched.append(relevant is None or (it["kind"], it["id"]) in relevant)
            used += len(line) + 1
        if len(lines) == 1:
            return ""
        head = lines[0][:-2] + ", listed by date):" if order == "time" else lines[0]

        def listed(entries):
            if order != "time":
                return [line for _, line in entries]
            body, day = [], None
            for t, line in sorted(entries, key=lambda x: x[0]):
                if _date(t) != day:
                    day = _date(t)
                    body.append(f"{day}:")
                body.append(line)
            return body
        entries = list(zip(said, lines[1:]))
        if relevant is None or all(vouched):
            return "\n".join([head] + listed(entries))
        sure = [x for x, v in zip(entries, vouched) if v]
        maybe = [x for x, v in zip(entries, vouched) if not v]
        out = [head]
        if sure:
            out += ["Relevant:"] + listed(sure)
        out += ["Possible matches (less certain; rely on one only if it clearly answers the message):"] + listed(maybe)
        return "\n".join(out)
